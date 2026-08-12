# HDPCG-ETG

HDPCG-ETG generates 3D platformer levels from Experience Topological Graphs.
It includes incremental topology-aware generation, four baselines, 5D
validation, reproducible experiment runners, and browser-based editing and
visualization tools.

## Install

```powershell
py -3 -m pip install -r requirements.txt
```

## Generate

```powershell
py -3 -m hdpcg generate
```

Generated files are written under `out/`, which is ignored by Git.

## Experiments

```powershell
py -3 -m hdpcg make-etg-bank
py -3 -m hdpcg run-benchmark
py -3 scripts/run_ablation.py
py -3 scripts/run_fall_guys_pilot.py
py -3 scripts/build_results.py
```

These defaults use the paper protocol. Simulator, QD selection, search budgets,
method profiles, metrics, and execution settings are defined in
`configs/paper.json`; ablation variants and optional overrides are in
`configs/ablation_profiles.json` and `configs/topology_overrides.json`.
Run outputs include resolved seeds and budgets, all eight paper dimensions,
Overall-score dispersion, runtime, and budget/non-budget failure summaries.
The paper CP-SAT profile uses one worker and deterministic-time stopping.

## Web tools

Start a server from the repository root:

```powershell
py -3 -m http.server 8000
```

Open:

- `http://localhost:8000/web/editor.html` for ETG editing.
- `http://localhost:8000/web/index.html` for runtime preview.
- `http://localhost:8000/web/hdpcg_viewer.html` for 5D inspection.
- `http://localhost:8000/web/obstacle_course_editor.html` for the procedural obstacle-course adapter.

The web tools render each scene with procedural geometry.
