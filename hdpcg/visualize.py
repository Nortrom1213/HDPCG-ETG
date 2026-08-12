"""Interactive HTML visualizations for 5D level states and ETG comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hdpcg_bfs import compute_reachable
from .hdpcg_grid import build_hdpcg_model


PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def _to_cell_list(cell_ids: set[str]) -> list[list[int]]:
    out = []
    for cid in cell_ids:
        try:
            x, y, z = cid.split(",")
            out.append([int(x), int(y), int(z)])
        except Exception:
            continue
    return out


def _extract_frame_data(model: Any, reachable_step: Any, reachable_cumulative: Any, max_time: int) -> dict[str, Any]:
    frames: dict[str, dict[str, Any]] = {}
    for t in range(max_time + 1):
        env_t = model.wrapTime(t)
        surface = model.surfaceByTime[env_t]
        enemies = _to_cell_list(set(model.enemiesByTime[env_t]))
        for phase in range(model.phaseCount):
            open_cells = []
            locked_cells = []
            for cell in surface.values():
                cid = f"{cell['x']},{cell['y']},{cell['z']}"
                if model.isLockedCell(cid, phase):
                    locked_cells.append([cell["x"], cell["y"], cell["z"]])
                else:
                    open_cells.append([cell["x"], cell["y"], cell["z"]])
            step_reach = reachable_step[t][phase] if reachable_step is not None else set()
            cum_reach = reachable_cumulative[t][phase] if reachable_cumulative is not None else set()
            frames[f"{t}|{phase}"] = {
                "open": open_cells,
                "locked": locked_cells,
                "reachable_step": _to_cell_list(step_reach),
                "reachable_cumulative": _to_cell_list(cum_reach),
                "enemies": enemies,
            }
    return frames


def write_level_5d_html(level: dict[str, Any], out_path: str | Path, options: dict[str, Any] | None = None) -> str:
    options = options or {}
    model = build_hdpcg_model(
        level,
        {
            "cellSize": options.get("cellSize", 1),
            "timeStep": options.get("timeStep", 1),
            "padding": options.get("padding", 4),
            "maxTimeHorizon": options.get("maxTimeHorizon", 180),
            "maxPeriodTicks": options.get("maxPeriodTicks", 180),
        },
    )
    skip_reachable = bool(options.get("skipReachable", False))
    raw_max_time = options.get("maxTime")
    max_time_cap = int(raw_max_time) if raw_max_time is not None else None
    if skip_reachable:
        max_t = max_time_cap if max_time_cap is not None else min(40, max(1, int(model.timeHorizon) * 2))
        bfs = {
            "maxTime": max_t,
            "maxTimeUsed": max_t,
            "lastReachableCellTime": max_t,
            "visitedCount": 0,
            "expanded": 0,
            "truncated": False,
            "reachableCumulativeByTimePhase": None,
            "reachableCumulativeByTimeUnion": None,
        }
    else:
        bfs = compute_reachable(
            model,
            {
                "maxTime": max_time_cap,
                "maxStates": options.get("maxStates", 250000),
                "maxQueue": options.get("maxQueue", 100000),
                "maxJumpOffsets": options.get("maxJumpOffsets", 1400),
                "maxGroundDistance": options.get("maxGroundDistance"),
                "maxJumpDistance": options.get("maxJumpDistance"),
            },
        )

    raw_visual_max_time = options.get("visualMaxTime")
    if raw_visual_max_time is None:
        max_time = int(bfs.get("lastReachableCellTime", bfs.get("maxTimeUsed", bfs.get("maxTime", 0))))
    else:
        visual_max_time = int(raw_visual_max_time)
        if visual_max_time < 0:
            max_time = int(bfs.get("lastReachableCellTime", bfs.get("maxTimeUsed", bfs.get("maxTime", 0))))
        else:
            max_time = visual_max_time
    max_time = max(0, min(max_time, int(bfs.get("maxTime", max_time))))

    data = {
        "maxTime": max_time,
        "phaseCount": int(model.phaseCount),
        "frames": _extract_frame_data(
            model,
            bfs.get("reachableByTimePhase"),
            bfs.get("reachableCumulativeByTimePhase"),
            max_time,
        ),
        "keys": [[int(x) for x in cid.split(",")] for cid in model.keyCells.keys()],
        "locks": [[int(x) for x in cid.split(",")] for cid in model.lockCells.keys()],
        "start": [model.startCell["x"], model.startCell["y"], model.startCell["z"]] if model.startCell else None,
        "goal": [model.goalCell["x"], model.goalCell["y"], model.goalCell["z"]] if model.goalCell else None,
        "meta": {
            "seed": (level.get("meta") or {}).get("seed"),
            "timeHorizon": int(model.timeHorizon),
            "phaseCount": int(model.phaseCount),
            "visited": int(bfs.get("visitedCount", 0)),
            "expanded": int(bfs.get("expanded", 0)),
            "truncated": bool(bfs.get("truncated", False)),
            "timeLimitSource": "lastReachableCellTime",
            "skipReachable": skip_reachable,
        },
    }

    html = f"""<!doctype html>
<html>
<head>
<meta charset=\"utf-8\" />
<title>HDPCG 5D Viewer</title>
<script src=\"{PLOTLY_CDN}\"></script>
<style>
body {{ margin: 0; font-family: ui-monospace, Menlo, Consolas, monospace; background: #f3f1ea; color: #222; }}
#panel {{ display: grid; grid-template-columns: 360px 1fr; gap: 10px; height: 100vh; padding: 10px; box-sizing: border-box; }}
#controls {{ background: #fff; border: 1px solid #ddd; padding: 12px; overflow: auto; }}
#plot {{ background: #fff; border: 1px solid #ddd; }}
label {{ display:block; margin-top:8px; }}
input[type=range] {{ width: 100%; }}
.small {{ font-size: 12px; color: #555; line-height: 1.4; }}
</style>
</head>
<body>
<div id=\"panel\">
  <div id=\"controls\">
    <h3>HDPCG 5D Viewer</h3>
    <div id=\"status\" class=\"small\"></div>
    <label>Time <span id=\"tVal\">0</span></label>
    <input id=\"time\" type=\"range\" min=\"0\" max=\"{max_time}\" value=\"0\" />
    <label>Phase <span id=\"pVal\">0</span></label>
    <input id=\"phase\" type=\"range\" min=\"0\" max=\"{max(0, int(model.phaseCount)-1)}\" value=\"0\" />
    <label><input type=\"checkbox\" id=\"showReach\" checked /> Show Reachable</label>
    <label><input type=\"checkbox\" id=\"reachCumulative\" /> Reachable Cumulative</label>
    <label><input type=\"checkbox\" id=\"showEnemy\" checked /> Show Enemies</label>
    <label><input type=\"checkbox\" id=\"showLocked\" checked /> Show Locked Cells</label>
    <label><input type=\"checkbox\" id=\"showKeys\" checked /> Show Keys</label>
    <label><input type=\"checkbox\" id=\"showLockVol\" checked /> Show Lock Volume</label>
    <div class=\"small\">3D orbit: mouse drag/scroll in Plotly.\nColor: open=gray, locked=purple, reachable=teal, enemies=red, keys=gold.</div>
  </div>
  <div id=\"plot\"></div>
</div>
<script>
const DATA = {json.dumps(data, ensure_ascii=False)};
const plot = document.getElementById('plot');
const tEl = document.getElementById('time');
const pEl = document.getElementById('phase');
const tVal = document.getElementById('tVal');
const pVal = document.getElementById('pVal');
const status = document.getElementById('status');

function scatter3(name, cells, color, size, opacity) {{
  const x = cells.map(c => c[0]);
  const y = cells.map(c => c[1]);
  const z = cells.map(c => c[2]);
  return {{
    type: 'scatter3d', mode: 'markers', name,
    x, y, z,
    marker: {{ size, color, opacity }}
  }};
}}

function update() {{
  const t = Number(tEl.value);
  const p = Number(pEl.value);
  tVal.textContent = String(t);
  pVal.textContent = String(p);
  const k = `${{t}}|${{p}}`;
  const f = DATA.frames[k] || {{ open:[], locked:[], reachable_step:[], reachable_cumulative:[], enemies:[] }};

  const traces = [];
  traces.push(scatter3('open', f.open, '#b0aca2', 2.8, 0.75));
  if (document.getElementById('showLocked').checked) traces.push(scatter3('locked', f.locked, '#6c3483', 2.8, 0.70));
  const reachCells = document.getElementById('reachCumulative').checked ? f.reachable_cumulative : f.reachable_step;
  if (document.getElementById('showReach').checked) traces.push(scatter3('reachable', reachCells, '#1f8a70', 2.2, 0.35));
  if (document.getElementById('showEnemy').checked) traces.push(scatter3('enemy', f.enemies, '#c0392b', 4.0, 0.75));
  if (document.getElementById('showKeys').checked) traces.push(scatter3('keys', DATA.keys || [], '#f1c40f', 4.0, 0.9));
  if (document.getElementById('showLockVol').checked) traces.push(scatter3('lock_cells', DATA.locks || [], '#512e5f', 2.2, 0.35));
  if (DATA.start) traces.push(scatter3('start', [DATA.start], '#1abc9c', 5.5, 1.0));
  if (DATA.goal) traces.push(scatter3('goal', [DATA.goal], '#27ae60', 5.5, 1.0));

  const layout = {{
    margin: {{ l: 0, r: 0, b: 0, t: 0 }},
    scene: {{
      xaxis: {{ title: 'x' }}, yaxis: {{ title: 'y' }}, zaxis: {{ title: 'z' }},
      aspectmode: 'data'
    }},
    legend: {{orientation:'h'}}
  }};

  Plotly.react(plot, traces, layout, {{displaylogo:false, responsive:true}});
  const truncHint = DATA.meta.truncated ? ' | warning=budget_truncated' : '';
  status.textContent = `seed=${{DATA.meta.seed || '-'}} | t=${{t}}/${{DATA.maxTime}} | phase=${{p}}/${{DATA.phaseCount-1}} | visited=${{DATA.meta.visited}} | expanded=${{DATA.meta.expanded}} | truncated=${{DATA.meta.truncated}}${{truncHint}}`;
}}

tEl.addEventListener('input', update);
pEl.addEventListener('input', update);
for (const id of ['showReach','reachCumulative','showEnemy','showLocked','showKeys','showLockVol']) {{
  document.getElementById(id).addEventListener('change', update);
}}
update();
</script>
</body>
</html>
"""

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


def _graph_to_plot_data(etg: dict[str, Any], x_offset: float = 0.0) -> dict[str, Any]:
    nodes = etg.get("nodes") or []
    edges = etg.get("edges") or []
    n = max(1, len(nodes))
    pos = {}
    for i, node in enumerate(nodes):
        a = (2 * 3.141592653589793 * i) / n
        pos[node.get("id")] = (x_offset + 10 * __import__('math').cos(a), 10 * __import__('math').sin(a))

    line_x, line_y = [], []
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a not in pos or b not in pos:
            continue
        line_x += [pos[a][0], pos[b][0], None]
        line_y += [pos[a][1], pos[b][1], None]

    node_x, node_y, node_text = [], [], []
    for node in nodes:
        nid = node.get("id")
        if nid not in pos:
            continue
        node_x.append(pos[nid][0])
        node_y.append(pos[nid][1])
        node_text.append(f"{nid}\\n{','.join(node.get('types') or [node.get('type','None')])}")

    return {
        "line_x": line_x,
        "line_y": line_y,
        "node_x": node_x,
        "node_y": node_y,
        "node_text": node_text,
    }


def write_etg_html(etg: dict[str, Any], out_path: str | Path, title: str = "ETG Graph") -> str:
    g = _graph_to_plot_data(etg, x_offset=0)
    payload = {"g": g, "title": title}
    html = f"""<!doctype html>
<html>
<head>
<meta charset=\"utf-8\" />
<title>{title}</title>
<script src=\"{PLOTLY_CDN}\"></script>
<style>
body {{ margin:0; font-family: ui-monospace, Menlo, Consolas, monospace; background:#f3f1ea; }}
#plot {{ width:100vw; height:100vh; }}
#tag {{ position:fixed; left:12px; top:12px; background:#fff; border:1px solid #ccc; padding:8px; font-size:12px; }}
</style>
</head>
<body>
<div id=\"tag\">{title}</div>
<div id=\"plot\"></div>
<script>
const D = {json.dumps(payload, ensure_ascii=False)};
const traces = [
  {{ type:'scatter', mode:'lines', x:D.g.line_x, y:D.g.line_y, line:{{color:'#5d6d7e', width:1.5}}, name:'edges' }},
  {{ type:'scatter', mode:'markers+text', x:D.g.node_x, y:D.g.node_y, text:D.g.node_text, textposition:'top center', marker:{{size:10, color:'#3498db'}}, name:'nodes' }}
];
const layout = {{ xaxis:{{visible:false}}, yaxis:{{visible:false, scaleanchor:'x', scaleratio:1}}, margin:{{l:20,r:20,t:20,b:20}}, showlegend:true }};
Plotly.newPlot('plot', traces, layout, {{displaylogo:false, responsive:true}});
</script>
</body>
</html>
"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


def write_etg_comparison_html(expected_etg: dict[str, Any], observed_etg: dict[str, Any], out_path: str | Path) -> str:
    left = _graph_to_plot_data(expected_etg, x_offset=-18)
    right = _graph_to_plot_data(observed_etg, x_offset=18)
    payload = {"left": left, "right": right}

    html = f"""<!doctype html>
<html>
<head>
<meta charset=\"utf-8\" />
<title>ETG Comparison</title>
<script src=\"{PLOTLY_CDN}\"></script>
<style>
body {{ margin:0; font-family: ui-monospace, Menlo, Consolas, monospace; background:#f3f1ea; }}
#plot {{ width:100vw; height:100vh; }}
#tag {{ position:fixed; left:12px; top:12px; background:#fff; border:1px solid #ccc; padding:8px; font-size:12px; }}
</style>
</head>
<body>
<div id=\"tag\">Left: expected ETG | Right: observed ETG from global 5D search</div>
<div id=\"plot\"></div>
<script>
const D = {json.dumps(payload, ensure_ascii=False)};
const traces = [
  {{ type:'scatter', mode:'lines', x:D.left.line_x, y:D.left.line_y, line:{{color:'#5d6d7e', width:1.5}}, name:'expected edges' }},
  {{ type:'scatter', mode:'markers+text', x:D.left.node_x, y:D.left.node_y, text:D.left.node_text, textposition:'top center', marker:{{size:10, color:'#3498db'}}, name:'expected nodes' }},
  {{ type:'scatter', mode:'lines', x:D.right.line_x, y:D.right.line_y, line:{{color:'#7d3c98', width:1.5}}, name:'observed edges' }},
  {{ type:'scatter', mode:'markers+text', x:D.right.node_x, y:D.right.node_y, text:D.right.node_text, textposition:'top center', marker:{{size:10, color:'#e67e22'}}, name:'observed nodes' }}
];
const layout = {{ xaxis:{{visible:false}}, yaxis:{{visible:false, scaleanchor:'x', scaleratio:1}}, margin:{{l:20,r:20,t:20,b:20}}, showlegend:true }};
Plotly.newPlot('plot', traces, layout, {{displaylogo:false, responsive:true}});
</script>
</body>
</html>
"""

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)
