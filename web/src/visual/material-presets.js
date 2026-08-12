import * as THREE from "../../vendor/three.module.js";

const textureCache = new Map();

export function createMaterialLibrary(theme, quality = "medium") {
  const palette = {
    brickBase: new THREE.Color(0xc86e2f),
    brickEdge: new THREE.Color(0x9f4a1c),
    grassTop: new THREE.Color(0x4cb34f),
    grassDark: new THREE.Color(0x2d7e36),
    moving: new THREE.Color(0xf4b43c),
    enemyBody: new THREE.Color(0x8b4d2f),
    enemyFace: new THREE.Color(0xf2d4a8),
    playerHat: new THREE.Color(0xe63a2f),
    playerOveralls: new THREE.Color(0x2f63d8),
    playerSkin: new THREE.Color(0xf5cb9c),
    keyGold: new THREE.Color(0xf7cc2d),
    lockClosed: new THREE.Color(0x694087),
    lockOpen: new THREE.Color(0x95a5a6),
    checkpoint: new THREE.Color(0x1abc9c),
    goal: new THREE.Color(0x27ae60),
    ground: new THREE.Color(0x8f6b43),
    fgPink: new THREE.Color(0xff4eb0),
    fgCyan: new THREE.Color(0x12c7d9),
    fgPurple: new THREE.Color(0x7b4dff),
    fgYellow: new THREE.Color(0xffd43b),
    fgMint: new THREE.Color(0x64e6a5),
    fgBlue: new THREE.Color(0x1b84ff),
    fgFoam: new THREE.Color(0xf7fbff),
  };

  const roughnessScale = quality === "high" ? 0.85 : quality === "medium" ? 0.9 : 0.96;

  const brickTexture = getPatternTexture("brick");
  const grassTexture = getPatternTexture("grass");
  const pipeTexture = getPatternTexture("pipe");
  const groundTexture = getPatternTexture("ground");

  return {
    platform(tags = [], kind = "static") {
      if (theme.id === "obstacle_course") {
        let color = palette.fgCyan;
        if (tags.includes("start")) color = palette.fgMint;
        if (tags.includes("runway")) color = palette.fgBlue;
        if (tags.includes("sweeper_zone")) color = palette.fgPurple;
        if (tags.includes("gate_zone")) color = palette.fgPink;
        if (tags.includes("fast_lane")) color = palette.fgYellow;
        if (tags.includes("safe_lane")) color = palette.fgCyan;
        if (tags.includes("finish")) color = palette.fgFoam;
        if (kind === "moving") color = palette.fgYellow;
        return new THREE.MeshStandardMaterial({
          color,
          roughness: 0.48 * roughnessScale,
          metalness: 0.03,
          map: getPatternTexture("obstacle_pad"),
        });
      }
      if (kind === "moving") {
        return new THREE.MeshStandardMaterial({
          color: palette.moving,
          roughness: 0.42 * roughnessScale,
          metalness: 0.05,
          map: pipeTexture,
        });
      }
      if (tags.includes("Lock") || tags.includes("lock_gate")) {
        return new THREE.MeshStandardMaterial({
          color: palette.lockClosed,
          roughness: 0.52 * roughnessScale,
          metalness: 0.12,
          map: brickTexture,
        });
      }
      if (tags.includes("Enemy") || tags.includes("Jump") || tags.includes("Drop")) {
        return new THREE.MeshStandardMaterial({
          color: palette.brickBase,
          roughness: 0.74 * roughnessScale,
          metalness: 0.02,
          map: brickTexture,
        });
      }
      return new THREE.MeshStandardMaterial({
        color: palette.grassTop,
        roughness: 0.8 * roughnessScale,
        metalness: 0,
        map: grassTexture,
      });
    },
    ground: new THREE.MeshStandardMaterial({
      color: palette.ground,
      roughness: 0.95,
      metalness: 0,
      map: groundTexture,
    }),
    enemyBody: new THREE.MeshStandardMaterial({ color: palette.enemyBody, roughness: 0.75, metalness: 0.02 }),
    enemyFace: new THREE.MeshStandardMaterial({ color: palette.enemyFace, roughness: 0.84, metalness: 0 }),
    enemyFeet: new THREE.MeshStandardMaterial({ color: 0x5b3218, roughness: 0.72, metalness: 0.02 }),
    playerHat: new THREE.MeshStandardMaterial({ color: palette.playerHat, roughness: 0.62, metalness: 0.05 }),
    playerOveralls: new THREE.MeshStandardMaterial({ color: palette.playerOveralls, roughness: 0.6, metalness: 0.04 }),
    playerSkin: new THREE.MeshStandardMaterial({ color: palette.playerSkin, roughness: 0.84, metalness: 0 }),
    playerHair: new THREE.MeshStandardMaterial({ color: 0x5f3a2a, roughness: 0.75, metalness: 0 }),
    key: new THREE.MeshStandardMaterial({ color: palette.keyGold, roughness: 0.3, metalness: 0.55, emissive: 0x8a6f10, emissiveIntensity: 0.15 }),
    lockClosed: new THREE.MeshStandardMaterial({ color: palette.lockClosed, roughness: 0.45, metalness: 0.42 }),
    lockOpen: new THREE.MeshStandardMaterial({ color: palette.lockOpen, roughness: 0.68, metalness: 0.2 }),
    checkpointPole: new THREE.MeshStandardMaterial({ color: 0xf3efe6, roughness: 0.45, metalness: 0.28 }),
    checkpointFlag: new THREE.MeshStandardMaterial({ color: palette.checkpoint, roughness: 0.65, metalness: 0.05 }),
    goalPole: new THREE.MeshStandardMaterial({ color: 0xe9e9e9, roughness: 0.34, metalness: 0.48 }),
    goalFlag: new THREE.MeshStandardMaterial({ color: palette.goal, roughness: 0.64, metalness: 0.02 }),
    goalOrb: new THREE.MeshStandardMaterial({ color: 0xfff1b7, roughness: 0.2, metalness: 0.45, emissive: 0xf1c40f, emissiveIntensity: 0.3 }),
    fgRail: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.38, metalness: 0.04 }),
    fgRailStripe: new THREE.MeshStandardMaterial({ color: 0xff4eb0, roughness: 0.42, metalness: 0.04 }),
    fgSweeperHub: new THREE.MeshStandardMaterial({ color: 0xffd43b, roughness: 0.35, metalness: 0.08 }),
    fgSweeperBar: new THREE.MeshStandardMaterial({ color: 0xff4eb0, roughness: 0.42, metalness: 0.06 }),
    fgSweeperTip: new THREE.MeshStandardMaterial({ color: 0x12c7d9, roughness: 0.45, metalness: 0.04 }),
    fgGateFrame: new THREE.MeshStandardMaterial({ color: 0x7b4dff, roughness: 0.36, metalness: 0.12 }),
    fgGatePanelClosed: new THREE.MeshStandardMaterial({ color: 0xff4eb0, roughness: 0.40, metalness: 0.08 }),
    fgGatePanelOpen: new THREE.MeshStandardMaterial({ color: 0x64e6a5, roughness: 0.44, metalness: 0.04 }),
    fgFinishStripeDark: new THREE.MeshStandardMaterial({ color: 0x1a1a24, roughness: 0.62, metalness: 0.0 }),
    fgFinishStripeLight: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.58, metalness: 0.0 }),
    skyTop: theme.palette?.skyTop ?? 0x79c9ff,
    skyBottom: theme.palette?.skyBottom ?? 0xd7f2ff,
    fog: theme.palette?.fog ?? 0xb8e5ff,
  };
}

function getPatternTexture(type) {
  if (textureCache.has(type)) return textureCache.get(type);
  const texture = buildPattern(type);
  textureCache.set(type, texture);
  return texture;
}

function buildPattern(type) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");

  if (!ctx) {
    const tex = new THREE.Texture();
    tex.needsUpdate = true;
    return tex;
  }

  if (type === "brick") {
    ctx.fillStyle = "#c56d2f";
    ctx.fillRect(0, 0, 128, 128);
    ctx.strokeStyle = "#9a4a1d";
    ctx.lineWidth = 3;
    for (let y = 0; y <= 128; y += 24) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(128, y);
      ctx.stroke();
    }
    for (let y = 0; y < 128; y += 24) {
      const offset = (Math.floor(y / 24) % 2) * 16;
      for (let x = offset; x <= 128; x += 32) {
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + 24);
        ctx.stroke();
      }
    }
  } else if (type === "grass") {
    ctx.fillStyle = "#3ea542";
    ctx.fillRect(0, 0, 128, 128);
    ctx.fillStyle = "#2f7f32";
    for (let y = 6; y < 128; y += 10) {
      for (let x = (y % 20) * 2; x < 128; x += 18) {
        ctx.fillRect(x, y, 3, 6);
      }
    }
  } else if (type === "pipe") {
    const g = ctx.createLinearGradient(0, 0, 128, 0);
    g.addColorStop(0, "#3aa73f");
    g.addColorStop(0.5, "#67ce6f");
    g.addColorStop(1, "#2b8530");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    ctx.fillStyle = "rgba(255,255,255,0.15)";
    ctx.fillRect(20, 0, 10, 128);
  } else if (type === "obstacle_pad") {
    ctx.fillStyle = "#19bfe0";
    ctx.fillRect(0, 0, 128, 128);
    ctx.fillStyle = "rgba(255,255,255,0.18)";
    for (let x = -128; x < 256; x += 34) {
      ctx.beginPath();
      ctx.moveTo(x, 128);
      ctx.lineTo(x + 92, 0);
      ctx.lineTo(x + 108, 0);
      ctx.lineTo(x + 16, 128);
      ctx.closePath();
      ctx.fill();
    }
    ctx.strokeStyle = "rgba(255,255,255,0.28)";
    ctx.lineWidth = 5;
    ctx.strokeRect(6, 6, 116, 116);
  } else {
    ctx.fillStyle = "#8f6b43";
    ctx.fillRect(0, 0, 128, 128);
    ctx.fillStyle = "#755533";
    for (let y = 0; y < 128; y += 16) {
      ctx.fillRect(0, y, 128, 2);
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(2.4, 2.4);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}
