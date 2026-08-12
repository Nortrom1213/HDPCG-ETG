import { computeCanonicalRoute, validateETG } from "./etg-utils.js";
import {
  createDefaultEtg,
  DEFAULT_SPEED,
  NODE_TYPES,
  NODE_TYPES_LIST,
  normalizeEtg,
} from "./etg-core.js";

const canvas = document.querySelector("#graph-canvas");
const nodeList = document.querySelector("#node-list");
const edgeList = document.querySelector("#edge-list");
const selectionPanel = document.querySelector("#selection-panel");
const validationOutput = document.querySelector("#validation-output");
const routeOutput = document.querySelector("#route-output");

const addNodeButton = document.querySelector("#add-node");
const addEdgeButton = document.querySelector("#add-edge");
const autoLayoutButton = document.querySelector("#auto-layout");
const validateButton = document.querySelector("#validate");
const exportButton = document.querySelector("#export-json");
const importInput = document.querySelector("#import-json");
const playButton = document.querySelector("#play-preview");
const hdpcgButton = document.querySelector("#hdpcg-preview");

const ctx = canvas.getContext("2d");
const view = { x: 0, y: 0, scale: 1 };

let graph = inflateLayout(createDefaultEtg());
let selection = null;
let dragging = null;
let panning = null;
let resizeObserver = null;
let edgeMode = { active: false, from: null };
let canonicalCache = { ok: false, edges: new Set(), nodes: [] };

const TYPE_COLORS = {
  [NODE_TYPES.START]: "#1abc9c",
  [NODE_TYPES.GOAL]: "#27ae60",
  [NODE_TYPES.NONE]: "#95a5a6",
  [NODE_TYPES.PLATFORM]: "#7f8c8d",
  [NODE_TYPES.JUMP]: "#d97732",
  [NODE_TYPES.DROP]: "#3498db",
  [NODE_TYPES.ENEMY]: "#c0392b",
  [NODE_TYPES.KEY]: "#f1c40f",
  [NODE_TYPES.LOCK]: "#8e44ad",
};

function inflateLayout(etgOrGraph) {
  const etg = etgOrGraph?.version === 2 ? etgOrGraph : normalizeEtg(etgOrGraph);
  const layout = etgOrGraph?.layout || {};
  const nodes = (etg.nodes || []).map((node, idx) => {
    const pos = layout[node.id];
    const hasLayout = pos && Number.isFinite(pos.x) && Number.isFinite(pos.y);
    return {
      ...node,
      x: hasLayout ? pos.x : 120 + idx * 140,
      y: hasLayout ? pos.y : 120,
    };
  });
  const edges = (etg.edges || []).map((edge) => ({ ...edge }));
  return {
    version: 2,
    nodes,
    edges,
    meta: {
      ...(etg.meta || {}),
      defaultSpeed: etg?.meta?.defaultSpeed ?? DEFAULT_SPEED,
    },
    layout,
  };
}

function deflateGraph() {
  const layout = {};
  const nodes = graph.nodes.map((node) => {
    layout[node.id] = { x: node.x, y: node.y };
    const { x, y, ...rest } = node;
    return rest;
  });
  const edges = graph.edges.map((edge) => ({ ...edge }));
  const meta = { ...(graph.meta || {}), defaultSpeed: graph?.meta?.defaultSpeed ?? DEFAULT_SPEED };
  return { version: 2, nodes, edges, meta, layout };
}

function recomputeCanonical() {
  const payload = deflateGraph();
  const normalized = normalizeEtg(payload);
  const canonical = computeCanonicalRoute(normalized, { defaultSpeed: normalized?.meta?.defaultSpeed ?? DEFAULT_SPEED });
  canonicalCache = {
    ok: Boolean(canonical.ok),
    nodes: canonical.nodes || [],
    edgeIds: canonical.edges || [],
    edges: new Set(canonical.edges || []),
    totalLength: canonical.totalLength || 0,
    totalEtaSeconds: canonical.totalEtaSeconds || 0,
    reason: canonical.reason || null,
    defaultSpeed: canonical.defaultSpeed || (normalized?.meta?.defaultSpeed ?? DEFAULT_SPEED),
  };
}

function updateRoutePanel() {
  recomputeCanonical();
  if (!routeOutput) return;
  if (!canonicalCache.ok) {
    routeOutput.textContent = `canonical: unavailable\nreason: ${canonicalCache.reason || "no feasible path"}`;
    return;
  }
  const lines = [];
  lines.push(`defaultSpeed: ${canonicalCache.defaultSpeed.toFixed(2)} u/s`);
  lines.push(`totalLength: ${canonicalCache.totalLength.toFixed(2)} u`);
  lines.push(`eta: ${canonicalCache.totalEtaSeconds.toFixed(2)} s`);
  lines.push(`nodes: ${canonicalCache.nodes.join(" -> ")}`);
  routeOutput.textContent = lines.join("\n");
}

function resizeCanvas() {
  const rect = canvas.parentElement.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;
  canvas.width = rect.width * window.devicePixelRatio;
  canvas.height = rect.height * window.devicePixelRatio;
  ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
  draw();
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.save();
  ctx.translate(view.x, view.y);
  ctx.scale(view.scale, view.scale);
  drawEdges();
  drawNodes();
  ctx.restore();
}

function nodeRadius(node) {
  const type = primaryType(node);
  if (type === NODE_TYPES.START || type === NODE_TYPES.GOAL) return 22;
  if (type === NODE_TYPES.NONE) return 20;
  const intensity = clamp(node?.intensity ?? 0.5, 0, 1);
  return 22 + intensity * 26;
}

function nodeLabel(node) {
  if (!node) return "";
  const types = getTypes(node);
  const labelParts = [];
  for (const t of types) {
    if (t === NODE_TYPES.NONE) continue;
    if (t === NODE_TYPES.KEY) {
      labelParts.push(`Key(${node.key_id || "K1"})`);
    } else if (t === NODE_TYPES.LOCK) {
      labelParts.push(`Lock(${node.requires_key_id || "K1"})`);
    } else {
      labelParts.push(t);
    }
  }
  return labelParts.join("+");
}

function drawNodes() {
  for (const node of graph.nodes) {
    const r = nodeRadius(node);
    const fill = TYPE_COLORS[primaryType(node)] || "#ffffff";
    const selected = selection?.type === "node" && selection.id === node.id;
    ctx.fillStyle = selected ? "#fef9f2" : fill;
    ctx.strokeStyle = selected ? "#d97732" : "#2d271f";
    ctx.lineWidth = selected ? 3 : 2;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#1e1b16";
    ctx.font = "16px 'Space Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText(nodeLabel(node), node.x, node.y + 4);
  }
}

function drawEdges() {
  recomputeCanonical();
  for (const edge of graph.edges) {
    const from = graph.nodes.find((n) => n.id === edge.from);
    const to = graph.nodes.find((n) => n.id === edge.to);
    if (!from || !to) continue;

    const isCanonical = canonicalCache.ok && canonicalCache.edges.has(edge.id);
    const baseColor = isCanonical ? "#2a7f71" : "#9b7d60";
    const selected = selection?.type === "edge" && selection.id === edge.id;
    ctx.strokeStyle = selected ? "#d97732" : baseColor;
    // Encode edge length as thickness (longer = thicker).
    const len = Math.max(1, Number(edge.length || 1));
    const thickness = clamp(1.5 + Math.log10(len + 1) * 3.5, 1.5, 10);
    ctx.lineWidth = (isCanonical ? 1.6 : 1.0) * thickness;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }
}

function screenToWorld(x, y) {
  return { x: (x - view.x) / view.scale, y: (y - view.y) / view.scale };
}

function pointerToWorld(event) {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  return screenToWorld(x, y);
}

function hitTestNode(point) {
  return graph.nodes.find((node) => {
    const r = nodeRadius(node);
    const dx = point.x - node.x;
    const dy = point.y - node.y;
    return dx * dx + dy * dy <= r * r;
  });
}

function distanceToSegment(point, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq === 0) return Math.hypot(point.x - a.x, point.y - a.y);
  let t = ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSq;
  t = Math.max(0, Math.min(1, t));
  const projX = a.x + t * dx;
  const projY = a.y + t * dy;
  return Math.hypot(point.x - projX, point.y - projY);
}

function hitTestEdge(point) {
  const threshold = 7 / view.scale;
  for (const edge of graph.edges) {
    const from = graph.nodes.find((n) => n.id === edge.from);
    const to = graph.nodes.find((n) => n.id === edge.to);
    if (!from || !to) continue;
    const dist = distanceToSegment(point, from, to);
    if (dist < threshold) return edge;
  }
  return null;
}

function setSelection(target) {
  selection = target;
  renderSelectionPanel();
  draw();
}

function updateLists() {
  nodeList.innerHTML = "";
  for (const node of graph.nodes) {
    const item = document.createElement("button");
    item.className = "list-item";
    const label = nodeLabel(node);
    item.textContent = `${node.id}${label ? ` (${label})` : ""} i=${Number(node.intensity ?? 0).toFixed(2)}`;
    item.addEventListener("click", () => setSelection({ type: "node", id: node.id }));
    nodeList.appendChild(item);
  }

  edgeList.innerHTML = "";
  for (const edge of graph.edges) {
    const item = document.createElement("button");
    item.className = "list-item";
    const len = Number(edge.length || 0).toFixed(0);
    item.textContent = `${edge.id} ${edge.from} -> ${edge.to} len=${len}`;
    item.addEventListener("click", () => setSelection({ type: "edge", id: edge.id }));
    edgeList.appendChild(item);
  }
}

function renderSelectionPanel() {
  selectionPanel.innerHTML = "";
  if (!selection) {
    selectionPanel.innerHTML = '<p class="hint">Select a node or edge to edit properties.</p>';
    return;
  }
  if (selection.type === "node") {
    const node = graph.nodes.find((n) => n.id === selection.id);
    if (!node) return;
    selectionPanel.appendChild(renderNodeForm(node));
  } else {
    const edge = graph.edges.find((e) => e.id === selection.id);
    if (!edge) return;
    selectionPanel.appendChild(renderEdgeForm(edge));
  }
}

function renderNodeForm(node) {
  const form = document.createElement("div");
  form.className = "form";

  form.appendChild(makeLabel("ID", makeReadOnlyInput(node.id)));
  const types = getTypes(node);
  const ground = getGroundType(types);
  const overlays = new Set(types.filter((t) => [NODE_TYPES.ENEMY, NODE_TYPES.KEY, NODE_TYPES.LOCK].includes(t)));

  form.appendChild(makeLabel("Ground Type", makeSelect(
    [NODE_TYPES.NONE, NODE_TYPES.PLATFORM, NODE_TYPES.JUMP, NODE_TYPES.DROP],
    ground,
    (value) => {
      const next = new Set(getTypes(node).filter((t) => ![NODE_TYPES.NONE, NODE_TYPES.PLATFORM, NODE_TYPES.JUMP, NODE_TYPES.DROP].includes(t)));
      next.add(value);
      // Preserve None for overlay-only nodes; this path always selects a ground type.
      setTypes(node, Array.from(next));
      updateLists();
      updateRoutePanel();
      draw();
    }
  )));

  form.appendChild(makeLabel("Overlays", makeOverlayChecks(overlays, (nextOverlays) => {
    const base = new Set([getGroundType(getTypes(node))]);
    for (const o of nextOverlays) base.add(o);
    setTypes(node, Array.from(base));
    updateLists();
    updateRoutePanel();
    draw();
  })));

  form.appendChild(makeLabel("Intensity (0-1)", makeRange(node.intensity ?? 0.5, 0, 1, 0.01, (value) => {
    node.intensity = value;
    updateLists();
    updateRoutePanel();
    draw();
  })));

  if (getTypes(node).includes(NODE_TYPES.KEY)) {
    form.appendChild(makeLabel("Key ID", makeTextInput(node.key_id || "K1", (value) => {
      node.key_id = value.trim() || "K1";
      updateRoutePanel();
    })));
  }
  if (getTypes(node).includes(NODE_TYPES.LOCK)) {
    form.appendChild(makeLabel("Requires Key ID", makeTextInput(node.requires_key_id || "K1", (value) => {
      node.requires_key_id = value.trim() || "K1";
      updateRoutePanel();
    })));
    form.appendChild(makeLabel("Lock ID (optional)", makeTextInput(node.lock_id || "", (value) => {
      node.lock_id = value.trim();
    })));
  }

  const removeButton = document.createElement("button");
  removeButton.textContent = "Delete Node";
  removeButton.addEventListener("click", () => {
    graph.edges = graph.edges.filter((edge) => edge.from !== node.id && edge.to !== node.id);
    graph.nodes = graph.nodes.filter((n) => n.id !== node.id);
    selection = null;
    updateLists();
    updateRoutePanel();
    renderSelectionPanel();
    draw();
  });
  form.appendChild(removeButton);

  return form;
}

function renderEdgeForm(edge) {
  const form = document.createElement("div");
  form.className = "form";

  form.appendChild(makeLabel("ID", makeReadOnlyInput(edge.id)));
  form.appendChild(makeLabel("From", makeSelect(graph.nodes.map((n) => n.id), edge.from, (value) => {
    edge.from = value;
    updateLists();
    updateRoutePanel();
    draw();
  })));
  form.appendChild(makeLabel("To", makeSelect(graph.nodes.map((n) => n.id), edge.to, (value) => {
    edge.to = value;
    updateLists();
    updateRoutePanel();
    draw();
  })));
  form.appendChild(makeLabel("Length (u)", makeNumberInput(edge.length ?? 30, 1, 100000, 1, (value) => {
    edge.length = value;
    updateLists();
    updateRoutePanel();
    draw();
  })));

  const removeButton = document.createElement("button");
  removeButton.textContent = "Delete Edge";
  removeButton.addEventListener("click", () => {
    graph.edges = graph.edges.filter((e) => e.id !== edge.id);
    selection = null;
    updateLists();
    updateRoutePanel();
    renderSelectionPanel();
    draw();
  });
  form.appendChild(removeButton);

  return form;
}

function validateGraph() {
  const payload = deflateGraph();
  const normalized = normalizeEtg(payload);
  const result = validateETG(normalized);
  const canonical = computeCanonicalRoute(normalized, { defaultSpeed: normalized?.meta?.defaultSpeed ?? DEFAULT_SPEED });
  const lines = [];
  if (result.issues.length === 0 && result.warnings.length === 0) {
    lines.push("ETG validation: ok");
  }
  if (result.issues.length) {
    lines.push("issues:");
    result.issues.forEach((issue) => lines.push(`- ${issue}`));
  }
  if (result.warnings.length) {
    lines.push("warnings:");
    result.warnings.forEach((warning) => lines.push(`- ${warning}`));
  }
  if (!canonical.ok) {
    lines.push("issues:");
    lines.push(`- canonical route missing: ${canonical.reason || "no feasible path"}`);
  }
  validationOutput.textContent = lines.join("\n");
  updateRoutePanel();
}

function exportJson() {
  const payload = deflateGraph();
  const json = JSON.stringify(payload, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "etg_graph.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function importJson(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result);
      let etg = null;
      etg = normalizeEtg(data);
      graph = inflateLayout({ ...etg, layout: data.layout || {} });
      updateLists();
      updateRoutePanel();
      renderSelectionPanel();
      draw();
    } catch (err) {
      validationOutput.textContent = "failed to import JSON";
    }
  };
  reader.readAsText(file);
}

function playPreview() {
  const payload = deflateGraph();
  localStorage.setItem("etg_override", JSON.stringify(payload));
  window.open("index.html?etg=1", "_blank");
}

function playHdpcgPreview() {
  const payload = deflateGraph();
  localStorage.setItem("etg_override", JSON.stringify(payload));
  window.open("hdpcg_viewer.html?etg=1", "_blank");
}

function autoLayout() {
  updateRoutePanel();
  if (!canonicalCache.ok) {
    // Space nodes by index.
    for (let i = 0; i < graph.nodes.length; i += 1) {
      graph.nodes[i].x = 120 + i * 160;
      graph.nodes[i].y = 120;
    }
    draw();
    return;
  }
  const payload = deflateGraph();
  const edgesById = new Map(payload.edges.map((e) => [e.id, e]));
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));

  let x = 120;
  const yMain = 140;
  const placed = new Set();
  for (let i = 0; i < canonicalCache.nodes.length; i += 1) {
    const nodeId = canonicalCache.nodes[i];
    const node = nodeById.get(nodeId);
    if (!node) continue;
    if (i > 0) {
      const usedEdgeId = canonicalCache.edgeIds?.[i - 1] || null;
      const edge = usedEdgeId ? edgesById.get(usedEdgeId) : null;
      const len = edge?.length ?? 30;
      x += Math.max(80, len * 4);
    }
    node.x = x;
    node.y = yMain;
    placed.add(node.id);
  }

  // Place non-canonical nodes in lanes near their closest connected canonical node.
  const laneY = [yMain + 160, yMain - 160, yMain + 320, yMain - 320];
  let laneIdx = 0;
  for (const node of graph.nodes) {
    if (placed.has(node.id)) continue;
    // Find a connected canonical neighbor to anchor x.
    const incident = graph.edges.find((e) => e.from === node.id || e.to === node.id);
    let anchorX = 200;
    if (incident) {
      const neighborId = incident.from === node.id ? incident.to : incident.from;
      const neighbor = nodeById.get(neighborId);
      if (neighbor) anchorX = neighbor.x;
    }
    node.x = anchorX + 80;
    node.y = laneY[laneIdx % laneY.length];
    laneIdx += 1;
  }

  updateLists();
  draw();
}

function loadStoredGraph() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("etg") !== "1") return;
  const raw = localStorage.getItem("etg_override");
  if (!raw) return;
  try {
    const data = JSON.parse(raw);
    const etg = normalizeEtg(data);
    graph = inflateLayout({ ...etg, layout: data.layout || {} });
    updateLists();
    updateRoutePanel();
    renderSelectionPanel();
    draw();
  } catch (err) {
    validationOutput.textContent = "failed to load stored ETG";
  }
}

function createNode(type, x, y) {
  const id = `N${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const node = { id, type, types: [type], intensity: 0.5, x, y };
  if (type === NODE_TYPES.KEY) node.key_id = "K1";
  if (type === NODE_TYPES.LOCK) {
    node.requires_key_id = "K1";
    node.lock_id = "L1";
  }
  return node;
}

function createEdge(from, to) {
  const id = `E${Date.now()}${Math.floor(Math.random() * 1000)}`;
  return { id, from, to, length: 30 };
}

function makeLabel(text, control) {
  const wrapper = document.createElement("label");
  wrapper.textContent = text;
  wrapper.appendChild(control);
  return wrapper;
}

function makeReadOnlyInput(value) {
  const input = document.createElement("input");
  input.type = "text";
  input.value = value;
  input.readOnly = true;
  return input;
}

function makeTextInput(value, onChange) {
  const input = document.createElement("input");
  input.type = "text";
  input.value = value;
  input.addEventListener("input", (event) => onChange(event.target.value));
  return input;
}

function makeNumberInput(value, min, max, step, onChange) {
  const input = document.createElement("input");
  input.type = "number";
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = Number(value ?? min);
  input.addEventListener("input", (event) => onChange(Number(event.target.value)));
  return input;
}

function makeRange(value, min, max, step, onChange) {
  const wrapper = document.createElement("div");
  wrapper.style.display = "grid";
  wrapper.style.gridTemplateColumns = "1fr auto";
  wrapper.style.gap = "8px";

  const input = document.createElement("input");
  input.type = "range";
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = Number(value ?? 0);
  const badge = document.createElement("div");
  badge.className = "hint";
  badge.textContent = Number(input.value).toFixed(2);

  const sync = () => {
    badge.textContent = Number(input.value).toFixed(2);
    onChange(Number(input.value));
  };
  input.addEventListener("input", sync);
  wrapper.appendChild(input);
  wrapper.appendChild(badge);
  return wrapper;
}

function makeSelect(options, value, onChange) {
  const select = document.createElement("select");
  for (const option of options) {
    const opt = document.createElement("option");
    opt.value = option;
    opt.textContent = option;
    if (option === value) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener("change", (event) => onChange(event.target.value));
  return select;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function getTypes(node) {
  if (Array.isArray(node?.types) && node.types.length) return node.types.slice();
  if (node?.type) return [node.type];
  return [NODE_TYPES.NONE];
}

function setTypes(node, types) {
  const cleaned = Array.from(new Set((types || []).filter((t) => NODE_TYPES_LIST.includes(t))));
  if (!cleaned.length) cleaned.push(NODE_TYPES.NONE);
  // Structural nodes are exclusive.
  if (cleaned.includes(NODE_TYPES.START)) cleaned.splice(0, cleaned.length, NODE_TYPES.START);
  if (cleaned.includes(NODE_TYPES.GOAL)) cleaned.splice(0, cleaned.length, NODE_TYPES.GOAL);
  // Ensure exactly one ground among None/Platform/Jump/Drop.
  const ground = getGroundType(cleaned);
  const overlays = cleaned.filter((t) => [NODE_TYPES.ENEMY, NODE_TYPES.KEY, NODE_TYPES.LOCK].includes(t));
  const finalTypes = [ground, ...overlays];
  node.types = finalTypes;
  node.type = primaryType(node); // compat
  if (!finalTypes.includes(NODE_TYPES.KEY)) delete node.key_id;
  if (!finalTypes.includes(NODE_TYPES.LOCK)) {
    delete node.requires_key_id;
    delete node.lock_id;
  }
  if (finalTypes.includes(NODE_TYPES.KEY) && !node.key_id) node.key_id = "K1";
  if (finalTypes.includes(NODE_TYPES.LOCK) && !node.requires_key_id) node.requires_key_id = "K1";
}

function getGroundType(types) {
  const set = new Set(types || []);
  if (set.has(NODE_TYPES.START)) return NODE_TYPES.START;
  if (set.has(NODE_TYPES.GOAL)) return NODE_TYPES.GOAL;
  if (set.has(NODE_TYPES.JUMP)) return NODE_TYPES.JUMP;
  if (set.has(NODE_TYPES.DROP)) return NODE_TYPES.DROP;
  if (set.has(NODE_TYPES.PLATFORM)) return NODE_TYPES.PLATFORM;
  return NODE_TYPES.NONE;
}

function primaryType(node) {
  return getGroundType(getTypes(node));
}

function makeOverlayChecks(selectedSet, onChange) {
  const wrapper = document.createElement("div");
  wrapper.className = "field-group";
  const make = (type, label) => {
    const row = document.createElement("label");
    row.className = "toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = selectedSet.has(type);
    input.addEventListener("change", () => {
      const next = new Set(selectedSet);
      if (input.checked) next.add(type);
      else next.delete(type);
      onChange(next);
    });
    row.appendChild(input);
    row.appendChild(document.createTextNode(label));
    return row;
  };
  wrapper.appendChild(make(NODE_TYPES.ENEMY, "Enemy"));
  wrapper.appendChild(make(NODE_TYPES.KEY, "Key"));
  wrapper.appendChild(make(NODE_TYPES.LOCK, "Lock"));
  return wrapper;
}

canvas.addEventListener("mousedown", (event) => {
  const point = pointerToWorld(event);
  const node = hitTestNode(point);
  if (edgeMode.active) {
    if (node) {
      if (!edgeMode.from) {
        edgeMode.from = node.id;
      } else {
        const edge = createEdge(edgeMode.from, node.id);
        graph.edges.push(edge);
        edgeMode = { active: false, from: null };
        addEdgeButton.classList.remove("active");
        updateLists();
        updateRoutePanel();
        draw();
      }
    }
    return;
  }

  if (node) {
    setSelection({ type: "node", id: node.id });
    dragging = { node, offsetX: point.x - node.x, offsetY: point.y - node.y };
    return;
  }

  const edge = hitTestEdge(point);
  if (edge) {
    setSelection({ type: "edge", id: edge.id });
    return;
  }

  panning = { startX: event.clientX, startY: event.clientY, baseX: view.x, baseY: view.y };
});

canvas.addEventListener("mousemove", (event) => {
  if (dragging) {
    const point = pointerToWorld(event);
    dragging.node.x = point.x - dragging.offsetX;
    dragging.node.y = point.y - dragging.offsetY;
    draw();
    return;
  }
  if (panning) {
    view.x = panning.baseX + (event.clientX - panning.startX);
    view.y = panning.baseY + (event.clientY - panning.startY);
    draw();
  }
});

canvas.addEventListener("mouseup", () => {
  dragging = null;
  panning = null;
});

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const delta = -event.deltaY * 0.001;
  view.scale = clamp(view.scale + delta, 0.5, 2.5);
  draw();
});

addNodeButton.addEventListener("click", () => {
  const node = createNode(NODE_TYPES.PLATFORM, 140, 160);
  graph.nodes.push(node);
  updateLists();
  updateRoutePanel();
  setSelection({ type: "node", id: node.id });
});

addEdgeButton.addEventListener("click", () => {
  edgeMode.active = !edgeMode.active;
  edgeMode.from = null;
  addEdgeButton.classList.toggle("active", edgeMode.active);
});

autoLayoutButton.addEventListener("click", autoLayout);
validateButton.addEventListener("click", validateGraph);
exportButton.addEventListener("click", exportJson);
importInput.addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) importJson(file);
});
playButton.addEventListener("click", playPreview);
hdpcgButton.addEventListener("click", playHdpcgPreview);

window.addEventListener("resize", resizeCanvas);
if ("ResizeObserver" in window) {
  resizeObserver = new ResizeObserver(() => resizeCanvas());
  resizeObserver.observe(canvas.parentElement);
}
resizeCanvas();
updateLists();
updateRoutePanel();
renderSelectionPanel();
draw();
loadStoredGraph();
