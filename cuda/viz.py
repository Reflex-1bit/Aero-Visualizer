"""Quick-look PNG slices of a solver result: python cuda/viz.py out/test grid_test.json"""
import json, sys
import numpy as np
from PIL import Image

pref, gjson = sys.argv[1], sys.argv[2]
m = json.load(open(gjson)); nx, ny, nz, dx = m["nx"], m["ny"], m["nz"], m["dx"]
a = np.fromfile(pref + "_avg.f32", np.float32).reshape(nz, ny, nx, 4)
solid = np.fromfile(gjson.replace(".json", ".bin"), np.uint8).reshape(nz, ny, nx)
spd = np.linalg.norm(a[..., :3], axis=-1)
cp = a[..., 3]
fl = solid == 0
print("speed/U  min %.2f max %.2f | Cp min %.2f max %.2f | mean Cp far field %.3f" % (
    spd[fl].min(), spd[fl].max(), cp[fl].min(), cp[fl].max(), cp[:, -4:, :].mean()))

def cmap(v, lo, hi):
    t = np.clip((v - lo) / (hi - lo), 0, 1)
    r = np.clip(1.5 - abs(4 * t - 3), 0, 1); g = np.clip(1.5 - abs(4 * t - 2), 0, 1); b = np.clip(1.5 - abs(4 * t - 1), 0, 1)
    return (np.stack([r, g, b], -1) * 255).astype(np.uint8)

def panel(field, sol, lo, hi):
    img = cmap(field, lo, hi); img[sol == 1] = 255
    return img

k = int(0.3 / dx); zc = 0 if m.get("half") else nz // 2  # centreline
rows = [panel(spd[zc][::-1], solid[zc][::-1], 0, 1.6),
        panel(cp[zc][::-1], solid[zc][::-1], -2, 1),
        panel(spd[:, max(1, int(0.05 / dx))], solid[:, max(1, int(0.05 / dx))], 0, 1.6),
        panel(spd[:, int(0.5 / dx)], solid[:, int(0.5 / dx)], 0, 1.6)]
sep = np.full((3, nx, 3), 90, np.uint8)
out = np.vstack(sum([[r, sep] for r in rows], [])[:-1])
scale = max(1, 900 // nx)
Image.fromarray(out).resize((out.shape[1] * scale, out.shape[0] * scale), Image.NEAREST).save(sys.argv[3] if len(sys.argv) > 3 else pref + "_slices.png")
