// 功能说明：复刻 platform 默认场地、滚动网格、障碍与虚线轨迹，并统一转换到 ROS 世界坐标。
import * as THREE from "three";
import { createPlatformRobot } from "./platformRobot";
import { buildItems } from "./platformObstacles";
import { visual } from "../../platform/ui";

/** 所有演示物体置于同一根节点；真实数据接管后整体隐藏，机器狗独立保留。 */
export function createPlatformArena(scene: THREE.Scene) {
  const conversion = new THREE.Matrix4().set(
    0,
    0,
    -1,
    0,
    -1,
    0,
    0,
    0,
    0,
    1,
    0,
    0,
    0,
    0,
    0,
    1,
  );
  const basis = new THREE.Quaternion().setFromRotationMatrix(conversion);
  const arena = new THREE.Group();
  arena.quaternion.copy(basis);
  scene.add(arena);
  const robot = createPlatformRobot(),
    robotBasis = new THREE.Group();
  robotBasis.quaternion.copy(basis);
  robotBasis.add(robot.root);
  scene.add(robotBasis);
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#e8e4da";
  ctx.fillRect(0, 0, 128, 128);
  ctx.strokeStyle = "rgba(97,94,84,.13)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0.5, 0);
  ctx.lineTo(0.5, 128);
  ctx.moveTo(0, 0.5);
  ctx.lineTo(128, 0.5);
  ctx.stroke();
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(140, 140);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  const groundMaterial = new THREE.MeshStandardMaterial({
    map: texture,
    roughness: 1,
  });
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(140, 140),
    groundMaterial,
  );
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  arena.add(ground);
  const yaw = 2.356,
    back = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw)),
    side = new THREE.Vector3(back.z, 0, -back.x);
  const items = buildItems();
  const obstacles = items.map((it) => {
    const column = it.shape === "column",
      strip = it.shape === "strip";
    const m = new THREE.Mesh(
      column
        ? new THREE.CylinderGeometry(it.w, it.w, it.h, 8)
        : new THREE.BoxGeometry(it.w, it.h, it.d),
      new THREE.MeshStandardMaterial({
        color: it.color,
        roughness: 0.95,
        flatShading: column,
        transparent: strip,
        opacity: strip ? 0.55 : 1,
      }),
    );
    m.rotation.set(it.shape === "ramp" ? 0.22 : 0, it.ry, 0);
    m.castShadow = m.receiveShadow = !strip;
    arena.add(m);
    return m;
  });
  const trails = Array.from({ length: 12 }, (_, i) => {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(0.05, 0.2),
      new THREE.MeshBasicMaterial({
        color: "#fdfcf8",
        transparent: true,
        depthWrite: false,
        opacity: 0.42 * (1 - i / 15) + 0.06,
      }),
    );
    m.rotation.set(-Math.PI / 2, 0, Math.atan2(back.x, back.z));
    m.renderOrder = 1;
    arena.add(m);
    return m;
  });
  const realTrailGeometry = new THREE.BufferGeometry(),
    realTrailMaterial = new THREE.LineDashedMaterial({
      color: "#7e9271",
      dashSize: 0.18,
      gapSize: 0.12,
    });
  const realTrail = new THREE.Line(realTrailGeometry, realTrailMaterial);
  // 固定容量并更新绘制范围，避免 setFromPoints 无法扩容已有 GPU 缓冲区。
  const trailCapacity = 3000;
  const trailPositions = new THREE.BufferAttribute(
    new Float32Array(trailCapacity * 3),
    3,
  ).setUsage(THREE.DynamicDrawUsage);
  const trailDistances = new THREE.BufferAttribute(
    new Float32Array(trailCapacity),
    1,
  ).setUsage(THREE.DynamicDrawUsage);
  realTrailGeometry.setAttribute("position", trailPositions);
  realTrailGeometry.setAttribute("lineDistance", trailDistances);
  realTrailGeometry.setDrawRange(0, 0);
  realTrail.frustumCulled = false;
  scene.add(realTrail);
  const trailPoints: THREE.Vector3[] = [];
  let time = 0,
    flow = 0,
    demoOpacity = 1,
    fade = 1,
    wasDemo = true,
    hasDisplayPose = false,
    lastPosition: THREE.Vector3 | null = null,
    lastPoseAt = 0,
    speed = 0;
  const lightRig = new THREE.Group();
  scene.add(lightRig);
  const hemi = new THREE.HemisphereLight("#fdfbf5", "#d8d2c2", 0.55);
  hemi.position.set(0, 0, 1);
  lightRig.add(hemi, new THREE.AmbientLight("#fff6e8", 0.45));
  const sun = new THREE.DirectionalLight("#fff2dd", 1.5);
  sun.position.set(-5, 7, 11);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {
    left: -16,
    right: 16,
    top: 16,
    bottom: -16,
    near: 1,
    far: 40,
  });
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  lightRig.add(sun);

  const demoMaterials = new Map<
    THREE.Material,
    { opacity: number; transparent: boolean }
  >();
  arena.traverse((object) => {
    const material = (object as THREE.Mesh).material;
    const materials = Array.isArray(material) ? material : [material];
    materials.forEach((item) => {
      if (item) {
        demoMaterials.set(item, {
          opacity: item.opacity,
          transparent: item.transparent,
        });
      }
    });
  });

  return {
    arena,
    robotBasis,
    /** 只淡出演示场地，机器狗独立保留，用于地图加载时保持视觉锚点。 */
    setDemoOpacity(opacity: number) {
      demoOpacity = THREE.MathUtils.clamp(opacity, 0, 1);
      demoMaterials.forEach((state, material) => {
        material.opacity = state.opacity * demoOpacity;
        material.transparent = state.transparent || demoOpacity < 1;
        material.needsUpdate = true;
      });
    },
    /** 返回机器狗当前显示位置，供相机/controls 在过渡期平滑跟随。 */
    getRobotPosition() {
      return robotBasis.position.clone();
    },
    update(
      dt: number,
      demo: boolean,
      connected: boolean,
      pose: THREE.Matrix4 | null,
    ) {
      dt = Math.min(dt, 0.05);
      time += dt;
      arena.visible = demo || demoOpacity > 0.001;
      sun.castShadow = visual.showShadows;
      if (demo) {
        robotBasis.position.set(0, 0, 0);
        robotBasis.quaternion.copy(basis);
        hasDisplayPose = true;
        robot.root.position.set(0, 0, 0);
        robot.root.rotation.set(0, yaw, 0);
        robotBasis.visible = true;
        speed =
          visual.robotAnim === "walk"
            ? 0.42
            : visual.robotAnim === "run"
              ? 1.15
              : 0;
        texture.offset.x = (texture.offset.x - back.x * speed * dt) % 1;
        texture.offset.y = (texture.offset.y + back.z * speed * dt) % 1;
        const nextMap = visual.showGrid ? texture : null;
        if (groundMaterial.map !== nextMap) {
          groundMaterial.map = nextMap;
          groundMaterial.color.set(visual.showGrid ? "#ffffff" : "#e8e4da");
          groundMaterial.needsUpdate = true;
        }
        items.forEach((it, i) => {
          it.along += speed * dt;
          if (it.along > 26) it.along -= 52;
          obstacles[i].position
            .copy(back)
            .multiplyScalar(it.along)
            .addScaledVector(side, it.lat);
          obstacles[i].position.y =
            it.h / 2 + (it.shape === "strip" ? 0.002 : 0);
        });
        flow = (flow + speed * dt) % 0.46;
        fade += ((speed > 0 ? 1 : 0) - fade) * (1 - Math.exp(-5 * dt));
        trails.forEach((m, i) => {
          const dist = 0.85 + i * 0.46 + flow,
            lateral = Math.sin(i * 1.7 + flow * 2.5) * 0.05;
          m.position.set(
            back.x * dist + back.z * lateral,
            0.012,
            back.z * dist - back.x * lateral,
          );
          m.material.opacity =
            (0.42 * (1 - i / 15) + 0.06) * fade * demoOpacity;
          m.visible = visual.showTrail;
        });
      } else if (pose) {
        const p = new THREE.Vector3(),
          q = new THREE.Quaternion(),
          s = new THREE.Vector3();
        pose.decompose(p, q, s);
        const targetQuaternion = q.clone().multiply(basis);
        const smoothing = hasDisplayPose ? 1 - Math.exp(-4.8 * dt) : 1;
        const now = performance.now();
        if (lastPosition && now - lastPoseAt > 100) {
          speed = p.distanceTo(lastPosition) / ((now - lastPoseAt) / 1000);
          lastPosition.copy(p);
          lastPoseAt = now;
        } else if (!lastPosition) {
          lastPosition = p.clone();
          lastPoseAt = now;
        }
        robotBasis.position.lerp(p, smoothing);
        robotBasis.quaternion.slerp(targetQuaternion, smoothing);
        robot.root.rotation.set(0, 0, 0);
        robot.root.position.y = -0.35;
        robotBasis.visible = true;
        hasDisplayPose = true;
        if (
          connected &&
          (!trailPoints.length ||
            trailPoints[trailPoints.length - 1].distanceTo(p) > 0.05)
        ) {
          trailPoints.push(p.clone());
          if (trailPoints.length > trailCapacity) trailPoints.shift();
          let distance = 0;
          trailPoints.forEach((point, index) => {
            if (index) distance += point.distanceTo(trailPoints[index - 1]);
            trailPositions.setXYZ(index, point.x, point.y, point.z);
            trailDistances.setX(index, distance);
          });
          trailPositions.needsUpdate = trailDistances.needsUpdate = true;
          realTrailGeometry.setDrawRange(0, trailPoints.length);
        }
      } else if (wasDemo) {
        robotBasis.visible = false;
      }
      realTrail.visible = !demo && visual.showTrail;
      robot.update(
        time,
        dt,
        demo
          ? visual.robotAnim
          : connected && speed > 0.05
            ? speed > 0.8
              ? "run"
              : "walk"
            : "idle",
        visual.showCone,
      );
      wasDemo = demo;
    },
    reset() {
      trailPoints.length = 0;
      realTrailGeometry.setDrawRange(0, 0);
      lastPosition = null;
      speed = 0;
    },
    dispose() {
      for (const group of [arena, robotBasis, lightRig, realTrail]) {
        scene.remove(group);
        group.traverse((o) => {
          const m = o as THREE.Mesh;
          m.geometry?.dispose();
          const materials = Array.isArray(m.material)
            ? m.material
            : [m.material];
          materials.forEach((mat) => mat?.dispose());
        });
      }
      texture.dispose();
    },
  };
}
