import * as THREE from "../../vendor/three.module.js";
import { AssetLoader } from "./asset-loader.js?v=10";
import { createMaterialLibrary } from "./material-presets.js?v=10";
import { resolveThemeDescriptor } from "./theme-manager.js?v=10";

export class VisualFactory {
  constructor(scene, options = {}) {
    this.scene = scene;
    this.themeId = options.themeId || "manual";
    this.quality = options.quality || "medium";
    this.debug = options.debug === true;
    this.renderClean = options.renderClean === true;

    this.theme = resolveThemeDescriptor(this.themeId);
    this.assetLoader = new AssetLoader(this.theme.id, this.quality);
    this.materials = createMaterialLibrary(this.theme, this.quality);

    this.environmentGroup = null;
  }

  setTheme(themeId, quality = this.quality, debug = this.debug) {
    this.themeId = themeId;
    this.quality = quality;
    this.debug = debug === true;
    this.theme = resolveThemeDescriptor(this.themeId);
    this.assetLoader.setTheme(this.theme.id, this.quality);
    this.materials = createMaterialLibrary(this.theme, this.quality);
  }

  applyEnvironment(scene, lights = {}) {
    if (this.environmentGroup && this.environmentGroup.parent) {
      this.environmentGroup.parent.remove(this.environmentGroup);
      disposeObjectDeep(this.environmentGroup);
    }

    scene.background = new THREE.Color(this.materials.skyBottom);
    scene.fog = new THREE.FogExp2(this.materials.fog, this.theme.environment?.fogDensity ?? 0.0018);

    const group = new THREE.Group();
    const sky = new THREE.Mesh(
      new THREE.SphereGeometry(260, 24, 24),
      new THREE.ShaderMaterial({
        uniforms: {
          topColor: { value: new THREE.Color(this.materials.skyTop) },
          bottomColor: { value: new THREE.Color(this.materials.skyBottom) },
          offset: { value: 14.0 },
          exponent: { value: 0.7 },
        },
        vertexShader: `
          varying vec3 vWorldPosition;
          void main() {
            vec4 worldPosition = modelMatrix * vec4(position, 1.0);
            vWorldPosition = worldPosition.xyz;
            gl_Position = projectionMatrix * viewMatrix * worldPosition;
          }
        `,
        fragmentShader: `
          uniform vec3 topColor;
          uniform vec3 bottomColor;
          uniform float offset;
          uniform float exponent;
          varying vec3 vWorldPosition;
          void main() {
            float h = normalize(vWorldPosition + vec3(0.0, offset, 0.0)).y;
            float t = pow(max(h, 0.0), exponent);
            gl_FragColor = vec4(mix(bottomColor, topColor, t), 1.0);
          }
        `,
        side: THREE.BackSide,
        depthWrite: false,
      })
    );
    group.add(sky);

    const cloudCount = this.renderClean ? 12 : this.quality === "high" ? 28 : this.quality === "medium" ? 20 : 12;
    const cloudMat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.88,
      metalness: 0,
      transparent: true,
      opacity: this.renderClean ? 0.34 : 0.75,
    });
    for (let i = 0; i < cloudCount; i += 1) {
      const cloud = new THREE.Mesh(new THREE.SphereGeometry(1 + Math.random() * 1.7, 10, 8), cloudMat);
      cloud.scale.set(2.0 + Math.random() * 2.2, 0.65 + Math.random() * 0.4, 1.4 + Math.random() * 1.8);
      if (this.renderClean) {
        const side = i % 2 === 0 ? -1 : 1;
        const lane = Math.floor(i / 2);
        cloud.position.set(-24 + lane * 48, 46 + (i % 3) * 5, side * (82 + (lane % 2) * 24));
      } else {
        cloud.position.set((Math.random() - 0.5) * 160, 32 + Math.random() * 34, (Math.random() - 0.5) * 160);
      }
      group.add(cloud);
    }

    if (lights.ambient) {
      lights.ambient.intensity = this.theme.environment?.ambientIntensity ?? 0.6;
      lights.ambient.color.setHex(this.theme.palette?.ambient ?? 0xffffff);
    }
    if (lights.directional) {
      lights.directional.intensity = this.theme.environment?.dirIntensity ?? 1.0;
      lights.directional.color.setHex(this.theme.palette?.dir ?? 0xffffff);
    }

    scene.add(group);
    this.environmentGroup = group;
  }

  createGround() {
    // Focus the replica view on level chunks.
    return null;
  }

  createPlatform(platform) {
    const root = new THREE.Group();
    root.position.set(platform.pos.x, platform.pos.y, platform.pos.z);
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const base = new THREE.Mesh(
      new THREE.BoxGeometry(platform.size.x, platform.size.y, platform.size.z),
      this.materials.platform(platform.tags || [], platform.kind)
    );
    base.castShadow = true;
    base.receiveShadow = true;
    placeholder.add(base);

    if (platform.kind !== "moving") {
      const isFallGuys = isFallGuysTheme(this.theme.id);
      const tags = platform.tags || [];
      const topCap = new THREE.Mesh(
        new THREE.BoxGeometry(platform.size.x * 0.98, Math.min(0.18, platform.size.y * 0.28), platform.size.z * 0.98),
        isFallGuys
          ? new THREE.MeshStandardMaterial({
              color: tags.includes("finish") ? 0xffffff : 0xf7fbff,
              roughness: 0.62,
              metalness: 0.02,
              transparent: !tags.includes("finish"),
              opacity: tags.includes("finish") ? 0.86 : 0.22,
            })
          : new THREE.MeshStandardMaterial({ color: 0x54bd56, roughness: 0.85, metalness: 0.01 })
      );
      topCap.position.y = platform.size.y * 0.5 - topCap.geometry.parameters.height * 0.5 + 0.01;
      topCap.receiveShadow = true;
      placeholder.add(topCap);

      if (isFallGuys && tags.includes("finish")) {
        addFinishCheckerboard(placeholder, platform.size, this.materials);
      }
    }

    if (this.debug) {
      root.add(createBoxDebug(platform.size, 0x2c3e50));
    }

    if (isFallGuysTheme(this.theme.id) && platform.asset_key) {
      const meshFirst = platform.asset_visual_mode === "replace" || platform.asset_replace_proxy === true;
      this._attachOptionalModel(root, platform.asset_key, platform.asset_target_size || platform.size, placeholder, {
        anchor: "center",
        scaleMode: platform.asset_scale_mode || "stretch",
        yOffset: Number(platform.asset_y_offset || platform.size.y * 0.35),
        keepPlaceholder: meshFirst ? false : platform.asset_keep_placeholder !== false,
        postScale: Number(platform.asset_post_scale || 1),
      });
    } else if (!isFallGuysTheme(this.theme.id)) {
      const modelKey =
        this.theme.id === "manual"
          ? "platform_static"
          : platform.kind === "moving"
          ? "platform_moving"
          : "platform_static";
      this._attachOptionalModel(root, modelKey, platform.size, placeholder, {
        anchor: "center",
        scaleMode: "stretch",
      });
    }

    return { root };
  }

  createEnemy(enemy) {
    const root = new THREE.Group();
    root.position.set(enemy.pos.x, enemy.pos.y, enemy.pos.z);
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const body = new THREE.Mesh(new THREE.SphereGeometry(enemy.radius * 0.95, 24, 18), this.materials.enemyBody);
    body.scale.y = 0.82;
    body.position.y = enemy.radius * 0.06;
    body.castShadow = true;
    placeholder.add(body);

    const face = new THREE.Mesh(new THREE.SphereGeometry(enemy.radius * 0.68, 20, 16), this.materials.enemyFace);
    face.scale.set(1.0, 0.62, 0.56);
    face.position.set(0, enemy.radius * 0.06, enemy.radius * 0.37);
    placeholder.add(face);

    const leftEye = new THREE.Mesh(new THREE.SphereGeometry(enemy.radius * 0.08, 10, 8), new THREE.MeshStandardMaterial({ color: 0xffffff }));
    const rightEye = leftEye.clone();
    leftEye.position.set(-enemy.radius * 0.2, enemy.radius * 0.22, enemy.radius * 0.63);
    rightEye.position.set(enemy.radius * 0.2, enemy.radius * 0.22, enemy.radius * 0.63);
    placeholder.add(leftEye, rightEye);

    const leftPupil = new THREE.Mesh(new THREE.SphereGeometry(enemy.radius * 0.035, 8, 8), new THREE.MeshStandardMaterial({ color: 0x202020 }));
    const rightPupil = leftPupil.clone();
    leftPupil.position.set(-enemy.radius * 0.2, enemy.radius * 0.2, enemy.radius * 0.69);
    rightPupil.position.set(enemy.radius * 0.2, enemy.radius * 0.2, enemy.radius * 0.69);
    placeholder.add(leftPupil, rightPupil);

    const footGeo = new THREE.SphereGeometry(enemy.radius * 0.33, 16, 12);
    const leftFoot = new THREE.Mesh(footGeo, this.materials.enemyFeet);
    const rightFoot = new THREE.Mesh(footGeo, this.materials.enemyFeet);
    leftFoot.scale.set(1.1, 0.55, 1.35);
    rightFoot.scale.set(1.1, 0.55, 1.35);
    leftFoot.position.set(-enemy.radius * 0.33, -enemy.radius * 0.56, 0);
    rightFoot.position.set(enemy.radius * 0.33, -enemy.radius * 0.56, 0);
    placeholder.add(leftFoot, rightFoot);

    if (this.debug) {
      root.add(createSphereDebug(enemy.radius, 0x2c3e50));
    }

    if (!isFallGuysTheme(this.theme.id)) {
      this._attachOptionalModel(root, "enemy", { x: enemy.radius * 2, y: enemy.radius * 2, z: enemy.radius * 2 }, placeholder, {
        anchor: "center",
      });
    }
    return { root };
  }

  createKey(key) {
    const root = new THREE.Group();
    root.position.set(key.pos.x, key.pos.y, key.pos.z);
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const coin = new THREE.Mesh(new THREE.CylinderGeometry(key.radius * 0.95, key.radius * 0.95, 0.18, 24), this.materials.key);
    coin.rotation.x = Math.PI * 0.5;
    coin.castShadow = true;
    placeholder.add(coin);

    const ring = new THREE.Mesh(new THREE.TorusGeometry(key.radius * 0.75, key.radius * 0.12, 12, 24), this.materials.key);
    ring.rotation.y = Math.PI * 0.5;
    placeholder.add(ring);

    if (this.debug) {
      root.add(createSphereDebug(key.radius, 0x2c3e50));
    }

    if (!isFallGuysTheme(this.theme.id)) {
      this._attachOptionalModel(root, "key", { x: key.radius * 2, y: key.radius * 2, z: key.radius * 2 }, placeholder, {
        anchor: "center",
      });
    }
    return { root };
  }

  createLock(lock) {
    const root = new THREE.Group();
    root.position.set(lock.pos.x, lock.pos.y, lock.pos.z);
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const frame = new THREE.Mesh(new THREE.BoxGeometry(lock.size.x, lock.size.y, lock.size.z), this.materials.lockClosed);
    frame.castShadow = true;
    frame.receiveShadow = true;
    placeholder.add(frame);

    const bars = [];
    const barCount = Math.max(2, Math.round((Math.abs(lock.size.x) + Math.abs(lock.size.z)) * 0.4));
    const vertical = lock.size.x >= lock.size.z;
    for (let i = 0; i < barCount; i += 1) {
      const t = barCount === 1 ? 0 : i / (barCount - 1);
      const bar = new THREE.Mesh(
        new THREE.CylinderGeometry(0.08, 0.08, lock.size.y * 0.92, 8),
        this.materials.lockClosed
      );
      if (vertical) {
        bar.position.set((t - 0.5) * lock.size.x * 0.92, 0, 0);
      } else {
        bar.position.set(0, 0, (t - 0.5) * lock.size.z * 0.92);
      }
      bars.push(bar);
      placeholder.add(bar);
    }

    if (this.debug) {
      root.add(createBoxDebug(lock.size, 0x2c3e50));
    }

    if (!isFallGuysTheme(this.theme.id)) {
      this._attachOptionalModel(root, "lock", lock.size, placeholder, {
        anchor: "center",
        scaleMode: "stretch",
      });
    }

    const setLocked = (locked) => {
      const mat = locked ? this.materials.lockClosed : this.materials.lockOpen;
      frame.material = mat;
      for (const bar of bars) bar.material = mat;
    };

    setLocked(lock.locked !== false);
    return { root, setLocked };
  }

  createCheckpoint(checkpoint) {
    const root = new THREE.Group();
    root.position.set(checkpoint.pos.x, checkpoint.pos.y, checkpoint.pos.z);
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 1.2, 12), this.materials.checkpointPole);
    pole.position.y = 0.6;
    placeholder.add(pole);

    const flag = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.35, 0.05), this.materials.checkpointFlag);
    flag.position.set(0.3, 0.95, 0);
    placeholder.add(flag);

    if (this.debug) {
      root.add(createSphereDebug(checkpoint.radius || 0.6, 0x2c3e50));
    }

    if (!isFallGuysTheme(this.theme.id)) {
      this._attachOptionalModel(root, "checkpoint", { x: 1.5, y: 3.6, z: 1.5 }, placeholder, {
        anchor: "bottom",
      });
    }
    return { root };
  }

  createGoal(goal) {
    if (isFallGuysTheme(this.theme.id)) {
      return this.createFallGuysFinish(goal);
    }

    const root = new THREE.Group();
    root.position.set(goal.x, goal.y + 1.2, goal.z);
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 3.4, 14), this.materials.goalPole);
    pole.position.y = 0.9;
    placeholder.add(pole);

    const flag = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.62, 0.06), this.materials.goalFlag);
    flag.position.set(0.56, 1.58, 0);
    placeholder.add(flag);

    const orb = new THREE.Mesh(new THREE.SphereGeometry(0.22, 14, 12), this.materials.goalOrb);
    orb.position.y = 2.58;
    placeholder.add(orb);

    if (this.debug) {
      root.add(createSphereDebug(1.4, 0x2c3e50));
    }

    const modelKey = this.theme.id === "manual" ? "checkpoint" : "goal";
    this._attachOptionalModel(root, modelKey, { x: 1.5, y: 3.6, z: 1.5 }, placeholder, {
      anchor: "bottom",
    });
    return { root, targetPos: new THREE.Vector3(goal.x, goal.y + 1.2, goal.z) };
  }

  createFallGuysFinish(goal) {
    const root = new THREE.Group();
    root.position.set(goal.x, goal.y + 1.15, goal.z);
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const archMat = this.materials.fgGateFrame;
    const stripeA = this.materials.fgFinishStripeDark;
    const stripeB = this.materials.fgFinishStripeLight;
    const left = new THREE.Mesh(new THREE.BoxGeometry(0.55, 3.2, 0.55), archMat);
    const right = left.clone();
    left.position.set(0, 1.25, -3.4);
    right.position.set(0, 1.25, 3.4);
    const top = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.55, 7.4), archMat);
    top.position.set(0, 2.95, 0);
    placeholder.add(left, right, top);

    for (let i = 0; i < 8; i += 1) {
      const mat = i % 2 === 0 ? stripeA : stripeB;
      const tile = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.06, 0.82), mat);
      tile.position.set(0.05, -1.04, -2.9 + i * 0.83);
      placeholder.add(tile);
    }

    const banner = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.74, 5.0), this.materials.fgSweeperBar);
    banner.position.set(-0.12, 2.95, 0);
    placeholder.add(banner);

    placeholder.traverse((obj) => {
      if (obj.isMesh) {
        obj.castShadow = true;
        obj.receiveShadow = true;
      }
    });

    this._attachOptionalModel(root, goal.asset_key || "fg_finish_arch_module", goal.asset_target_size || { x: 4.5, y: 4.3, z: 8.0 }, placeholder, {
      anchor: "center",
      scaleMode: goal.asset_scale_mode || "uniform",
      keepPlaceholder: true,
      postScale: Number(goal.asset_post_scale || 1),
    });

    return { root, targetPos: new THREE.Vector3(goal.x, goal.y + 1.2, goal.z) };
  }

  createSweeper(sweeper) {
    const root = new THREE.Group();
    root.position.set(sweeper.pos.x, sweeper.pos.y, sweeper.pos.z);
    const meshFirst = sweeper.asset_visual_mode === "replace" || sweeper.asset_replace_proxy === true;
    const proceduralGroup = new THREE.Group();
    root.add(proceduralGroup);

    const hubRadius = Number(sweeper.hubRadius || 0.72);
    const barLength = Number(sweeper.barLength || sweeper.radius * 2 || 9.0);
    const barWidth = Number(sweeper.barWidth || 0.38);
    const barHeight = Number(sweeper.barHeight || 0.38);

    const hub = new THREE.Mesh(new THREE.CylinderGeometry(hubRadius, hubRadius, 0.62, 28), this.materials.fgSweeperHub);
    hub.rotation.x = Math.PI * 0.5;
    hub.castShadow = true;
    proceduralGroup.add(hub);

    const barGroup = new THREE.Group();
    const bar = new THREE.Mesh(new THREE.BoxGeometry(barLength, barHeight, barWidth), this.materials.fgSweeperBar);
    bar.castShadow = true;
    bar.receiveShadow = true;
    barGroup.add(bar);

    const tipGeo = new THREE.SphereGeometry(barWidth * 0.72, 16, 10);
    const leftTip = new THREE.Mesh(tipGeo, this.materials.fgSweeperTip);
    const rightTip = leftTip.clone();
    leftTip.position.x = -barLength * 0.5;
    rightTip.position.x = barLength * 0.5;
    barGroup.add(leftTip, rightTip);

    proceduralGroup.add(barGroup);
    const modelGroup = new THREE.Group();
    root.add(modelGroup);

    const setAngle = (angle) => {
      barGroup.rotation.y = angle;
      modelGroup.rotation.y = angle;
    };
    setAngle(Number(sweeper.phase || 0));
    if (sweeper.visual_hidden === true) {
      proceduralGroup.visible = false;
    }

    if (this.debug) {
      root.add(createSphereDebug(Number(sweeper.radius || barLength * 0.5), 0x2c3e50));
    }

    if (sweeper.asset_key) {
      this._attachOptionalModel(modelGroup, sweeper.asset_key, sweeper.asset_target_size || { x: barLength, y: 2.4, z: barLength }, proceduralGroup, {
        anchor: "center",
        scaleMode: sweeper.asset_scale_mode || "uniform",
        keepPlaceholder: meshFirst ? false : true,
        postScale: Number(sweeper.asset_post_scale || 1),
      });
    }

    return { root, setAngle };
  }

  createTimedGate(gate) {
    const root = new THREE.Group();
    root.position.set(gate.pos.x, gate.pos.y, gate.pos.z);
    const meshFirst = gate.asset_visual_mode === "replace" || gate.asset_replace_proxy === true;
    const proceduralGroup = new THREE.Group();
    root.add(proceduralGroup);

    const size = gate.size || { x: 0.7, y: 3.0, z: 8.0 };
    const panelWidth = Math.max(0.25, Number(size.z || 8.0) * 0.5);
    const panelDepth = Math.max(0.28, Number(size.x || 0.7));
    const panelHeight = Math.max(1.0, Number(size.y || 3.0));
    const travel = Number(gate.openTravel || 2.6);
    const frameHalf = Math.max(1.0, Number(size.z || 8.0) * 0.5 + 0.42);

    const frameMat = this.materials.fgGateFrame;
    const leftPost = new THREE.Mesh(new THREE.BoxGeometry(panelDepth * 1.2, panelHeight + 0.55, 0.35), frameMat);
    const rightPost = leftPost.clone();
    leftPost.position.set(0, 0, -frameHalf);
    rightPost.position.set(0, 0, frameHalf);
    const top = new THREE.Mesh(new THREE.BoxGeometry(panelDepth * 1.25, 0.35, frameHalf * 2 + 0.35), frameMat);
    top.position.y = panelHeight * 0.5 + 0.28;
    proceduralGroup.add(leftPost, rightPost, top);

    const panelMat = this.materials.fgGatePanelClosed;
    const leftPanel = new THREE.Mesh(new THREE.BoxGeometry(panelDepth, panelHeight, panelWidth), panelMat.clone());
    const rightPanel = new THREE.Mesh(new THREE.BoxGeometry(panelDepth, panelHeight, panelWidth), panelMat.clone());
    leftPanel.position.z = -panelWidth * 0.5;
    rightPanel.position.z = panelWidth * 0.5;
    proceduralGroup.add(leftPanel, rightPanel);

    const assetPanelGroup = new THREE.Group();
    const leftAssetPanel = new THREE.Group();
    const rightAssetPanel = new THREE.Group();
    leftAssetPanel.position.z = leftPanel.position.z;
    rightAssetPanel.position.z = rightPanel.position.z;
    assetPanelGroup.add(leftAssetPanel, rightAssetPanel);
    root.add(assetPanelGroup);

    proceduralGroup.traverse((obj) => {
      if (obj.isMesh) {
        obj.castShadow = true;
        obj.receiveShadow = true;
      }
    });

    const setOpen = (open, phase01 = 0) => {
      const eased = open ? Math.min(1, Math.max(0, phase01)) : 0;
      leftPanel.position.z = -panelWidth * 0.5 - travel * eased;
      rightPanel.position.z = panelWidth * 0.5 + travel * eased;
      leftAssetPanel.position.z = leftPanel.position.z;
      rightAssetPanel.position.z = rightPanel.position.z;
      leftPanel.material = open ? this.materials.fgGatePanelOpen : this.materials.fgGatePanelClosed;
      rightPanel.material = leftPanel.material;
    };
    setOpen(Boolean(gate.open));
    if (gate.visual_hidden === true) {
      proceduralGroup.visible = false;
      assetPanelGroup.visible = false;
    }

    if (this.debug) {
      root.add(createBoxDebug(size, 0x2c3e50));
    }

    if (gate.panel_asset_key) {
      const panelTarget = gate.panel_asset_target_size || { x: panelDepth, y: panelHeight, z: panelWidth };
      const panelOptions = {
        anchor: "center",
        scaleMode: gate.panel_asset_scale_mode || "uniform",
        keepPlaceholder: false,
        postScale: Number(gate.panel_asset_post_scale || 1),
      };
      this._attachOptionalModel(leftAssetPanel, gate.panel_asset_key, panelTarget, proceduralGroup, panelOptions);
      this._attachOptionalModel(rightAssetPanel, gate.panel_asset_key, panelTarget, proceduralGroup, panelOptions);
    }

    if (gate.asset_key) {
      this._attachOptionalModel(root, gate.asset_key, gate.asset_target_size || { x: 3.6, y: panelHeight + 0.8, z: frameHalf * 2.0 }, proceduralGroup, {
        anchor: "center",
        scaleMode: gate.asset_scale_mode || "uniform",
        keepPlaceholder: meshFirst ? false : true,
        postScale: Number(gate.asset_post_scale || 1),
      });
    }

    return { root, setOpen };
  }

  createBumper(bumper) {
    const root = new THREE.Group();
    root.position.set(bumper.pos.x, bumper.pos.y, bumper.pos.z);
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const radius = Number(bumper.radius || 1.1);
    const height = Number(bumper.height || 2.1);
    const body = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius * 0.92, height, 28), this.materials.fgSweeperBar);
    body.position.y = 0;
    body.castShadow = true;
    body.receiveShadow = true;
    placeholder.add(body);

    const capTop = new THREE.Mesh(new THREE.SphereGeometry(radius * 0.98, 24, 12), this.materials.fgSweeperTip);
    capTop.scale.y = 0.28;
    capTop.position.y = height * 0.5;
    const capBottom = capTop.clone();
    capBottom.position.y = -height * 0.5;
    placeholder.add(capTop, capBottom);

    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius * 1.02, radius * 0.08, 10, 28), this.materials.fgSweeperHub);
    ring.rotation.x = Math.PI * 0.5;
    ring.position.y = height * 0.12;
    placeholder.add(ring);

    const setActive = (active) => {
      const scale = active ? 1.12 : 1.0;
      placeholder.scale.set(scale, active ? 0.94 : 1.0, scale);
    };
    if (bumper.visual_hidden === true) {
      placeholder.visible = false;
    }

    if (this.debug) {
      root.add(createSphereDebug(radius, 0x2c3e50));
    }

    this._attachOptionalModel(root, bumper.asset_key || "fg_bounce_bumper_module", bumper.asset_target_size || { x: radius * 2.2, y: height * 1.15, z: radius * 2.2 }, placeholder, {
      anchor: "center",
      scaleMode: bumper.asset_scale_mode || "uniform",
      keepPlaceholder: bumper.asset_keep_placeholder === true,
      postScale: Number(bumper.asset_post_scale || 1),
    });

    return { root, setActive };
  }

  createPlayer(radius) {
    if (isFallGuysTheme(this.theme.id)) {
      return this.createFallGuysPlayer(radius);
    }

    const root = new THREE.Group();
    const placeholder = new THREE.Group();
    root.add(placeholder);

    const torso = new THREE.Mesh(new THREE.CapsuleGeometry(radius * 0.45, radius * 0.58, 8, 16), this.materials.playerOveralls);
    torso.position.y = -radius * 0.03;
    torso.castShadow = true;
    placeholder.add(torso);

    const belly = new THREE.Mesh(new THREE.SphereGeometry(radius * 0.39, 16, 12), this.materials.playerOveralls);
    belly.scale.set(1.1, 0.85, 0.88);
    belly.position.y = -radius * 0.24;
    placeholder.add(belly);

    const head = new THREE.Mesh(new THREE.SphereGeometry(radius * 0.37, 18, 16), this.materials.playerSkin);
    head.position.y = radius * 0.46;
    placeholder.add(head);

    const hatTop = new THREE.Mesh(new THREE.SphereGeometry(radius * 0.32, 16, 12), this.materials.playerHat);
    hatTop.scale.y = 0.62;
    hatTop.position.y = radius * 0.71;
    placeholder.add(hatTop);

    const hatBrim = new THREE.Mesh(new THREE.CylinderGeometry(radius * 0.34, radius * 0.34, radius * 0.08, 16), this.materials.playerHat);
    hatBrim.position.set(0, radius * 0.57, radius * 0.08);
    placeholder.add(hatBrim);

    const nose = new THREE.Mesh(new THREE.SphereGeometry(radius * 0.09, 12, 10), this.materials.playerSkin);
    nose.position.set(0, radius * 0.43, radius * 0.31);
    placeholder.add(nose);

    const mustache = new THREE.Mesh(new THREE.BoxGeometry(radius * 0.34, radius * 0.08, radius * 0.06), this.materials.playerHair);
    mustache.position.set(0, radius * 0.34, radius * 0.33);
    placeholder.add(mustache);

    if (this.debug) {
      root.add(createSphereDebug(radius, 0x2c3e50));
    }

    this._attachOptionalModel(root, "player", { x: radius * 2, y: radius * 2, z: radius * 2 }, placeholder, {
      anchor: "bottom",
      yOffset: -radius,
      postScale: this.theme.id === "manual" ? 0.62 : 1,
    });
    return { root };
  }

  createFallGuysPlayer(radius) {
    const root = new THREE.Group();
    const placeholder = new THREE.Group();
    root.add(placeholder);
    const animation = {
      mixer: null,
      action: null,
      targetWeight: 0,
      currentWeight: 0,
      speed: 0,
    };

    const bodyMat = new THREE.MeshStandardMaterial({ color: 0xff66b8, roughness: 0.62, metalness: 0.02 });
    const faceMat = new THREE.MeshStandardMaterial({ color: 0xf7fbff, roughness: 0.68, metalness: 0.01 });
    const eyeMat = new THREE.MeshStandardMaterial({ color: 0x202033, roughness: 0.72, metalness: 0.0 });
    const limbMat = new THREE.MeshStandardMaterial({ color: 0x5f46ff, roughness: 0.58, metalness: 0.02 });

    const body = new THREE.Mesh(new THREE.CapsuleGeometry(radius * 0.48, radius * 0.74, 12, 22), bodyMat);
    body.position.y = -radius * 0.03;
    body.castShadow = true;
    placeholder.add(body);

    const face = new THREE.Mesh(new THREE.SphereGeometry(radius * 0.30, 22, 14), faceMat);
    face.scale.set(1.18, 0.74, 0.28);
    face.position.set(0, radius * 0.25, radius * 0.45);
    placeholder.add(face);

    const eyeGeo = new THREE.SphereGeometry(radius * 0.045, 10, 8);
    const leftEye = new THREE.Mesh(eyeGeo, eyeMat);
    const rightEye = leftEye.clone();
    leftEye.position.set(-radius * 0.12, radius * 0.29, radius * 0.53);
    rightEye.position.set(radius * 0.12, radius * 0.29, radius * 0.53);
    placeholder.add(leftEye, rightEye);

    const armGeo = new THREE.CapsuleGeometry(radius * 0.075, radius * 0.45, 8, 12);
    const leftArm = new THREE.Mesh(armGeo, limbMat);
    const rightArm = leftArm.clone();
    leftArm.rotation.z = -0.45;
    rightArm.rotation.z = 0.45;
    leftArm.position.set(-radius * 0.54, -radius * 0.05, radius * 0.05);
    rightArm.position.set(radius * 0.54, -radius * 0.05, radius * 0.05);
    placeholder.add(leftArm, rightArm);

    const footGeo = new THREE.CapsuleGeometry(radius * 0.10, radius * 0.24, 8, 12);
    const leftFoot = new THREE.Mesh(footGeo, limbMat);
    const rightFoot = leftFoot.clone();
    leftFoot.rotation.x = Math.PI * 0.5;
    rightFoot.rotation.x = Math.PI * 0.5;
    leftFoot.position.set(-radius * 0.22, -radius * 0.72, radius * 0.08);
    rightFoot.position.set(radius * 0.22, -radius * 0.72, radius * 0.08);
    placeholder.add(leftFoot, rightFoot);

    if (this.debug) {
      root.add(createSphereDebug(radius, 0x2c3e50));
    }

    this._attachOptionalModel(root, "player", { x: radius * 0.62, y: radius * 1.05, z: radius * 0.54 }, placeholder, {
      anchor: "bottom",
      yOffset: -radius,
      postScale: 0.05,
      onModel: (model) => {
        const clips = model.userData?.assetAnimations || model.animations || [];
        if (!clips.length) return;
        const clip = clips.find((item) => /run/i.test(String(item?.name || ""))) || clips[0];
        animation.mixer = new THREE.AnimationMixer(model);
        animation.action = animation.mixer.clipAction(clip);
        animation.action.enabled = true;
        animation.action.setLoop(THREE.LoopRepeat, Infinity);
        animation.action.setEffectiveWeight(0);
        animation.action.play();
      },
    });
    return {
      root,
      setMotion: ({ speed = 0, grounded = true } = {}) => {
        animation.speed = Math.max(0, Number(speed) || 0);
        animation.targetWeight = grounded && animation.speed > 0.35 ? 1 : 0;
        if (animation.action) {
          animation.action.timeScale = clampNumber(animation.speed / 5.8, 0.65, 1.75);
        }
      },
      update: (dt) => {
        if (!animation.mixer || !animation.action) return;
        const t = clampNumber(Number(dt) * 10, 0, 1);
        animation.currentWeight += (animation.targetWeight - animation.currentWeight) * t;
        animation.action.setEffectiveWeight(animation.currentWeight);
        animation.mixer.update(dt);
      },
    };
  }

  _attachOptionalModel(root, key, targetSize, placeholder, options = {}) {
    this.assetLoader.loadModel(key).then((model) => {
      if (!model) return;
      if (!root || root.userData.visualDisposed) return;
      if (countRenderableMeshes(model) === 0) {
        console.warn(`[visual-factory] model '${key}' has no renderable mesh, keep placeholder`);
        return;
      }
      const normalized = fitModelToBox(model, targetSize, options);
      if (!normalized) {
        console.warn(`[visual-factory] normalization failed for key='${key}', keep placeholder`);
        return;
      }
      const rotationY = Number(options.rotationY || 0);
      if (Number.isFinite(rotationY) && rotationY !== 0) {
        model.rotation.y += rotationY;
      }
      model.traverse((obj) => {
        if (!obj.isMesh) return;
        obj.castShadow = true;
        obj.receiveShadow = true;
        if (obj.isSkinnedMesh) obj.frustumCulled = false;
      });
      root.add(model);
      if (placeholder && options.keepPlaceholder !== true) placeholder.visible = false;
      if (typeof options.onModel === "function") options.onModel(model);
    });
  }
}

function addFinishCheckerboard(parent, size, materials) {
  const cols = 8;
  const rows = 3;
  const tileX = (Number(size.x) * 0.86) / cols;
  const tileZ = (Number(size.z) * 0.62) / rows;
  const y = Number(size.y) * 0.5 + 0.06;
  for (let ix = 0; ix < cols; ix += 1) {
    for (let iz = 0; iz < rows; iz += 1) {
      const mat = (ix + iz) % 2 === 0 ? materials.fgFinishStripeDark : materials.fgFinishStripeLight;
      const tile = new THREE.Mesh(new THREE.BoxGeometry(tileX * 0.94, 0.045, tileZ * 0.92), mat);
      tile.position.set((ix - (cols - 1) * 0.5) * tileX, y, (iz - (rows - 1) * 0.5) * tileZ);
      tile.receiveShadow = true;
      parent.add(tile);
    }
  }
}

export function createMechanicsSnapshot(level, playerRadius) {
  return stableSerialize({
    playerRadius,
    start: cloneVec(level?.start),
    goal: cloneVec(level?.goal),
    platforms: sortById((level?.platforms || []).map((item) => sanitizePlatform(item))),
    enemies: sortById((level?.enemies || []).map((item) => sanitizeEnemy(item))),
    keys: sortById((level?.keys || []).map((item) => sanitizeKey(item))),
    locks: sortById((level?.locks || []).map((item) => sanitizeLock(item))),
    checkpoints: sortById((level?.checkpoints || []).map((item) => sanitizeCheckpoint(item))),
  });
}

export function assertMechanicsInvariant(level, snapshot, playerRadius) {
  const next = createMechanicsSnapshot(level, playerRadius);
  if (next !== snapshot) {
    throw new Error("Mechanics invariant failed: visual layer attempted to mutate gameplay data.");
  }
}

export function disposeObjectDeep(root) {
  if (!root) return;
  root.traverse((obj) => {
    obj.userData.visualDisposed = true;
    if (obj.geometry?.dispose) obj.geometry.dispose();
    if (obj.material) {
      if (Array.isArray(obj.material)) {
        for (const mat of obj.material) {
          disposeMaterial(mat);
        }
      } else {
        disposeMaterial(obj.material);
      }
    }
  });
}

function disposeMaterial(material) {
  if (!material) return;
  // Textures are cached globally across reloads; dispose only the material object.
  if (material.dispose) material.dispose();
}

function isFallGuysTheme(themeId) {
  return themeId === "obstacle_course";
}

function fitModelToBox(model, targetSize, options = {}) {
  const anchor = options.anchor || "center";
  const scaleMode = options.scaleMode || "uniform";
  const postScale = clampNumber(Number(options.postScale || 1), 1e-4, 1e4);
  const yOffset = Number(options.yOffset || 0);

  let bounds = computeRenderableBounds(model);
  if (!bounds) return false;

  const current = bounds.size;
  const tx = Math.max(Number(targetSize?.x) || 0, 1e-4);
  const ty = Math.max(Number(targetSize?.y) || 0, 1e-4);
  const tz = Math.max(Number(targetSize?.z) || 0, 1e-4);
  const cx = Math.max(current.x, 1e-4);
  const cy = Math.max(current.y, 1e-4);
  const cz = Math.max(current.z, 1e-4);

  if (scaleMode === "stretch") {
    const sx = clampNumber((tx / cx) * 0.98, 1e-4, 1e4);
    const sy = clampNumber((ty / cy) * 0.98, 1e-4, 1e4);
    const sz = clampNumber((tz / cz) * 0.98, 1e-4, 1e4);
    if (!Number.isFinite(sx) || !Number.isFinite(sy) || !Number.isFinite(sz)) return false;
    model.scale.multiply(new THREE.Vector3(sx, sy, sz));
  } else {
    let scale = Math.min(tx / cx, ty / cy, tz / cz) * 0.98;
    if (!Number.isFinite(scale) || scale <= 0) return false;
    scale = clampNumber(scale, 1e-4, 1e4);
    model.scale.multiplyScalar(scale);
  }

  if (postScale !== 1) {
    model.scale.multiplyScalar(postScale);
  }

  bounds = computeRenderableBounds(model);
  if (!bounds) return false;

  // Second pass: hard clamp any oversized result caused by source transform quirks.
  const over = Math.max(bounds.size.x / tx, bounds.size.y / ty, bounds.size.z / tz);
  if (Number.isFinite(over) && over > 1.02) {
    const correction = clampNumber((1 / over) * 0.98, 1e-4, 1);
    if (scaleMode === "stretch") {
      model.scale.multiply(new THREE.Vector3(correction, correction, correction));
    } else {
      model.scale.multiplyScalar(correction);
    }
    bounds = computeRenderableBounds(model);
    if (!bounds) return false;
  }

  const finalOver = Math.max(bounds.size.x / tx, bounds.size.y / ty, bounds.size.z / tz);
  if (!Number.isFinite(finalOver) || finalOver > 1.08) {
    return false;
  }

  model.position.x -= bounds.center.x;
  model.position.z -= bounds.center.z;
  if (anchor === "bottom") {
    model.position.y -= bounds.min.y;
  } else {
    model.position.y -= bounds.center.y;
  }
  model.position.y += yOffset;
  return true;
}

function computeRenderableBounds(root) {
  root.updateWorldMatrix(true, true);
  const box = new THREE.Box3();
  box.expandByObject(root, false);

  if (box.isEmpty()) return null;
  if (!isFiniteBox(box)) return null;

  const center = new THREE.Vector3();
  const size = new THREE.Vector3();
  box.getCenter(center);
  box.getSize(size);
  return {
    box,
    center,
    size,
    min: box.min.clone(),
    max: box.max.clone(),
  };
}

function isFiniteBox(box) {
  return (
    Number.isFinite(box.min.x) &&
    Number.isFinite(box.min.y) &&
    Number.isFinite(box.min.z) &&
    Number.isFinite(box.max.x) &&
    Number.isFinite(box.max.y) &&
    Number.isFinite(box.max.z)
  );
}

function countRenderableMeshes(root) {
  let n = 0;
  root.traverse((obj) => {
    if (obj?.isMesh && obj.geometry) n += 1;
  });
  return n;
}

function clampNumber(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

function createBoxDebug(size, color) {
  const mesh = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x, size.y, size.z)),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.45 })
  );
  return mesh;
}

function createSphereDebug(radius, color) {
  return new THREE.Mesh(
    new THREE.SphereGeometry(radius, 14, 10),
    new THREE.MeshBasicMaterial({ color, wireframe: true, transparent: true, opacity: 0.28 })
  );
}

function cloneVec(v) {
  if (!v) return null;
  return {
    x: Number(v.x) || 0,
    y: Number(v.y) || 0,
    z: Number(v.z) || 0,
  };
}

function sanitizePlatform(item) {
  return {
    id: item?.id || "",
    pos: cloneVec(item?.pos),
    size: cloneVec(item?.size),
    kind: item?.kind || "static",
    motion: item?.motion
      ? {
          axis: item.motion.axis,
          amplitude: item.motion.amplitude,
          period: item.motion.period,
          phase: item.motion.phase,
        }
      : null,
    tags: [...(item?.tags || [])],
    node_id: item?.node_id || null,
  };
}

function sanitizeEnemy(item) {
  return {
    id: item?.id || "",
    pos: cloneVec(item?.pos),
    radius: Number(item?.radius) || 0,
    patrol: item?.patrol
      ? {
          from: cloneVec(item.patrol.from),
          to: cloneVec(item.patrol.to),
        }
      : null,
    speed: Number(item?.speed) || 0,
    node_id: item?.node_id || null,
  };
}

function sanitizeKey(item) {
  return {
    id: item?.id || "",
    key_id: item?.key_id || null,
    pos: cloneVec(item?.pos),
    radius: Number(item?.radius) || 0,
    node_id: item?.node_id || null,
  };
}

function sanitizeLock(item) {
  return {
    id: item?.id || "",
    lock_id: item?.lock_id || null,
    key_id: item?.key_id || null,
    pos: cloneVec(item?.pos),
    size: cloneVec(item?.size),
    node_id: item?.node_id || null,
    locked: item?.locked !== false,
  };
}

function sanitizeCheckpoint(item) {
  return {
    id: item?.id || "",
    pos: cloneVec(item?.pos),
    radius: Number(item?.radius) || 0,
    node_id: item?.node_id || null,
  };
}

function sortById(arr) {
  return [...arr].sort((a, b) => String(a.id).localeCompare(String(b.id)));
}

function stableSerialize(value) {
  return JSON.stringify(sortDeep(value));
}

function sortDeep(value) {
  if (Array.isArray(value)) return value.map((item) => sortDeep(item));
  if (value && typeof value === "object") {
    const out = {};
    const keys = Object.keys(value).sort((a, b) => a.localeCompare(b));
    for (const key of keys) out[key] = sortDeep(value[key]);
    return out;
  }
  return value;
}
