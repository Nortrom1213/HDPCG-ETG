import {
  computeCanonicalRoute,
  normalizeEtg,
  validateEtg,
} from "./etg-core.js";

export function normalizeETG(etg, config, rng) {
  return normalizeEtg(etg, { defaultSpeed: config?.defaultSpeed });
}

export function validateETG(etg) {
  const result = validateEtg(etg);
  return { issues: result.issues || [], warnings: result.warnings || [] };
}

export { computeCanonicalRoute } from "./etg-core.js";

export function toETGJson(etg) {
  return JSON.stringify(etg, null, 2);
}
