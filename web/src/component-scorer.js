function safeNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function noveltyFromUsage(familyUsage, family) {
  const usage = safeNumber(familyUsage?.[family], 0);
  return 1 / (1 + usage);
}

function softmax(weights, temperature) {
  const t = clamp(safeNumber(temperature, 0.80), 0.05, 4);
  const max = Math.max(...weights);
  const exps = weights.map((w) => Math.exp((w - max) / t));
  const sum = exps.reduce((a, b) => a + b, 0) || 1;
  return exps.map((x) => x / sum);
}

function sampleIndex(probs, rng) {
  const r = rng();
  let acc = 0;
  for (let i = 0; i < probs.length; i += 1) {
    acc += probs[i];
    if (r <= acc) return i;
  }
  return Math.max(0, probs.length - 1);
}

export function scoreCandidate(candidate, context) {
  const cfg = context?.weights || {};
  const usage = context?.familyUsage || {};
  const edgeLength = safeNumber(context?.edgeLength, 24);

  const wa = safeNumber(cfg.alignmentWeight, 0.35);
  const wp = safeNumber(cfg.playabilityWeight, 0.30);
  const wn = safeNumber(cfg.noveltyWeight, 0.20);
  const ws = safeNumber(cfg.shapeWeight, 0.15);
  const wr = safeNumber(cfg.riskWeight, 0.20);

  const alignment = 1 - Math.abs(clamp(candidate.complexity, 0, 1) - clamp(edgeLength / 48, 0, 1));
  const playability = 1 - Math.max(0, candidate.complexity - 0.75);
  const novelty = 0.5 * noveltyFromUsage(usage, candidate.connectorFamily) + 0.5 * noveltyFromUsage(usage, candidate.nodeFamily);
  const shape = clamp(
    Math.abs((candidate.connector?.lateralAmplitude || 0) - (candidate.node?.scaleZ || 0)) * 0.35 +
      Math.abs((candidate.connector?.verticalAmplitude || 0) - (candidate.node?.verticalBias || 0)) * 0.2,
    0,
    1
  );
  const risk = clamp(candidate.complexity * 0.85, 0, 1);

  const score = wa * alignment + wp * playability + wn * novelty + ws * shape - wr * risk;
  return {
    ...candidate,
    score,
    scoreDetail: { alignment, playability, novelty, shape, risk },
  };
}

export function selectCandidateOrder(scoredCandidates, options, rng) {
  if (!Array.isArray(scoredCandidates) || scoredCandidates.length === 0) return [];
  const topP = clamp(safeNumber(options?.selectionTopP, 0.70), 0.05, 1);
  const temperature = safeNumber(options?.selectionTemperature, 0.80);

  const sorted = scoredCandidates.slice().sort((a, b) => b.score - a.score);
  const keep = Math.max(1, Math.ceil(sorted.length * topP));
  const pool = sorted.slice(0, keep);
  const output = [];

  while (pool.length > 0) {
    const probs = softmax(pool.map((item) => item.score), temperature);
    const idx = sampleIndex(probs, rng);
    output.push(pool[idx]);
    pool.splice(idx, 1);
  }
  return output;
}
