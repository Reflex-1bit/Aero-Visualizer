# -*- coding: utf-8 -*-
from pathlib import Path

path = Path(r"c:\Model\index.html")
t = path.read_text(encoding="utf-8")

print("has cambered2DProfile fn:", "function cambered2DProfile" in t)

CAMBER = r'''
function cambered2DProfile(chord, camberFrac, thicknessFrac, nPts = 24) {
  const pts = [];
  for (let i = 0; i <= nPts; i++) {
    const u = i / nPts;
    const x = u * chord;
    const camber = camberFrac * chord * Math.sin(Math.PI * u);
    const thickness = thicknessFrac * chord * Math.sin(Math.PI * u) * (1 - u * 0.3);
    pts.push(new THREE.Vector2(x, camber + thickness));
  }
  for (let i = nPts; i >= 0; i--) {
    const u = i / nPts;
    const x = u * chord;
    const camber = camberFrac * chord * Math.sin(Math.PI * u);
    const thickness = thicknessFrac * chord * Math.sin(Math.PI * u) * (1 - u * 0.3);
    pts.push(new THREE.Vector2(x, camber - thickness));
  }
  return pts;
}

'''

if "function cambered2DProfile" not in t:
    needle = "// PANEL\n\nconst SPAN"
    if needle not in t:
        needle = "// PANEL\r\n\r\nconst SPAN"
    if needle not in t:
        # fallback
        t = t.replace("const SPAN = 1.65;", CAMBER + "const SPAN = 1.65;", 1)
    else:
        t = t.replace(needle, "// PANEL\n" + CAMBER + "const SPAN", 1)
    print("inserted cambered2DProfile")
else:
    print("already present")

# Harden recompute so a throw can't silently kill flow
old = """  solvePanelSystem();
  buildStreamlines();
}"""
new = """  try {
    solvePanelSystem();
    buildStreamlines();
  } catch (err) {
    console.error('[aero] solve/stream failed:', err);
    const mlNote = document.getElementById('ml-readout');
    if (mlNote) mlNote.textContent = 'aero error: ' + (err && err.message ? err.message : err);
  }
}"""
if old in t:
    t = t.replace(old, new, 1)
    print("hardened recompute")
else:
    print("recompute block not found exactly")

path.write_text(t, encoding="utf-8")
print("done", path.stat().st_size)
