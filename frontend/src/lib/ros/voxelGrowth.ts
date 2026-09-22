// 功能说明：提供离线点云 voxel 的 GPU 生长动画材质和实例属性配置。
import * as THREE from "three";

export type VoxelGrowthMode = "voxel" | "render";

const SPREAD_SECONDS = 2.0;
const GROW_SECONDS = 0.6;
const LAYER_DELAY_SECONDS = 0.028;
const MAX_LAYER_BONUS_SECONDS = 0.4;
const JITTER_SECONDS = 0.07;
const GAP_RATIO = 0.94;

const VERTEX_SHADER = /* glsl */ `
attribute vec3 aOffset;
attribute vec3 aDims;
attribute float aDelay;
attribute vec3 aColor;

uniform float uTime;
uniform float uGrowDuration;
uniform float uVoxelSize;

varying vec3 vColor;
varying vec3 vNormal;
varying float vGlow;
varying float vProgress;

float easeOutCubic(float t) {
  float p = 1.0 - t;
  return 1.0 - p * p * p;
}

void main() {
  float rawProgress = (uTime - aDelay) / uGrowDuration;
  float clampedProgress = clamp(rawProgress, 0.0, 1.0);
  float growth = easeOutCubic(clampedProgress);

  vec3 localPosition = position * aDims;
  localPosition.z = -aDims.z * 0.5 + (position.z + 0.5) * aDims.z * growth;
  vec3 worldPosition = aOffset + localPosition;

  vColor = aColor;
  vNormal = normalize(normalMatrix * normal);
  vProgress = clampedProgress;
  vGlow = clampedProgress > 0.0 ? 1.0 - smoothstep(0.08, 0.92, clampedProgress) : 0.0;

  vec4 mvPosition = modelViewMatrix * vec4(worldPosition, 1.0);
  gl_Position = projectionMatrix * mvPosition;

  if (rawProgress <= 0.0) {
    gl_Position = vec4(0.0, 0.0, 2.0, 1.0);
  }
}
`;

const FRAGMENT_SHADER = /* glsl */ `
uniform float uFade;
uniform float uOpacity;
uniform float uMode;
uniform vec3 uLightDir;
uniform vec3 uFogColor;
uniform float uFogNear;
uniform float uFogFar;

varying vec3 vColor;
varying vec3 vNormal;
varying float vGlow;
varying float vProgress;

void main() {
  vec3 normal = normalize(vNormal);
  float topLight = normal.z * 0.5 + 0.5;
  float diffuse = max(dot(normal, normalize(uLightDir)), 0.0);
  vec3 renderColor = vColor * (0.52 + diffuse * 0.42 + topLight * 0.18);
  renderColor += vec3(1.0, 0.82, 0.48) * vGlow * 0.18;

  vec3 voxelColor = mix(vec3(0.12, 0.48, 0.72), vec3(0.42, 0.86, 0.95), topLight);
  voxelColor += vec3(1.0, 0.78, 0.45) * vGlow * 0.1;

  vec3 color = mix(voxelColor, renderColor, step(0.5, uMode));
  float alpha = uOpacity * uFade * smoothstep(0.0, 0.06, vProgress);

  gl_FragColor = vec4(color, alpha);
  #include <colorspace_fragment>
}
`;

/** 构建与目标项目一致的单位 Box 实例几何，真实尺寸通过 shader attribute 控制。 */
export function createVoxelGrowthGeometry() {
  const base = new THREE.BoxGeometry(1, 1, 1);
  const geometry = base.clone();
  base.dispose();
  return geometry;
}

/** 创建可在占据网格和渲染模式之间保持同一套生长动画的 shader 材质。 */
export function createVoxelGrowthMaterial(mode: VoxelGrowthMode) {
  const material = new THREE.ShaderMaterial({
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    transparent: true,
    depthWrite: mode === "render",
    depthTest: true,
    uniforms: {
      uTime: { value: 0 },
      uGrowDuration: { value: GROW_SECONDS },
      uVoxelSize: { value: 0.1 },
      uFade: { value: 1 },
      uOpacity: { value: mode === "render" ? 1 : 0.28 },
      uMode: { value: mode === "render" ? 1 : 0 },
      uLightDir: { value: new THREE.Vector3(-0.55, -0.35, 0.78).normalize() },
      uFogColor: { value: new THREE.Color("#e8e4da") },
      uFogNear: { value: 34 },
      uFogFar: { value: 80 },
    },
  });
  material.name = `voxel-growth-${mode}`;
  return material;
}

/** 更新材质显示模式；切换模式时复用已经写好的实例延迟和颜色。 */
export function setVoxelGrowthMaterialMode(
  material: THREE.Material | THREE.Material[],
  mode: VoxelGrowthMode,
) {
  if (Array.isArray(material) || !(material instanceof THREE.ShaderMaterial)) {
    return;
  }
  material.uniforms.uMode.value = mode === "render" ? 1 : 0;
  material.uniforms.uOpacity.value = mode === "render" ? 1 : 0.28;
  material.depthWrite = mode === "render";
  material.needsUpdate = true;
}

/** 每帧只推进 uniform，实例本身不做 CPU 级重算。 */
export function updateVoxelGrowthTime(
  material: THREE.Material | THREE.Material[],
  elapsedSeconds: number,
) {
  if (Array.isArray(material)) {
    return;
  }
  const uniforms = voxelGrowthUniforms(material);
  if (uniforms) {
    uniforms.uTime.value = elapsedSeconds;
    return;
  }
  if (!(material instanceof THREE.ShaderMaterial)) return;
  material.uniforms.uTime.value = elapsedSeconds;
}

/** 给标准材质注入同一套底部锚定生长逻辑，避免过渡结束时再切材质。 */
export function attachVoxelGrowthToStandardMaterial(
  material: THREE.MeshStandardMaterial,
) {
  const uniforms = {
    uTime: { value: 0 },
    uGrowDuration: { value: GROW_SECONDS },
    uVoxelSize: { value: 0.1 },
  };
  material.userData.voxelGrowthUniforms = uniforms;
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = uniforms.uTime;
    shader.uniforms.uGrowDuration = uniforms.uGrowDuration;
    shader.uniforms.uVoxelSize = uniforms.uVoxelSize;
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        `#include <common>
attribute float aDelay;
uniform float uTime;
uniform float uGrowDuration;
float voxelEaseOutCubic(float t) {
  float p = 1.0 - t;
  return 1.0 - p * p * p;
}`,
      )
      .replace(
        "#include <begin_vertex>",
        `#include <begin_vertex>
float voxelRawProgress = (uTime - aDelay) / uGrowDuration;
float voxelProgress = clamp(voxelRawProgress, 0.0, 1.0);
float voxelGrowth = voxelEaseOutCubic(voxelProgress);
transformed.z = -0.5 + (transformed.z + 0.5) * voxelGrowth;
if (voxelRawProgress <= 0.0) {
  transformed = vec3(1000000.0);
}`,
      );
  };
  material.needsUpdate = true;
}

/** 用水平距离和层号为当前可见 voxel 写入一次性动画属性。 */
export function configureVoxelGrowthAttributes(
  mesh: THREE.InstancedMesh,
  visibleCenters: number[],
  voxelSize: number,
  version: number,
  visualCenter?: THREE.Vector2,
) {
  const count = Math.floor(visibleCenters.length / 3);
  const offsets = new Float32Array(count * 3);
  const dims = new Float32Array(count * 3);
  const delays = new Float32Array(count);
  const colors = new Float32Array(count * 3);
  const center = visualCenter ?? visualCenterFromCenters(visibleCenters);
  const minZ = minZFromCenters(visibleCenters);
  const maxRadius = maxHorizontalRadius(visibleCenters, center);
  const random = mulberry32(0xc0ffee + version * 97);
  const color = new THREE.Color();
  let maxDelay = 0;

  for (let instance = 0; instance < count; instance += 1) {
    const offset = instance * 3;
    const x = visibleCenters[offset];
    const y = visibleCenters[offset + 1];
    const z = visibleCenters[offset + 2];
    const radius = Math.hypot(x - center.x, y - center.y);
    const radialDelay = (radius / maxRadius) * SPREAD_SECONDS;
    const layer = Math.max(0, Math.floor((z - minZ) / Math.max(voxelSize, 1e-6)));
    const delay =
      radialDelay +
      Math.min(layer * LAYER_DELAY_SECONDS, MAX_LAYER_BONUS_SECONDS) +
      random() * JITTER_SECONDS;
    maxDelay = Math.max(maxDelay, delay);

    offsets[offset] = x;
    offsets[offset + 1] = y;
    offsets[offset + 2] = z;
    dims[offset] = voxelSize * GAP_RATIO;
    dims[offset + 1] = voxelSize * GAP_RATIO;
    dims[offset + 2] = voxelSize * GAP_RATIO;
    delays[instance] = delay;

    voxelGrowthColor(x, y, z, voxelSize, color);
    colors[offset] = color.r;
    colors[offset + 1] = color.g;
    colors[offset + 2] = color.b;
  }

  mesh.geometry.setAttribute(
    "aOffset",
    new THREE.InstancedBufferAttribute(offsets, 3),
  );
  mesh.geometry.setAttribute(
    "aDims",
    new THREE.InstancedBufferAttribute(dims, 3),
  );
  mesh.geometry.setAttribute(
    "aDelay",
    new THREE.InstancedBufferAttribute(delays, 1),
  );
  mesh.geometry.setAttribute(
    "aColor",
    new THREE.InstancedBufferAttribute(colors, 3),
  );
  mesh.geometry.computeBoundingSphere();
  mesh.count = count;

  if (mesh.material instanceof THREE.ShaderMaterial) {
    mesh.material.uniforms.uVoxelSize.value = voxelSize;
    mesh.material.uniforms.uTime.value = 0;
  }
  const uniforms = voxelGrowthUniforms(mesh.material);
  if (uniforms) {
    uniforms.uVoxelSize.value = voxelSize;
    uniforms.uTime.value = 0;
  }

  return maxDelay + GROW_SECONDS;
}

function voxelGrowthUniforms(material: THREE.Material | THREE.Material[]) {
  if (Array.isArray(material)) {
    return null;
  }
  const uniforms = material.userData.voxelGrowthUniforms as
    | {
        uTime: { value: number };
        uGrowDuration: { value: number };
        uVoxelSize: { value: number };
      }
    | undefined;
  return uniforms ?? null;
}

function visualCenterFromCenters(centers: number[]) {
  const bounds = {
    minX: Number.POSITIVE_INFINITY,
    maxX: Number.NEGATIVE_INFINITY,
    minY: Number.POSITIVE_INFINITY,
    maxY: Number.NEGATIVE_INFINITY,
  };
  for (let index = 0; index < centers.length; index += 3) {
    bounds.minX = Math.min(bounds.minX, centers[index]);
    bounds.maxX = Math.max(bounds.maxX, centers[index]);
    bounds.minY = Math.min(bounds.minY, centers[index + 1]);
    bounds.maxY = Math.max(bounds.maxY, centers[index + 1]);
  }
  return new THREE.Vector2(
    (bounds.minX + bounds.maxX) * 0.5,
    (bounds.minY + bounds.maxY) * 0.5,
  );
}

function minZFromCenters(centers: number[]) {
  let minZ = Number.POSITIVE_INFINITY;
  for (let index = 2; index < centers.length; index += 3) {
    minZ = Math.min(minZ, centers[index]);
  }
  return Number.isFinite(minZ) ? minZ : 0;
}

function maxHorizontalRadius(centers: number[], center: THREE.Vector2) {
  let maxRadius = 1;
  for (let index = 0; index < centers.length; index += 3) {
    maxRadius = Math.max(
      maxRadius,
      Math.hypot(centers[index] - center.x, centers[index + 1] - center.y),
    );
  }
  return maxRadius;
}

function voxelGrowthColor(
  x: number,
  y: number,
  z: number,
  size: number,
  color: THREE.Color,
) {
  const seed =
    Math.sin(
      Math.floor(x / size) * 12.9898 +
        Math.floor(y / size) * 78.233 +
        Math.floor(z / size) * 37.719,
    ) * 43758.5453;
  const variation = seed - Math.floor(seed);
  return color.setHSL(
    0.13 + variation * 0.055,
    0.1 + variation * 0.08,
    0.58 + variation * 0.12,
  );
}

function mulberry32(seed: number) {
  return () => {
    let next = (seed += 0x6d2b79f5);
    next = Math.imul(next ^ (next >>> 15), next | 1);
    next ^= next + Math.imul(next ^ (next >>> 7), next | 61);
    return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
  };
}
