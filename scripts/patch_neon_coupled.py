# -*- coding: utf-8 -*-
"""Restore neon silhouette + full-car aero interactions feeding the rear wing wind."""
from pathlib import Path

path = Path(r"c:\Model\index.html")
t = path.read_text(encoding="utf-8")

# --- Caption / title ---
t = t.replace(
    "solid body · ML wing solve · no-penetration flow",
    "neon silhouette · coupled front→floor→rear wing flow",
)
t = t.replace(
    """<div class="caption">
  Solid flat-shaded car · wind cannot pass through voxels.<br>
  ML Cl → Γ → horseshoe + panels on the rear wing.<br>
  Neon green = key aero edges.
</div>""",
    """<div class="caption">
  Neon silhouette (white / cyan / gold).<br>
  Wind couples front wing → floor/diffuser → rear wing<br>
  via horseshoes + your ML panel solve. Body is sealed.
</div>""",
)

# --- Replace fieldVelocityWorld / stations + vortex-only / fieldVelocity ---
# First add carStations after WING_Y declarations
old_wing = """let WING_X = -2.55, WING_Y = 0.95;
function worldToAero(P) { return new THREE.Vector3(P.x - WING_X, P.y - WING_Y, P.z); }
function aeroToWorld(P) { return new THREE.Vector3(P.x + WING_X, P.y + WING_Y, P.z); }
function fieldVelocityWorld(Pworld) { return fieldVelocity(worldToAero(Pworld)); }"""

new_wing = """let WING_X = -2.55, WING_Y = 0.95;
// Stations for how the whole car feeds the rear wing (set after mesh load)
const carStations = {
  frontWing: { x: 2.4, y: 0.14, span: 1.75, chord: 0.32 },
  floorY: 0.08,
  floorX0: -1.8,
  floorX1: 2.0,
  diffuser: { x: -2.35, y: 0.12, span: 1.35 },
  bodyHalfW: 0.55,
  bodyX0: -1.6,
  bodyX1: 1.4,
};
function worldToAero(P) { return new THREE.Vector3(P.x - WING_X, P.y - WING_Y, P.z); }
function aeroToWorld(P) { return new THREE.Vector3(P.x + WING_X, P.y + WING_Y, P.z); }

// Horseshoe in WORLD coordinates (bound vortex at x,y spanning ±spanHalf in z)
function horseshoeWorld(P, x, y, spanHalf, Gamma) {
  return horseshoeVelocity(
    new THREE.Vector3(P.x - x, P.y - y, P.z),
    spanHalf, 0, 0, Gamma
  );
}

// --- Car / wing interactions ---
// Front wing: downforce horseshoe → downwash in the wake that changes rear-wing inflow AoA
// Floor: Venturi acceleration under the tub (faster -x between floor and ground)
// Diffuser: converts underfloor speed into upwash that feeds the rear wing underside
// Body: mild spanwise displacement around the sidepods (blockage)
// Rear wing: your ML Cl → Γ + panel method (in aero frame)
function floorDiffuserVelocity(P) {
  const v = new THREE.Vector3();
  const fw = carStations.frontWing;
  const diff = carStations.diffuser;

  // Underfloor venturi: between ground and floor plane, mid-car
  if (P.y < carStations.floorY + 0.18 && P.y > 0.02 &&
      P.x > carStations.floorX0 && P.x < carStations.floorX1 &&
      Math.abs(P.z) < carStations.bodyHalfW + 0.35) {
    const depth = 1 - Math.min(1, P.y / (carStations.floorY + 0.18));
    const center = 1 - Math.min(1, Math.abs(P.z) / (carStations.bodyHalfW + 0.35));
    // Accelerate rearward flow (more negative vx) — feeds diffuser
    v.x -= state.Vinf * 0.55 * depth * center * state.floorLoad;
  }

  // Diffuser ramp upwash near the rear (feeds rear wing)
  {
    const dx = P.x - diff.x, dy = P.y - diff.y;
    const r2 = dx * dx + dy * dy + 0.04;
    const spanGate = Math.exp(-((P.z * P.z) / ((diff.span * 0.55) ** 2)));
    // Pair of vortices / source-like upwash concentrated at diffuser exit
    const strength = state.Vinf * 0.45 * state.floorLoad * spanGate;
    v.y += strength * (0.12 / r2);
    v.x -= strength * 0.08 * (dx / r2);
  }

  // Front-wing wake downwash along the centerline toward the rear
  {
    const dx = P.x - fw.x;
    if (dx < 0) { // only downstream of front wing (toward -x)
      const wake = Math.exp(-(dx * dx) / 18) * Math.exp(-(P.z * P.z) / ((fw.span * 0.45) ** 2));
      const heightGate = Math.exp(-((P.y - fw.y) * (P.y - fw.y)) / 0.35);
      // Downwash (negative vy) scales with front-wing circulation
      v.y += -Math.abs(state.gammaFront) * 1.8 * wake * heightGate;
    }
  }

  // Body blockage — push flow outward around sidepods
  if (P.x > carStations.bodyX0 && P.x < carStations.bodyX1 && P.y < 0.85) {
    const lateral = P.z;
    const near = Math.exp(-((Math.abs(lateral) - carStations.bodyHalfW) ** 2) / 0.08);
    if (Math.abs(lateral) > carStations.bodyHalfW * 0.55) {
      v.z += Math.sign(lateral || 1) * state.Vinf * 0.22 * near;
      v.y += state.Vinf * 0.08 * near; // some flow goes over the sidepod
    }
  }
  return v;
}

function rearWingInduced(Pl) {
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
}

function fieldVelocityWorld(Pworld) {
  const v = new THREE.Vector3(-state.Vinf, 0, 0);

  // 1) Front wing horseshoe (downforce)
  const fw = carStations.frontWing;
  v.add(horseshoeWorld(Pworld, fw.x, fw.y, fw.span * 0.5, state.gammaFront));

  // 2) Floor / diffuser / body coupling
  v.add(floorDiffuserVelocity(Pworld));

  // 3) Rear wing (ML + panels + horseshoe), aero frame
  v.add(rearWingInduced(worldToAero(Pworld)));

  if (!isFinite(v.x) || !isFinite(v.y) || !isFinite(v.z) || v.lengthSq() < 1e-8) {
    return new THREE.Vector3(-state.Vinf, 0, 0);
  }
  return v;
}"""

if old_wing not in t:
    raise SystemExit("WING block not found")
t = t.replace(old_wing, new_wing, 1)
print("patched carStations + fieldVelocityWorld")

# --- state: add gammaFront, floorLoad ---
t = t.replace(
    "gammaMain: 0, gammaFlap: 0, Vinf: 1.0",
    "gammaMain: 0, gammaFlap: 0, gammaFront: 0, floorLoad: 1.0, Vinf: 1.0",
)

# --- recompute: coupled AoA + front wing + floor ---
old_recompute_mid = """  const predMain = predictClCd(mainInputAoA, MODEL.main_cst);
  const predFlap = predictClCd(flapInputAoA, MODEL.flap_cst);
  state.clMain = predMain.Cl;
  state.clFlap = predFlap.Cl;

  state.gammaMain = -0.5 * state.clMain * state.Vinf * MAIN_CHORD;
  state.gammaFlap = -0.5 * state.clFlap * state.Vinf * FLAP_CHORD * 0.75; // flap partially shielded by main plane wake"""

new_recompute_mid = """  // Front wing first (same ML net, slightly lower AoA — front wing runs less aggressive)
  const frontAoA = clampToTrainingRange(state.aoaDeg * 0.65);
  const predFront = predictClCd(frontAoA, MODEL.main_cst);
  state.clFront = predFront.Cl;
  state.gammaFront = -0.5 * state.clFront * state.Vinf * carStations.frontWing.chord;

  // Interaction: front-wing downwash + diffuser upwash at the rear-wing station
  // Sample induced vertical velocity at rear wing LE in WORLD, convert to AoA delta
  const probeRW = new THREE.Vector3(WING_X, WING_Y, 0);
  let induced = new THREE.Vector3(-state.Vinf, 0, 0);
  induced.add(horseshoeWorld(probeRW, carStations.frontWing.x, carStations.frontWing.y, carStations.frontWing.span * 0.5, state.gammaFront));
  // provisional floor load from last frame / default
  induced.add(floorDiffuserVelocity(probeRW));
  const inducedAoA = THREE.MathUtils.radToDeg(Math.atan2(induced.y, Math.max(0.2, -induced.x)));

  const mainInputAoA2 = clampToTrainingRange(state.aoaDeg + inducedAoA * 0.85);
  const flapInputAoA2 = clampToTrainingRange(state.aoaDeg + state.flapDeg + inducedAoA * 0.85);
  const predMain = predictClCd(mainInputAoA2, MODEL.main_cst);
  const predFlap = predictClCd(flapInputAoA2, MODEL.flap_cst);
  state.clMain = predMain.Cl;
  state.clFlap = predFlap.Cl;
  state.inducedAoA = inducedAoA;

  state.gammaMain = -0.5 * state.clMain * state.Vinf * MAIN_CHORD;
  state.gammaFlap = -0.5 * state.clFlap * state.Vinf * FLAP_CHORD * 0.75;
  // Floor/diffuser load tracks how hard the rear wing is pulling (coupled)
  state.floorLoad = 0.65 + 0.55 * Math.min(1.4, Math.abs(state.clMain) + 0.5 * Math.abs(state.clFlap));"""

# Fix: original already defines mainInputAoA - we're duplicating clamp. Need to replace including the clamp block usage.
# Actually looking at recompute - it defines mainInputAoA then predMain. My replacement still references mainInputAoA for clamped flags. Let me replace a larger chunk.

old_bigger = """  const clampToTrainingRange = a => Math.max(-4, Math.min(8, a));
  const mainInputAoA = clampToTrainingRange(state.aoaDeg);
  const flapInputAoA = clampToTrainingRange(state.aoaDeg + state.flapDeg);
  const mainClamped = mainInputAoA !== state.aoaDeg;
  const flapClamped = flapInputAoA !== (state.aoaDeg + state.flapDeg);

  const predMain = predictClCd(mainInputAoA, MODEL.main_cst);
  const predFlap = predictClCd(flapInputAoA, MODEL.flap_cst);
  state.clMain = predMain.Cl;
  state.clFlap = predFlap.Cl;

  state.gammaMain = -0.5 * state.clMain * state.Vinf * MAIN_CHORD;
  state.gammaFlap = -0.5 * state.clFlap * state.Vinf * FLAP_CHORD * 0.75; // flap partially shielded by main plane wake"""

new_bigger = """  const clampToTrainingRange = a => Math.max(-4, Math.min(8, a));

  // Front wing circulation (feeds downwash into the rear wing)
  const frontAoA = clampToTrainingRange(state.aoaDeg * 0.65);
  const predFront = predictClCd(frontAoA, MODEL.main_cst);
  state.clFront = predFront.Cl;
  state.gammaFront = -0.5 * state.clFront * state.Vinf * carStations.frontWing.chord;

  // Sample inflow at rear wing: freestream + front-wing wake + floor/diffuser
  state.floorLoad = 1.0;
  const probeRW = new THREE.Vector3(WING_X, WING_Y, 0);
  const induced = new THREE.Vector3(-state.Vinf, 0, 0);
  induced.add(horseshoeWorld(probeRW, carStations.frontWing.x, carStations.frontWing.y, carStations.frontWing.span * 0.5, state.gammaFront));
  induced.add(floorDiffuserVelocity(probeRW));
  const inducedAoA = THREE.MathUtils.radToDeg(Math.atan2(induced.y, Math.max(0.25, -induced.x)));
  state.inducedAoA = inducedAoA;

  const mainInputAoA = clampToTrainingRange(state.aoaDeg + inducedAoA * 0.85);
  const flapInputAoA = clampToTrainingRange(state.aoaDeg + state.flapDeg + inducedAoA * 0.85);
  const mainClamped = Math.abs(mainInputAoA - (state.aoaDeg + inducedAoA * 0.85)) > 1e-6;
  const flapClamped = Math.abs(flapInputAoA - (state.aoaDeg + state.flapDeg + inducedAoA * 0.85)) > 1e-6;

  const predMain = predictClCd(mainInputAoA, MODEL.main_cst);
  const predFlap = predictClCd(flapInputAoA, MODEL.flap_cst);
  state.clMain = predMain.Cl;
  state.clFlap = predFlap.Cl;

  state.gammaMain = -0.5 * state.clMain * state.Vinf * MAIN_CHORD;
  state.gammaFlap = -0.5 * state.clFlap * state.Vinf * FLAP_CHORD * 0.75;
  state.floorLoad = 0.65 + 0.55 * Math.min(1.4, Math.abs(state.clMain) + 0.5 * Math.abs(state.clFlap));"""

if old_bigger not in t:
    raise SystemExit("recompute mid block not found")
t = t.replace(old_bigger, new_bigger, 1)
print("patched recompute coupling")

# Update ml readout
t = t.replace(
    """mlNote.textContent = `ML Cl main ${state.clMain.toFixed(2)} · flap ${state.clFlap.toFixed(2)}${flag}`;""",
    """mlNote.textContent = `front ${state.clFront.toFixed(2)} · rear ${state.clMain.toFixed(2)}/${state.clFlap.toFixed(2)} · ind ${(state.inducedAoA||0).toFixed(1)}°${flag}`;""",
)

# Remove old fieldVelocityVortexOnly / fieldVelocity that double-count — solvePanelSystem still needs vortex-only in aero frame
old_fv_pair = """function fieldVelocityVortexOnly(P) {
  const v = new THREE.Vector3(-state.Vinf, 0, 0); // freestream travels toward -x
  v.add(horseshoeVelocity(P, SPAN / 2, 0, 0, state.gammaMain));
  v.add(horseshoeVelocity(P, SPAN * 0.94 / 2, MAIN_CHORD * 0.72, 0.12, state.gammaFlap));
  return v;
}

function fieldVelocity(P) {
  const v = fieldVelocityVortexOnly(P);
  // Emphasize wing induction so deflection is visible at car scale
  v.x = -state.Vinf + (v.x + state.Vinf) * 1.65;
  v.y *= 1.65;
  v.z *= 1.65;
  if (panelSystem && panelSystem.panels && panelSystem.sigma) {
    for (let j = 0; j < panelSystem.panels.length; j++) {
      const sig = panelSystem.sigma[j];
      if (!isFinite(sig)) continue;
      const infl = panelSourceInfluence2D(P, panelSystem.panels[j], sig);
      if (isFinite(infl.x) && isFinite(infl.y)) {
        v.x += infl.x * 1.8;
        v.y += infl.y * 1.8;
      }
    }
  }
  if (!isFinite(v.x) || !isFinite(v.y) || !isFinite(v.z) || v.lengthSq() < 1e-8) {
    return new THREE.Vector3(-state.Vinf, 0, 0);
  }
  return v;
}"""

new_fv_pair = """// Used by the panel solver in aero-local frame (rear wing only + freestream)
function fieldVelocityVortexOnly(P) {
  const v = new THREE.Vector3(-state.Vinf, 0, 0);
  v.add(horseshoeVelocity(P, SPAN / 2, 0, 0, state.gammaMain));
  v.add(horseshoeVelocity(P, SPAN * 0.94 / 2, MAIN_CHORD * 0.72, 0.12, state.gammaFlap));
  return v;
}

function fieldVelocity(P) {
  // aero-local full rear-wing field (for any leftover callers)
  const v = fieldVelocityVortexOnly(P);
  if (panelSystem && panelSystem.panels && panelSystem.sigma) {
    for (let j = 0; j < panelSystem.panels.length; j++) {
      const sig = panelSystem.sigma[j];
      if (!isFinite(sig)) continue;
      const infl = panelSourceInfluence2D(P, panelSystem.panels[j], sig);
      if (isFinite(infl.x) && isFinite(infl.y)) { v.x += infl.x; v.y += infl.y; }
    }
  }
  if (!isFinite(v.x) || !isFinite(v.y) || !isFinite(v.z) || v.lengthSq() < 1e-8) {
    return new THREE.Vector3(-state.Vinf, 0, 0);
  }
  return v;
}"""

if old_fv_pair not in t:
    raise SystemExit("fieldVelocity pair not found")
t = t.replace(old_fv_pair, new_fv_pair, 1)
print("patched fieldVelocity pair")

# --- Restore neon silhouette loader (replace solid Phong section) ---
old_solid = """  // Solid flat-shaded car (game-style polygons, not a ghost wireframe)
  const shell = new THREE.Group();
  let mi = 0;
  const bodyMat = new THREE.MeshPhongMaterial({
    color: 0xd8e4ea, flatShading: true, shininess: 18, specular: 0x33444a, side: THREE.DoubleSide
  });
  const accentMat = new THREE.MeshPhongMaterial({
    color: 0x9ec4d0, flatShading: true, shininess: 22, specular: 0x226677, side: THREE.DoubleSide
  });
  src.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return;
    const geo = obj.geometry.clone();
    geo.applyMatrix4(obj.matrixWorld);
    if (!geo.attributes.normal) geo.computeVertexNormals();
    // Force faceted look
    const nonIndex = geo.toNonIndexed ? geo.toNonIndexed() : geo;
    nonIndex.computeVertexNormals();
    const mesh = new THREE.Mesh(nonIndex, (mi % 3 === 0) ? accentMat : bodyMat);
    mesh.castShadow = false;
    mesh.receiveShadow = false;
    shell.add(mesh);
    mi++;
  });
  box = new THREE.Box3().setFromObject(shell);
  shell.position.set(-(box.min.x + box.max.x) * 0.5, -box.min.y, -(box.min.z + box.max.z) * 0.5);
  carGroup.add(shell);

  // Bake impermeable voxel body from the solid mesh
  voxelizeCar(shell, 0.065);

  const fb = new THREE.Box3().setFromObject(carGroup);
  const fsz = fb.getSize(new THREE.Vector3());
  WING_X = fb.min.x + 0.55;
  WING_Y = fb.min.y + fsz.y * 0.72;
  lookAt.set(0, Math.max(0.25, fsz.y * 0.35), 0);
  camDist = Math.max(6, fsz.length() * 0.55 * 1.1);
  targetDist = camDist;
  Object.assign(viewPresets['3q'], { dist: camDist });
  updateCamera();

  document.getElementById('loading').classList.add('hidden');
  aeroReady = true;
  recompute();

  // Neon-green aero edge accents only (after solid body is up)
  setTimeout(() => {
    try {
      const carBox = new THREE.Box3().setFromObject(shell);
      const carSize = carBox.getSize(new THREE.Vector3());
      const carMin = carBox.min.clone();
      let frontPeak = 0, rearPeak = 0;
      shell.traverse((obj) => {
        if (!obj.isMesh || !obj.geometry) return;
        const p = obj.geometry.attributes.position;
        const v = new THREE.Vector3();
        for (let i = 0; i < p.count; i += 32) {
          v.fromBufferAttribute(p, i);
          const len = (v.x - carMin.x) / Math.max(carSize.x, 1e-6);
          const h = (v.y - carMin.y) / Math.max(carSize.y, 1e-6);
          if (len > 0.85) frontPeak = Math.max(frontPeak, h);
          if (len < 0.15) rearPeak = Math.max(rearPeak, h);
        }
      });
      const noseAtMaxX = frontPeak < rearPeak;
      function isAeroPoint(x, y, z) {
        let len = (x - carMin.x) / Math.max(carSize.x, 1e-6);
        if (!noseAtMaxX) len = 1 - len;
        const h = (y - carMin.y) / Math.max(carSize.y, 1e-6);
        if (len > 0.82 && h < 0.34) return true;
        if (len < 0.18 && h > 0.48) return true;
        if (len < 0.26 && h < 0.22) return true;
        return false;
      }
      const edgeGroup = new THREE.Group();
      shell.traverse((obj) => {
        if (!obj.isMesh || !obj.geometry) return;
        let edges;
        try { edges = new THREE.EdgesGeometry(obj.geometry, 30); } catch (e) { return; }
        const pos = edges.attributes.position.array;
        const aero = [];
        for (let i = 0; i < pos.length; i += 6) {
          if (!isAeroPoint((pos[i]+pos[i+3])*0.5, (pos[i+1]+pos[i+4])*0.5, (pos[i+2]+pos[i+5])*0.5)) continue;
          aero.push(pos[i], pos[i+1], pos[i+2], pos[i+3], pos[i+4], pos[i+5]);
        }
        if (aero.length) {
          const g = new THREE.BufferGeometry();
          g.setAttribute('position', new THREE.Float32BufferAttribute(aero, 3));
          edgeGroup.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: NEON_GREEN, transparent: true, opacity: 0.95 })));
        }
        edges.dispose();
      });
      shell.add(edgeGroup);
    } catch (e) {
      showAeroError('aero edges: ' + e.message);
    }
  }, 30);
}, xhr => {
  if (xhr.total) document.getElementById('loading').textContent = 'Loading solid car + voxels… ' + Math.round(xhr.loaded / xhr.total * 100) + '%';
}, err => {
  console.error(err);
  document.getElementById('loading').textContent = 'Failed to load rb19.glb — open via http://127.0.0.1:8765';
});"""

new_neon = """  // Original neon silhouette: translucent fill + white/cyan/gold edges
  const shell = new THREE.Group();
  let mi = 0;
  const geos = [];
  src.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return;
    const geo = obj.geometry.clone();
    geo.applyMatrix4(obj.matrixWorld);
    geos.push(geo);
    shell.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      color: (mi % 2) ? NEON_CYAN : NEON_WHITE,
      transparent: true, opacity: 0.12, depthWrite: true, side: THREE.DoubleSide
    })));
    mi++;
  });
  box = new THREE.Box3().setFromObject(shell);
  shell.position.set(-(box.min.x + box.max.x) * 0.5, -box.min.y, -(box.min.z + box.max.z) * 0.5);
  carGroup.add(shell);

  voxelizeCar(shell, 0.065);

  const fb = new THREE.Box3().setFromObject(carGroup);
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
  carStations.bodyHalfW = fsz.z * 0.28;

  lookAt.set(0, Math.max(0.25, fsz.y * 0.35), 0);
  camDist = Math.max(6, fsz.length() * 0.55 * 1.1);
  targetDist = camDist;
  Object.assign(viewPresets['3q'], { dist: camDist });
  updateCamera();

  document.getElementById('loading').classList.add('hidden');
  aeroReady = true;
  recompute();

  // Edge trace: gold on aero, white/cyan on body (original scheme)
  setTimeout(() => {
    try {
      const carBox = new THREE.Box3().setFromObject(shell);
      const carSize = carBox.getSize(new THREE.Vector3());
      const carMin = carBox.min.clone();
      let frontPeak = 0, rearPeak = 0;
      shell.traverse((obj) => {
        if (!obj.isMesh || !obj.geometry) return;
        const p = obj.geometry.attributes.position;
        const v = new THREE.Vector3();
        for (let i = 0; i < p.count; i += 32) {
          v.fromBufferAttribute(p, i);
          const len = (v.x - carMin.x) / Math.max(carSize.x, 1e-6);
          const h = (v.y - carMin.y) / Math.max(carSize.y, 1e-6);
          if (len > 0.85) frontPeak = Math.max(frontPeak, h);
          if (len < 0.15) rearPeak = Math.max(rearPeak, h);
        }
      });
      const noseAtMaxX = frontPeak < rearPeak;
      function isAeroPoint(x, y, z) {
        let len = (x - carMin.x) / Math.max(carSize.x, 1e-6);
        if (!noseAtMaxX) len = 1 - len;
        const h = (y - carMin.y) / Math.max(carSize.y, 1e-6);
        if (len > 0.82 && h < 0.34) return true; // front wing
        if (len < 0.18 && h > 0.48) return true; // rear wing
        if (len < 0.26 && h < 0.22) return true; // diffuser
        return false;
      }
      const edgeGroup = new THREE.Group();
      let ei = 0;
      shell.traverse((obj) => {
        if (!obj.isMesh || !obj.geometry) return;
        let edges;
        try { edges = new THREE.EdgesGeometry(obj.geometry, 22); } catch (e) { return; }
        const pos = edges.attributes.position.array;
        const aero = [], body = [];
        for (let i = 0; i < pos.length; i += 6) {
          const dest = isAeroPoint((pos[i]+pos[i+3])*0.5, (pos[i+1]+pos[i+4])*0.5, (pos[i+2]+pos[i+5])*0.5) ? aero : body;
          dest.push(pos[i], pos[i+1], pos[i+2], pos[i+3], pos[i+4], pos[i+5]);
        }
        const mk = (arr, color, op) => {
          if (!arr.length) return null;
          const g = new THREE.BufferGeometry();
          g.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
          return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity: op }));
        };
        const a = mk(aero, NEON_GOLD, 0.95);
        const b = mk(body, (ei % 2) ? NEON_CYAN : NEON_WHITE, 0.55);
        if (b) edgeGroup.add(b); if (a) edgeGroup.add(a);
        edges.dispose(); ei++;
      });
      shell.add(edgeGroup);
    } catch (e) {
      showAeroError('neon edges: ' + e.message);
    }
  }, 30);
}, xhr => {
  if (xhr.total) document.getElementById('loading').textContent = 'Loading neon car + coupled aero… ' + Math.round(xhr.loaded / xhr.total * 100) + '%';
}, err => {
  console.error(err);
  document.getElementById('loading').textContent = 'Failed to load rb19.glb — open via http://127.0.0.1:8765';
});"""

if old_solid not in t:
    raise SystemExit("solid loader block not found")
t = t.replace(old_solid, new_neon, 1)
print("patched neon loader")

# Soften / remove harsh Phong lights — keep subtle or remove
# Optional: leave lights, MeshBasic ignores them. Fine.

path.write_text(t, encoding="utf-8")
print("OK", path.stat().st_size)
