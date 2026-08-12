const THEMES = {
  manual: {
    id: "manual",
    name: "Procedural",
    manifestPath: "assets/manifests/manual.json",
    fallbackThemeId: null,
    palette: {
      skyTop: 0x79c9ff,
      skyBottom: 0xd7f2ff,
      fog: 0xb8e5ff,
      ambient: 0xffffff,
      dir: 0xfff3d6,
      accent: 0xf39c12,
      uiAccent: "#ff5b22",
      uiAccent2: "#12a66a",
    },
    environment: {
      fogDensity: 0.0018,
      lightIntensity: 0.92,
      ambientIntensity: 0.62,
      dirIntensity: 1.12,
      exposure: { low: 0.96, medium: 1.02, high: 1.08 },
      saturation: { low: 1.0, medium: 1.08, high: 1.14 },
    },
  },
};

const VISUAL_QUALITY = new Set(["low", "medium", "high"]);

export function resolveVisualConfig(raw = {}) {
  return {
    themeId: THEMES[raw.themeId] ? raw.themeId : "manual",
    quality: VISUAL_QUALITY.has(raw.quality) ? raw.quality : "medium",
    postfx: raw.postfx !== false,
    debug: raw.debug === true,
    renderClean: raw.renderClean === true,
  };
}

export function listVisualThemes() {
  return Object.values(THEMES).map(({ id, name }) => ({ id, name }));
}

export function resolveThemeDescriptor(themeId) {
  return THEMES[themeId] || THEMES.manual;
}

export function defaultThemeId() {
  return "manual";
}
