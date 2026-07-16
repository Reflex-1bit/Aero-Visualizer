# -*- coding: utf-8 -*-
"""Fix rear-wing aero: place station on mesh, carve voxels, strengthen near-field."""
from pathlib import Path
import re

path = Path(r"c:\Model\index.html")
t = path.read_text(encoding="utf-8")

# --- 1) Better horseshoeWorld (relative z) + stronger rearWingInduced ---
old_hw = """// Horseshoe in WORLD coordinates (bound vortex at x,y spanning ±spanHalf in z)
function horseshoeWorld(P, x, y, spanHalf, Gamma) {
  return horseshoeVelocity(
    new THREE.Vector3(P.x - x, P.y - y, P.z),
    spanHalf, 0, 0, Gamma
  );
}"""

new_hw = """// Horseshoe in WORLD coordinates (bound vortex at x,y spanning ±spanHalf in z)
function horseshoeWorld(P, x, y, spanHalf, Gamma) {
  return horseshoeVelocity(
    new THREE.Vector3(P.x - x, P.y - y, P.z),
    spanHalf, 0, 0, Gamma
  );
}

function clearWingVoxels(cx, cy, rx, ry, rz) {
  if (!carVoxels) return;
  const { origin, cell, nx, ny, nz, solid } = carVoxels;
  const i0x = Math.max(0, Math.floor((cx - rx - origin.x) / cell));
  const i1x = Math.min(nx - 1, Math.floor((cx + rx - origin.x) / cell));
  const i0y = Math.max(0, Math.floor((cy - ry - origin.y) / cell));
  const i1y = Math.min(ny - 1, Math.floor((cy + ry - origin.y) / cell));
  const i0z = Math.max(0, Math.floor((0 - rz - origin.z) / cell));
  const i1z = Math.min(nz - 1, Math.floor((0 + rz - origin.z) / cell));
  for (let ix = i0x; ix <= i1x; ix++) {
    for (let iy = i0y; iy <= i1y; iy++) {
      for (let iz = i0z; iz <= i1z; iz++) {
        const wx = origin.x + (ix + 0.5) * cell;
        const wy = origin.y + (iy + 0.5) * cell;
        const wz = origin.z + (iz + 0.5) * cell;
        const ex = (wx - cx) / rx, ey = (wy - cy) / ry, ez = wz / rz;
        if (ex * ex + ey * ey + ez * ez <= 1) solid[ix + nx * (iy + ny * iz)] = 0;
      }
    }
  }
}"""

if old_hw not in t:
    raise SystemExit("horseshoeWorld block missing")
t = t.replace(old_hw, new_hw, 1)

# --- 2) Replace rearWingInduced with amplified near-field ---
old_rwi = """function rearWingInduced(Pl) {
  // Induced field only (no freestream) in aero-local coords
  const v = new THREE.Vector3();
  v.add(horseshoeVelocity(Pl, SPAN / 2, 0, 0, state.gammaMain));
  v.add(horseshoeVelocity(Pl, SPAN * 0.94 / 2, MAIN_CHORD * 0.72, 0.12, state.gammaFlap));
  if (panelSystem && panelSystem.panels && panelSystem.sigma) {
    for (let j = 0; j < panelSystem.panels.length; j++) {
      const sig = panelSystem.sigma[j];
      if (!isFinite(sig)) continue;
      const infl = panelSourceInfluence2D(Pl, panelSystem.panels[j], sig);
      if (isFinite(infl.x) && isFinite(infl.y)) {
        v.x += infl.x;
        v.y += infl.y;
      }
    }
  }
  return v;
}"""

new_rwi = """function rearWingInduced(Pl) {
  // Induced field only (no freestream) in aero-local coords — same as your wing viz
  const v = new THREE.Vector3();
  v.add(horseshoeVelocity(Pl, SPAN / 2, 0, 0, state.gammaMain));
  v.add(horseshoeVelocity(Pl, SPAN * 0.94 / 2, MAIN_CHORD * 0.72, 0.12, state.gammaFlap));
  if (panelSystem && panelSystem.panels && panelSystem.sigma) {
    for (let j = 0; j < panelSystem.panels.length; j++) {
      const sig = panelSystem.sigma[j];
      if (!isFinite(sig)) continue;
      const infl = panelSourceInfluence2D(Pl, panelSystem.panels[j], sig);
      if (isFinite(infl.x) && isFinite(infl.y)) {
        v.x += infl.x;
        v.y += infl.y;
      }
    }
  }
  // Near-field gain: car-scale freestream dwarfs wing Γ unless we boost locally
  const r2 = Pl.x * Pl.x + Pl.y * Pl.y;
  const gain = 1.35 + 3.2 * Math.exp(-r2 / 0.28);
  v.multiplyScalar(gain);
  return v;
}"""

if old_rwi not in t:
    raise SystemExit("rearWingInduced missing")
t = t.replace(old_rwi, new_rwi, 1)
print("induced ok")

# --- 3) Fix station placement after bbox + carve wing voxels ---
old_stations = """  const fb = new THREE.Box3().setFromObject(carGroup);
  const fsz = fb.getSize(new THREE.Vector3());
  // Map aero stations onto the fitted car
  WING_X = fb.min.x + 0.55;
  WING_Y = fb.min.y + fsz.y * 0.72;
  carStations.frontWing.x = fb.max.x - 0.35;
  carStations.frontWing.y = fb.min.y + 0.12;
  carStations.frontWing.span = Math.min(1.85, fsz.z * 0.92);
  carStations.diffuser.x = fb.min.x + 0.45;
  carStations.diffuser.y = fb.min.y + 0.10;
  carStations.diffuser.span = Math.min(1.4, fsz.z * 0.75);
  carStations.floorX0 = fb.min.x + 0.7;
  carStations.floorX1 = fb.max.x - 0.5;
  carStations.floorY = fb.min.y + 0.07;
  carStations.bodyX0 = fb.min.x + 1.0;
  carStations.bodyX1 = fb.max.x - 1.1;
  carStations.bodyHalfW = fsz.z * 0.28;"""

new_stations = """  const fb = new THREE.Box3().setFromObject(carGroup);
  const fsz = fb.getSize(new THREE.Vector3());

  // Detect nose: the end whose top is LOWER is the nose (front wing height << airbox/rear wing)
  let peakLoX = 0, peakHiX = 0;
  carGroup.updateMatrixWorld(true);
  carGroup.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return;
    const pos = obj.geometry.attributes.position;
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i += 20) {
      v.fromBufferAttribute(pos, i).applyMatrix4(obj.matrixWorld);
      const u = (v.x - fb.min.x) / Math.max(fsz.x, 1e-6);
      if (u < 0.18) peakLoX = Math.max(peakLoX, v.y);
      if (u > 0.82) peakHiX = Math.max(peakHiX, v.y);
    }
  });
  const noseAtMaxX = peakHiX < peakLoX; // nose = short end
  const rearMinX = noseAtMaxX; // if nose at max x, rear is min x

  // Place rear wing on the high geometry in the rear 22% of the car
  let rwX = 0, rwY = 0, rwN = 0;
  let fwX = 0, fwY = 0, fwN = 0;
  carGroup.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return;
    const pos = obj.geometry.attributes.position;
    const v = new THREE.Vector3();
    for (let i = 0; i < pos.count; i += 12) {
      v.fromBufferAttribute(pos, i).applyMatrix4(obj.matrixWorld);
      const u = (v.x - fb.min.x) / Math.max(fsz.x, 1e-6);
      const atRear = rearMinX ? (u < 0.22) : (u > 0.78);
      const atFront = rearMinX ? (u > 0.82) : (u < 0.18);
      if (atRear && v.y > fb.min.y + fsz.y * 0.45) { rwX += v.x; rwY += v.y; rwN++; }
      if (atFront && v.y < fb.min.y + fsz.y * 0.35) { fwX += v.x; fwY += v.y; fwN++; }
    }
  });
  WING_X = rwN ? (rwX / rwN) : (rearMinX ? fb.min.x + 0.5 : fb.max.x - 0.5);
  WING_Y = rwN ? (rwY / rwN) : (fb.min.y + fsz.y * 0.78);
  carStations.frontWing.x = fwN ? (fwX / fwN) : (rearMinX ? fb.max.x - 0.35 : fb.min.x + 0.35);
  carStations.frontWing.y = fwN ? (fwY / fwN) : (fb.min.y + 0.12);
  carStations.frontWing.span = Math.min(1.85, fsz.z * 0.92);
  carStations.diffuser.x = rearMinX ? fb.min.x + 0.45 : fb.max.x - 0.45;
  carStations.diffuser.y = fb.min.y + 0.10;
  carStations.diffuser.span = Math.min(1.4, fsz.z * 0.75);
  carStations.floorX0 = fb.min.x + 0.7;
  carStations.floorX1 = fb.max.x - 0.5;
  carStations.floorY = fb.min.y + 0.07;
  carStations.bodyX0 = fb.min.x + 1.0;
  carStations.bodyX1 = fb.max.x - 1.1;
  carStations.bodyHalfW = fsz.z * 0.28;

  // CRITICAL: open voxel cavities at the wings so YOUR panel/horseshoe solve owns the flow there
  // (dilated body voxels were sealing the rear wing and killing the aero)
  clearWingVoxels(WING_X + MAIN_CHORD * 0.15, WING_Y + 0.06, 0.65, 0.42, SPAN * 0.58);
  clearWingVoxels(carStations.frontWing.x, carStations.frontWing.y, 0.45, 0.28, carStations.frontWing.span * 0.55);
  console.log('[aero] rear wing @', WING_X.toFixed(2), WING_Y.toFixed(2), 'front @', carStations.frontWing.x.toFixed(2), carStations.frontWing.y.toFixed(2), 'noseAtMaxX', noseAtMaxX);"""

if old_stations not in t:
    raise SystemExit("stations block missing")
t = t.replace(old_stations, new_stations, 1)
print("stations ok")

# --- 4) Also make wall-slide weaker near rear wing so aero field dominates ---
old_slide = """function applyWallSlide(p, v) {
  const o = occupancy(p);
  if (o < 0.2) return v;
  const n = solidNormal(p);
  const into = v.dot(n);
  if (into < 0) v.addScaledVector(n, -into);
  if (o > 0.45) v.addScaledVector(n, (o - 0.45) * state.Vinf * 1.8);
  return v;
}"""

new_slide = """function applyWallSlide(p, v) {
  // Near the rear-wing aero box, let the panel/horseshoe field win (don't fight it with voxels)
  const dx = p.x - WING_X, dy = p.y - WING_Y;
  if (dx * dx + dy * dy < 0.55 * 0.55 && Math.abs(p.z) < SPAN * 0.6) return v;

  const o = occupancy(p);
  if (o < 0.2) return v;
  const n = solidNormal(p);
  const into = v.dot(n);
  if (into < 0) v.addScaledVector(n, -into);
  if (o > 0.45) v.addScaledVector(n, (o - 0.45) * state.Vinf * 1.8);
  return v;
}"""

if old_slide not in t:
    raise SystemExit("slide missing")
t = t.replace(old_slide, new_slide, 1)
print("slide ok")

# --- 5) Tiny gold markers at wing stations so placement is obvious (optional visual) ---
# Add after recompute() call in loader - a small debug group
old_ready = """  document.getElementById('loading').classList.add('hidden');
  aeroReady = true;
  recompute();"""

new_ready = """  document.getElementById('loading').classList.add('hidden');
  aeroReady = true;

  // Gold station markers (rear wing aero origin + front wing)
  const mark = (x, y, color) => {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(0.04, 10, 10),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 })
    );
    m.position.set(x, y, 0);
    carGroup.add(m);
  };
  mark(WING_X, WING_Y, NEON_GOLD);
  mark(carStations.frontWing.x, carStations.frontWing.y, NEON_CYAN);

  recompute();"""

if old_ready not in t:
    raise SystemExit("ready block missing")
t = t.replace(old_ready, new_ready, 1)
print("markers ok")

path.write_text(t, encoding="utf-8")
print("done", path.stat().st_size)
