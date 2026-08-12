import * as THREE from "../../vendor/three.module.js";
import { GLTFLoader } from "../../vendor/GLTFLoader.js";
import { ColladaLoader } from "../../vendor/ColladaLoader.js";
import { OBJLoader } from "../../vendor/OBJLoader.js";
import { MTLLoader } from "../../vendor/MTLLoader.js";
import { resolveThemeDescriptor } from "./theme-manager.js?v=10";
import { cloneWithSkeletons } from "./skeleton-utils.js?v=10";

export class AssetLoader {
  constructor(themeId, quality = "medium") {
    this.themeId = themeId;
    this.quality = quality;
    this.textureLoader = new THREE.TextureLoader();
    this.gltfLoader = new GLTFLoader();
    this.colladaLoader = new ColladaLoader();
    this.objLoader = new OBJLoader();
    this.mtlLoader = new MTLLoader();
    this.manifestPromise = null;
    this.manifestCache = null;
    this.modelSourceCache = new Map();
    this.textureCache = new Map();
  }

  setTheme(themeId, quality = this.quality) {
    this.themeId = themeId;
    this.quality = quality;
    this.manifestPromise = null;
    this.manifestCache = null;
    this.modelSourceCache.clear();
    this.textureCache.clear();
  }

  async ensureManifest() {
    if (this.manifestCache) return this.manifestCache;
    if (!this.manifestPromise) {
      this.manifestPromise = this._loadManifestWithFallback(this.themeId);
    }
    this.manifestCache = await this.manifestPromise;
    return this.manifestCache;
  }

  async _loadManifestWithFallback(themeId) {
    const theme = resolveThemeDescriptor(themeId);
    const primary = await safeFetchJson(theme.manifestPath);
    if (primary) {
      primary.__theme = theme;
      return primary;
    }
    if (!theme.fallbackThemeId) {
      return {
        id: theme.id,
        models: {},
        textures: {},
        palette: {},
        __theme: theme,
      };
    }
    const fallbackTheme = resolveThemeDescriptor(theme.fallbackThemeId);
    const fallbackManifest = await safeFetchJson(fallbackTheme.manifestPath);
    if (fallbackManifest) {
      fallbackManifest.__theme = fallbackTheme;
      return fallbackManifest;
    }
    return {
      id: fallbackTheme.id,
      models: {},
      textures: {},
      palette: {},
      __theme: fallbackTheme,
    };
  }

  async loadTexture(key) {
    if (this.textureCache.has(key)) return this.textureCache.get(key);
    const promise = this._loadTextureInternal(key);
    this.textureCache.set(key, promise);
    return promise;
  }

  async _loadTextureInternal(key) {
    const manifest = await this.ensureManifest();
    const path = manifest?.textures?.[key];
    if (!path) return null;
    return new Promise((resolve) => {
      this.textureLoader.load(
        path,
        (texture) => {
          texture.wrapS = THREE.RepeatWrapping;
          texture.wrapT = THREE.RepeatWrapping;
          texture.colorSpace = THREE.SRGBColorSpace;
          resolve(texture);
        },
        undefined,
        () => resolve(null)
      );
    });
  }

  async loadModel(key) {
    if (!this.modelSourceCache.has(key)) {
      this.modelSourceCache.set(key, this._loadModelInternal(key));
    }
    const source = await this.modelSourceCache.get(key);
    const clone = source ? cloneWithSkeletons(source) : null;
    if (clone && source?.userData?.assetAnimations) {
      clone.userData.assetAnimations = source.userData.assetAnimations;
      clone.animations = source.userData.assetAnimations;
    }
    return clone;
  }

  async _loadModelInternal(key) {
    const manifest = await this.ensureManifest();
    const path = manifest?.models?.[key];
    if (!path) {
      if (Object.keys(manifest?.models || {}).length > 0) {
        console.warn(`[asset-loader] missing model path for key='${key}' theme='${this.themeId}'`);
      }
      return null;
    }
    const cleanPath = String(path).split("?")[0];
    const ext = cleanPath.slice(cleanPath.lastIndexOf(".")).toLowerCase();
    if (ext === ".dae") return this._loadDaeModel(path, key);
    if (ext === ".obj") return this._loadObjModel(path, key);
    if (ext === ".gltf" || ext === ".glb") return this._loadGltfModel(path, key);
    console.warn(`[asset-loader] unsupported model extension '${ext}' for key='${key}' path='${path}'`);
    return null;
  }

  async _loadGltfModel(path, key) {
    return new Promise((resolve) => {
      this.gltfLoader.load(
        path,
        (gltf) => {
          const source = gltf?.scene || gltf?.scenes?.[0] || null;
          if (!source) {
            console.warn(`[asset-loader] gltf loaded but empty for key='${key}' path='${path}'`);
            resolve(null);
            return;
          }
          const finalized = this._finalizeModel(source, key);
          if (finalized) {
            finalized.userData.assetAnimations = Array.isArray(gltf.animations) ? gltf.animations : [];
            finalized.animations = finalized.userData.assetAnimations;
          }
          resolve(finalized);
        },
        undefined,
        () => {
          console.warn(`[asset-loader] failed to load gltf for key='${key}' path='${path}'`);
          resolve(null);
        }
      );
    });
  }

  async _loadDaeModel(path, key) {
    return new Promise((resolve) => {
      this.colladaLoader.load(
        path,
        (collada) => {
          const source = collada?.scene || null;
          if (!source) {
            console.warn(`[asset-loader] dae loaded but empty for key='${key}' path='${path}'`);
            resolve(null);
            return;
          }
          const finalized = this._finalizeModel(source, key);
          if (finalized) {
            finalized.userData.assetAnimations = Array.isArray(collada.animations) ? collada.animations : [];
            finalized.animations = finalized.userData.assetAnimations;
          }
          resolve(finalized);
        },
        undefined,
        () => {
          console.warn(`[asset-loader] failed to load dae for key='${key}' path='${path}'`);
          resolve(null);
        }
      );
    });
  }

  async _loadObjModel(path, key) {
    const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/") + 1) : "";
    const base = path.includes(".") ? path.slice(0, path.lastIndexOf(".")) : path;
    const mtlPath = `${base}.mtl`;

    const materials = await new Promise((resolve) => {
      this.mtlLoader.setPath("");
      this.mtlLoader.setResourcePath(dir);
      this.mtlLoader.load(
        mtlPath,
        (creator) => {
          creator.preload();
          resolve(creator);
        },
        undefined,
        () => resolve(null)
      );
    });

    return new Promise((resolve) => {
      const loader = this.objLoader;
      if (materials) loader.setMaterials(materials);
      loader.load(
        path,
        (obj) => {
          if (!obj) {
            console.warn(`[asset-loader] obj loaded but empty for key='${key}' path='${path}'`);
            resolve(null);
            return;
          }
          resolve(this._finalizeModel(obj, key));
        },
        undefined,
        () => {
          console.warn(`[asset-loader] failed to load obj for key='${key}' path='${path}'`);
          resolve(null);
        }
      );
    });
  }

  _finalizeModel(root, key = "") {
    this._pruneVariantMeshes(root, key);

    root.traverse((obj) => {
      if (!obj.isMesh || !obj.material) return;
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      for (const mat of mats) {
        if (!mat) continue;
        if (mat.map) {
          mat.map.colorSpace = THREE.SRGBColorSpace;
          mat.map.minFilter = THREE.LinearMipmapLinearFilter;
          mat.map.magFilter = THREE.LinearFilter;
          mat.map.generateMipmaps = true;
          mat.map.anisotropy = Math.max(mat.map.anisotropy || 1, 4);
          mat.map.needsUpdate = true;
        }
        mat.side = THREE.DoubleSide;
        if (!Number.isFinite(mat.opacity) || mat.opacity <= 0.02) {
          mat.opacity = 1;
        }
        if (key === "player") {
          mat.alphaMap = null;
          mat.transparent = false;
          mat.opacity = 1;
          mat.depthWrite = true;
          if (this.themeId === "obstacle_course") {
            if ("metalness" in mat) mat.metalness = Math.min(Number(mat.metalness) || 0, 0.08);
            if ("roughness" in mat) mat.roughness = Math.max(Number(mat.roughness) || 0.72, 0.62);
          }
        }
        if (key === "player" || key === "enemy") {
          mat.vertexColors = false;
        }
        if (!mat.alphaMap && mat.opacity >= 0.999) {
          mat.transparent = false;
          mat.depthWrite = true;
        }
        if ("needsUpdate" in mat) mat.needsUpdate = true;
      }
    });
    return root;
  }

  _pruneVariantMeshes(root, key) {
    if (key === "player") {
      prunePlayerVariants(root);
      return;
    }
    if (key === "enemy") {
      pruneEnemyVariants(root);
    }
  }
}

async function safeFetchJson(path) {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) return null;
    return await response.json();
  } catch (err) {
    return null;
  }
}

function prunePlayerVariants(root) {
  const toRemove = [];
  root.traverse((obj) => {
    const name = String(obj?.name || "");
    if (!name) return;
    if (/^Hand[LR]\d\d__/.test(name) && !/^Hand[LR]00__/.test(name)) {
      toRemove.push(obj);
      return;
    }
    if (/^Face\d\d__/.test(name) && !/^Face00__/.test(name)) {
      toRemove.push(obj);
    }
  });
  removeNodes(toRemove);
}

function pruneEnemyVariants(root) {
  const toRemove = [];
  root.traverse((obj) => {
    const name = String(obj?.name || "");
    if (!name) return;
    // Keep Body__ base frame and one eye layer; remove overlapping blink variants.
    if (/^EyeClose__/.test(name) || /^EyeHalfClose__/.test(name)) {
      toRemove.push(obj);
      return;
    }
    // EyeOpen includes a duplicated body layer and an eye layer; keep only the eye mesh.
    if (/^EyeOpen__/.test(name) && !/KuriboEyeMat00/.test(name)) {
      toRemove.push(obj);
    }
  });
  removeNodes(toRemove);
}

function removeNodes(nodes) {
  const unique = Array.from(new Set(nodes));
  for (const node of unique) {
    if (node?.parent) node.parent.remove(node);
  }
}
