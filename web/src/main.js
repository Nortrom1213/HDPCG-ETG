import { rngFromSeed } from "./random.js";
import { createETG, summarizeETG } from "./etg.js";
import { generateLevel } from "./generator.js";
import { validateAndRepair } from "./validator.js";
import { buildExportPackage } from "./exporter.js";
import { normalizeETG } from "./etg-utils.js";
import { Game } from "./game.js";
import { loadPaperConfig } from "./paper-config.js";
import { listVisualThemes, resolveVisualConfig } from "./visual/theme-manager.js";

const paperConfig = await loadPaperConfig();

const canvas = document.querySelector("#game-canvas");
const etgOutput = document.querySelector("#etg-output");
const reportOutput = document.querySelector("#report-output");
const statusOutput = document.querySelector("#status-output");

const exportButton = document.querySelector("#export");
const visualThemeInput = document.querySelector("#visual-theme");
const visualQualityInput = document.querySelector("#visual-quality");
const postfxToggle = document.querySelector("#postfx-toggle");
const visualDebugToggle = document.querySelector("#visual-debug-toggle");
const applyVisualButton = document.querySelector("#apply-visual");
const toggleViewModeButton = document.querySelector("#toggle-view-mode");

const initialVisualConfig = readVisualConfig();
const game = new Game(canvas, updateStatus, initialVisualConfig);
let latestPackage = null;
let latestLevel = null;
let latestReport = null;

hydrateVisualControls(initialVisualConfig);
updateViewModeButton();

function updateStatus(state) {
  const keyText = state.keys.length ? state.keys.join(", ") : "none";
  const lockText = state.locks.map((lock) => `${lock.id}:${lock.locked ? "locked" : "open"}`).join(" ");
  const modeText = state.viewMode === "god" ? "god" : "player";
  statusOutput.textContent = `mode=${modeText} | keys=${keyText} | locks=${lockText || "none"} | goal=${state.goalReached ? "reached" : "not yet"}`;
}

function readVisualConfig() {
  const params = new URLSearchParams(window.location.search);
  return resolveVisualConfig({
    themeId: (params.get("visualTheme") || "manual").trim(),
    quality: (params.get("visualQuality") || "medium").trim(),
    postfx: parseBool(params.get("postfx"), true),
    debug: parseBool(params.get("visualDebug"), false),
  });
}

function hydrateVisualControls(config) {
  if (visualThemeInput) {
    const options = listVisualThemes();
    visualThemeInput.innerHTML = options
      .map((item) => `<option value=\"${item.id}\">${item.id}</option>`)
      .join("");
    visualThemeInput.value = config.themeId;
  }
  if (visualQualityInput) visualQualityInput.value = config.quality;
  if (postfxToggle) postfxToggle.checked = config.postfx;
  if (visualDebugToggle) visualDebugToggle.checked = config.debug;
}

function readConfig() {
  const selection = paperConfig.candidate_selection;
  const weights = selection.weights;
  const main = paperConfig.benchmark.methods.find((method) => method.id === "main").config;
  const defaults = {
    seed: "paper-demo",
    length: 9,
    difficulty: 0.55,
    branchChance: 0.7,
    keyLockEnabled: true,
    generatorMode: "hdpcg_incremental",
    maxAttempts: main.maxAttempts,
    sectorCount: 8,
    safetyMargin: 1.0,
    topologyValidate: true,
    extra_connectivity_policy: "strict_1hop",
    toleranceRadiusCells: 2,
    validationMaxTime: main.validationMaxTime,
    componentStrategy: "diverse",
    candidatePoolSize: selection.pool_size,
    selectionTopP: selection.top_p,
    selectionTemperature: selection.temperature,
    noveltyWeight: weights.novelty,
    alignmentWeight: weights.alignment,
    playabilityWeight: weights.playability,
    shapeWeight: weights.shape,
    riskWeight: weights.risk,
    maxLocalRejects: main.maxLocalRejects,
    fallbackEnabled: true,
    familyBalanceWindow: 40,
    maxCanonicalRetries: main.maxCanonicalRetries,
    validationTimeStep: paperConfig.state_model.time_step_seconds,
    validationMaxTimeHorizon: paperConfig.state_model.max_time_horizon,
    validationMaxPeriodTicks: paperConfig.state_model.max_period_ticks,
    validationLocalPaddingCells: paperConfig.state_model.local_padding_cells,
  };

  const params = new URLSearchParams(window.location.search);

  const seed = (params.get("seed") || defaults.seed).trim();
  const length = clampInt(params.get("length") ?? defaults.length, 4, 16);
  const difficulty = clampFloat(params.get("difficulty") ?? defaults.difficulty, 0.1, 0.95);
  const branchChance = clampFloat(params.get("branchChance") ?? defaults.branchChance, 0, 1);
  const keyLockEnabled = parseBool(params.get("keyLockEnabled"), defaults.keyLockEnabled);

  let keyLock = keyLockEnabled;
  if (keyLockEnabled) {
    const branchRng = rngFromSeed(`${seed}-branch`);
    keyLock = branchRng() < branchChance;
  }

  return {
    seed,
    length,
    difficulty,
    branchChance,
    keyLock,
    generatorMode: (params.get("generatorMode") || defaults.generatorMode).trim(),
    maxAttempts: clampInt(params.get("maxAttempts") ?? defaults.maxAttempts, 5, 80),
    sectorCount: clampInt(params.get("sectorCount") ?? defaults.sectorCount, 4, 32),
    safetyMargin: clampFloat(params.get("safetyMargin") ?? defaults.safetyMargin, 0, 8),
    topologyValidate: parseBool(params.get("topologyValidate"), defaults.topologyValidate),
    extra_connectivity_policy: (params.get("extra_connectivity_policy") || defaults.extra_connectivity_policy).trim(),
    toleranceRadiusCells: clampInt(params.get("toleranceRadiusCells") ?? defaults.toleranceRadiusCells, 0, 12),
    validationMaxTime: clampInt(params.get("validationMaxTime") ?? defaults.validationMaxTime, 1, 500),
    componentStrategy: (params.get("componentStrategy") || defaults.componentStrategy).trim(),
    candidatePoolSize: clampInt(params.get("candidatePoolSize") ?? defaults.candidatePoolSize, 1, 48),
    selectionTopP: clampFloat(params.get("selectionTopP") ?? defaults.selectionTopP, 0.05, 1),
    selectionTemperature: clampFloat(params.get("selectionTemperature") ?? defaults.selectionTemperature, 0.05, 4),
    noveltyWeight: clampFloat(params.get("noveltyWeight") ?? defaults.noveltyWeight, 0, 2),
    alignmentWeight: clampFloat(params.get("alignmentWeight") ?? defaults.alignmentWeight, 0, 2),
    playabilityWeight: clampFloat(params.get("playabilityWeight") ?? defaults.playabilityWeight, 0, 2),
    shapeWeight: clampFloat(params.get("shapeWeight") ?? defaults.shapeWeight, 0, 2),
    riskWeight: clampFloat(params.get("riskWeight") ?? defaults.riskWeight, 0, 2),
    maxLocalRejects: clampInt(params.get("maxLocalRejects") ?? defaults.maxLocalRejects, 1, 120),
    fallbackEnabled: parseBool(params.get("fallbackEnabled"), defaults.fallbackEnabled),
    familyBalanceWindow: clampInt(params.get("familyBalanceWindow") ?? defaults.familyBalanceWindow, 4, 200),
    maxCanonicalRetries: clampInt(params.get("maxCanonicalRetries") ?? defaults.maxCanonicalRetries, 0, 8),
    validationTimeStep: defaults.validationTimeStep,
    validationMaxTimeHorizon: defaults.validationMaxTimeHorizon,
    validationMaxPeriodTicks: defaults.validationMaxPeriodTicks,
    validationLocalPaddingCells: defaults.validationLocalPaddingCells,
  };
}

function generate() {
  const t0 = performance.now();
  const config = readConfig();
  const rngEtg = rngFromSeed(`${config.seed}-etg`);
  const rngGeo = rngFromSeed(`${config.seed}-geo`);

  const override = loadEtgOverride();
  const etg = override ? normalizeETG(override, config, rngEtg) : createETG(config, rngEtg);
  const tEtg = performance.now();
  const level = generateLevel(etg, config, rngGeo);
  const tGen = performance.now();
  const report = validateAndRepair(level, {
    maxGap: 5.2,
    maxVertical: 3.2,
  });
  const tValidate = performance.now();
  latestLevel = level;
  latestReport = report;

  latestPackage = buildExportPackage(level, report, {
    sampleDuration: 12,
    sampleStep: paperConfig.state_model.time_step_seconds,
  });
  const tExport = performance.now();
  const perf = {
    etg_ms: Math.round(tEtg - t0),
    generation_ms: Math.round(tGen - tEtg),
    validation_ms: Math.round(tValidate - tGen),
    export_ms: Math.round(tExport - tValidate),
    total_ms: Math.round(tExport - t0),
  };

  etgOutput.textContent = JSON.stringify(summarizeETG(etg), null, 2);
  reportOutput.textContent = formatReport(report, perf);

  game.stop();
  game.loadLevel(level);
  game.start();
  updateViewModeButton();
}

function formatReport(report, perf = null) {
  if (!report) return "validation: unavailable";
  const lines = [];
  if (perf) {
    lines.push(
      `perf(ms): total=${perf.total_ms}, etg=${perf.etg_ms}, generate=${perf.generation_ms}, validate=${perf.validation_ms}, export=${perf.export_ms}`
    );
  }
  if (report.issues.length === 0 && report.fixes.length === 0 && report.warnings.length === 0) {
    lines.push("validation: ok");
    return lines.join("\n");
  }
  lines.push(`validation: ${report.status}`);
  for (const issue of report.issues) lines.push(`- issue: ${issue}`);
  for (const fix of report.fixes) lines.push(`- fix: ${fix}`);
  for (const warning of report.warnings) lines.push(`- warning: ${warning}`);
  return lines.join("\n");
}

function downloadPackage() {
  if (!latestPackage) return;
  const json = JSON.stringify(latestPackage, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `level_package_${latestPackage.meta.seed}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function clampInt(value, min, max) {
  const n = Math.round(Number(value) || min);
  return Math.min(max, Math.max(min, n));
}

function clampFloat(value, min, max) {
  const n = Number(value);
  if (Number.isNaN(n)) return min;
  return Math.min(max, Math.max(min, n));
}

function parseBool(raw, fallback) {
  if (raw === null || raw === undefined || raw === "") return fallback;
  const v = String(raw).trim().toLowerCase();
  if (v === "1" || v === "true" || v === "yes" || v === "y" || v === "on") return true;
  if (v === "0" || v === "false" || v === "no" || v === "n" || v === "off") return false;
  return fallback;
}

function updateViewModeButton() {
  if (!toggleViewModeButton) return;
  const mode = game.getViewMode();
  toggleViewModeButton.textContent = mode === "god" ? "Switch to Player View" : "Switch to God View";
}

exportButton?.addEventListener("click", downloadPackage);
applyVisualButton?.addEventListener("click", applyVisualSettings);
toggleViewModeButton?.addEventListener("click", () => {
  game.toggleViewMode();
  updateViewModeButton();
});

bootstrap();

function loadEtgOverride() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("etg") !== "1") return null;
  const raw = localStorage.getItem("etg_override");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (err) {
    return null;
  }
}

function bootstrap() {
  const params = new URLSearchParams(window.location.search);
  const wantsEtg = params.get("etg") === "1";

  if (!wantsEtg) {
    lockEntry("Entry locked. Please open this page from the ETG Editor preview (Play Preview).");
    return;
  }

  if (wantsEtg && !loadEtgOverride()) {
    lockEntry("Missing ETG preview data. Please click Play Preview in the ETG Editor.");
    return;
  }

  generate();
}

function lockEntry(message) {
  try {
    game.stop();
  } catch (err) {
    return;
  }
  if (statusOutput) statusOutput.textContent = "status: locked";
  if (etgOutput) etgOutput.textContent = "waiting...";
  if (reportOutput) reportOutput.textContent = message;
  updateViewModeButton();
}

function applyVisualSettings() {
  const next = resolveVisualConfig({
    themeId: visualThemeInput?.value || "manual",
    quality: visualQualityInput?.value || "medium",
    postfx: Boolean(postfxToggle?.checked),
    debug: Boolean(visualDebugToggle?.checked),
  });

  const prevTheme = game.visualConfig?.themeId || "manual";
  game.setVisualOptions(next);

  if (next.themeId !== prevTheme) {
    game.setVisualTheme(next.themeId);
  } else {
    game.reloadVisuals(latestLevel || game.level || null);
  }

  const params = new URLSearchParams(window.location.search);
  params.set("visualTheme", next.themeId);
  params.set("visualQuality", next.quality);
  params.set("postfx", next.postfx ? "1" : "0");
  params.set("visualDebug", next.debug ? "1" : "0");
  window.history.replaceState({}, "", `${window.location.pathname}?${params.toString()}`);
}
