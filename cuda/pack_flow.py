"""Pack a solver result into the compact flow field the website loads.

Usage:
    python cuda/pack_flow.py cuda/out/all cuda/grid_all.json flow/all.flow [--dx 0.05]

Crops the tunnel to the region around the car and its wake, box-filters down to
the web resolution, and quantises (ux, uy, uz, Cp) to int8. The file is gzip
compressed (the page inflates it with DecompressionStream):

    bytes 0..3   : little-endian uint32 header length H
    bytes 4..4+H : JSON header {nx, ny, nz, dx, origin, vscale, pscale, cd, cl, ...}
    rest         : int8 [nz][ny][nx][4]  (x fastest), value = q * scale
"""
import argparse
import csv
import gzip
import json
import struct
from pathlib import Path

import numpy as np

CROP = {"x": (-9.0, 4.5), "y": (0.0, 2.4), "z": (-2.2, 2.2)}
VSCALE = 1 / 60   # velocity / U   -> int8 covers about +-2.1
PSCALE = 1 / 40   # Cp             -> int8 covers about +-3.2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("grid_json")
    ap.add_argument("out")
    ap.add_argument("--dx", type=float, default=0.05)
    args = ap.parse_args()

    g = json.loads(Path(args.grid_json).read_text())
    nx, ny, nz, dx = g["nx"], g["ny"], g["nz"], g["dx"]
    org = np.array(g["origin"])
    a = np.fromfile(args.prefix + "_avg.f32", np.float32).reshape(nz, ny, nx, 4)
    solid = np.fromfile(args.grid_json.replace(".json", ".bin"), np.uint8).reshape(nz, ny, nx)
    if g.get("half"):
        # Symmetry-plane solve covers z >= 0: mirror it (flipping uz) for z < 0.
        mirror = a[::-1].copy(); mirror[..., 2] *= -1
        a = np.concatenate([mirror, a]); solid = np.concatenate([solid[::-1], solid])
        nz *= 2; org = org.copy(); org[2] = -org[2] - g["nz"] * dx

    f = round(args.dx / dx)
    lo = [round((CROP[k][0] - org[i]) / dx) for i, k in enumerate("xyz")]
    n = [round((CROP[k][1] - CROP[k][0]) / args.dx) for k in "xyz"]
    sub = a[lo[2]:lo[2] + n[2] * f, lo[1]:lo[1] + n[1] * f, lo[0]:lo[0] + n[0] * f]
    ssub = solid[lo[2]:lo[2] + n[2] * f, lo[1]:lo[1] + n[1] * f, lo[0]:lo[0] + n[0] * f]
    # Box filter over fluid cells only, so walls don't smear zeros into the flow.
    fluid = (ssub == 0).astype(np.float32)
    blk = lambda v: v.reshape(n[2], f, n[1], f, n[0], f, *v.shape[3:]).sum((1, 3, 5))
    wsum = blk(fluid)
    field = blk(sub * fluid[..., None]) / np.maximum(wsum, 1)[..., None]
    field[wsum == 0] = 0  # fully solid coarse cells

    q = np.empty(field.shape, np.int8)
    q[..., :3] = np.clip(np.round(field[..., :3] / VSCALE), -127, 127)
    q[..., 3] = np.clip(np.round(field[..., 3] / PSCALE), -127, 127)

    forces = Path(args.prefix + "_forces.csv")
    cd = cl = None
    if forces.exists():
        rows = list(csv.DictReader(forces.open()))
        tail = rows[len(rows) // 2:]
        cd = float(np.mean([float(r["Cd"]) for r in tail]))
        cl = float(np.mean([float(r["Cl"]) for r in tail]))

    header = {
        "nx": n[0], "ny": n[1], "nz": n[2], "dx": args.dx,
        "origin": [CROP["x"][0], CROP["y"][0], CROP["z"][0]],
        "vscale": VSCALE, "pscale": PSCALE,
        "cd": cd, "cl": cl, "solver": "D3Q19 LBM, regularized BGK + Smagorinsky LES, rolling road",
        "sim_dx": dx,
    }
    hb = json.dumps(header).encode()
    raw = struct.pack("<I", len(hb)) + hb + q.tobytes()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(gzip.compress(raw, 9))
    print(f"{n} cells, raw {len(raw) / 1e6:.1f} MB -> {out} {out.stat().st_size / 1e6:.2f} MB | Cd={cd} Cl={cl}")


if __name__ == "__main__":
    main()
