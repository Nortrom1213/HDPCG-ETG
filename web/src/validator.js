import { isEtg, validateEtg } from "./etg-core.js";
import { computeCanonicalRoute } from "./etg-utils.js";

const DEFAULTS = {
  maxGap: 5.5,
  maxVertical: 3.2,
  minPeriod: 1.2,
  maxAmplitude: 3.2,
  minWindowSpan: 0.15,
  minWindowOpen: 0.1,
  maxWindowClose: 0.95,
  mainLaneZ: 0,
  laneTolerance: 2,
  repairSideLanes: false,
  skipRegionConnectors: true,
  autoRepairMissingKeys: true,
};

export function validateAndRepair(level, config = {}) {
  const settings = { ...DEFAULTS, ...config };
  if (!settings.generatorMode) settings.generatorMode = level?.meta?.generator_mode || null;
  const report = {
    status: "ok",
    issues: [],
    fixes: [],
    warnings: [],
  };

  validateEtgStructure(level, report);
  validateKeyLock(level, settings, report);
  validatePlatforms(level, settings, report);
  validateMovingPlatforms(level, settings, report);
  validateEnemies(level, report);
  validateTimingConstraints(level, settings, report);
  validateMapping(level, report);
  validateEtgOrdering(level, report);

  if (report.issues.length > 0 || report.fixes.length > 0) {
    report.status = "repaired";
  }

  return report;
}

function validateEtgStructure(level, report) {
  if (!isEtg(level?.etg)) return;
  const result = validateEtg(level.etg);
  for (const issue of result.issues || []) report.warnings.push(`etg: ${issue}`);
  for (const warning of result.warnings || []) report.warnings.push(`etg: ${warning}`);
  const canonical = computeCanonicalRoute(level.etg, { defaultSpeed: level.etg?.meta?.defaultSpeed });
  if (!canonical.ok) {
    report.warnings.push(`etg: canonical route missing (${canonical.reason || "no feasible path"})`);
  }
}

function validateKeyLock(level, settings, report) {
  const keyIds = new Set(level.keys.map((key) => key.key_id));
  for (const lock of level.locks) {
    if (!keyIds.has(lock.key_id)) {
      report.issues.push(`lock ${lock.lock_id} missing key ${lock.key_id}`);
      if (settings.autoRepairMissingKeys) {
        const synthetic = insertSyntheticKey(level, lock);
        keyIds.add(lock.key_id);
        report.fixes.push(`insert key ${synthetic.id} (${synthetic.key_id}) for lock ${lock.lock_id}`);
      } else {
        report.warnings.push(`lock ${lock.lock_id} remains locked without a valid key`);
      }
    }
  }
}

function validatePlatforms(level, settings, report) {
  if (settings.generatorMode && settings.generatorMode !== "lane") {
    return;
  }
  const lanes = groupByLane(level.platforms);
  const canonical = level.etg ? computeCanonicalRoute(level.etg, { defaultSpeed: level.etg?.meta?.defaultSpeed }) : null;
  const mainNodes = new Set(canonical?.ok ? canonical.nodes : []);
  for (const [laneKey, lane] of Object.entries(lanes)) {
    const laneZ = Number(laneKey);
    lane.sort((a, b) => a.pos.x - b.pos.x);
    for (let i = 0; i < lane.length - 1; i += 1) {
      const left = lane[i];
      const right = lane[i + 1];
      if (!shouldRepairLane(left, right, laneZ, settings, mainNodes)) continue;
      const gap = right.pos.x - left.pos.x - (left.size.x + right.size.x) * 0.5;
      const vertical = Math.abs(right.pos.y - left.pos.y);
      if (gap > settings.maxGap) {
        report.issues.push(`gap ${gap.toFixed(2)} too large between ${left.id} and ${right.id}`);
        const mid = {
          x: (left.pos.x + right.pos.x) * 0.5,
          y: Math.min(left.pos.y, right.pos.y) + 0.2,
          z: left.pos.z,
        };
        const platform = addConnector(level, mid, right.node_id || left.node_id);
        report.fixes.push(`insert connector ${platform.id} between ${left.id} and ${right.id}`);
      }
      if (vertical > settings.maxVertical) {
        report.issues.push(`vertical delta ${vertical.toFixed(2)} too large between ${left.id} and ${right.id}`);
        right.pos.y = left.pos.y + Math.sign(right.pos.y - left.pos.y) * settings.maxVertical;
        report.fixes.push(`clamp height of ${right.id}`);
      }
    }
  }
}

function insertSyntheticKey(level, lock) {
  const existingIds = new Set((level.keys || []).map((item) => item?.id).filter(Boolean));
  let idx = (level.keys || []).length;
  let id = `K${idx}`;
  while (existingIds.has(id)) {
    idx += 1;
    id = `K${idx}`;
  }
  const anchor = lock?.node_id ? level.anchors?.[lock.node_id] : null;
  const base = anchor?.entry || level.start || lock?.pos || { x: 0, y: 0, z: 0 };
  const key = {
    id,
    key_id: lock.key_id,
    pos: {
      x: Number(base.x) + 1.6,
      y: Number(base.y) + 1.2,
      z: Number(base.z),
    },
    radius: 0.4,
    node_id: lock.node_id || "__auto_key_repair",
  };
  level.keys.push(key);
  if (!level.mapping?.node?.[key.node_id]) {
    if (!level.mapping) level.mapping = { node: {}, edge: {} };
    if (!level.mapping.node) level.mapping.node = {};
    level.mapping.node[key.node_id] = {
      platforms: [],
      enemies: [],
      keys: [],
      locks: [],
      checkpoints: [],
    };
  }
  level.mapping.node[key.node_id].keys.push(key.id);
  return key;
}

function validateMovingPlatforms(level, settings, report) {
  for (const platform of level.platforms) {
    if (platform.kind !== "moving" || !platform.motion) continue;
    if (platform.motion.period < settings.minPeriod) {
      report.issues.push(`moving platform ${platform.id} period too small`);
      platform.motion.period = settings.minPeriod;
      report.fixes.push(`clamp period for ${platform.id}`);
    }
    if (platform.motion.amplitude > settings.maxAmplitude) {
      report.issues.push(`moving platform ${platform.id} amplitude too large`);
      platform.motion.amplitude = settings.maxAmplitude;
      report.fixes.push(`clamp amplitude for ${platform.id}`);
    }
  }
}

function validateEnemies(level, report) {
  for (const enemy of level.enemies) {
    if (!enemy.patrol) continue;
    const dx = enemy.patrol.to.x - enemy.patrol.from.x;
    if (Math.abs(dx) < 0.5) {
      report.issues.push(`enemy ${enemy.id} patrol too short`);
      enemy.patrol.to.x = enemy.patrol.from.x + 1.2;
      report.fixes.push(`extend patrol for ${enemy.id}`);
    }
  }
}

function validateTimingConstraints(level, settings, report) {
  if (!level.etg) return;
  for (const node of level.etg.nodes) {
    if (!node.data || !node.data.timing_window) continue;
    const window = node.data.timing_window;
    if (window.close - window.open < settings.minWindowSpan) {
      report.issues.push(`timing window too narrow on node ${node.id}`);
      window.close = Math.min(settings.maxWindowClose, window.open + settings.minWindowSpan);
      report.fixes.push(`expand timing window on node ${node.id}`);
    }
    if (window.open < settings.minWindowOpen) {
      report.issues.push(`timing window open too small on node ${node.id}`);
      window.open = settings.minWindowOpen;
      report.fixes.push(`clamp timing open on node ${node.id}`);
    }
    if (window.close > settings.maxWindowClose) {
      report.issues.push(`timing window close too large on node ${node.id}`);
      window.close = settings.maxWindowClose;
      report.fixes.push(`clamp timing close on node ${node.id}`);
    }
  }
}

function validateMapping(level, report) {
  if (!level.mapping || !level.mapping.node) return;
  for (const nodeId of Object.keys(level.mapping.node)) {
    const mapping = level.mapping.node[nodeId];
    if (!mapping || (!mapping.platforms && !mapping.enemies)) {
      report.warnings.push(`node ${nodeId} missing mapping`);
    }
  }
}

function hasType(node, type) {
  const types = Array.isArray(node?.types) && node.types.length ? node.types : node?.type ? [node.type] : [];
  return types.includes(type);
}

function validateEtgOrdering(level, report) {
  const canonical = level.etg ? computeCanonicalRoute(level.etg, { defaultSpeed: level.etg?.meta?.defaultSpeed }) : null;
  if (!canonical?.ok || !canonical.nodes?.length) return;
  const indexOf = (nodeId) => canonical.nodes.indexOf(nodeId);
  for (const node of level.etg.nodes) {
    if (!hasType(node, "Lock")) continue;
    const keyId = node.requires_key_id;
    if (!keyId) continue;
    const keyNode = level.etg.nodes.find((item) => hasType(item, "Key") && item.key_id === keyId);
    if (!keyNode) continue;
    const lockIndex = indexOf(node.id);
    const keyIndex = indexOf(keyNode.id);
    if (lockIndex >= 0 && keyIndex > lockIndex) {
      report.warnings.push(`key ${keyId} appears after lock ${node.id} on canonical route`);
    }
  }
}

function shouldRepairLane(left, right, laneZ, settings, mainNodes) {
  const laneOk =
    settings.repairSideLanes || Math.abs(laneZ - settings.mainLaneZ) <= settings.laneTolerance;
  if (!laneOk) return false;

  if (!settings.repairSideLanes && mainNodes.size > 0) {
    const leftMain = left.node_id && mainNodes.has(left.node_id);
    const rightMain = right.node_id && mainNodes.has(right.node_id);
    if (!leftMain || !rightMain) return false;
  }

  if (settings.skipRegionConnectors) {
    if (hasTag(left, "region") || hasTag(right, "region")) return false;
  }

  return true;
}

function hasTag(platform, tag) {
  return Array.isArray(platform.tags) && platform.tags.includes(tag);
}

function groupByLane(platforms) {
  const lanes = {};
  for (const platform of platforms) {
    const key = Math.round(platform.pos.z / 4) * 4;
    if (!lanes[key]) lanes[key] = [];
    lanes[key].push(platform);
  }
  return lanes;
}

function addConnector(level, pos, nodeId) {
  const id = `P${level.platforms.length}`;
  const platform = {
    id,
    pos: { ...pos },
    size: { x: 4.5, y: 0.6, z: 4.5 },
    kind: "static",
    motion: null,
    tags: ["connector"],
    node_id: nodeId || null,
  };
  level.platforms.push(platform);
  if (nodeId && level.mapping.node[nodeId]) {
    level.mapping.node[nodeId].platforms.push(platform.id);
  }
  return platform;
}
