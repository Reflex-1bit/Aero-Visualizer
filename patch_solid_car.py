# -*- coding: utf-8 -*-
"""Patch index.html: solid low-poly car + voxel no-penetration + stronger wing physics."""
from pathlib import Path
import re

path = Path(r"c:\Model\index.html")
t = path.read_text(encoding="utf-8")

# --- 1) Lights + collision globals after carGroup ---
old_car = """const NEON_WHITE = 0xf4f8ff, NEON_CYAN = 0x00d4ff, NEON_GOLD = 0xffc966, NEON_GREEN = 0x39ff88;
const carGroup = new THREE.Group(); scene.add(carGroup);
scene.add(new THREE.GridHelper(20, 30, 0x0a2a2e, 0x0a2a2e));"""

new_car = """const NEON_WHITE = 0xf4f8ff, NEON_CYAN = 0x00d4ff, NEON_GOLD = 0xffc966, NEON_GREEN = 0x39ff88;
const carGroup = new THREE.Group(); scene.add(carGroup);
scene.add(new THREE.GridHelper(20, 30, 0x0a2a2e, 0x0a2a2e));

// Studio lights so flat-shaded solid car reads properly
scene.add(new THREE.AmbientLight(0x6a7a88, 0.55));
const keyLight = new THREE.DirectionalLight(0xffffff, 0.95);
keyLight.position.set(5, 10, 4); scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0x88aacc, 0.35);
fillLight.position.set(-6, 4, -2); scene.add(fillLight);
const rimLight = new THREE.DirectionalLight(0x39ff88, 0.25);
rimLight.position.set(-2, 3, 8); scene.add(rimLight);

// Voxel solid body — streamlines cannot enter these cells (game-style collision)
let carVoxels = null;
function worldToVoxel(p) {
  if (!carVoxels) return null;
  const { origin, cell, nx, ny, nz } = carVoxels;
  const ix = Math.floor((p.x - origin.x) / cell);
  const iy = Math.floor((p.y - origin.y) / cell);
  const iz = Math.floor((p.z - origin.z) / cell);
  if (ix < 0 || iy < 0 || iz < 0 || ix >= nx || iy >= ny || iz >= nz) return null;
  return { ix, iy, iz, i: ix + nx * (iy + ny * iz) };
}
function isCarSolid(p) {
  const v = worldToVoxel(p);
  return v ? carVoxels.solid[v.i] === 1 : false;
}
function pushOutOfCar(p, preferDir) {
  if (!carVoxels || !isCarSolid(p)) return p.clone();
  const { origin, cell, nx, ny, nz, solid } = carVoxels;
  // Walk opposite flow / outward to nearest empty voxel
  const dir = preferDir && preferDir.lengthSq() > 1e-8
    ? preferDir.clone().normalize().multiplyScalar(-1)
    : new THREE.Vector3(0, 1, 0);
  let q = p.clone();
  for (let step = 0; step < 48; step++) {
    q.addScaledVector(dir, cell * 0.55);
    if (!isCarSolid(q)) {
      // Extra clearance so tubes don't clip
      q.addScaledVector(dir, cell * 0.8);
      return q;
    }
  }
  // Fallback: search 6-neighborhood from voxel
  const v = worldToVoxel(p);
  if (!v) return p.clone();
  const dirs = [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]];
  for (let r = 1; r <= 8; r++) {
    for (const [dx,dy,dz] of dirs) {
      const ix = v.ix + dx * r, iy = v.iy + dy * r, iz = v.iz + dz * r;
      if (ix < 0 || iy < 0 || iz < 0 || ix >= nx || iy >= ny || iz >= nz) continue;
      const i = ix + nx * (iy + ny * iz);
      if (solid[i] === 0) {
        return new THREE.Vector3(
          origin.x + (ix + 0.5) * cell,
          origin.y + (iy + 0.5) * cell,
          origin.z + (iz + 0.5) * cell
        );
      }
    }
  }
  return p.clone();
}

function voxelizeCar(shell, cellSize = 0.07) {
  const box = new THREE.Box3().setFromObject(shell);
  // Pad so surface sits inside grid
  box.min.addScalar(-cellSize);
  box.max.addScalar(cellSize);
  const size = box.getSize(new THREE.Vector3());
  const nx = Math.max(8, Math.ceil(size.x / cellSize));
  const ny = Math.max(6, Math.ceil(size.y / cellSize));
  const nz = Math.max(8, Math.ceil(size.z / cellSize));
  const solid = new Uint8Array(nx * ny * nz);
  const origin = box.min.clone();
  const vA = new THREE.Vector3(), vB = new THREE.Vector3(), vC = new THREE.Vector3();

  shell.updateMatrixWorld(true);
  shell.traverse((obj) => {
    if (!obj.isMesh || !obj.geometry) return;
    const geo = obj.geometry;
    const pos = geo.attributes.position;
    const idx = geo.index;
    const triCount = idx ? idx.count / 3 : pos.count / 3;
    // Stride long meshes so load stays interactive, still dense enough to seal the body
    const stride = triCount > 80000 ? 3 : (triCount > 30000 ? 2 : 1);
    for (let t = 0; t < triCount; t += stride) {
      let i0, i1, i2;
      if (idx) {
        i0 = idx.getX(t * 3); i1 = idx.getX(t * 3 + 1); i2 = idx.getX(t * 3 + 2);
      } else {
        i0 = t * 3; i1 = t * 3 + 1; i2 = t * 3 + 2;
      }
      vA.fromBufferAttribute(pos, i0).applyMatrix4(obj.matrixWorld);
      vB.fromBufferAttribute(pos, i1).applyMatrix4(obj.matrixWorld);
      vC.fromBufferAttribute(pos, i2).applyMatrix4(obj.matrixWorld);
      const minX = Math.min(vA.x, vB.x, vC.x), maxX = Math.max(vA.x, vB.x, vC.x);
      const minY = Math.min(vA.y, vB.y, vC.y), maxY = Math.max(vA.y, vB.y, vC.y);
      const minZ = Math.min(vA.z, vB.z, vC.z), maxZ = Math.max(vA.z, vB.z, vC.z);
      const i0x = Math.max(0, Math.floor((minX - origin.x) / cellSize));
      const i1x = Math.min(nx - 1, Math.floor((maxX - origin.x) / cellSize));
      const i0y = Math.max(0, Math.floor((minY - origin.y) / cellSize));
      const i1y = Math.min(ny - 1, Math.floor((maxY - origin.y) / cellSize));
      const i0z = Math.max(0, Math.floor((minZ - origin.z) / cellSize));
      const i1z = Math.min(nz - 1, Math.floor((maxZ - origin.z) / cellSize));
      for (let ix = i0x; ix <= i1x; ix++) {
        for (let iy = i0y; iy <= i1y; iy++) {
          for (let iz = i0z; iz <= i1z; iz++) {
            solid[ix + nx * (iy + ny * iz)] = 1;
          }
        }
      }
    }
  });

  // Dilate once so thin panels (wings) don't leak
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
  carVoxels = { solid: dilate, origin, cell: cellSize, nx, ny, nz };
  console.log('[aero] voxels', nx, ny, nz, 'solid', filled);
}"""

if old_car not in t:
    raise SystemExit("carGroup block not found")
t = t.replace(old_car, new_car, 1)
print("patched lights + voxels")

# --- 2) Stronger field near wing (scale panel + vortex) ---
old_fv = """function fieldVelocity(P) {
  const v = fieldVelocityVortexOnly(P);
  if (panelSystem && panelSystem.panels && panelSystem.sigma) {
    for (let j = 0; j < panelSystem.panels.length; j++) {
      const sig = panelSystem.sigma[j];
      if (!isFinite(sig)) continue;
      const infl = panelSourceInfluence2D(P, panelSystem.panels[j], sig);
      if (isFinite(infl.x) && isFinite(infl.y)) { v.x += infl.x; v.y += infl.y; }
    }
  }
  // Always keep freestream alive so wind never dies
  if (!isFinite(v.x) || !isFinite(v.y) || !isFinite(v.z) || v.lengthSq() < 1e-8) {
    return new THREE.Vector3(-state.Vinf, 0, 0);
  }
  return v;
}"""

new_fv = """function fieldVelocity(P) {
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

if old_fv not in t:
    raise SystemExit("fieldVelocity block not found")
t = t.replace(old_fv, new_fv, 1)
print("patched fieldVelocity")

# --- 3) Integrate with car voxel collision ---
old_int = """function integrateStreamline(seed) {
  const pts = [seed.clone()];
  let p = seed.clone();
  for (let i = 0; i < STREAM_STEPS; i++) {
    for (let sub = 0; sub < 3; sub++) {
      const dt = STREAM_DT / 3;
      const v = fieldVelocityWorld(p);
      if (!v || !isFinite(v.x) || v.length() < 1e-5) { i = STREAM_STEPS; break; }
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
        const c = state.tubeRadius + 0.01;
        next = aeroToWorld(new THREE.Vector3(pA.x + r2d.x * closestT + hitPanel.nx * c, pA.y + r2d.y * closestT + hitPanel.ny * c, nA.z));
      } else if (panelSystem.polygons) {
        for (const poly of panelSystem.polygons) {
          if (pointInPolygon({ x: nA.x, y: nA.y }, poly)) {
            const pushed = nearestPanelPushOut({ x: nA.x, y: nA.y });
            next = aeroToWorld(new THREE.Vector3(pushed.x, pushed.y, nA.z));
            break;
          }
        }
      }
      p = next; pts.push(p.clone());
      if (p.x < -5.2 || Math.abs(p.z) > 2.2 || p.y < -0.15 || p.y > 2.4) { i = STREAM_STEPS; break; }
    }
  }
  return pts;
}"""

new_int = """function integrateStreamline(seed) {
  const pts = [seed.clone()];
  let p = seed.clone();
  if (isCarSolid(p)) p = pushOutOfCar(p, new THREE.Vector3(-1, 0, 0));

  for (let i = 0; i < STREAM_STEPS; i++) {
    for (let sub = 0; sub < 3; sub++) {
      const dt = STREAM_DT / 3;
      let v = fieldVelocityWorld(p);
      if (!v || !isFinite(v.x) || v.length() < 1e-5) { i = STREAM_STEPS; break; }

      // If about to enter solid car, strip the into-body component (impermeable wall)
      let probe = p.clone().addScaledVector(v, dt * 0.35);
      if (isCarSolid(probe)) {
        // Try slide: kill velocity into solid by testing axis cancellations
        const candidates = [
          new THREE.Vector3(0, v.y, v.z),
          new THREE.Vector3(v.x, 0, v.z),
          new THREE.Vector3(v.x, v.y, 0),
          new THREE.Vector3(v.x * 0.2, v.y + Math.sign(v.y || 1) * 0.35, v.z),
          new THREE.Vector3(v.x * 0.2, v.y, v.z + (p.z >= 0 ? 0.5 : -0.5)),
        ];
        let found = false;
        for (const c of candidates) {
          if (c.lengthSq() < 1e-6) continue;
          const test = p.clone().addScaledVector(c.clone().normalize().multiplyScalar(v.length()), dt * 0.35);
          if (!isCarSolid(test)) { v = c.setLength(v.length()); found = true; break; }
        }
        if (!found) {
          p = pushOutOfCar(p, v);
          pts.push(p.clone());
          continue;
        }
      }

      const mid = p.clone().addScaledVector(v, dt * 0.5);
      let next = p.clone().addScaledVector(fieldVelocityWorld(mid), dt);

      // Wing panel no-penetration (your source-panel solve)
      const pA = worldToAero(p), nA = worldToAero(next);
      const r2d = { x: nA.x - pA.x, y: nA.y - pA.y };
      let closestT = null, hitPanel = null;
      for (const panel of panelSystem.panels) {
        const hit = segIntersect2D({ x: pA.x, y: pA.y }, r2d, panel.a, { x: panel.b.x - panel.a.x, y: panel.b.y - panel.a.y });
        if (hit && (closestT === null || hit.t < closestT)) { closestT = hit.t; hitPanel = panel; }
      }
      if (closestT !== null && hitPanel) {
        const c = state.tubeRadius + 0.012;
        next = aeroToWorld(new THREE.Vector3(
          pA.x + r2d.x * closestT + hitPanel.nx * c,
          pA.y + r2d.y * closestT + hitPanel.ny * c,
          nA.z
        ));
      } else if (panelSystem.polygons) {
        for (const poly of panelSystem.polygons) {
          if (pointInPolygon({ x: nA.x, y: nA.y }, poly)) {
            const pushed = nearestPanelPushOut({ x: nA.x, y: nA.y });
            next = aeroToWorld(new THREE.Vector3(pushed.x, pushed.y, nA.z));
            break;
          }
        }
      }

      // Full-car solid body block
      if (isCarSolid(next)) next = pushOutOfCar(next, v);

      p = next;
      pts.push(p.clone());
      if (p.x < -5.2 || Math.abs(p.z) > 2.4 || p.y < -0.15 || p.y > 2.5) { i = STREAM_STEPS; break; }
    }
  }
  return pts;
}"""

if old_int not in t:
    raise SystemExit("integrateStreamline block not found")
t = t.replace(old_int, new_int, 1)
print("patched integrateStreamline")

# --- 4) Replace car loader with solid flat-shaded mesh + voxelize ---
# Find from `let aeroReady = false;` through the loader's closing `});` before physicsIsDirty
start = t.find("let aeroReady = false;")
end = t.find("\nlet physicsIsDirty = false;")
if start < 0 or end < 0:
    raise SystemExit("loader bounds not found")

new_loader = r'''let aeroReady = false;
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

  // Solid flat-shaded car (game-style polygons, not a ghost wireframe)
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
});

'''

t = t[:start] + new_loader + t[end:]
print("patched loader")

# Caption tweak
t = t.replace(
    """<div class="caption">
  Red / blue = streamlines · bright dots ride the wind.<br>
  ML net sets rear-wing circulation; wind slider = speed.
</div>""",
    """<div class="caption">
  Solid flat-shaded car · wind cannot pass through voxels.<br>
  ML Cl → Γ → horseshoe + panels on the rear wing.<br>
  Neon green = key aero edges.
</div>""",
)

# Title sub
t = t.replace(
    "ML section Cl · horseshoe + panel method",
    "solid body · ML wing solve · no-penetration flow",
)

path.write_text(t, encoding="utf-8")
print("OK bytes", path.stat().st_size)
