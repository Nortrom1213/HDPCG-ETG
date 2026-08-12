import * as THREE from "../../vendor/three.module.js";

export class PostFXManager {
  constructor(renderer, config = {}) {
    this.renderer = renderer;
    this.enabled = config.enabled !== false;
    this.quality = config.quality || "medium";
    this.theme = config.theme || null;
    this._applyRendererSettings();
  }

  setEnabled(enabled) {
    this.enabled = enabled !== false;
    this._applyRendererSettings();
  }

  setQuality(quality) {
    this.quality = quality || "medium";
    this._applyRendererSettings();
  }

  setTheme(theme) {
    this.theme = theme || null;
    this._applyRendererSettings();
  }

  render(scene, camera) {
    this.renderer.render(scene, camera);
  }

  _applyRendererSettings() {
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = this.enabled ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping;

    const fallback = this.quality === "high" ? 1.12 : this.quality === "low" ? 0.96 : 1.04;
    const exposure = this.theme?.environment?.exposure?.[this.quality] ?? fallback;
    this.renderer.toneMappingExposure = this.enabled ? exposure : 1.0;
  }
}
