# -*- coding: utf-8 -*-
from pathlib import Path
import re

path = Path(r"c:\Model\index.html")
t = path.read_text(encoding="utf-8")

t = t.replace("voxelizeCar(shell, 0.065);", "voxelizeCar(shell, 0.045);")
t = t.replace(
    "const stride = triCount > 80000 ? 3 : (triCount > 30000 ? 2 : 1);",
    "const stride = triCount > 120000 ? 2 : 1;",
)

old_dilate = """  // Dilate once so thin panels (wings) don't leak
  const dilate = new Uint8Array(solid);
  const nbs = [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]];
  for (let ix = 1; ix < nx - 1; ix++) {
    for (let iy = 1; iy < ny - 1; iy++) {
      for (let iz = 1; iz < nz - 1; iz++) {
        const i = ix + nx * (iy + ny * iz);
        if (solid[i]) continue;
        for (const [dx,dy,dz] of nbs) {
          if (solid[(ix+dx) + nx * ((iy+dy) + ny * (iz+dz))]) { dilate[i] = 1; break; }
        }
      }
    }
  }
  let filled = 0;
  for (let i = 0; i < dilate.length; i++) if (dilate[i]) filled++;
  carVoxels = { solid: dilate, origin, cell: cellSize, nx, ny, nz };"""

new_dilate = """  const nbs = [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]];
  function dilateOnce(src) {
    const out = new Uint8Array(src);
    for (let ix = 1; ix < nx - 1; ix++) {
      for (let iy = 1; iy < ny - 1; iy++) {
        for (let iz = 1; iz < nz - 1; iz++) {
          const i = ix + nx * (iy + ny * iz);
          if (src[i]) continue;
          for (const [dx,dy,dz] of nbs) {
            if (src[(ix+dx) + nx * ((iy+dy) + ny * (iz+dz))]) { out[i] = 1; break; }
          }
        }
      }
    }
    return out;
  }
  const dilate = dilateOnce(dilateOnce(solid));
  let filled = 0;
  for (let i = 0; i < dilate.length; i++) if (dilate[i]) filled++;
  carVoxels = { solid: dilate, origin, cell: cellSize, nx, ny, nz };"""

if old_dilate not in t:
    raise SystemExit("dilate missing")
t = t.replace(old_dilate, new_dilate, 1)
print("dilate ok")

# Replace pushOutOfCar only
m = re.search(r"function pushOutOfCar\(p, preferDir\) \{.*?\n\}", t, re.S)
if not m:
    raise SystemExit("pushOut missing")

new_push = r'''function occupancy(p) {
  if (!carVoxels) return 0;
  const { origin, cell, nx, ny, nz, solid } = carVoxels;
  const fx = (p.x - origin.x) / cell;
  const fy = (p.y - origin.y) / cell;
  const fz = (p.z - origin.z) / cell;
  const ix = Math.floor(fx), iy = Math.floor(fy), iz = Math.floor(fz);
  if (ix < 1 || iy < 1 || iz < 1 || ix >= nx - 2 || iy >= ny - 2 || iz >= nz - 2) return 0;
  let s = 0, w = 0;
  for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
    const jx = ix + dx, jy = iy + dy, jz = iz + dz;
    const d2 = (fx - jx - 0.5) ** 2 + (fy - jy - 0.5) ** 2 + (fz - jz - 0.5) ** 2;
    const wt = 1 / (0.35 + d2);
    s += solid[jx + nx * (jy + ny * jz)] * wt; w += wt;
  }
  return s / w;
}
function solidNormal(p) {
  const e = (carVoxels ? carVoxels.cell : 0.05) * 0.85;
  const gx = occupancy(new THREE.Vector3(p.x + e, p.y, p.z)) - occupancy(new THREE.Vector3(p.x - e, p.y, p.z));
  const gy = occupancy(new THREE.Vector3(p.x, p.y + e, p.z)) - occupancy(new THREE.Vector3(p.x, p.y - e, p.z));
  const gz = occupancy(new THREE.Vector3(p.x, p.y, p.z + e)) - occupancy(new THREE.Vector3(p.x, p.y, p.z - e));
  const n = new THREE.Vector3(-gx, -gy, -gz);
  return n.lengthSq() < 1e-10 ? new THREE.Vector3(0, 1, 0) : n.normalize();
}
function pushOutOfCar(p, preferDir) {
  if (!carVoxels || occupancy(p) < 0.35) return p.clone();
  let q = p.clone();
  for (let i = 0; i < 24; i++) {
    if (occupancy(q) < 0.28) break;
    q.addScaledVector(solidNormal(q), carVoxels.cell * 0.4);
  }
  return q;
}
function applyWallSlide(p, v) {
  const o = occupancy(p);
  if (o < 0.2) return v;
  const n = solidNormal(p);
  const into = v.dot(n);
  if (into < 0) v.addScaledVector(n, -into);
  if (o > 0.45) v.addScaledVector(n, (o - 0.45) * state.Vinf * 1.8);
  return v;
}
function advanceSafe(p, v, dt) {
  let speed = v.length();
  if (speed < 1e-6) return p.clone();
  const dir = v.clone().normalize();
  let step = speed * dt;
  let next = p.clone().addScaledVector(dir, step);
  if (occupancy(next) > 0.5 || isCarSolid(next)) {
    let lo = 0, hi = 1;
    for (let k = 0; k < 8; k++) {
      const m = (lo + hi) * 0.5;
      const trial = p.clone().addScaledVector(dir, step * m);
      if (occupancy(trial) > 0.5 || isCarSolid(trial)) hi = m; else lo = m;
    }
    next = p.clone().addScaledVector(dir, step * lo);
    let v2 = applyWallSlide(next, v.clone());
    next.addScaledVector(v2, dt * (1 - lo) * 0.85);
    if (occupancy(next) > 0.55) next = pushOutOfCar(next, v2);
  }
  return next;
}
function declutterPath(pts) {
  if (pts.length < 3) return pts;
  const out = [pts[0].clone()];
  for (let i = 1; i < pts.length - 1; i++) {
    const prev = out[out.length - 1], cur = pts[i], nxt = pts[i + 1];
    if (prev.distanceTo(cur) < 0.012) continue;
    const a = cur.clone().sub(prev).normalize();
    const b = nxt.clone().sub(cur).normalize();
    if (a.dot(b) < 0.15) continue;
    out.push(cur.clone());
  }
  out.push(pts[pts.length - 1].clone());
  if (out.length < 4) return out;
  const smooth = [out[0].clone()];
  for (let i = 0; i < out.length - 1; i++) {
    smooth.push(out[i].clone().lerp(out[i + 1], 0.25));
    smooth.push(out[i].clone().lerp(out[i + 1], 0.75));
  }
  smooth.push(out[out.length - 1].clone());
  return smooth;
}'''

t = t[:m.start()] + new_push + t[m.end():]
print("push/helpers ok")

# Replace integrateStreamline
m2 = re.search(r"function integrateStreamline\(seed\) \{.*?\n\}", t, re.S)
if not m2:
    raise SystemExit("integrate missing")

new_int = r'''function integrateStreamline(seed) {
  const pts = [seed.clone()];
  let p = seed.clone();
  if (occupancy(p) > 0.4) p = pushOutOfCar(p, new THREE.Vector3(-1, 0.2, 0));

  for (let i = 0; i < STREAM_STEPS; i++) {
    for (let sub = 0; sub < 4; sub++) {
      const dt = STREAM_DT / 4;
      let v = fieldVelocityWorld(p);
      if (!v || !isFinite(v.x) || v.length() < 1e-5) { i = STREAM_STEPS; break; }
      v = applyWallSlide(p, v);
      const mid = p.clone().addScaledVector(v, dt * 0.5);
      let vMid = applyWallSlide(mid, fieldVelocityWorld(mid));
      let next = advanceSafe(p, vMid, dt);

      const pA = worldToAero(p), nA = worldToAero(next);
      const r2d = { x: nA.x - pA.x, y: nA.y - pA.y };
      let closestT = null, hitPanel = null;
      for (const panel of panelSystem.panels) {
        const hit = segIntersect2D({ x: pA.x, y: pA.y }, r2d, panel.a, { x: panel.b.x - panel.a.x, y: panel.b.y - panel.a.y });
        if (hit && (closestT === null || hit.t < closestT)) { closestT = hit.t; hitPanel = panel; }
      }
      if (closestT !== null && hitPanel) {
        const c = state.tubeRadius + 0.014;
        next = aeroToWorld(new THREE.Vector3(
          pA.x + r2d.x * closestT + hitPanel.nx * c,
          pA.y + r2d.y * closestT + hitPanel.ny * c,
          nA.z
        ));
      }

      p = next;
      pts.push(p.clone());
      if (p.x < -5.2 || Math.abs(p.z) > 2.6 || p.y < -0.1 || p.y > 2.6) { i = STREAM_STEPS; break; }
    }
  }
  return declutterPath(pts);
}'''

t = t[:m2.start()] + new_int + t[m2.end():]
print("integrate ok")

# More seeds
t = t.replace(
    "const N_SPAN_SEEDS = 5, N_HEIGHT_SEEDS = 5, STREAM_STEPS = 140, STREAM_DT = 0.06, SEED_X = 4.5;",
    "const N_SPAN_SEEDS = 8, N_HEIGHT_SEEDS = 7, STREAM_STEPS = 160, STREAM_DT = 0.045, SEED_X = 4.5;",
)

# buildStreamlines seed loops
old_build_inner = """  // Seed a sparse sheet upstream — keep the car readable
  for (let hi = 0; hi < N_HEIGHT_SEEDS; hi++) {
    const yFrac = hi / (N_HEIGHT_SEEDS - 1); // 0..1
    const y = 0.25 + yFrac * 1.05; // skip ground clutter, focus mid→wing
    for (let si = 0; si < N_SPAN_SEEDS; si++) {
      const zFrac = (si / (N_SPAN_SEEDS - 1)) * 2 - 1;
      const z = zFrac * 0.85;
      const seed = new THREE.Vector3(SEED_X, y, z);
      const side = (y > WING_Y) ? 1 : -1;
      const pts = integrateStreamline(seed);
      if (pts.length < 6) continue;

      // Drop degenerate paths (barely moved)
      if (pts[0].distanceTo(pts[pts.length - 1]) < 0.4) continue;

      const color = side > 0 ? RED : BLUE;
      try {
        const curve = new THREE.CatmullRomCurve3(pts);
        const tubeGeo = new THREE.TubeGeometry(curve, Math.max(24, Math.min(100, pts.length)), state.tubeRadius, 6, false);
        const mat = new THREE.MeshBasicMaterial({
          color, transparent: true, opacity: 0.42, depthWrite: false
        });
        streamlineGroup.add(new THREE.Mesh(tubeGeo, mat));
      } catch (e) {
        continue;
      }"""

new_build_inner = """  for (let hi = 0; hi < N_HEIGHT_SEEDS; hi++) {
    const yFrac = hi / (N_HEIGHT_SEEDS - 1);
    const y = 0.18 + yFrac * 1.2;
    for (let si = 0; si < N_SPAN_SEEDS; si++) {
      const zFrac = (si / (N_SPAN_SEEDS - 1)) * 2 - 1;
      const z = zFrac * 1.05;
      const seed = new THREE.Vector3(SEED_X, y, z);
      if (occupancy(seed) > 0.4) continue;
      const side = (y > WING_Y) ? 1 : -1;
      const pts = integrateStreamline(seed);
      if (pts.length < 8) continue;
      if (pts[0].distanceTo(pts[pts.length - 1]) < 0.8) continue;

      const color = side > 0 ? RED : BLUE;
      try {
        const curve = new THREE.CatmullRomCurve3(pts);
        const tubeGeo = new THREE.TubeGeometry(curve, Math.max(32, Math.min(120, pts.length)), state.tubeRadius, 5, false);
        const mat = new THREE.MeshBasicMaterial({
          color, transparent: true, opacity: 0.5, depthWrite: false
        });
        streamlineGroup.add(new THREE.Mesh(tubeGeo, mat));
      } catch (e) {
        continue;
      }"""

if old_build_inner not in t:
    raise SystemExit("build inner missing")
t = t.replace(old_build_inner, new_build_inner, 1)
print("build ok")

path.write_text(t, encoding="utf-8")
print("done", path.stat().st_size)
