# CUDA CFD pipeline

The site's streamlines are traced through a real, time-averaged flow field computed
offline by a GPU lattice Boltzmann solver (`lbm.cu`). The result ships as
`flow/rb19.flow` (a gzip'd int8 grid, a few MB), and the page loads it next to
`rb19.glb`. Visitors don't need a GPU. The CUDA work happens once, here.

## Solver (`lbm.cu`)

- **D3Q19 lattice Boltzmann**, regularized BGK collision with a **Smagorinsky LES**
  eddy viscosity, so it stays stable at the very low viscosity a race car needs.
- **Car:** halfway bounce-back (no-slip) on the voxelized body.
- **Rolling road:** air enters from the ground at freestream speed. The density is
  chosen so the road is impermeable. This mirrors an F1 wind tunnel's moving belt.
- **Inlet / ceiling / sides:** freestream equilibrium. **Outlet:** fixed pressure
  plus a viscous sponge that absorbs the wake.
- **Forces:** momentum exchange on every car link, summed every step, giving drag
  and lift coefficients on the frontal area (`Cl < 0` = downforce).
- **Memory:** populations are stored as fp16 relative deviations, and an optional
  z = 0 symmetry plane simulates half the car. Together these fit a 50M-cell,
  1.25 cm tunnel in about 4.5 GB.
- **Output:** time-averaged velocity and pressure coefficient per cell.

Throughput is about 1.5 billion cell updates per second on an RTX 5060 Laptop GPU.

**Validation:** a cube in free stream gives Cd 1.06 (fp16) / 1.05 (fp32), against
about 1.05 in the literature. A half cube on the symmetry plane gives 1.05.

## Rebuilding the flow field

```bat
:: 1. export the exact triangles the site renders (serve the repo, open the page)
python cuda/export_server.py
::    -> open http://127.0.0.1:8765/cuda/export.html, wait for "done", then Ctrl+C

:: 2. voxelize the half tunnel at 1.25 cm (prints the grid dims for step 3)
python cuda/voxelize.py --dx 0.0125 --half --out cuda/grid_half.bin

:: 3. build and run the solver (needs the CUDA toolkit + Visual Studio C++), ~25 min
cuda\build.bat
cuda\lbm.exe cuda\grid_half.bin 1160 224 192 cuda\out\half 40000 20000 0.07 1e-5 0.13 1

:: 4. pack for the web (mirrors the half back to a full car) and take a quick look
python cuda/pack_flow.py cuda/out/half cuda/grid_half.json flow/rb19.flow --dx 0.0375
python cuda/viz.py cuda/out/half cuda/grid_half.json
```

Solver arguments: `grid nx ny nz out_prefix [steps] [avg_start] [u_lattice] [nu_lattice] [smagorinsky_cs] [symmetry]`.

For a quick look, use a coarse full-width tunnel: `voxelize.py --dx 0.05` with
`lbm.exe ... 340 64 120 ... 12000 6000`, which takes about 20 seconds.

## Honest limits

- The lattice Reynolds number is about 3M, below a real F1 car's roughly 10–20M. LES
  covers the unresolved turbulence, but boundary layers aren't resolved (there's no
  wall model), so separation points are approximate.
- The geometry is a visual model, voxelized at 1.25 cm. The floor sits 5–8 cm off
  the road (4–6 cells), and wing elements are a few cells thick, so the absolute
  downforce is less trustworthy than the flow pattern.
- The simulation assumes the car is symmetric left to right. The wheels are
  stationary solids (no rotation), and there are no cooling internals.
- The isolated-part views on the site trace through the full-car field, so you see
  each part working in the car's real flow.
