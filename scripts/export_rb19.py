from pxr import Usd, UsdGeom
from pathlib import Path
import numpy as np
import struct
import json

stage = Usd.Stage.Open(r"c:\Model\rb19_extract\scene.usdc")
meters = UsdGeom.GetStageMetersPerUnit(stage)

all_pos, all_nrm, all_uv, all_idx = [], [], [], []
vbase = 0


def triangulate(counts, indices):
    tris = []
    i = 0
    for c in counts:
        face = indices[i : i + c]
        for k in range(1, c - 1):
            tris.extend([int(face[0]), int(face[k]), int(face[k + 1])])
        i += c
    return np.array(tris, dtype=np.uint32)


for prim in stage.Traverse():
    if prim.GetTypeName() != "Mesh":
        continue
    mesh = UsdGeom.Mesh(prim)
    pts = np.array(mesh.GetPointsAttr().Get(), dtype=np.float32)
    counts = np.array(mesh.GetFaceVertexCountsAttr().Get(), dtype=np.int32)
    indices = np.array(mesh.GetFaceVertexIndicesAttr().Get(), dtype=np.int32)
    normals = mesh.GetNormalsAttr().Get()
    pv = UsdGeom.PrimvarsAPI(prim)
    st = pv.GetPrimvar("st0")
    uvs = (
        np.array(st.Get(), dtype=np.float32).reshape(-1, 2)
        if st and st.Get()
        else np.zeros((len(pts), 2), np.float32)
    )

    xformable = UsdGeom.Xformable(prim)
    mat = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    ones = np.ones((len(pts), 1), np.float32)
    hp = np.hstack([pts, ones])
    M = np.array([[mat[i][j] for j in range(4)] for i in range(4)], dtype=np.float32)
    pts_w = (hp @ M)[:, :3].astype(np.float32)

    if normals is not None and len(normals) == len(pts):
        nrm = np.array(normals, dtype=np.float32)
        R = M[:3, :3]
        nrm_w = nrm @ R
        lens = np.linalg.norm(nrm_w, axis=1, keepdims=True)
        lens[lens == 0] = 1
        nrm_w = (nrm_w / lens).astype(np.float32)
    else:
        nrm_w = np.zeros_like(pts_w)
        nrm_w[:, 1] = 1

    tris = triangulate(counts, indices) + vbase
    all_pos.append(pts_w)
    all_nrm.append(nrm_w)
    all_uv.append(uvs)
    all_idx.append(tris)
    vbase += len(pts_w)
    print(prim.GetName(), "ok", len(pts_w), "tris", len(tris) // 3)

pos = np.concatenate(all_pos)
nrm = np.concatenate(all_nrm)
uv = np.concatenate(all_uv)
idx = np.concatenate(all_idx)
print("TOTAL verts", len(pos), "tris", len(idx) // 3)

pos *= float(meters)
minv = pos.min(0)
maxv = pos.max(0)
center = (minv + maxv) * 0.5
pos[:, 0] -= center[0]
pos[:, 2] -= center[2]
pos[:, 1] -= minv[1]
print("final bbox", pos.min(0), pos.max(0))

pos_b = pos.astype(np.float32).tobytes()
nrm_b = nrm.astype(np.float32).tobytes()
uv_b = uv.astype(np.float32).tobytes()
idx_b = idx.astype(np.uint32).tobytes()
tex_bytes = Path(r"c:\Model\rb19_extract\0\Full_Body_Baked_baseColor.jpg").read_bytes()

buf = bytearray()


def add(data):
    while len(buf) % 4:
        buf.append(0)
    off = len(buf)
    buf.extend(data)
    return off, len(data)


o_pos, l_pos = add(pos_b)
o_nrm, l_nrm = add(nrm_b)
o_uv, l_uv = add(uv_b)
o_idx, l_idx = add(idx_b)
o_img, l_img = add(tex_bytes)
blob = bytes(buf)
blob += b"\x00" * ((4 - (len(blob) % 4)) % 4)

minin = [float(x) for x in pos.min(0)]
maxin = [float(x) for x in pos.max(0)]

gltf = {
    "asset": {"version": "2.0", "generator": "rb19-usd-export"},
    "scene": 0,
    "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0, "name": "RB19"}],
    "meshes": [
        {
            "name": "Full_Body_Baked",
            "primitives": [
                {
                    "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                    "indices": 3,
                    "material": 0,
                }
            ],
        }
    ],
    "materials": [
        {
            "name": "Full_Body_Baked",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.15,
                "roughnessFactor": 0.45,
            },
            "doubleSided": True,
        }
    ],
    "textures": [{"source": 0}],
    "images": [{"mimeType": "image/jpeg", "bufferView": 4, "name": "baseColor"}],
    "accessors": [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": len(pos),
            "type": "VEC3",
            "max": maxin,
            "min": minin,
        },
        {"bufferView": 1, "componentType": 5126, "count": len(nrm), "type": "VEC3"},
        {"bufferView": 2, "componentType": 5126, "count": len(uv), "type": "VEC2"},
        {"bufferView": 3, "componentType": 5125, "count": len(idx), "type": "SCALAR"},
    ],
    "bufferViews": [
        {"buffer": 0, "byteOffset": o_pos, "byteLength": l_pos, "target": 34962},
        {"buffer": 0, "byteOffset": o_nrm, "byteLength": l_nrm, "target": 34962},
        {"buffer": 0, "byteOffset": o_uv, "byteLength": l_uv, "target": 34962},
        {"buffer": 0, "byteOffset": o_idx, "byteLength": l_idx, "target": 34963},
        {"buffer": 0, "byteOffset": o_img, "byteLength": l_img},
    ],
    "buffers": [{"byteLength": len(blob)}],
}

json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
json_bytes += b" " * ((4 - (len(json_bytes) % 4)) % 4)
total = 12 + 8 + len(json_bytes) + 8 + len(blob)
out = bytearray()
out += struct.pack("<4sII", b"glTF", 2, total)
out += struct.pack("<I4s", len(json_bytes), b"JSON")
out += json_bytes
out += struct.pack("<I4s", len(blob), b"BIN\x00")
out += blob
out_path = Path(r"c:\Model\rb19.glb")
out_path.write_bytes(out)
print("Wrote", out_path, "sizeMB", round(out_path.stat().st_size / 1e6, 2))
