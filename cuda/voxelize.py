"""Voxelize exported part triangles into a solid occupancy grid for the LBM solver.

Usage:
    python cuda/voxelize.py [--dx 0.025] [--parts all|frontwing,nose,...] [--out cuda/grid_all.bin]

Output: a raw uint8 grid (x fastest, then y, then z) plus a .json sidecar with
dims, origin and dx in the site's world coordinates (nose at +x, ground y=0,
car centred on z=0). The grid covers the whole wind-tunnel domain.

Solid = triangle surface cells (dilated one cell to close pinholes) plus the
body interior, found with a morphological closing + exterior flood fill that is
restricted to cells enclosed by skin on every axis, so the thin gap under the
floor stays open.
"""
import argparse
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PARTS = ["frontwing", "nose", "sidepods", "floor", "rearwing"]

# Wind-tunnel extents in world units (the car is ~5.5 long, nose at x≈+2.75).
DOMAIN = {"x": (-11.0, 6.0), "y": (0.0, 3.2), "z": (-3.0, 3.0)}
# Half tunnel for the symmetry-plane solve (z >= 0 only), used for fine grids.
DOMAIN_HALF = {"x": (-9.0, 5.5), "y": (0.0, 2.8), "z": (0.0, 2.4)}


def load_tris(parts):
    arrs = [np.fromfile(HERE / "geom" / f"{p}.f32", dtype=np.float32) for p in parts]
    return np.concatenate(arrs).reshape(-1, 3, 3).astype(np.float64)


def surface_cells(tris, origin, dx, dims):
    """Mark every cell touched by a triangle by sampling it at < dx/2 spacing."""
    solid = np.zeros(dims[::-1], dtype=np.uint8)  # (nz, ny, nx)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    longest = np.maximum.reduce([np.linalg.norm(b - a, axis=1),
                                 np.linalg.norm(c - b, axis=1),
                                 np.linalg.norm(a - c, axis=1)])
    steps = np.ceil(longest / (dx * 0.4)).astype(int) + 1
    for n in np.unique(steps):
        sel = steps == n
        ta, tb, tc = a[sel], b[sel], c[sel]
        # barycentric lattice with n subdivisions per edge
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        keep = i + j <= n
        u = (i[keep] / n)[None, :, None]
        v = (j[keep] / n)[None, :, None]
        for s in range(0, len(ta), max(1, 400000 // u.shape[1])):
            pa, pb, pc = ta[s:s + 400000 // u.shape[1] or 1], tb[s:s + 400000 // u.shape[1] or 1], tc[s:s + 400000 // u.shape[1] or 1]
            pts = pa[:, None] + u * (pb - pa)[:, None] + v * (pc - pa)[:, None]
            idx = np.floor((pts.reshape(-1, 3) - origin) / dx).astype(int)
            ok = np.all((idx >= 0) & (idx < dims), axis=1)
            idx = idx[ok]
            solid[idx[:, 2], idx[:, 1], idx[:, 0]] = 1
    return solid


def dilate(solid, k=1):
    """Grow by k cells (cube structuring element, separable per axis).
    Padded so nothing wraps across opposite faces of the grid."""
    out = np.pad(solid, k)
    for ax in range(3):
        acc = out.copy()
        for s in range(1, k + 1):
            acc |= np.roll(out, s, ax) | np.roll(out, -s, ax)
        out = acc
    return out[k:-k, k:-k, k:-k]


def erode(solid, k=1):
    return 1 - dilate(1 - solid, k)


def between(surface, ax):
    """1 where a cell has surface on both sides of it along axis `ax`."""
    before = np.maximum.accumulate(surface, axis=ax)
    after = np.flip(np.maximum.accumulate(np.flip(surface, ax), axis=ax), ax)
    return before & after


def fill_interior(solid):
    """Flood-fill the exterior from the grid faces; unreached cells are solid."""
    free = solid == 0
    reached = np.zeros(solid.shape, dtype=bool)
    for sl in [np.s_[0], np.s_[-1], np.s_[:, 0], np.s_[:, -1], np.s_[:, :, 0], np.s_[:, :, -1]]:
        reached[sl] = free[sl]
    frontier = reached.copy()
    while frontier.any():  # grow the outside region one layer per pass
        grow = np.zeros_like(frontier)
        grow[1:] |= frontier[:-1]; grow[:-1] |= frontier[1:]
        grow[:, 1:] |= frontier[:, :-1]; grow[:, :-1] |= frontier[:, 1:]
        grow[:, :, 1:] |= frontier[:, :, :-1]; grow[:, :, :-1] |= frontier[:, :, 1:]
        frontier = grow & free & ~reached
        reached |= frontier
    return (~reached).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dx", type=float, default=0.025)
    ap.add_argument("--parts", default="all")
    ap.add_argument("--out", default=None)
    ap.add_argument("--close", type=float, default=0.1, help="hole-closing radius (world units)")
    ap.add_argument("--half", action="store_true", help="z >= 0 only, for the solver's symmetry plane")
    args = ap.parse_args()
    parts = PARTS if args.parts == "all" else args.parts.split(",")
    out = Path(args.out or HERE / f"grid_{args.parts.replace(',', '+')}.bin")

    dx = args.dx
    dom = DOMAIN_HALF if args.half else DOMAIN
    origin = np.array([dom["x"][0], dom["y"][0], dom["z"][0]])
    dims = np.array([round((dom[k][1] - dom[k][0]) / dx) for k in "xyz"])
    tris = load_tris(parts)
    print(f"{len(tris)} triangles, grid {dims.tolist()} = {dims.prod() / 1e6:.1f}M cells")
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    print(f"car bounds {lo.round(3).tolist()} .. {hi.round(3).tolist()}")

    surface = dilate(surface_cells(tris, origin, dx, dims), 1)
    # The skin isn't watertight, so a plain flood fill leaks into the body.
    # Close gaps up to ~2*close cells: dilate, fill, then erode back (a
    # morphological closing of the filled volume), and keep the thin surfaces
    # (wing elements, endplates) that the closing would shave off.
    close = max(1, round(args.close / dx))
    pad = close + 2  # room around the car so the closing never touches the grid faces
    closed = erode(fill_interior(dilate(np.pad(surface, pad), close)), close)[pad:-pad, pad:-pad, pad:-pad]
    # Closing alone would also seal the thin gap under the floor (and between
    # nearby parts), killing ground effect. Only keep closed cells that are
    # enclosed by skin along every axis, i.e. genuinely inside the body.
    solid = (closed & between(surface, 0) & between(surface, 1) & between(surface, 2)) | surface
    solid[:, 0, :] = 0  # the ground row is handled by the solver's moving wall
    assert not solid[:, -1, :].any() and not solid[-1].any(), "car touches the tunnel walls"
    assert args.half or not solid[0].any(), "car touches the tunnel walls"
    print(f"solid cells: {solid.sum()} ({solid.mean() * 100:.2f}%)")

    solid.tofile(out)
    meta = {"nx": int(dims[0]), "ny": int(dims[1]), "nz": int(dims[2]),
            "dx": dx, "origin": origin.tolist(), "parts": parts, "half": args.half,
            "car_min": lo.tolist(), "car_max": hi.tolist()}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
