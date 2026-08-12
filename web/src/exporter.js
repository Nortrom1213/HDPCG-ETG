export function buildExportPackage(level, report, options = {}) {
  const sampleDuration = options.sampleDuration ?? 10;
  const sampleStep = options.sampleStep ?? 1.0;
  const timingWindows = buildTimingWindows(level.etg);
  const phaseFlags = buildPhaseFlags(level.etg);

  const timeline = [];
  for (let t = 0; t <= sampleDuration + 1e-6; t += sampleStep) {
    timeline.push({
      t: Number(t.toFixed(2)),
      moving_platforms: level.platforms
        .filter((p) => p.kind === "moving" && p.motion)
        .map((p) => ({
          id: p.id,
          pos: sampleMotion(p, t),
        })),
      sweepers: (level.sweepers || []).map((s) => ({
        id: s.id,
        angle: sampleSweeperAngle(s, t),
      })),
      timed_gates: (level.timed_gates || []).map((g) => ({
        id: g.id,
        open: sampleTimedGateOpen(g, t),
      })),
      bumpers: level.bumpers || [],
      showcase_characters: level.showcase_characters || [],
      enemies: (level.enemies || []).map((e) => ({
        id: e.id,
        pos: sampleEnemy(e, t),
      })),
      flags: {
        has_key: buildFlagMap(level.keys, 0),
        lock_open: buildFlagMap(level.locks, 0),
      },
      phase: 0,
    });
  }

  return {
    meta: {
      ...level.meta,
      component_generation: level.meta?.component_generation || null,
    },
    etg: level.etg,
    constraints: {
      timing_windows: timingWindows,
      phase_flags: phaseFlags,
      component_generation: level.meta?.component_generation || null,
    },
    level: {
      platforms: level.platforms,
      enemies: level.enemies,
      sweepers: level.sweepers || [],
      timed_gates: level.timed_gates || [],
      bumpers: level.bumpers || [],
      showcase_characters: level.showcase_characters || [],
      keys: level.keys,
      locks: level.locks,
      checkpoints: level.checkpoints,
      start: level.start,
      goal: level.goal,
    },
    mapping: level.mapping,
    anchors: level.anchors,
    time_expanded: {
      duration: sampleDuration,
      step: sampleStep,
      timeline,
    },
    validation: report,
  };
}

function sampleMotion(platform, t) {
  const { axis, amplitude, period, phase } = platform.motion;
  const omega = (2 * Math.PI) / period;
  const offset = Math.sin(omega * t + phase) * amplitude;
  const pos = { ...platform.pos };
  pos[axis] = platform.pos[axis] + offset;
  return pos;
}

function sampleEnemy(enemy, t) {
  if (!enemy.patrol) return { ...enemy.pos };
  const span = enemy.patrol.to.x - enemy.patrol.from.x;
  const speed = enemy.speed || 1.0;
  const phase = (t * speed) % (2 * Math.abs(span));
  let offset = phase;
  if (offset > Math.abs(span)) offset = 2 * Math.abs(span) - offset;
  const dir = span >= 0 ? 1 : -1;
  return {
    x: enemy.patrol.from.x + dir * offset,
    y: enemy.patrol.from.y,
    z: enemy.patrol.from.z,
  };
}

function sampleSweeperAngle(sweeper, t) {
  const period = Math.max(0.001, Number(sweeper.period || 4.0));
  const direction = Number(sweeper.direction || 1) >= 0 ? 1 : -1;
  const phase = Number(sweeper.phase || 0);
  return direction * ((2 * Math.PI * t) / period) + phase;
}

function sampleTimedGateOpen(gate, t) {
  const period = Math.max(0.001, Number(gate.period || 5.0));
  const openDuration = Math.max(0, Math.min(period, Number(gate.openDuration || period * 0.45)));
  const phase = Number(gate.phase || 0);
  const local = ((t + phase) % period + period) % period;
  return local < openDuration;
}

function buildFlagMap(items, value) {
  const map = {};
  for (const item of items) {
    const key = item.key_id || item.lock_id || item.id;
    map[key] = value;
  }
  return map;
}

function buildTimingWindows(etg) {
  if (!etg) return {};
  const windows = {};
  for (const node of etg.nodes) {
    if (node.data?.timing_window) windows[node.id] = node.data.timing_window;
  }
  for (const edge of etg.edges) {
    if (edge.data?.window) windows[edge.id] = edge.data.window;
  }
  return windows;
}

function buildPhaseFlags(etg) {
  if (!etg) return {};
  const flags = {};
  if (etg.version === 2) {
    for (const node of etg.nodes || []) {
      const types = Array.isArray(node.types) && node.types.length ? node.types : node.type ? [node.type] : [];
      if (types.includes("Key")) {
        const keyId = node.key_id || "K1";
        flags[node.id] = [`has_key[${keyId}]=1`];
      }
      if (types.includes("Lock")) {
        const keyId = node.requires_key_id || "K1";
        flags[`${node.id}:pre`] = [`has_key[${keyId}]==1`];
      }
    }
    // Store edge length as an annotation.
    for (const edge of etg.edges || []) {
      if (typeof edge.length === "number" && Number.isFinite(edge.length)) {
        flags[edge.id] = [`edge_length=${Number(edge.length.toFixed?.(2) ?? edge.length)}`];
      }
    }
    return flags;
  }
  for (const node of etg.nodes) {
    if (node.effects && node.effects.length) flags[node.id] = node.effects.slice();
    if (node.preconditions && node.preconditions.length) flags[`${node.id}:pre`] = node.preconditions.slice();
  }
  for (const edge of etg.edges) {
    if (edge.effects && edge.effects.length) flags[edge.id] = edge.effects.slice();
    if (edge.preconditions && edge.preconditions.length) flags[`${edge.id}:pre`] = edge.preconditions.slice();
  }
  return flags;
}
