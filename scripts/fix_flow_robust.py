# -*- coding: utf-8 -*-
"""Make flow robust: freestream fallback + on-screen errors + verify camber."""
from pathlib import Path

path = Path(r"c:\Model\index.html")
t = path.read_text(encoding="utf-8")

assert "function cambered2DProfile" in t, "camber still missing!"

# Soften fieldVelocity if panels empty
old_fv = """function fieldVelocity(P) {
  const v = fieldVelocityVortexOnly(P);
  // Add the solved source-panel contribution - this is what makes flow actually
  // follow the wing's surface instead of passing through it, replacing the old
  // bounding-box clamp with a real, numerically-verified boundary condition.
  for (let j = 0; j < panelSystem.panels.length; j++) {
    const infl = panelSourceInfluence2D(P, panelSystem.panels[j], panelSystem.sigma[j]);
    v.x += infl.x; v.y += infl.y;
  }
  return v;
}"""

new_fv = """function fieldVelocity(P) {
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

if old_fv in t:
    t = t.replace(old_fv, new_fv, 1)
    print("patched fieldVelocity")
else:
    print("WARN: fieldVelocity block not exact match")

# Add window error overlay after canvas container
if "id=\"aero-error\"" not in t:
    t = t.replace(
        '<div id="loading">Loading car + aero solve…</div>',
        '''<div id="loading">Loading car + aero solve…</div>
<div id="aero-error" style="display:none;position:absolute;left:32px;top:120px;max-width:420px;z-index:20;font-family:JetBrains Mono,monospace;font-size:11px;color:#ff6b6b;line-height:1.5;pointer-events:none;"></div>''',
        1,
    )
    # inject error handlers near start of script after scene
    t = t.replace(
        "const container = document.getElementById('canvas-container');",
        """const container = document.getElementById('canvas-container');
function showAeroError(msg) {
  const el = document.getElementById('aero-error');
  if (el) { el.style.display = 'block'; el.textContent = String(msg); }
  console.error(msg);
}
window.addEventListener('error', e => showAeroError(e.message || e));
window.addEventListener('unhandledrejection', e => showAeroError(e.reason));
""",
        1,
    )
    print("added error overlay")

# In catch block of recompute, use showAeroError
t = t.replace(
    "console.error('[aero] solve/stream failed:', err);",
    "showAeroError('[aero] solve/stream failed: ' + (err && err.stack ? err.stack : err));",
    1,
)

path.write_text(t, encoding="utf-8")
print("size", path.stat().st_size)
