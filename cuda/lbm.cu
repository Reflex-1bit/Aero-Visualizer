// D3Q19 lattice Boltzmann wind tunnel for the RB19 aero visualizer.
//
//   lbm <grid.bin> <nx> <ny> <nz> <out_prefix> [steps] [avg_start] [u_lb] [nu_lb] [cs] [sym]
//
// Grid: uint8 occupancy (1 = car), x fastest. World frame matches index.html:
// nose at +x, air travels toward -x, ground at y = 0.
//
// Physics
//   * Regularized BGK collision + Smagorinsky LES eddy viscosity (stable at the
//     very low molecular viscosity needed for a high-Reynolds race car).
//   * Car surfaces: halfway bounce-back (no-slip).
//   * Ground: rolling road - air enters from the ground at the freestream speed
//     (mass-conserving), like an F1 tunnel's moving belt.
//   * Inlet (+x), ceiling and side walls: freestream equilibrium.
//   * Optional symmetry plane at z = 0 ([sym] = 1) to simulate half the car.
//   * Populations stored in fp16 (see store_t) to fit finer grids in 8 GB.
//   * Outlet (-x): fixed pressure, plus a viscous sponge to absorb the wake.
//   * Forces on the car via momentum exchange -> drag / downforce coefficients.
//
// Output (after the run)
//   <out>_avg.f32 : time-averaged (ux, uy, uz, p) per cell, float32, in units of
//                   the freestream speed U (so freestream = (-1, 0, 0)); p is the
//                   pressure coefficient Cp = (p - p_inf) / (0.5 rho U^2).
//   <out>_forces.csv : step, Cd, Cl, Cs(side) history.

#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cmath>
#include <vector>
#include <string>
#include <chrono>

#define CK(x) do { cudaError_t e = (x); if (e != cudaSuccess) { \
  fprintf(stderr, "CUDA %s at %s:%d\n", cudaGetErrorString(e), __FILE__, __LINE__); exit(1); } } while (0)

constexpr int Q = 19;
__constant__ int CX[Q] = { 0, 1,-1, 0, 0, 0, 0, 1,-1, 1,-1, 1,-1, 1,-1, 0, 0, 0, 0 };
__constant__ int CY[Q] = { 0, 0, 0, 1,-1, 0, 0, 1,-1,-1, 1, 0, 0, 0, 0, 1,-1, 1,-1 };
__constant__ int CZ[Q] = { 0, 0, 0, 0, 0, 1,-1, 0, 0, 0, 0, 1,-1,-1, 1, 1,-1,-1, 1 };
__constant__ int OPP[Q] = { 0, 2, 1, 4, 3, 6, 5, 8, 7,10, 9,12,11,14,13,16,15,18,17 };
__constant__ int MZ[Q] = { 0, 1, 2, 3, 4, 6, 5, 7, 8, 9,10,13,14,11,12,17,18,15,16 };  // mirror in z
__constant__ float W[Q] = { 1.f/3,
  1.f/18, 1.f/18, 1.f/18, 1.f/18, 1.f/18, 1.f/18,
  1.f/36, 1.f/36, 1.f/36, 1.f/36, 1.f/36, 1.f/36,
  1.f/36, 1.f/36, 1.f/36, 1.f/36, 1.f/36, 1.f/36 };

// Populations are stored as 16-bit relative deviations h = f / w_i - 1 (the
// idea behind FluidX3D's FP16S): half the memory and bandwidth of float32,
// and plenty of precision at this Mach number. Build with -DFP32 to compare.
#ifdef FP32
typedef float store_t;
__device__ __forceinline__ float ld(const store_t* b, int i, size_t n, size_t idx, float w) { return b[i * n + idx] + w; }
__device__ __forceinline__ void st(store_t* b, int i, size_t n, size_t idx, float w, float f) { b[i * n + idx] = f - w; }
#else
typedef __half store_t;
__device__ __forceinline__ float ld(const store_t* b, int i, size_t n, size_t idx, float w) { return w * (1.f + __half2float(b[i * n + idx])); }
__device__ __forceinline__ void st(store_t* b, int i, size_t n, size_t idx, float w, float f) { b[i * n + idx] = __float2half(f / w - 1.f); }
#endif

struct Params {
  int nx, ny, nz;
  size_t n;
  float u_in;       // freestream speed (lattice units), air moves toward -x
  float tau0;       // molecular relaxation time
  float cs2_smag;   // Smagorinsky constant squared
  int sponge;       // sponge thickness at the outlet (cells)
  int accumulate;   // add this step's macros to the running average
  int force;        // accumulate the momentum-exchange force
  int sym;          // z = 0 is a symmetry plane (simulate half the car)
};

__device__ __forceinline__ float feq(int i, float rho, float ux, float uy, float uz, float usq) {
  const float cu = CX[i] * ux + CY[i] * uy + CZ[i] * uz;
  return W[i] * rho * (1.f + 3.f * cu + 4.5f * cu * cu - 1.5f * usq);
}

__global__ void step_kernel(const store_t* __restrict__ fin, store_t* __restrict__ fout,
                            const uint8_t* __restrict__ solid, Params P,
                            float4* __restrict__ avg, double* __restrict__ force) {
  const int x = blockIdx.x * blockDim.x + threadIdx.x;
  const int y = blockIdx.y, z = blockIdx.z;
  float fx = 0.f, fy = 0.f, fz = 0.f;
  if (x < P.nx) {
    const size_t n = (size_t)x + (size_t)P.nx * ((size_t)y + (size_t)P.ny * z);
    if (!solid[n]) {
      const float U = P.u_in;
      float f[Q];
      // Rolling road: populations entering from the ground carry the road's
      // velocity (-U, 0, 0), so the ground never grows a stationary boundary
      // layer. The density is chosen so the mass entering from the road equals
      // the mass that left into it (sum of feq over the 5 upward directions is
      // exactly rho/6), making the ground impermeable. (Moving halfway
      // bounce-back was linearly unstable next to the equilibrium inlet here.)
      float rhoWall = 1.f;
      if (y == 0) {
        float out = 0.f;
        for (int i = 0; i < Q; i++) if (CY[i] == -1) out += ld(fin, i, P.n, n, W[i]);
        rhoWall = 6.f * out;
      }
      // Pressure outlet: populations entering from beyond x = 0 are the
      // equilibrium at p_inf (rho = 1) and this cell's own velocity, so the
      // tunnel has a pressure reference and wake pressure waves leave cleanly.
      float uox = 0.f, uoy = 0.f, uoz = 0.f;
      if (x == 0) {
        float r = 0.f;
        for (int i = 0; i < Q; i++) {
          const float fi = ld(fin, i, P.n, n, W[i]);
          r += fi; uox += fi * CX[i]; uoy += fi * CY[i]; uoz += fi * CZ[i];
        }
        uox /= r; uoy /= r; uoz /= r;
        uox = fminf(uox, 0.f);  // never let the outlet push air back upstream
      }
      #pragma unroll
      for (int i = 0; i < Q; i++) {
        const int sx = x - CX[i], sy = y - CY[i], sz = z - CZ[i];
        float v;
        if (sy < 0) {
          v = feq(i, rhoWall, -U, 0.f, 0.f, U * U);
        } else if (sx >= P.nx || sy >= P.ny || sz >= P.nz || (sz < 0 && !P.sym)) {
          v = feq(i, 1.f, -U, 0.f, 0.f, U * U);           // far field / inlet
        } else if (sx < 0) {
          v = feq(i, 1.f, uox, uoy, uoz, uox * uox + uoy * uoy + uoz * uoz);  // pressure outlet
        } else if (sz < 0) {
          // Symmetry plane: the mirror image of cell z = -1 is cell z = 0, so take
          // the z-mirrored population from the same (x, y) neighbour at z = 0.
          const size_t s = (size_t)sx + (size_t)P.nx * (size_t)sy;
          v = solid[s] ? ld(fin, OPP[i], P.n, n, W[i]) : ld(fin, MZ[i], P.n, s, W[i]);
        } else {
          const size_t s = (size_t)sx + (size_t)P.nx * ((size_t)sy + (size_t)P.ny * sz);
          if (solid[s]) {
            const float fo = ld(fin, OPP[i], P.n, n, W[i]);
            v = fo;                                        // no-slip bounce-back
            if (P.force) {                                 // momentum exchange on the car
              fx += 2.f * fo * CX[OPP[i]]; fy += 2.f * fo * CY[OPP[i]]; fz += 2.f * fo * CZ[OPP[i]];
            }
          } else {
            v = ld(fin, i, P.n, s, W[i]);
          }
        }
        f[i] = v;
      }

      float rho = 0.f, ux = 0.f, uy = 0.f, uz = 0.f;
      #pragma unroll
      for (int i = 0; i < Q; i++) { rho += f[i]; ux += f[i] * CX[i]; uy += f[i] * CY[i]; uz += f[i] * CZ[i]; }
      const float inv = 1.f / rho;
      ux *= inv; uy *= inv; uz *= inv;
      const float usq = ux * ux + uy * uy + uz * uz;

      // Non-equilibrium momentum flux Pi_neq = sum c c (f - feq).
      float pxx = 0, pyy = 0, pzz = 0, pxy = 0, pxz = 0, pyz = 0;
      #pragma unroll
      for (int i = 0; i < Q; i++) {
        const float d = f[i] - feq(i, rho, ux, uy, uz, usq);
        pxx += d * CX[i] * CX[i]; pyy += d * CY[i] * CY[i]; pzz += d * CZ[i] * CZ[i];
        pxy += d * CX[i] * CY[i]; pxz += d * CX[i] * CZ[i]; pyz += d * CY[i] * CZ[i];
      }
      const float pipi = pxx * pxx + pyy * pyy + pzz * pzz + 2.f * (pxy * pxy + pxz * pxz + pyz * pyz);

      // Sponge: ramp molecular viscosity up near the outlet to absorb the wake.
      float tau0 = P.tau0;
      if (x < P.sponge) { const float s = 1.f - (float)x / P.sponge; tau0 += 0.35f * s * s; }
      // Smagorinsky eddy viscosity from the local strain rate (Hou et al. 1996).
      const float tau = 0.5f * (tau0 + sqrtf(tau0 * tau0 + 18.f * 1.41421356f * P.cs2_smag * sqrtf(pipi) * inv));
      const float keep = 1.f - 1.f / tau;
      const float tr = (pxx + pyy + pzz) * (1.f / 3.f);

      #pragma unroll
      for (int i = 0; i < Q; i++) {
        // Regularized non-equilibrium part: w_i / (2 cs^4) * Q_i : Pi_neq
        const float ccpi = CX[i] * CX[i] * pxx + CY[i] * CY[i] * pyy + CZ[i] * CZ[i] * pzz
                         + 2.f * (CX[i] * CY[i] * pxy + CX[i] * CZ[i] * pxz + CY[i] * CZ[i] * pyz);
        const float f1 = 4.5f * W[i] * (ccpi - tr);  // tr = cs^2 * trace(Pi)
        st(fout, i, P.n, n, W[i], feq(i, rho, ux, uy, uz, usq) + keep * f1);
      }

      if (P.accumulate) {
        float4 a = avg[n];
        a.x += ux; a.y += uy; a.z += uz; a.w += rho;
        avg[n] = a;
      }
    }
  }
  if (P.force) {
    // Warp-reduce then one atomic per warp.
    for (int o = 16; o > 0; o >>= 1) {
      fx += __shfl_down_sync(0xffffffff, fx, o);
      fy += __shfl_down_sync(0xffffffff, fy, o);
      fz += __shfl_down_sync(0xffffffff, fz, o);
    }
    if ((threadIdx.x & 31) == 0 && (fx != 0.f || fy != 0.f || fz != 0.f)) {
      atomicAdd(&force[0], (double)fx); atomicAdd(&force[1], (double)fy); atomicAdd(&force[2], (double)fz);
    }
  }
}

__global__ void init_kernel(store_t* f, const uint8_t* solid, Params P) {
  const int x = blockIdx.x * blockDim.x + threadIdx.x;
  if (x >= P.nx) return;
  const size_t n = (size_t)x + (size_t)P.nx * ((size_t)blockIdx.y + (size_t)P.ny * blockIdx.z);
  const float ux = solid[n] ? 0.f : -P.u_in;
  for (int i = 0; i < Q; i++) st(f, i, P.n, n, W[i], feq(i, 1.f, ux, 0.f, 0.f, ux * ux));
}

int main(int argc, char** argv) {
  if (argc < 6) {
    fprintf(stderr, "usage: lbm <grid.bin> <nx> <ny> <nz> <out_prefix> [steps] [avg_start] [u_lb] [nu_lb] [cs] [sym]\n");
    return 1;
  }
  Params P{};
  const char* gridPath = argv[1];
  P.nx = atoi(argv[2]); P.ny = atoi(argv[3]); P.nz = atoi(argv[4]);
  const std::string out = argv[5];
  const int steps = argc > 6 ? atoi(argv[6]) : 20000;
  const int avgStart = argc > 7 ? atoi(argv[7]) : steps / 2;
  P.u_in = argc > 8 ? (float)atof(argv[8]) : 0.07f;
  const float nu = argc > 9 ? (float)atof(argv[9]) : 2e-5f;
  const float cs = argc > 10 ? (float)atof(argv[10]) : 0.13f;
  P.sym = argc > 11 ? atoi(argv[11]) : 0;
  P.tau0 = 3.f * nu + 0.5f;
  P.cs2_smag = cs * cs;
  P.sponge = P.nx / 12;
  P.n = (size_t)P.nx * P.ny * P.nz;

  std::vector<uint8_t> hsolid(P.n);
  FILE* fp = fopen(gridPath, "rb");
  if (!fp || fread(hsolid.data(), 1, P.n, fp) != P.n) { fprintf(stderr, "failed to read %s\n", gridPath); return 1; }
  fclose(fp);

  // Frontal area (cells^2) and a rough length (cells) for the coefficients.
  std::vector<uint8_t> proj((size_t)P.ny * P.nz, 0);
  int xmin = P.nx, xmax = -1;
  for (int z = 0; z < P.nz; z++) for (int y = 0; y < P.ny; y++) for (int x = 0; x < P.nx; x++)
    if (hsolid[(size_t)x + (size_t)P.nx * (y + (size_t)P.ny * z)]) { proj[y + (size_t)P.ny * z] = 1; xmin = std::min(xmin, x); xmax = std::max(xmax, x); }
  double area = 0; for (auto p : proj) area += p;
  if (area == 0) area = 1;  // empty tunnel (BC tests)
  const double L = xmax - xmin + 1;

  cudaDeviceProp prop; CK(cudaGetDeviceProperties(&prop, 0));
  printf("GPU %s | grid %dx%dx%d = %.1fM cells | %.2f GB populations\n", prop.name, P.nx, P.ny, P.nz,
         P.n / 1e6, 2.0 * Q * P.n * sizeof(store_t) / 1e9);
  printf("%s", P.sym ? "half car (symmetry plane at z=0) | " : "");
  printf("U=%.3f nu=%.2e tau0=%.5f Cs=%.2f | car length %.0f cells | Re_lb=%.3g | frontal area %.0f cells^2\n",
         P.u_in, nu, P.tau0, cs, L, P.u_in * L / nu, area);

  store_t *fA, *fB; uint8_t* dsolid; float4* davg; double* dforce;
  CK(cudaMalloc(&fA, sizeof(store_t) * Q * P.n));
  CK(cudaMalloc(&fB, sizeof(store_t) * Q * P.n));
  CK(cudaMalloc(&dsolid, P.n));
  CK(cudaMalloc(&davg, sizeof(float4) * P.n));
  CK(cudaMalloc(&dforce, sizeof(double) * 3));
  CK(cudaMemcpy(dsolid, hsolid.data(), P.n, cudaMemcpyHostToDevice));
  CK(cudaMemset(davg, 0, sizeof(float4) * P.n));

  const dim3 block(128), grid((P.nx + 127) / 128, P.ny, P.nz);
  init_kernel<<<grid, block>>>(fA, dsolid, P);
  CK(cudaGetLastError());

  FILE* fcsv = fopen((out + "_forces.csv").c_str(), "w");
  fprintf(fcsv, "step,Cd,Cl,Cside\n");
  const double qA = 0.5 * 1.0 * P.u_in * P.u_in * area;
  // The force is summed on the GPU every step and reported as a 50-step mean:
  // single-step samples alias with the tunnel's acoustic oscillations.
  const int forceEvery = 50;
  int nAvg = 0;
  double sumCd = 0, sumCl = 0; int nCoef = 0;
  CK(cudaMemset(dforce, 0, sizeof(double) * 3));
  P.force = 1;
  auto t0 = std::chrono::steady_clock::now();
  for (int t = 1; t <= steps; t++) {
    P.accumulate = t > avgStart;
    step_kernel<<<grid, block>>>(fA, fB, dsolid, P, davg, dforce);
    std::swap(fA, fB);
    nAvg += P.accumulate;
    if (t % forceEvery == 0) {
      double F[3]; CK(cudaMemcpy(F, dforce, sizeof(F), cudaMemcpyDeviceToHost));
      CK(cudaMemset(dforce, 0, sizeof(double) * 3));
      for (double& v : F) v /= forceEvery;
      // Air moves toward -x, so drag on the car points along -x.
      const double Cd = -F[0] / qA, Cl = F[1] / qA, Cs = F[2] / qA;
      fprintf(fcsv, "%d,%.5f,%.5f,%.5f\n", t, Cd, Cl, Cs);
      if (!std::isfinite(Cd)) { fprintf(stderr, "diverged at step %d\n", t); return 2; }
      if (P.accumulate) { sumCd += Cd; sumCl += Cl; nCoef++; }
      if (t % 1000 == 0) {
        CK(cudaDeviceSynchronize());
        const double sec = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        printf("step %6d/%d  Cd=%7.3f  Cl=%7.3f  | %.0f MLUPS, ETA %.0fs\n", t, steps, Cd, Cl,
               (double)P.n * t / sec / 1e6, sec / t * (steps - t));
        fflush(stdout);
      }
    }
  }
  fclose(fcsv);
  CK(cudaDeviceSynchronize());
  if (nCoef) printf("MEAN over averaging window: Cd=%.3f  Cl=%.3f (negative = downforce)\n", sumCd / nCoef, sumCl / nCoef);

  // Normalise averages: velocity / U, pressure -> Cp.
  std::vector<float4> havg(P.n);
  CK(cudaMemcpy(havg.data(), davg, sizeof(float4) * P.n, cudaMemcpyDeviceToHost));
  const float inv = nAvg ? 1.f / nAvg : 0.f;
  const float qinf = 0.5f * P.u_in * P.u_in;
  for (size_t i = 0; i < P.n; i++) {
    float4& a = havg[i];
    if (hsolid[i]) { a = make_float4(0, 0, 0, 0); continue; }
    a.x = a.x * inv / P.u_in; a.y = a.y * inv / P.u_in; a.z = a.z * inv / P.u_in;
    a.w = (a.w * inv - 1.f) / 3.f / qinf;  // p = rho cs^2
  }
  FILE* fo = fopen((out + "_avg.f32").c_str(), "wb");
  fwrite(havg.data(), sizeof(float4), P.n, fo);
  fclose(fo);
  printf("wrote %s_avg.f32 (%d averaged steps)\n", out.c_str(), nAvg);
  return 0;
}
