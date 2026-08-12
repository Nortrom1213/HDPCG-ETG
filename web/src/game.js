import * as THREE from "../vendor/three.module.js";
import { resolveVisualConfig, resolveThemeDescriptor } from "./visual/theme-manager.js?v=10";
import {
  VisualFactory,
  assertMechanicsInvariant,
  createMechanicsSnapshot,
  disposeObjectDeep,
} from "./visual/visual-factory.js?v=10";
import { PostFXManager } from "./visual/postfx.js?v=10";

const PLAYER_RADIUS = 1.2;
const COLLISION_SKIN_Y = 0.08;
const COLLISION_SKIN_XZ = 0.02;
const MAX_PHYSICS_STEP = 1 / 120;
const PLAYER_VISUAL_YAW_OFFSET = 0;
const GOD_MOVE_SPEED = 11.5;
const GOD_SPRINT_SPEED = 17.0;


export class Game {
  constructor(canvas, statusSink, visualConfig = {}) {
    this.canvas = canvas;
    this.statusSink = statusSink;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xd7f2ff);

    this.camera = new THREE.PerspectiveCamera(65, 1, 0.1, 500);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio || 1);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.clock = new THREE.Clock();
    this.keys = new Set();

    this.yaw = 0;
    this.pitch = -0.35;
    this.cameraDistance = 14;
    this.cameraTargetYOffset = 0;
    this.canvasFocused = false;
    this.viewMode = "player";
    this.godPosition = new THREE.Vector3(0, 8, 0);

    this.player = null;
    this.playerMesh = null;
    this.playerVisual = null;
    this.playerVel = new THREE.Vector3();
    this.onGround = false;

    this.platforms = [];
    this.enemies = [];
    this.sweepers = [];
    this.timedGates = [];
    this.bumpers = [];
    this.showcaseCharacters = [];
    this.keysEntities = [];
    this.locks = [];
    this.checkpoints = [];
    this.goal = null;

    this.respawn = new THREE.Vector3(0, 2, 0);
    this.collectedKeys = new Set();
    this.goalReached = false;
    this.level = null;

    this.visualConfig = resolveVisualConfig(visualConfig);
    this.visualFactory = new VisualFactory(this.scene, this.visualConfig);
    this.lights = { ambient: null, directional: null };
    this.postfx = new PostFXManager(this.renderer, {
      enabled: this.visualConfig.postfx,
      quality: this.visualConfig.quality,
      theme: resolveThemeDescriptor(this.visualConfig.themeId),
    });

    this._bindEvents();
    this._setupLights();
  }

  _bindEvents() {
    window.addEventListener("resize", () => this._resize());
    window.addEventListener("keydown", (event) => {
      if (shouldPreventScroll(event, this.canvasFocused)) event.preventDefault();
      this.keys.add(event.code);
    });
    window.addEventListener("keyup", (event) => this.keys.delete(event.code));
    this.canvas.addEventListener("click", () => {
      this.canvasFocused = true;
      if (document.pointerLockElement !== this.canvas) {
        this.canvas.requestPointerLock();
      }
    });
    this.canvas.addEventListener("mousedown", () => {
      this.canvasFocused = true;
    });
    window.addEventListener("blur", () => {
      this.canvasFocused = false;
    });
    window.addEventListener("mousemove", (event) => {
      if (document.pointerLockElement !== this.canvas) return;
      const sensitivity = 0.0025;
      this.yaw += event.movementX * sensitivity;
      this.pitch -= event.movementY * sensitivity;
      this.pitch = this._clampPitch(this.pitch);
    });
  }

  _clampPitch(value) {
    if (this.viewMode === "god") {
      return clamp(value, -1.45, 1.45);
    }
    return clamp(value, -1.1, -0.1);
  }

  _setupLights() {
    const ambient = new THREE.AmbientLight(0xffffff, 0.62);
    this.scene.add(ambient);
    const dir = new THREE.DirectionalLight(0xfff3d6, 1.08);
    dir.position.set(10, 20, 10);
    dir.castShadow = true;
    dir.shadow.mapSize.width = 1024;
    dir.shadow.mapSize.height = 1024;
    dir.shadow.camera.near = 0.5;
    dir.shadow.camera.far = 140;
    dir.shadow.camera.left = -45;
    dir.shadow.camera.right = 45;
    dir.shadow.camera.top = 45;
    dir.shadow.camera.bottom = -45;
    dir.shadow.bias = -0.00012;
    this.scene.add(dir);
    this.lights.ambient = ambient;
    this.lights.directional = dir;
    this.visualFactory.applyEnvironment(this.scene, this.lights);
  }

  _resize() {
    const { clientWidth, clientHeight } = this.canvas.parentElement;
    this.camera.aspect = clientWidth / clientHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(clientWidth, clientHeight, false);
  }

  loadLevel(level) {
    this._clearScene();
    this.level = level;
    this.collectedKeys.clear();
    this.goalReached = false;
    this.visualFactory.setTheme(this.visualConfig.themeId, this.visualConfig.quality, this.visualConfig.debug);
    this.postfx.setTheme(resolveThemeDescriptor(this.visualConfig.themeId));
    this.postfx.setQuality(this.visualConfig.quality);
    this.postfx.setEnabled(this.visualConfig.postfx);
    this.visualFactory.applyEnvironment(this.scene, this.lights);

    const mechanicsSnapshot = createMechanicsSnapshot(level, PLAYER_RADIUS);

    for (const platform of level.platforms) {
      const visual = this.visualFactory.createPlatform(platform);
      const mesh = visual.root;
      mesh.position.set(platform.pos.x, platform.pos.y, platform.pos.z);
      mesh.rotation.y = Number(platform.yaw || platform.rotation_y || 0);
      mesh.userData.platform = platform;
      this.scene.add(mesh);
      this.platforms.push({ data: platform, mesh, visual, basePos: { ...platform.pos } });
    }

    for (const gate of level.timed_gates || []) {
      const visual = this.visualFactory.createTimedGate(gate);
      const mesh = visual.root;
      mesh.position.set(gate.pos.x, gate.pos.y, gate.pos.z);
      mesh.rotation.y = Number(gate.yaw || gate.rotation_y || 0);
      this.scene.add(mesh);
      this.timedGates.push({ data: gate, mesh, visual, open: false });
    }

    for (const sweeper of level.sweepers || []) {
      const visual = this.visualFactory.createSweeper(sweeper);
      const mesh = visual.root;
      mesh.position.set(sweeper.pos.x, sweeper.pos.y, sweeper.pos.z);
      mesh.rotation.y = Number(sweeper.yaw || sweeper.rotation_y || 0);
      this.scene.add(mesh);
      this.sweepers.push({ data: sweeper, mesh, visual });
    }

    for (const bumper of level.bumpers || []) {
      const visual = this.visualFactory.createBumper(bumper);
      const mesh = visual.root;
      mesh.position.set(bumper.pos.x, bumper.pos.y, bumper.pos.z);
      mesh.rotation.y = Number(bumper.yaw || bumper.rotation_y || 0);
      this.scene.add(mesh);
      this.bumpers.push({ data: bumper, mesh, visual, cooldown: 0 });
    }

    for (const enemy of level.enemies) {
      const visual = this.visualFactory.createEnemy(enemy);
      const mesh = visual.root;
      mesh.position.set(enemy.pos.x, enemy.pos.y, enemy.pos.z);
      this.scene.add(mesh);
      this.enemies.push({ data: enemy, mesh, visual, dir: 1 });
    }

    for (const key of level.keys) {
      const visual = this.visualFactory.createKey(key);
      const mesh = visual.root;
      mesh.position.set(key.pos.x, key.pos.y, key.pos.z);
      this.scene.add(mesh);
      this.keysEntities.push({ data: key, mesh, visual, collected: false });
    }

    for (const lock of level.locks) {
      const visual = this.visualFactory.createLock(lock);
      const mesh = visual.root;
      mesh.position.set(lock.pos.x, lock.pos.y, lock.pos.z);
      this.scene.add(mesh);
      this.locks.push({ data: lock, mesh, visual });
      this._setLockVisualState(this.locks[this.locks.length - 1], lock.locked !== false);
    }

    for (const checkpoint of level.checkpoints) {
      const visual = this.visualFactory.createCheckpoint(checkpoint);
      const mesh = visual.root;
      mesh.position.set(checkpoint.pos.x, checkpoint.pos.y, checkpoint.pos.z);
      this.scene.add(mesh);
      this.checkpoints.push({ data: checkpoint, mesh, visual });
    }

    for (const character of level.showcase_characters || []) {
      const radius = Number(character.radius || PLAYER_RADIUS * 0.95);
      const visual = this.visualFactory.createPlayer(radius);
      const mesh = visual.root;
      const pos = character.pos || { x: level.start.x + 3, y: 1.2, z: level.start.z - 1.5 };
      mesh.position.set(Number(pos.x || 0), Number(pos.y || 1.2), Number(pos.z || 0));
      mesh.rotation.y = Number(character.yaw || 0);
      this.scene.add(mesh);
      this.showcaseCharacters.push({ data: character, mesh, visual });
    }

    if (level.goal) {
      const visual = this.visualFactory.createGoal(level.goal);
      const mesh = visual.root;
      this.scene.add(mesh);
      this.goal = { pos: visual.targetPos.clone(), mesh, visual };
    }

    this.player = new THREE.Vector3(level.start.x, level.start.y + 2, level.start.z);
    this.respawn.copy(this.player);
    if (this.viewMode === "god") {
      this.godPosition.set(level.start.x, level.start.y + 8, level.start.z + 12);
    }

    const playerVisual = this.visualFactory.createPlayer(PLAYER_RADIUS);
    this.playerVisual = playerVisual;
    this.playerMesh = playerVisual.root;
    this.playerMesh.position.copy(this.player);
    this.scene.add(this.playerMesh);

    const ground = this.visualFactory.createGround();
    if (ground?.root) this.scene.add(ground.root);

    assertMechanicsInvariant(level, mechanicsSnapshot, PLAYER_RADIUS);

    this._resize();
  }

  _clearScene() {
    for (const child of [...this.scene.children]) {
      this.scene.remove(child);
      disposeObjectDeep(child);
    }
    this._setupLights();
    this.platforms = [];
    this.enemies = [];
    this.sweepers = [];
    this.timedGates = [];
    this.bumpers = [];
    this.showcaseCharacters = [];
    this.keysEntities = [];
    this.locks = [];
    this.checkpoints = [];
    this.goal = null;
    this.playerMesh = null;
    this.playerVisual = null;
  }

  start() {
    this.clock.start();
    const loop = () => {
      const dt = Math.min(this.clock.getDelta(), 0.05);
      this._update(dt);
      this.postfx.render(this.scene, this.camera);
      this._animation = requestAnimationFrame(loop);
    };
    loop();
  }

  stop() {
    if (this._animation) cancelAnimationFrame(this._animation);
    this._animation = null;
  }

  _update(dt) {
    if (!this.player) return;
    this._updateMovingPlatforms(dt);
    this._updateEnemies(dt);
    this._updateTimedGates();
    this._updateSweepers();
    this._updateBumpers(dt);
    if (this.viewMode === "god") {
      this._updateGod(dt);
    } else {
      this._updatePlayer(dt);
    }
    this._updatePlayerVisualAnimation(dt);
    this._updateCamera();
    this._updateStatus();
  }

  _updateGod(dt) {
    const isSprinting = this.keys.has("ShiftLeft") || this.keys.has("ShiftRight");
    const speed = isSprinting ? GOD_SPRINT_SPEED : GOD_MOVE_SPEED;
    const horizontal = new THREE.Vector3();
    const forward = new THREE.Vector3(Math.cos(this.yaw), 0, Math.sin(this.yaw));
    const right = new THREE.Vector3(-Math.sin(this.yaw), 0, Math.cos(this.yaw));

    if (this.keys.has("KeyW")) horizontal.add(forward);
    if (this.keys.has("KeyS")) horizontal.add(forward.clone().negate());
    if (this.keys.has("KeyA")) horizontal.add(right.clone().negate());
    if (this.keys.has("KeyD")) horizontal.add(right);

    if (horizontal.lengthSq() > 0) {
      horizontal.normalize().multiplyScalar(speed * dt);
      this.godPosition.add(horizontal);
    }

    let vertical = 0;
    if (this.keys.has("Space")) vertical += speed * dt;
    if (this.keys.has("ControlLeft") || this.keys.has("ControlRight")) vertical -= speed * dt;
    this.godPosition.y += vertical;
  }

  _updateMovingPlatforms(dt) {
    for (const entry of this.platforms) {
      const platform = entry.data;
      if (platform.kind !== "moving" || !platform.motion) continue;
      const { axis, amplitude, period, phase } = platform.motion;
      const omega = (2 * Math.PI) / period;
      const offset = Math.sin(this.clock.elapsedTime * omega + phase) * amplitude;
      const base = entry.basePos;
      const pos = { ...base };
      pos[axis] = base[axis] + offset;
      entry.mesh.position.set(pos.x, pos.y, pos.z);
      platform.pos = pos;
    }
  }

  _updateEnemies(dt) {
    for (const entry of this.enemies) {
      const enemy = entry.data;
      if (!enemy.patrol) continue;
      const span = enemy.patrol.to.x - enemy.patrol.from.x;
      const travel = enemy.speed * dt * entry.dir;
      enemy.pos.x += travel;
      if (span >= 0 && (enemy.pos.x < enemy.patrol.from.x || enemy.pos.x > enemy.patrol.to.x)) {
        entry.dir *= -1;
        enemy.pos.x = clamp(enemy.pos.x, enemy.patrol.from.x, enemy.patrol.to.x);
      }
      if (span < 0 && (enemy.pos.x > enemy.patrol.from.x || enemy.pos.x < enemy.patrol.to.x)) {
        entry.dir *= -1;
        enemy.pos.x = clamp(enemy.pos.x, enemy.patrol.to.x, enemy.patrol.from.x);
      }
      entry.mesh.position.set(enemy.pos.x, enemy.pos.y, enemy.pos.z);
    }
  }

  _updateTimedGates() {
    const t = this.clock.elapsedTime;
    for (const entry of this.timedGates) {
      const gate = entry.data;
      const state = timedGateState(gate, t);
      entry.open = state.open;
      gate.open = state.open;
      if (entry.visual?.setOpen) entry.visual.setOpen(state.open, state.openPhase);
    }
  }

  _updateSweepers() {
    const t = this.clock.elapsedTime;
    for (const entry of this.sweepers) {
      const baseYaw = Number(entry.data.yaw || entry.data.rotation_y || 0);
      const localAngle = sweeperAngle(entry.data, t);
      const worldAngle = baseYaw + localAngle;
      entry.prevAngle = Number.isFinite(entry.angle) ? entry.angle : worldAngle;
      entry.angle = worldAngle;
      entry.mesh.rotation.y = baseYaw;
      if (entry.visual?.setAngle) entry.visual.setAngle(localAngle);
    }
  }

  _updateBumpers(dt) {
    for (const entry of this.bumpers) {
      entry.cooldown = Math.max(0, Number(entry.cooldown || 0) - dt);
      if (entry.visual?.setActive) entry.visual.setActive(entry.cooldown > 0);
    }
  }

  _updatePlayer(dt) {
    const speed = 7.5;
    const accel = 30;
    const gravity = -24;
    const jumpSpeed = 9.6;

    const move = new THREE.Vector3();
    const forward = new THREE.Vector3(Math.cos(this.yaw), 0, Math.sin(this.yaw));
    const right = new THREE.Vector3(-Math.sin(this.yaw), 0, Math.cos(this.yaw));
    if (this.keys.has("KeyW") || this.keys.has("ArrowUp")) move.add(forward);
    if (this.keys.has("KeyS") || this.keys.has("ArrowDown")) move.add(forward.clone().negate());
    if (this.keys.has("KeyA") || this.keys.has("ArrowLeft")) move.add(right.clone().negate());
    if (this.keys.has("KeyD") || this.keys.has("ArrowRight")) move.add(right);
    if (move.lengthSq() > 0) move.normalize().multiplyScalar(speed);

    const wantsJump = this.onGround && this.keys.has("Space");
    if (wantsJump) {
      this.playerVel.y = jumpSpeed;
      this.onGround = false;
    }

    let remaining = dt;
    while (remaining > 0) {
      const step = Math.min(remaining, MAX_PHYSICS_STEP);
      remaining -= step;

      this.playerVel.x += (move.x - this.playerVel.x) * Math.min(1, accel * step);
      this.playerVel.z += (move.z - this.playerVel.z) * Math.min(1, accel * step);
      this.playerVel.y += gravity * step;

      const prev = this.player.clone();
      this.player.x += this.playerVel.x * step;
      this.player.y += this.playerVel.y * step;
      this.player.z += this.playerVel.z * step;

      this.onGround = false;
      this._resolvePlatformCollisions(prev);
      if (this.onGround && this.playerVel.y < 0) {
        this.playerVel.y = 0;
      }
    }
    this._checkEntityInteractions();
    if (this.player.y < -30) this._respawn();

    this.playerMesh.position.copy(this.player);
    this._updatePlayerVisualFacing(dt);
  }

  _updatePlayerVisualFacing(dt) {
    if (!this.playerMesh) return;
    const vx = this.playerVel.x;
    const vz = this.playerVel.z;
    const speedSq = vx * vx + vz * vz;
    if (speedSq < 0.09) return;

    const targetYaw = Math.atan2(vx, vz) + PLAYER_VISUAL_YAW_OFFSET;
    const smooth = clamp(dt * 12, 0, 1);
    this.playerMesh.rotation.y = lerpAngle(this.playerMesh.rotation.y, targetYaw, smooth);
  }

  _updatePlayerVisualAnimation(dt) {
    if (!this.playerVisual) return;
    const speed = this.viewMode === "player" ? Math.hypot(this.playerVel.x, this.playerVel.z) : 0;
    if (this.playerVisual.setMotion) {
      this.playerVisual.setMotion({ speed, grounded: this.onGround });
    }
    if (this.playerVisual.update) {
      this.playerVisual.update(dt);
    }
  }

  _resolvePlatformCollisions(prev) {
    const radius = PLAYER_RADIUS;
    const skinY = COLLISION_SKIN_Y;
    const skinXZ = COLLISION_SKIN_XZ;
    const curr = this.player;
    const radiusXZ = radius + skinXZ;
    for (const entry of this.platforms) {
      const platform = entry.data;
      const half = {
        x: platform.size.x * 0.5,
        y: platform.size.y * 0.5,
        z: platform.size.z * 0.5,
      };
      const min = {
        x: platform.pos.x - half.x,
        y: platform.pos.y - half.y,
        z: platform.pos.z - half.z,
      };
      const max = {
        x: platform.pos.x + half.x,
        y: platform.pos.y + half.y,
        z: platform.pos.z + half.z,
      };
      const top = max.y;

      if (this.playerVel.y > 0) continue;

      const planeY = top + radius;
      const prevAbove = prev.y >= planeY - skinY;
      const currBelow = curr.y <= planeY + skinY;

      if (prevAbove && currBelow) {
        const dy = curr.y - prev.y;
        const t = dy !== 0 ? (planeY - prev.y) / dy : 0;
        if (t >= 0 && t <= 1) {
          const ix = prev.x + (curr.x - prev.x) * t;
          const iz = prev.z + (curr.z - prev.z) * t;
          if (
            ix >= min.x - radiusXZ &&
            ix <= max.x + radiusXZ &&
            iz >= min.z - radiusXZ &&
            iz <= max.z + radiusXZ
          ) {
            curr.y = planeY;
            this.playerVel.y = 0;
            this.onGround = true;
            continue;
          }
        }
      }

      if (prevAbove) {
        const closestX = clamp(curr.x, min.x, max.x);
        const closestY = clamp(curr.y, min.y, max.y);
        const closestZ = clamp(curr.z, min.z, max.z);
        const dx = curr.x - closestX;
        const dy = curr.y - closestY;
        const dz = curr.z - closestZ;
        if (dx * dx + dy * dy + dz * dz <= radiusXZ * radiusXZ) {
          curr.y = planeY;
          this.playerVel.y = 0;
          this.onGround = true;
        }
      }
    }

    for (const lock of this.locks) {
      if (!lock.data.locked) continue;
      const half = {
        x: lock.data.size.x * 0.5,
        y: lock.data.size.y * 0.5,
        z: lock.data.size.z * 0.5,
      };
      const min = {
        x: lock.data.pos.x - half.x,
        y: lock.data.pos.y - half.y,
        z: lock.data.pos.z - half.z,
      };
      const max = {
        x: lock.data.pos.x + half.x,
        y: lock.data.pos.y + half.y,
        z: lock.data.pos.z + half.z,
      };
      const closestX = clamp(this.player.x, min.x, max.x);
      const closestY = clamp(this.player.y, min.y, max.y);
      const closestZ = clamp(this.player.z, min.z, max.z);
      const dx = this.player.x - closestX;
      const dy = this.player.y - closestY;
      const dz = this.player.z - closestZ;
      const distSq = dx * dx + dy * dy + dz * dz;
      if (distSq >= radius * radius) continue;

      const horizDistSq = dx * dx + dz * dz;
      if (horizDistSq > 1e-6) {
        const dist = Math.sqrt(horizDistSq);
        const push = (radius - dist) / dist;
        this.player.x += dx * push;
        this.player.z += dz * push;
      } else {
        const penX = Math.min(this.player.x - min.x, max.x - this.player.x);
        const penZ = Math.min(this.player.z - min.z, max.z - this.player.z);
        if (penX <= penZ) {
          const dir = this.player.x >= lock.data.pos.x ? 1 : -1;
          this.player.x += dir * (radius + penX);
        } else {
          const dir = this.player.z >= lock.data.pos.z ? 1 : -1;
          this.player.z += dir * (radius + penZ);
        }
      }
      this.playerVel.x = 0;
      this.playerVel.z = 0;
    }

    for (const gate of this.timedGates) {
      if (gate.open) continue;
      const half = {
        x: gate.data.size.x * 0.5,
        y: gate.data.size.y * 0.5,
        z: gate.data.size.z * 0.5,
      };
      const yaw = Number(gate.data.yaw || gate.data.rotation_y || 0);
      const local = worldToLocal2D(this.player.x, this.player.z, gate.data.pos.x, gate.data.pos.z, yaw);
      const closestLocalX = clamp(local.x, -half.x, half.x);
      const closestY = clamp(this.player.y, gate.data.pos.y - half.y, gate.data.pos.y + half.y);
      const closestLocalZ = clamp(local.z, -half.z, half.z);
      const dxLocal = local.x - closestLocalX;
      const dy = this.player.y - closestY;
      const dzLocal = local.z - closestLocalZ;
      const distSq = dxLocal * dxLocal + dy * dy + dzLocal * dzLocal;
      if (distSq >= radius * radius) continue;

      const horizDistSq = dxLocal * dxLocal + dzLocal * dzLocal;
      if (horizDistSq > 1e-6) {
        const dist = Math.sqrt(horizDistSq);
        const push = (radius - dist) / dist;
        const pushWorld = localVectorToWorld2D(dxLocal * push, dzLocal * push, yaw);
        this.player.x += pushWorld.x;
        this.player.z += pushWorld.z;
      } else {
        const dir = local.x >= 0 ? 1 : -1;
        const pushWorld = localVectorToWorld2D(dir * (radius + Math.max(0.05, half.x)), 0, yaw);
        this.player.x += pushWorld.x;
        this.player.z += pushWorld.z;
      }
      this.playerVel.x = 0;
      this.playerVel.z = 0;
    }
  }

  _checkEntityInteractions() {
    for (const key of this.keysEntities) {
      if (key.collected) continue;
      if (this.player.distanceTo(key.mesh.position) < 1.1) {
        key.collected = true;
        this.collectedKeys.add(key.data.key_id);
        this.scene.remove(key.mesh);
        for (const lock of this.locks) {
          if (lock.data.key_id === key.data.key_id) {
            this._setLockVisualState(lock, false);
          }
        }
      }
    }

    for (const checkpoint of this.checkpoints) {
      if (this.player.distanceTo(checkpoint.mesh.position) < 1.0) {
        this.respawn.copy(checkpoint.mesh.position).add(new THREE.Vector3(0, 2, 0));
      }
    }

    for (const enemy of this.enemies) {
      if (this.player.distanceTo(enemy.mesh.position) < 1.1) {
        this._respawn();
      }
    }

    for (const sweeper of this.sweepers) {
      if (this._playerHitsSweeper(sweeper)) {
        this._respawn();
        break;
      }
    }

    for (const bumper of this.bumpers) {
      this._checkBumperInteraction(bumper);
    }

    if (this.goal && this.player.distanceTo(this.goal.pos) < 1.4) {
      this.goalReached = true;
    }
  }

  _playerHitsSweeper(entry) {
    const sweeper = entry.data;
    const center = sweeper.pos || { x: 0, y: 0, z: 0 };
    const vertical = Math.abs(this.player.y - Number(center.y || 0));
    if (vertical > PLAYER_RADIUS * 0.82) return false;

    const currentAngle = Number.isFinite(entry.angle) ? entry.angle : sweeperWorldAngle(sweeper, this.clock.elapsedTime);
    const previousAngle = Number.isFinite(entry.prevAngle) ? entry.prevAngle : currentAngle;
    const delta = Math.atan2(Math.sin(currentAngle - previousAngle), Math.cos(currentAngle - previousAngle));
    const samples = Math.max(1, Math.ceil(Math.abs(delta) / (Math.PI / 18)));
    for (let i = 0; i <= samples; i += 1) {
      const angle = previousAngle + delta * (i / samples);
      if (this._playerHitsSweeperAtAngle(sweeper, angle)) return true;
    }
    return false;
  }

  _playerHitsSweeperAtAngle(sweeper, angle) {
    const center = sweeper.pos || { x: 0, y: 0, z: 0 };
    const half = Number(sweeper.barLength || sweeper.radius * 2 || 9.0) * 0.5;
    const width = Number(sweeper.barWidth || 0.38) * 0.5 + PLAYER_RADIUS * 0.38;
    const ax = Number(center.x || 0) - Math.cos(angle) * half;
    const az = Number(center.z || 0) - Math.sin(angle) * half;
    const bx = Number(center.x || 0) + Math.cos(angle) * half;
    const bz = Number(center.z || 0) + Math.sin(angle) * half;
    const dist = pointSegmentDistance2D(this.player.x, this.player.z, ax, az, bx, bz);
    return dist <= width;
  }

  _checkBumperInteraction(entry) {
    if (entry.cooldown > 0) return;
    const bumper = entry.data;
    const pos = bumper.pos || { x: 0, y: 0, z: 0 };
    const radius = Number(bumper.radius || 1.25) + PLAYER_RADIUS * 0.45;
    const dx = this.player.x - Number(pos.x || 0);
    const dz = this.player.z - Number(pos.z || 0);
    const distSq = dx * dx + dz * dz;
    if (distSq > radius * radius) return;
    const dist = Math.max(0.001, Math.sqrt(distSq));
    const strength = Number(bumper.knockback || 10.0);
    this.playerVel.x = (dx / dist) * strength;
    this.playerVel.z = (dz / dist) * strength;
    this.playerVel.y = Math.max(this.playerVel.y, Number(bumper.lift || 4.2));
    this.player.x += (dx / dist) * 0.35;
    this.player.z += (dz / dist) * 0.35;
    entry.cooldown = 0.5;
  }

  _respawn() {
    this.player.copy(this.respawn);
    this.playerVel.set(0, 0, 0);
  }

  _updateCamera() {
    if (this.viewMode === "god") {
      const direction = new THREE.Vector3(
        Math.cos(this.pitch) * Math.cos(this.yaw),
        Math.sin(this.pitch),
        Math.cos(this.pitch) * Math.sin(this.yaw)
      ).normalize();
      this.camera.position.copy(this.godPosition);
      this.camera.lookAt(this.godPosition.clone().add(direction));
      return;
    }

    const target = this.player.clone();
    target.y += this.cameraTargetYOffset;
    const direction = new THREE.Vector3(
      Math.cos(this.pitch) * Math.cos(this.yaw),
      Math.sin(this.pitch),
      Math.cos(this.pitch) * Math.sin(this.yaw)
    );
    const desired = target.clone().sub(direction.multiplyScalar(this.cameraDistance));
    this.camera.position.lerp(desired, 0.15);
    this.camera.lookAt(target);
  }

  _updateStatus() {
    if (!this.statusSink) return;
    this.statusSink({
      keys: Array.from(this.collectedKeys),
      locks: this.locks.map((lock) => ({ id: lock.data.lock_id, locked: lock.data.locked })),
      goalReached: this.goalReached,
      position: { x: this.player.x, y: this.player.y, z: this.player.z },
      viewMode: this.viewMode,
    });
  }

  getViewMode() {
    return this.viewMode;
  }

  setViewMode(mode) {
    const next = mode === "god" ? "god" : "player";
    if (next === this.viewMode) return this.viewMode;

    if (next === "god") {
      this.godPosition.copy(this.camera.position);
    }
    this.viewMode = next;
    this.pitch = this._clampPitch(this.pitch);
    return this.viewMode;
  }

  setShowcaseCamera(position, target) {
    const pos = new THREE.Vector3(Number(position?.x || 0), Number(position?.y || 28), Number(position?.z || 32));
    const tgt = new THREE.Vector3(Number(target?.x || 0), Number(target?.y || 0), Number(target?.z || 0));
    const dir = tgt.clone().sub(pos).normalize();
    this.viewMode = "god";
    this.godPosition.copy(pos);
    this.yaw = Math.atan2(dir.z, dir.x);
    this.pitch = Math.asin(clamp(dir.y, -0.98, 0.98));
    this.pitch = this._clampPitch(this.pitch);
    this.camera.position.copy(pos);
    this.camera.lookAt(tgt);
    return this.viewMode;
  }

  setThirdPersonCamera(options = {}) {
    const distance = Number(options.distance);
    const pitch = Number(options.pitch);
    const yaw = Number(options.yaw);
    if (Number.isFinite(distance)) {
      this.cameraDistance = clamp(distance, 6, 32);
    }
    const targetYOffset = Number(options.targetYOffset);
    if (Number.isFinite(targetYOffset)) {
      this.cameraTargetYOffset = clamp(targetYOffset, -1, 4);
    }
    if (Number.isFinite(pitch)) {
      this.pitch = this._clampPitch(pitch);
    }
    if (Number.isFinite(yaw)) {
      this.yaw = yaw;
    }
    this.viewMode = "player";
    return {
      distance: this.cameraDistance,
      pitch: this.pitch,
      yaw: this.yaw,
    };
  }

  respawnPlayer() {
    if (!this.player) return;
    this._respawn();
  }

  toggleViewMode() {
    return this.setViewMode(this.viewMode === "god" ? "player" : "god");
  }

  setVisualTheme(themeId) {
    this.visualConfig.themeId = themeId;
    this.postfx.setTheme(resolveThemeDescriptor(this.visualConfig.themeId));
    this.reloadVisuals(this.level);
  }

  setVisualOptions(options = {}) {
    if (options.themeId) this.visualConfig.themeId = options.themeId;
    if (options.quality) this.visualConfig.quality = options.quality;
    if (typeof options.postfx === "boolean") this.visualConfig.postfx = options.postfx;
    if (typeof options.debug === "boolean") this.visualConfig.debug = options.debug;

    this.postfx.setTheme(resolveThemeDescriptor(this.visualConfig.themeId));
    this.postfx.setQuality(this.visualConfig.quality);
    this.postfx.setEnabled(this.visualConfig.postfx);
  }

  reloadVisuals(level = this.level) {
    if (!level) return;
    const runtime = this._captureRuntimeState();
    const wasRunning = Boolean(this._animation);
    this.stop();
    this.loadLevel(level);
    this._restoreRuntimeState(runtime);
    if (wasRunning) this.start();
  }

  _captureRuntimeState() {
    if (!this.level || !this.player) return null;
    return {
      player: this.player.clone(),
      playerVel: this.playerVel.clone(),
      onGround: this.onGround,
      respawn: this.respawn.clone(),
      viewMode: this.viewMode,
      godPosition: this.godPosition.clone(),
      collectedKeys: new Set(this.collectedKeys),
      goalReached: this.goalReached,
      keyCollected: new Map(this.keysEntities.map((entry) => [entry.data.id, Boolean(entry.collected)])),
      lockStates: new Map(this.locks.map((entry) => [entry.data.id, entry.data.locked !== false])),
      enemyDir: new Map(this.enemies.map((entry) => [entry.data.id, entry.dir])),
    };
  }

  _restoreRuntimeState(runtime) {
    if (!runtime || !this.player) return;
    this.player.copy(runtime.player);
    this.playerVel.copy(runtime.playerVel);
    this.onGround = runtime.onGround;
    this.respawn.copy(runtime.respawn);
    this.viewMode = runtime.viewMode === "god" ? "god" : "player";
    this.pitch = this._clampPitch(this.pitch);
    if (runtime.godPosition) this.godPosition.copy(runtime.godPosition);
    this.collectedKeys = new Set(runtime.collectedKeys);
    this.goalReached = runtime.goalReached;
    this.playerMesh.position.copy(this.player);

    for (const entry of this.enemies) {
      if (runtime.enemyDir.has(entry.data.id)) entry.dir = runtime.enemyDir.get(entry.data.id);
    }

    for (const lock of this.locks) {
      if (!runtime.lockStates.has(lock.data.id)) continue;
      const isLocked = runtime.lockStates.get(lock.data.id);
      this._setLockVisualState(lock, isLocked);
    }

    for (const key of this.keysEntities) {
      const collected = runtime.keyCollected.get(key.data.id);
      key.collected = Boolean(collected);
      if (key.collected) this.scene.remove(key.mesh);
    }
  }

  _setLockVisualState(lockEntry, isLocked) {
    if (!lockEntry) return;
    lockEntry.data.locked = Boolean(isLocked);
    if (lockEntry.visual?.setLocked) {
      lockEntry.visual.setLocked(lockEntry.data.locked);
    } else if (lockEntry.mesh?.material?.color) {
      lockEntry.mesh.material.color.setHex(lockEntry.data.locked ? 0x5f6a72 : 0x95a5a6);
    }
    if (lockEntry.mesh) {
      lockEntry.mesh.visible = lockEntry.data.locked;
    }
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function lerpAngle(from, to, t) {
  const delta = Math.atan2(Math.sin(to - from), Math.cos(to - from));
  return from + delta * t;
}

function sweeperAngle(sweeper, t) {
  const period = Math.max(0.001, Number(sweeper.period || 4.0));
  const direction = Number(sweeper.direction || 1) >= 0 ? 1 : -1;
  const phase = Number(sweeper.phase || 0);
  return direction * ((2 * Math.PI * t) / period) + phase;
}

function sweeperWorldAngle(sweeper, t) {
  return Number(sweeper.yaw || sweeper.rotation_y || 0) + sweeperAngle(sweeper, t);
}

function timedGateState(gate, t) {
  const period = Math.max(0.001, Number(gate.period || 5.0));
  const openDuration = Math.max(0, Math.min(period, Number(gate.openDuration || period * 0.45)));
  const phase = Number(gate.phase || 0);
  const local = ((t + phase) % period + period) % period;
  const open = local < openDuration;
  const edge = Math.min(local, Math.max(0, openDuration - local));
  const openPhase = open ? clamp(edge / 0.35, 0, 1) : 0;
  return { open, openPhase, local };
}

function worldToLocal2D(x, z, originX, originZ, yaw) {
  const dx = x - Number(originX || 0);
  const dz = z - Number(originZ || 0);
  const c = Math.cos(yaw);
  const s = Math.sin(yaw);
  return {
    x: c * dx + s * dz,
    z: -s * dx + c * dz,
  };
}

function localVectorToWorld2D(x, z, yaw) {
  const c = Math.cos(yaw);
  const s = Math.sin(yaw);
  return {
    x: c * x - s * z,
    z: s * x + c * z,
  };
}

function pointSegmentDistance2D(px, pz, ax, az, bx, bz) {
  const vx = bx - ax;
  const vz = bz - az;
  const wx = px - ax;
  const wz = pz - az;
  const lenSq = vx * vx + vz * vz;
  if (lenSq <= 1e-8) return Math.hypot(px - ax, pz - az);
  const t = clamp((wx * vx + wz * vz) / lenSq, 0, 1);
  const cx = ax + vx * t;
  const cz = az + vz * t;
  return Math.hypot(px - cx, pz - cz);
}

function shouldPreventScroll(event, isFocused) {
  const tag = (event.target && event.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || event.target?.isContentEditable) return false;
  const codes = new Set(["Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);
  if (!codes.has(event.code)) return false;
  return isFocused || document.pointerLockElement !== null;
}
