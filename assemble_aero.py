# -*- coding: utf-8 -*-
"""Assemble RB19 neon silhouette + rear-wing ML/physics/flow into index.html."""
from pathlib import Path
import re

ROOT = Path(r"c:\Model")
WING = Path(r"c:\Users\adity\Downloads\rearwing_flow_visualization (3).html")
lines = WING.read_text(encoding="utf-8").splitlines()

PANEL = "\n".join(lines[317:440])  # include cambered2DProfile .. PANEL_RES + panelSystem
PANEL = PANEL.replace("const SPAN = 2.6;", "const SPAN = 1.65;")
PANEL = PANEL.replace("const MAIN_CHORD = 0.55;", "const MAIN_CHORD = 0.38;")
PANEL = PANEL.replace("const FLAP_CHORD = 0.28;", "const FLAP_CHORD = 0.20;")
# Drop buildWingElement — not needed for car
PANEL = re.sub(
    r"function buildWingElement\(.*?^}\n",
    "",
    PANEL,
    count=1,
    flags=re.S | re.M,
)
if "PANEL_RES" not in PANEL:
    PANEL += "\nconst PANEL_RES = 9;\nlet panelSystem = { panels: [], sigma: [], polygons: [] };\n"

MODEL = lines[507]
PHYS = "\n".join(lines[509:642])
PHYS = PHYS.replace("\u26a0", "!")
PHYS = PHYS.replace(
    "aoaDeg: 6, flapDeg: 18, windMult: 1.0, tubeRadius: 0.005,",
    "aoaDeg: 6, flapDeg: 18, windMult: 1.0, tubeRadius: 0.005,\n"
    "  alphaMainRad: 0, alphaFlapRad: 0,",
)
PHYS = PHYS.replace(
    "const alphaFlap = THREE.MathUtils.degToRad(state.aoaDeg + state.flapDeg);",
    "const alphaFlap = THREE.MathUtils.degToRad(state.aoaDeg + state.flapDeg);\n"
    "  state.alphaMainRad = -alphaMain;\n"
    "  state.alphaFlapRad = -alphaFlap;",
)
PHYS = re.sub(r"mainWingGroup\.rotation\.z\s*=\s*[^;]+;", "", PHYS)
PHYS = re.sub(r"flapGroup\.rotation\.z\s*=\s*[^;]+;", "", PHYS)
PHYS = re.sub(
    r"\n\s*// reposition flap visually\n\s*const flapPivotX = MAIN_CHORD \* 0\.72;\n\s*flapGroup\.position\.set\([^)]+\);\n?",
    "\n",
    PHYS,
)

SOLVE = r'''
function solvePanelSystem() {
  const mainRaw = cambered2DProfile(MAIN_CHORD, -0.09, 0.045, PANEL_RES);
  const flapRaw = cambered2DProfile(FLAP_CHORD, -0.14, 0.04, PANEL_RES);
  const flapPivotX = MAIN_CHORD * 0.72;
  const mainWorld = transformPoly2D(mainRaw, MAIN_CHORD, state.alphaMainRad, 0, 0);
  const flapWorld = transformPoly2D(flapRaw, FLAP_CHORD, state.alphaFlapRad, flapPivotX, 0.12);
  const allPanels = [...buildPanelsFromPolygon(mainWorld), ...buildPanelsFromPolygon(flapWorld)];
  const n = allPanels.length;
  const Amat = Array.from({ length: n }, () => new Array(n).fill(0));
  const bvec = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    const ni = { x: allPanels[i].nx, y: allPanels[i].ny };
    const bg = fieldVelocityVortexOnly(new THREE.Vector3(allPanels[i].mid.x, allPanels[i].mid.y, 0));
    bvec[i] = -(bg.x * ni.x + bg.y * ni.y);
    for (let j = 0; j < n; j++) {
      const infl = panelSourceInfluence2D(allPanels[i].mid, allPanels[j], 1.0);
      Amat[i][j] = infl.x * ni.x + infl.y * ni.y;
    }
  }
  panelSystem = { panels: allPanels, sigma: solveLinearSystem(Amat, bvec), polygons: [mainWorld, flapWorld] };
}
'''

HTML_HEAD = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>F1 Car — Aero Flow · ML + Horseshoe</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: 100%; height: 100%; background: #000; overflow: hidden; font-family: 'Inter', sans-serif; }
  #canvas-container { position: absolute; inset: 0; }
  .hud { position: absolute; color: #d8f5ff; pointer-events: none; user-select: none; }
  .title-block { top: 28px; left: 32px; }
  .title-block .eyebrow {
    font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.25em;
    color: #39ff88; text-transform: uppercase; margin-bottom: 6px;
  }
  .title-block h1 { font-size: 22px; font-weight: 600; color: #f0feff; }
  .title-block .sub { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #5b8a91; margin-top: 4px; }
  .telemetry { top: 28px; right: 32px; text-align: right; font-family: 'JetBrains Mono', monospace; }
  .telemetry .row { margin-bottom: 10px; }
  .telemetry .label { font-size: 10px; letter-spacing: 0.15em; text-transform: uppercase; color: #4d6a70; margin-bottom: 2px; }
  .telemetry .value { font-size: 28px; font-weight: 700; color: #39ff88; text-shadow: 0 0 12px rgba(57,255,136,0.5); }
  .telemetry .value.cd { color: #00d4ff; text-shadow: 0 0 12px rgba(0,212,255,0.5); }
  .hint { position: absolute; bottom: 118px; left: 32px; font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #2e4448; }
  .caption {
    position: absolute; bottom: 28px; right: 32px; max-width: 300px;
    font-family: 'JetBrains Mono', monospace; font-size: 10px; line-height: 1.6; color: #3d5459; text-align: right;
  }
  .view-presets { position: absolute; top: 28px; left: 50%; transform: translateX(-50%); display: flex; gap: 6px; pointer-events: auto; }
  .view-btn {
    font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase;
    background: rgba(255,255,255,0.04); border: 1px solid rgba(127,176,184,0.25); color: #7fb0b8;
    padding: 7px 14px; cursor: pointer; transition: all 0.15s ease;
  }
  .view-btn:hover { border-color: #39ff88; color: #d8f5ff; }
  .view-btn.active { background: rgba(57,255,136,0.12); border-color: #39ff88; color: #39ff88; }
  .controls {
    position: absolute; bottom: 28px; left: 32px; display: flex; gap: 18px; flex-wrap: wrap;
    pointer-events: auto; max-width: 55%;
  }
  .ctrl { min-width: 150px; }
  .ctrl .label {
    font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #7fb0b8;
    display: flex; justify-content: space-between; margin-bottom: 4px;
  }
  .ctrl .label span.val { color: #39ff88; }
  .ctrl input[type="range"] {
    -webkit-appearance: none; appearance: none; width: 100%; height: 2px;
    background: #1a2f33; outline: none; border-radius: 1px;
  }
  .ctrl input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none; appearance: none; width: 12px; height: 12px;
    border-radius: 50%; background: #39ff88; cursor: pointer; box-shadow: 0 0 8px rgba(57,255,136,0.6);
  }
  .ctrl input[type="range"]::-moz-range-thumb {
    width: 12px; height: 12px; border: none; border-radius: 50%; background: #39ff88; cursor: pointer;
  }
  #loading {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    background: #000; color: #39ff88; font-family: 'JetBrains Mono', monospace; font-size: 12px;
    letter-spacing: 0.2em; text-transform: uppercase; z-index: 10;
  }
  #loading.hidden { display: none; }
</style>
</head>
<body>
<div id="canvas-container"></div>
<div id="loading">Loading car + aero solve…</div>
<div class="hud title-block">
  <div class="eyebrow">Flow Field — Live</div>
  <h1>F1 Car · RB19</h1>
  <div class="sub">ML section Cl · horseshoe + panel method</div>
</div>
<div class="hud telemetry">
  <div class="row"><div class="label">C<sub>L</sub> (downforce)</div><div class="value" id="cl-readout">0.00</div></div>
  <div class="row"><div class="label">C<sub>Di</sub> (induced)</div><div class="value cd" id="cd-readout">0.000</div></div>
  <div class="row" style="margin-top:14px;"><div class="label" style="color:#5b8a91;font-size:9px;" id="ml-readout">model Cl: —</div></div>
</div>
<div class="hint">drag to orbit · scroll to zoom</div>
<div class="view-presets">
  <button class="view-btn active" id="view-3q">3/4</button>
  <button class="view-btn" id="view-side">Side</button>
  <button class="view-btn" id="view-front">Front</button>
  <button class="view-btn" id="view-top">Top</button>
  <button class="view-btn" id="view-rear">Rear</button>
</div>
<div class="controls">
  <div class="ctrl">
    <div class="label"><span>Main plane AoA</span><span class="val" id="aoa-val">6°</span></div>
    <input type="range" id="aoa" min="-2" max="18" step="0.5" value="6">
  </div>
  <div class="ctrl">
    <div class="label"><span>Flap angle</span><span class="val" id="flap-val">18°</span></div>
    <input type="range" id="flap" min="0" max="40" step="1" value="18">
  </div>
  <div class="ctrl">
    <div class="label"><span>Wind speed</span><span class="val" id="wind-val">1.0×</span></div>
    <input type="range" id="wind" min="0.3" max="2" step="0.1" value="1.0">
  </div>
  <div class="ctrl">
    <div class="label"><span>Line thickness</span><span class="val" id="thickness-val">0.005</span></div>
    <input type="range" id="thickness" min="0.002" max="0.009" step="0.001" value="0.005">
  </div>
</div>
<div class="caption">
  Neon silhouette · gold = aero surfaces.<br>
  Streamlines: top seed = red · bottom = blue.<br>
  Your trained net + horseshoe/panel solve on the rear wing.
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js"></script>
<script>
'''

JS_SCENE = r'''
const container = document.getElementById('canvas-container');
const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x000000, 0.028);
scene.background = new THREE.Color(0x000000);
const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 200);
let camDist = 9, camTheta = 0.9, camPhi = 1.15;
const lookAt = new THREE.Vector3(0, 0.35, 0);
function updateCamera() {
  camera.position.set(
    camDist * Math.sin(camPhi) * Math.cos(camTheta),
    camDist * Math.cos(camPhi),
    camDist * Math.sin(camPhi) * Math.sin(camTheta)
  );
  camera.lookAt(lookAt);
}
updateCamera();
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0x000000, 1);
container.appendChild(renderer.domElement);
let isDragging = false, lastX = 0, lastY = 0;
renderer.domElement.addEventListener('mousedown', e => { isDragging = true; lastX = e.clientX; lastY = e.clientY; });
window.addEventListener('mouseup', () => { isDragging = false; });
window.addEventListener('mousemove', e => {
  if (!isDragging) return;
  camTheta -= (e.clientX - lastX) * 0.005;
  camPhi = Math.max(0.15, Math.min(Math.PI - 0.15, camPhi - (e.clientY - lastY) * 0.005));
  lastX = e.clientX; lastY = e.clientY; updateCamera();
});
renderer.domElement.addEventListener('wheel', e => {
  camDist = Math.max(3, Math.min(25, camDist + e.deltaY * 0.008));
  updateCamera(); e.preventDefault();
}, { passive: false });
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
const viewPresets = {
  '3q': { theta: 0.9, phi: 1.15, dist: 9 },
  side: { theta: Math.PI / 2, phi: 1.5, dist: 8 },
  front: { theta: 0, phi: 1.35, dist: 7 },
  top: { theta: 0.9, phi: 0.2, dist: 10 },
  rear: { theta: Math.PI, phi: 1.35, dist: 7 },
};
function setView(name) {
  const p = viewPresets[name];
  camTheta = p.theta; camPhi = p.phi; camDist = p.dist; updateCamera();
  document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
}
['3q','side','front','top','rear'].forEach(n => document.getElementById('view-' + n).addEventListener('click', () => setView(n)));
renderer.domElement.addEventListener('mousedown', () => document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active')));

const NEON_WHITE = 0xf4f8ff, NEON_CYAN = 0x00d4ff, NEON_GOLD = 0xffc966;
const carGroup = new THREE.Group(); scene.add(carGroup);
scene.add(new THREE.GridHelper(20, 30, 0x0a2a2e, 0x0a2a2e));

let WING_X = -2.55, WING_Y = 0.95;
function worldToAero(P) { return new THREE.Vector3(P.x - WING_X, P.y - WING_Y, P.z); }
function aeroToWorld(P) { return new THREE.Vector3(P.x + WING_X, P.y + WING_Y, P.z); }
function fieldVelocityWorld(Pworld) { return fieldVelocity(worldToAero(Pworld)); }
'''

JS_STREAM = r'''
const N_SPAN_SEEDS = 9, N_HEIGHT_SEEDS = 7, STREAM_STEPS = 110, STREAM_DT = 0.05, SEED_X = 4.2;
const RED = new THREE.Color(0xff3b3b), BLUE = new THREE.Color(0x3b9bff);
let streamlineGroup = new THREE.Group(); scene.add(streamlineGroup);
let flowMarkerGroup = new THREE.Group(); scene.add(flowMarkerGroup);
let streamPaths = [];

function segIntersect2D(p, r, q, s) {
  const rxs = r.x * s.y - r.y * s.x;
  if (Math.abs(rxs) < 1e-12) return null;
  const qmp = { x: q.x - p.x, y: q.y - p.y };
  const t = (qmp.x * s.y - qmp.y * s.x) / rxs;
  const u = (qmp.x * r.y - qmp.y * r.x) / rxs;
  if (t >= 0 && t <= 1 && u >= 0 && u <= 1) return { t };
  return null;
}
function pointInPolygon(pt, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i].x, yi = poly[i].y, xj = poly[j].x, yj = poly[j].y;
    if (((yi > pt.y) !== (yj > pt.y)) && (pt.x < (xj - xi) * (pt.y - yi) / (yj - yi) + xi)) inside = !inside;
  }
  return inside;
}
function closestPointOnSegment(pt, a, b) {
  const abx = b.x - a.x, aby = b.y - a.y, lenSq = abx * abx + aby * aby;
  if (lenSq < 1e-12) return { x: a.x, y: a.y };
  let t = ((pt.x - a.x) * abx + (pt.y - a.y) * aby) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return { x: a.x + t * abx, y: a.y + t * aby };
}
function nearestPanelPushOut(pt) {
  let best = null, bestDist = Infinity, bestPoint = null;
  for (const panel of panelSystem.panels) {
    const cp = closestPointOnSegment(pt, panel.a, panel.b);
    const d = (pt.x - cp.x) ** 2 + (pt.y - cp.y) ** 2;
    if (d < bestDist) { bestDist = d; best = panel; bestPoint = cp; }
  }
  if (!best) return pt;
  const c = state.tubeRadius + 0.002;
  return { x: bestPoint.x + best.nx * c, y: bestPoint.y + best.ny * c };
}

function integrateStreamline(seed) {
  const pts = [seed.clone()];
  let p = seed.clone();
  for (let i = 0; i < STREAM_STEPS; i++) {
    for (let sub = 0; sub < 3; sub++) {
      const dt = STREAM_DT / 3;
      const v = fieldVelocityWorld(p);
      if (v.length() < 1e-5) { i = STREAM_STEPS; break; }
      const mid = p.clone().addScaledVector(v, dt * 0.5);
      let next = p.clone().addScaledVector(fieldVelocityWorld(mid), dt);
      const pA = worldToAero(p), nA = worldToAero(next);
      const r2d = { x: nA.x - pA.x, y: nA.y - pA.y };
      let closestT = null, hitPanel = null;
      for (const panel of panelSystem.panels) {
        const hit = segIntersect2D({ x: pA.x, y: pA.y }, r2d, panel.a, { x: panel.b.x - panel.a.x, y: panel.b.y - panel.a.y });
        if (hit && (closestT === null || hit.t < closestT)) { closestT = hit.t; hitPanel = panel; }
      }
      if (closestT !== null && hitPanel) {
        const c = state.tubeRadius + 0.002;
        next = aeroToWorld(new THREE.Vector3(pA.x + r2d.x * closestT + hitPanel.nx * c, pA.y + r2d.y * closestT + hitPanel.ny * c, nA.z));
      } else {
        for (const poly of panelSystem.polygons) {
          if (pointInPolygon({ x: nA.x, y: nA.y }, poly)) {
            const pushed = nearestPanelPushOut({ x: nA.x, y: nA.y });
            next = aeroToWorld(new THREE.Vector3(pushed.x, pushed.y, nA.z));
            break;
          }
        }
      }
      p = next; pts.push(p.clone());
      if (p.x < -5.0 || Math.abs(p.z) > SPAN * 1.5 || p.y < -0.2 || p.y > 2.2) { i = STREAM_STEPS; break; }
    }
  }
  return pts;
}

function buildStreamlines() {
  scene.remove(streamlineGroup); scene.remove(flowMarkerGroup);
  streamlineGroup = new THREE.Group(); flowMarkerGroup = new THREE.Group(); streamPaths = [];
  for (let hi = 0; hi < N_HEIGHT_SEEDS; hi++) {
    const yFrac = (hi / (N_HEIGHT_SEEDS - 1)) * 2 - 1;
    const y = WING_Y + yFrac * 0.28;
    for (let si = 2; si < N_SPAN_SEEDS - 2; si++) {
      const z = ((si / (N_SPAN_SEEDS - 1)) * 2 - 1) * SPAN * 0.62;
      const seed = new THREE.Vector3(SEED_X, y, z);
      const side = (y > WING_Y + 0.02) ? 1 : -1;
      const pts = integrateStreamline(seed);
      if (pts.length < 4) continue;
      const color = side > 0 ? RED : BLUE;
      const curve = new THREE.CatmullRomCurve3(pts);
      const tubeGeo = new THREE.TubeGeometry(curve, Math.max(20, Math.min(90, pts.length)), state.tubeRadius, 8, false);
      streamlineGroup.add(new THREE.Mesh(tubeGeo, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.62 })));
      const cumLen = [0];
      for (let i = 1; i < pts.length; i++) cumLen.push(cumLen[i - 1] + pts[i].distanceTo(pts[i - 1]));
      streamPaths.push({ points: pts, color, cumLen, totalLen: cumLen[cumLen.length - 1], phase: Math.random() });
    }
  }
  scene.add(streamlineGroup); scene.add(flowMarkerGroup); buildFlowMarkers();
}

let markerMeshes = [];
function buildFlowMarkers() {
  markerMeshes = [];
  const geo = new THREE.SphereGeometry(0.014, 6, 6);
  streamPaths.forEach((path, pi) => {
    for (let m = 0; m < 2; m++) {
      const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: path.color, transparent: true, opacity: 0.95 }));
      flowMarkerGroup.add(mesh);
      markerMeshes.push({ mesh, pathIndex: pi, offset: m / 2 });
    }
  });
}
function pointAtArcLength(path, s) {
  const target = ((s % path.totalLen) + path.totalLen) % path.totalLen;
  for (let i = 1; i < path.cumLen.length; i++) {
    if (path.cumLen[i] >= target) {
      const f = (target - path.cumLen[i - 1]) / Math.max(path.cumLen[i] - path.cumLen[i - 1], 1e-6);
      return path.points[i - 1].clone().lerp(path.points[i], f);
    }
  }
  return path.points[path.points.length - 1].clone();
}
let flowTime = 0;
function updateFlowMarkers(dt) {
  flowTime += dt * state.windMult;
  markerMeshes.forEach(({ mesh, pathIndex, offset }) => {
    const path = streamPaths[pathIndex];
    if (!path || path.totalLen < 1e-4) return;
    mesh.position.copy(pointAtArcLength(path, flowTime * 0.9 * path.totalLen * 0.35 + offset * path.totalLen + path.phase * path.totalLen));
  });
}
'''

JS_CAR = r'''
let aeroReady = false;
new THREE.GLTFLoader().load('./rb19.glb', (gltf) => {
  const src = gltf.scene;
  src.rotation.y = Math.PI / 2;
  let box = new THREE.Box3().setFromObject(src);
  const size = box.getSize(new THREE.Vector3());
  src.position.sub(box.getCenter(new THREE.Vector3()));
  src.position.y += size.y * 0.5;
  src.updateMatrixWorld(true);
  src.scale.setScalar(5.5 / Math.max(size.x, size.z));
  src.updateMatrixWorld(true);
  box = new THREE.Box3().setFromObject(src);
  src.position.y -= box.min.y;
  src.updateMatrixWorld(true);

  const carBox = new THREE.Box3().setFromObject(src);
  const carSize = carBox.getSize(new THREE.Vector3());
  const carMin = carBox.min.clone();
  let frontPeak = 0, rearPeak = 0;
  src.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return;
    const p = obj.geometry.attributes.position; const v = new THREE.Vector3();
    for (let i = 0; i < p.count; i += 8) {
      v.fromBufferAttribute(p, i).applyMatrix4(obj.matrixWorld);
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
    const w = Math.abs(z - (carMin.z + carSize.z * 0.5)) / Math.max(carSize.z * 0.5, 1e-6);
    if (len > 0.80 && h < 0.38) return true;
    if (len < 0.18 && h > 0.42) return true;
    if (len < 0.22 && h > 0.22 && h < 0.55) return true;
    if (h < 0.14 || (len < 0.32 && h < 0.32)) return true;
    if (len > 0.22 && len < 0.72 && h > 0.08 && h < 0.52 && w > 0.38) return true;
    if (len > 0.72 && h < 0.22) return true;
    return false;
  }
  function splitEdges(edgesGeo) {
    const pos = edgesGeo.attributes.position.array;
    const aero = [], body = [];
    for (let i = 0; i < pos.length; i += 6) {
      const dest = isAeroPoint((pos[i]+pos[i+3])*0.5, (pos[i+1]+pos[i+4])*0.5, (pos[i+2]+pos[i+5])*0.5) ? aero : body;
      dest.push(pos[i],pos[i+1],pos[i+2],pos[i+3],pos[i+4],pos[i+5]);
    }
    const mk = (arr, color, op) => {
      if (!arr.length) return null;
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
      return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity: op }));
    };
    return { aero: mk(aero, NEON_GOLD, 0.95), body: mk(body, NEON_WHITE, 0.5) };
  }

  const shell = new THREE.Group();
  let mi = 0;
  src.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return;
    const geo = obj.geometry.clone(); geo.applyMatrix4(obj.matrixWorld);
    shell.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      color: mi % 2 ? NEON_CYAN : NEON_WHITE, transparent: true, opacity: 0.05, depthWrite: false, side: THREE.DoubleSide
    })));
    const edges = new THREE.EdgesGeometry(geo, 18);
    const { aero, body } = splitEdges(edges);
    if (body) shell.add(body); if (aero) shell.add(aero);
    edges.dispose(); mi++;
  });
  box = new THREE.Box3().setFromObject(shell);
  shell.position.set(-(box.min.x+box.max.x)*0.5, -box.min.y, -(box.min.z+box.max.z)*0.5);
  carGroup.add(shell);

  const fb = new THREE.Box3().setFromObject(carGroup);
  const fsz = fb.getSize(new THREE.Vector3());
  WING_X = fb.min.x + 0.55;
  WING_Y = fb.min.y + fsz.y * 0.72;
  lookAt.set(0, Math.max(0.25, fsz.y * 0.35), 0);
  camDist = Math.max(6, fsz.length() * 0.55 * 1.1);
  Object.assign(viewPresets['3q'], { dist: camDist });
  updateCamera();

  document.getElementById('loading').classList.add('hidden');
  aeroReady = true;
  recompute();
}, xhr => {
  if (xhr.total) document.getElementById('loading').textContent = 'Loading car + aero solve… ' + Math.round(xhr.loaded/xhr.total*100) + '%';
}, err => {
  console.error(err);
  document.getElementById('loading').textContent = 'Failed to load rb19.glb — open via http://127.0.0.1:8765';
});

let physicsIsDirty = false;
document.getElementById('aoa').addEventListener('input', e => {
  state.aoaDeg = parseFloat(e.target.value);
  document.getElementById('aoa-val').textContent = state.aoaDeg.toFixed(1) + '°';
  physicsIsDirty = true;
});
document.getElementById('flap').addEventListener('input', e => {
  state.flapDeg = parseFloat(e.target.value);
  document.getElementById('flap-val').textContent = state.flapDeg.toFixed(0) + '°';
  physicsIsDirty = true;
});
document.getElementById('wind').addEventListener('input', e => {
  state.windMult = parseFloat(e.target.value);
  document.getElementById('wind-val').textContent = state.windMult.toFixed(1) + '×';
});
document.getElementById('thickness').addEventListener('input', e => {
  state.tubeRadius = parseFloat(e.target.value);
  document.getElementById('thickness-val').textContent = state.tubeRadius.toFixed(3);
  if (aeroReady) buildStreamlines();
});

let lastT = performance.now();
function animate() {
  requestAnimationFrame(animate);
  const now = performance.now();
  const dt = Math.min((now - lastT) / 1000, 0.05);
  lastT = now;
  if (physicsIsDirty && aeroReady) { physicsIsDirty = false; recompute(); }
  if (aeroReady) updateFlowMarkers(dt);
  renderer.render(scene, camera);
}
animate();
'''

# Ensure recompute calls solve + buildStreamlines
if "solvePanelSystem()" not in PHYS:
    PHYS = PHYS.rstrip()
    # insert before final closing of recompute — find last occurrence of ml-readout block end
    if "buildStreamlines()" not in PHYS:
        PHYS += "\n  solvePanelSystem();\n  buildStreamlines();\n"

# If PHYS already has solve/build from original, good. Check original end of recompute
phys_end = "\n".join(lines[600:642])
print("PHYS tail has solve:", "solvePanelSystem" in phys_end)
print("PHYS tail has build:", "buildStreamlines" in phys_end)

out = HTML_HEAD + JS_SCENE + "\n// PANEL\n" + PANEL + "\n" + SOLVE + "\n" + MODEL + "\n" + PHYS + "\n" + JS_STREAM + "\n" + JS_CAR + "\n</script>\n</body>\n</html>\n"
(ROOT / "index.html").write_text(out, encoding="utf-8")
print("Wrote", ROOT / "index.html", "bytes", (ROOT / "index.html").stat().st_size)
