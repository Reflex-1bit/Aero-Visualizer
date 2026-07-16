# -*- coding: utf-8 -*-
from pathlib import Path
import re

path = Path(r"c:\Model\index.html")
t = path.read_text(encoding="utf-8")

# Replace force readout block inside recompute
t2, n = re.subn(
    r"document\.getElementById\('cl-readout'\)\.textContent = CL\.toFixed\(2\);\s*"
    r"document\.getElementById\('cd-readout'\)\.textContent = CDi\.toFixed\(3\);\s*"
    r"const mlNote = document\.getElementById\('ml-readout'\);\s*"
    r"if \(mlNote\) \{\s*"
    r"const flag = \(mainClamped \|\| flapClamped\) \? ' ! outside trained AoA range, clamped' : '';\s*"
    r"mlNote\.textContent = `model Cl: main \$\{state\.clMain\.toFixed\(3\)\} · flap \$\{state\.clFlap\.toFixed\(3\)\}\$\{flag\}`;\s*"
    r"\}",
    """const flowNote = document.getElementById('flow-readout');
  if (flowNote) flowNote.textContent = 'solving…';
  const mlNote = document.getElementById('ml-readout');
  if (mlNote) {
    const flag = (mainClamped || flapClamped) ? ' · AoA clamped to train range' : '';
    mlNote.textContent = `ML Cl main ${state.clMain.toFixed(2)} · flap ${state.clFlap.toFixed(2)}${flag}`;
  }""",
    t,
    count=1,
)
print("replaced readout block", n)
t = t2

# After successful buildStreamlines, update flow readout — patch buildStreamlines console.log end
old_log = """  console.log('[aero] streamlines:', streamPaths.length, 'panels:', panelSystem.panels.length,
    'Cl wing:', document.getElementById('cl-readout').textContent);"""
new_log = """  const flowNote = document.getElementById('flow-readout');
  if (flowNote) flowNote.textContent = streamPaths.length ? (streamPaths.length + ' streams live') : 'no streams';
  console.log('[aero] streamlines:', streamPaths.length, 'panels:', panelSystem.panels.length);"""
if old_log in t:
    t = t.replace(old_log, new_log, 1)
    print("patched buildStreamlines status")
else:
    print("log block missing, trying loose match")
    if "console.log('[aero] streamlines:'" in t:
        t = t.replace(
            "console.log('[aero] streamlines:', streamPaths.length, 'panels:', panelSystem.panels.length,\n    'Cl wing:', document.getElementById('cl-readout').textContent);",
            new_log,
            1,
        )
        print("patched loose")

# Caption
t = t.replace(
    """<div class="caption">
  Red / blue tubes = live streamlines (markers ride them).<br>
  CL is rear-wing only: your net predicts section Cl,<br>
  then Kutta–Joukowski → Γ → horseshoe CL — not full-car load.
</div>""",
    """<div class="caption">
  Red / blue = streamlines · bright dots ride the wind.<br>
  ML net sets rear-wing circulation; wind slider = speed.
</div>""",
)

path.write_text(t, encoding="utf-8")
print("cl refs left", t.count("cl-readout"), "cd", t.count("cd-readout"))
