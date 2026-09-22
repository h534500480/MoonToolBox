// 功能说明：为离线占据体素提供可撤销的暮光材质、定向软阴影和冷色补光。
import * as THREE from "three";
import { attachVoxelGrowthToStandardMaterial } from "./voxelGrowth";

const SHADOW_SIZE = 2048;

/** 根据世界坐标生成稳定的用户主色变体；裁剪重新排列实例时颜色保持不变。 */
export function voxelSurfaceColor(
  x: number,
  y: number,
  z: number,
  size: number,
  baseColor: THREE.Color,
  targetColor: THREE.Color,
) {
  const seed =
    Math.sin(
      Math.floor(x / size) * 12.9898 +
        Math.floor(y / size) * 78.233 +
        Math.floor(z / size) * 37.719,
    ) * 43758.5453;
  const variation = seed - Math.floor(seed);
  const baseHsl = { h: 0, s: 0, l: 0 };
  baseColor.getHSL(baseHsl);
  return targetColor.setHSL(
    baseHsl.h,
    Math.min(1, Math.max(0, baseHsl.s * (0.84 + variation * 0.2))),
    Math.min(0.82, Math.max(0.12, baseHsl.l * (0.82 + variation * 0.3))),
  );
}

/** 基于现有体素包围盒布光，不添加推测地面；返回恢复和资源释放入口，切换模式时必须调用。 */
export function createOfflineVoxelRender(
  scene: THREE.Scene,
  renderer: THREE.WebGLRenderer,
  mesh: THREE.InstancedMesh,
) {
  const original = {
    material: mesh.material,
    background: scene.background,
    toneMapping: renderer.toneMapping,
    exposure: renderer.toneMappingExposure,
    shadowEnabled: renderer.shadowMap.enabled,
    shadowType: renderer.shadowMap.type,
    shadowAutoUpdate: renderer.shadowMap.autoUpdate,
    castShadow: mesh.castShadow,
    receiveShadow: mesh.receiveShadow,
  };
  const existingLights: {
    light: THREE.Light;
    visible: boolean;
    intensity: number;
  }[] = [];
  // 平台灯光位于组内，必须遍历整棵场景树，避免两套照明叠加。
  scene.traverse((object) => {
    if (object instanceof THREE.Light) {
      existingLights.push({
        light: object,
        visible: object.visible,
        intensity: object.intensity,
      });
    }
  });

  const material = new THREE.MeshStandardMaterial({
    color: "#ffffff",
    roughness: 0.62,
    metalness: 0.12,
    // 实例颜色由 Three.js 自动启用；没有顶点颜色属性时启用它会将底色乘黑。
    vertexColors: mesh.geometry.hasAttribute("color"),
  });
  attachVoxelGrowthToStandardMaterial(material);
  mesh.material = material;
  let materialRestored = false;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  const startBackground =
    original.background instanceof THREE.Color
      ? original.background.clone()
      : new THREE.Color("#e8e4da");
  const targetBackground = new THREE.Color("#141e20");
  const startExposure = renderer.toneMappingExposure;
  const targetExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  // 地图静止时复用阴影贴图；仅加载、裁剪或上下文恢复时重新生成。
  renderer.shadowMap.autoUpdate = false;

  const sky = new THREE.HemisphereLight("#a0bbc2", "#333d36", 1.45);
  sky.position.set(0, 0, 1);
  const sun = new THREE.DirectionalLight("#ffdb9b", 3.6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(SHADOW_SIZE, SHADOW_SIZE);
  sun.shadow.camera.up.set(0, 0, 1);
  sun.shadow.bias = -0.00015;
  sun.shadow.radius = 2;
  const fill = new THREE.DirectionalLight("#87b8c5", 0.65);
  const rig = new THREE.Group();
  rig.name = "offline-voxel-twilight-lighting";
  rig.add(sky, sun, sun.target, fill, fill.target);
  scene.add(rig);
  const targetIntensities = {
    sky: sky.intensity,
    sun: sun.intensity,
    fill: fill.intensity,
  };
  sky.intensity = 0;
  sun.intensity = 0;
  fill.intensity = 0;

  /** 渲染模式进入时渐变背景和灯光，避免从平台场景硬切到暮光场景。 */
  function setTransitionProgress(progress: number) {
    const amount = THREE.MathUtils.clamp(progress, 0, 1);
    scene.background = startBackground.clone().lerp(targetBackground, amount);
    renderer.toneMappingExposure = THREE.MathUtils.lerp(
      startExposure,
      targetExposure,
      amount,
    );
    renderer.toneMapping =
      amount >= 1 ? THREE.ACESFilmicToneMapping : original.toneMapping;
    existingLights.forEach(({ light, visible, intensity }) => {
      light.visible = visible && amount < 1;
      light.intensity = intensity * (1 - amount);
    });
    sky.intensity = targetIntensities.sky * amount;
    sun.intensity = targetIntensities.sun * amount;
    fill.intensity = targetIntensities.fill * amount;
    renderer.shadowMap.needsUpdate = true;
  }

  /** 根据裁剪后真实几何收紧阴影相机，以提高当前可见区域的阴影精度。 */
  function update() {
    renderer.shadowMap.needsUpdate = true;
    if (mesh.count === 0) {
      return;
    }
    mesh.computeBoundingBox();
    mesh.computeBoundingSphere();
    const bounds = mesh.boundingBox!.clone().applyMatrix4(mesh.matrixWorld);
    const center = bounds.getCenter(new THREE.Vector3());
    const radius = Math.max(
      bounds.getSize(new THREE.Vector3()).length() * 0.5,
      1,
    );
    sun.position
      .copy(center)
      .add(
        new THREE.Vector3(-1.1, -0.7, 0.85)
          .normalize()
          .multiplyScalar(radius * 3),
      );
    sun.target.position.copy(center);
    fill.position.copy(center).add(new THREE.Vector3(radius, radius, radius));
    fill.target.position.copy(center);
    const camera = sun.shadow.camera;
    camera.left = camera.bottom = -radius * 1.05;
    camera.right = camera.top = radius * 1.05;
    camera.near = radius * 0.1;
    camera.far = radius * 5;
    camera.updateProjectionMatrix();
    sun.shadow.normalBias = Math.min(radius / SHADOW_SIZE, 0.035);
    renderer.shadowMap.needsUpdate = true;
  }

  /** 退出渲染模式时先恢复 mesh 材质，环境反向渐变可继续独立执行。 */
  function restoreMeshMaterial() {
    if (materialRestored) {
      return;
    }
    materialRestored = true;
    if (mesh.material === material) {
      mesh.material = original.material;
    }
    material.dispose();
  }

  function dispose(options: { restoreMaterial?: boolean } = {}) {
    const restoreMaterial = options.restoreMaterial ?? true;
    if (restoreMaterial) {
      restoreMeshMaterial();
    } else {
      if (!materialRestored) {
        material.dispose();
      }
      if (Array.isArray(original.material)) {
        original.material.forEach((item) => item.dispose());
      } else {
        original.material.dispose();
      }
    }
    mesh.castShadow = original.castShadow;
    mesh.receiveShadow = original.receiveShadow;
    scene.remove(rig);
    sun.shadow.dispose();
    existingLights.forEach(({ light, visible, intensity }) => {
      light.visible = visible;
      light.intensity = intensity;
    });
    scene.background = original.background;
    renderer.toneMapping = original.toneMapping;
    renderer.toneMappingExposure = original.exposure;
    renderer.shadowMap.enabled = original.shadowEnabled;
    renderer.shadowMap.type = original.shadowType;
    renderer.shadowMap.autoUpdate = original.shadowAutoUpdate;
    renderer.shadowMap.needsUpdate = true;
  }

  setTransitionProgress(0);
  update();
  return { update, dispose, setTransitionProgress, restoreMeshMaterial };
}
