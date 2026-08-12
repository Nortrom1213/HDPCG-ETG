import { randRange, pick } from "./random.js";
import { familyBaseComplexity, listConnectorFamilies, listNodeFamilies } from "./component-catalog.js";

function connectorParams(family, rng) {
  return {
    lateralAmplitude: randRange(rng, 0.2, 2.8),
    verticalAmplitude: randRange(rng, 0.15, 2.4),
    zigzagPeriod: randRange(rng, 2.5, 7.5),
    stairStep: randRange(rng, 0.4, 1.25),
    movingRate: randRange(rng, 0.2, 0.7),
    hazardDensity: randRange(rng, 0.1, 0.65),
    family,
  };
}

function nodeParams(family, rng) {
  return {
    scaleX: randRange(rng, 0.8, 1.8),
    scaleZ: randRange(rng, 0.8, 1.8),
    verticalBias: randRange(rng, -0.6, 1.4),
    enemyBias: randRange(rng, 0.0, 1.0),
    movingBias: randRange(rng, 0.0, 1.0),
    branchBias: randRange(rng, 0.0, 1.0),
    family,
  };
}

export function buildCandidatePool({ edge, toNode, rng, poolSize }) {
  const size = Math.max(1, Math.round(Number(poolSize) || 12));
  const connectorFamilies = listConnectorFamilies(edge?.length);
  const nodeFamilies = listNodeFamilies(toNode);
  const out = [];

  for (let i = 0; i < size; i += 1) {
    const connectorFamily = pick(rng, connectorFamilies);
    const nodeFamily = pick(rng, nodeFamilies);
    const connector = connectorParams(connectorFamily, rng);
    const node = nodeParams(nodeFamily, rng);
    out.push({
      id: `cand_${i}`,
      connectorFamily,
      nodeFamily,
      connector,
      node,
      complexity: (familyBaseComplexity(connectorFamily) + familyBaseComplexity(nodeFamily)) * 0.5,
    });
  }

  return out;
}
