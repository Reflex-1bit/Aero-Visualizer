# F1 Aero Flow — RB19 Streamline Visualizer

An interactive 3D aerodynamics visualizer for a Formula 1 car (RB19 model). It renders
the car as a translucent neon shell and traces wind streamlines over, around, and under
the body using a lightweight potential-flow model (freestream + horseshoe-vortex +
source-panel solve for the rear wing, with voxel-based body deflection for the rest).

**Live demo:** https://aero-visual.vercel.app

## Screenshots

| 3/4 view — streamlines over the body | Rear view — underbody & wake flow |
| --- | --- |
| ![3/4 flow view](screenshots/flow-3q.png) | ![rear flow view](screenshots/flow-rear.png) |

## Features

- Real-time streamlines that hug the bodywork and glide along the ground.
- Structural part menu — isolate the front wing, nose, sidepods, floor, or rear wing
  and see each part's solid shell plus its own wind interaction.
- Rear wing driven by an ML-trained section-Cl model feeding a horseshoe/panel solve;
  other parts use freestream deflected around their voxelized solids.
- Neon-green highlighting on the key aero surfaces (front & rear wings), black
  silhouette outlining, and soft cast shadows.
- Camera presets (3/4, side, front, top, rear), wind-speed and line-thickness controls.
- Mobile-friendly: responsive HUD, one-finger orbit, two-finger pinch zoom, and reduced
  GPU load on phones.

## Machine learning · airfoil Cl/Cd model

The rear-wing aerodynamics are informed by a small ML model that predicts lift (`Cl`) and
drag (`Cd`) coefficients directly from airfoil shape. The full training notebook lives in
[`ml/airfoil_ml_project.ipynb`](ml/airfoil_ml_project.ipynb).

**Data.** A public OpenFOAM CFD dataset of 2,946 airfoils at Reynolds number 1e5. Each
airfoil is described by 8 [CST shape coefficients](https://en.wikipedia.org/wiki/Class_shape_transformation)
and sampled across ~11–13 angles of attack, giving `Cl` and `Cd` per (shape, AoA).

**Features → targets.** Inputs are `AoA` + the 8 CST coefficients (9 features); outputs are
`[Cl, Cd]`.

**Leakage-safe split.** Because each airfoil appears in many rows (one per AoA), a naive
row-level split would leak the same shape into both train and validation. The notebook uses
`GroupShuffleSplit` keyed on the airfoil filename so every shape lands entirely in train
*or* validation — never both — giving an honest estimate of generalization to unseen shapes.

**Models.**
- *Baseline:* multi-output linear regression on standardized features.
- *Neural net (`AeroNet`, PyTorch):* a 9 → 64 → 64 → 2 MLP with ReLU activations, trained
  with Adam (lr 1e-3, MSE, 300 epochs, batch 256). Both inputs **and** targets are
  standardized so the loss isn't dominated by `Cl`'s larger scale (`Cl` ~ -1..2 vs
  `Cd` ~ 0.001..0.09); predictions are inverse-transformed back to physical units.

**Evaluation.** Beyond a single R², the notebook breaks error down by angle of attack,
surfaces the worst individual predictions, and plots predicted-vs-true parity for both
coefficients — error rising near stall (high AoA) is expected as the flow becomes nonlinear.

Run the notebook top-to-bottom with `airfoil_data.csv` alongside it; later cells depend on
variables (`df`, `model`, …) defined earlier.

## Running locally

The app loads `rb19.glb` via `fetch`, so it must be served over HTTP (not opened as a
`file://` URL):

```bash
python -m http.server 8765
# then open http://127.0.0.1:8765/index.html
```

## Project layout

| Path | Description |
| --- | --- |
| `index.html` | The entire app (Three.js scene, physics, UI). |
| `rb19.glb` | The 3D car model loaded at runtime (Draco-compressed, ~2.5 MB). |
| `ml/` | Airfoil Cl/Cd machine-learning notebook. |
| `scripts/` | Model export / aero-assembly pipeline and iterative build patches (`export_rb19.py`, `assemble_aero.py`, `fix_*.py`, `patch_*.py`). |
| `data/` | Model source & metadata (`rb19.zip`, `_model_extract.json`, `model.txt`). |
| `dev/` | Dev / debugging harnesses (`probe.html`, `smoke_flow.html`, `debug_flow.js`, `check_dom.py`). |
| `screenshots/` | Preview images used in this README. |

## Tech

- [Three.js](https://threejs.org/) r128 + GLTFLoader / DRACOLoader (via CDN)
- Vanilla JS, no build step
- Deployed as a static site on Vercel

## Deploy

```bash
# static deploy of the site + model
vercel deploy ./dist --prod
```
