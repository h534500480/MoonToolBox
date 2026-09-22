// 功能说明：以原生 Three.js 复用 platform 的机器狗几何、步态和传感器扇形。
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

/** 模型局部坐标保持 Y 向上、前方 -Z；调用方通过父组转换到 ROS 坐标。 */
export function createPlatformRobot() {
  const root = new THREE.Group(),
    body = new THREE.Group(),
    head = new THREE.Group(),
    cone = new THREE.Group();
  root.add(body, cone);
  body.add(head);
  head.position.set(0, 0.4, -0.38);
  cone.position.y = 0.02;
  const thighs: THREE.Group[] = [],
    calves: THREE.Group[] = [];
  function mesh(
    parent: THREE.Object3D,
    geometry: THREE.BufferGeometry,
    color: string,
    position: number[],
    roughness = 0.9,
  ) {
    const m = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({ color, roughness, flatShading: true }),
    );
    m.position.set(position[0], position[1], position[2]);
    m.castShadow = true;
    m.receiveShadow = true;
    parent.add(m);
    return m;
  }
  function box(
    parent: THREE.Object3D,
    size: number[],
    position: number[],
    color: string,
    radius = 0,
  ) {
    return mesh(
      parent,
      radius
        ? new RoundedBoxGeometry(size[0], size[1], size[2], 3, radius)
        : new THREE.BoxGeometry(...(size as [number, number, number])),
      color,
      position,
    );
  }
  box(body, [0.3, 0.16, 0.62], [0, 0.36, 0], "#eeeadf", 0.045);
  box(body, [0.24, 0.035, 0.44], [0, 0.452, 0.02], "#dcd6c8", 0.015);
  mesh(
    body,
    new THREE.CylinderGeometry(0.055, 0.06, 0.05, 10),
    "#2b2e31",
    [0, 0.49, -0.12],
    0.6,
  );
  const lamp = box(body, [0.022, 0.018, 0.006], [0, 0.49, -0.178], "#d98e4a");
  (lamp.material as THREE.MeshStandardMaterial).emissive.set("#d98e4a");
  (lamp.material as THREE.MeshStandardMaterial).emissiveIntensity = 0.5;
  box(body, [0.03, 0.035, 0.06], [0, 0.44, 0.31], "#2b2e31");
  box(head, [0.22, 0.15, 0.2], [0, 0, 0], "#eeeadf", 0.04);
  box(head, [0.17, 0.08, 0.02], [0, 0, -0.105], "#2b2e31");
  box(head, [0.11, 0.018, 0.008], [0, -0.01, -0.118], "#d98e4a");
  const legs = [
    { x: 0.17, z: -0.22, phase: 0, bend: -1 },
    { x: -0.17, z: -0.22, phase: Math.PI, bend: -1 },
    { x: 0.17, z: 0.24, phase: Math.PI, bend: -1 },
    { x: -0.17, z: 0.24, phase: 0, bend: -1 },
  ];
  for (const { x, z } of legs) {
    const hip = new THREE.Group(),
      thigh = new THREE.Group(),
      calf = new THREE.Group();
    root.add(hip);
    hip.position.set(x, 0.36, z);
    hip.add(thigh);
    thigh.add(calf);
    calf.position.y = -0.23;
    thighs.push(thigh);
    calves.push(calf);
    mesh(
      hip,
      new THREE.CylinderGeometry(0.036, 0.036, 0.072, 10),
      "#3a3d41",
      [0, 0, 0],
      0.6,
    ).rotation.z = Math.PI / 2;
    box(thigh, [0.06, 0.23, 0.08], [0, -0.115, 0], "#e6e1d5");
    mesh(
      thigh,
      new THREE.CylinderGeometry(0.03, 0.03, 0.062, 10),
      "#3a3d41",
      [0, -0.23, 0],
      0.6,
    ).rotation.z = Math.PI / 2;
    box(calf, [0.042, 0.2, 0.052], [0, -0.1, 0], "#cfc9bc");
    mesh(
      calf,
      new THREE.CylinderGeometry(0.026, 0.03, 0.035, 10),
      "#2b2e31",
      [0, -0.205, 0],
      0.8,
    );
  }
  const span = 1.1,
    start = Math.PI / 2 - span / 2;
  const coneMaterials: THREE.MeshBasicMaterial[] = [];
  for (const [i, g] of [
    new THREE.CircleGeometry(2.4, 28, start, span),
    new THREE.CircleGeometry(1.4, 28, start, span),
    new THREE.RingGeometry(2.355, 2.4, 28, 1, start, span),
  ].entries()) {
    g.rotateX(-Math.PI / 2);
    const material = new THREE.MeshBasicMaterial({
      color: ["#a3b894", "#9db38e", "#8ba17e"][i],
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    coneMaterials.push(material);
    const m = new THREE.Mesh(g, material);
    m.renderOrder = 2;
    cone.add(m);
  }
  let phase = 0,
    freq = 7.2,
    amp = 0.46;
  return {
    root,
    update(
      time: number,
      dt: number,
      mode: "idle" | "walk" | "run",
      showCone: boolean,
    ) {
      const f = mode === "walk" ? 7.2 : mode === "run" ? 11.5 : 0,
        a = mode === "walk" ? 0.46 : mode === "run" ? 0.72 : 0;
      freq += (f - freq) * (1 - Math.exp(-6 * dt));
      amp += (a - amp) * (1 - Math.exp(-6 * dt));
      phase += freq * dt;
      const intensity = amp / 0.46;
      legs.forEach((leg, i) => {
        const ph = phase + leg.phase,
          stride = Math.sin(ph),
          lift = Math.max(0, stride),
          bend = leg.bend;
        thighs[i].rotation.x = bend * (0.42 + stride * amp * 0.82);
        calves[i].rotation.x =
          bend *
          (-1.05 + Math.sin(ph - 0.85) * amp * 0.7 - lift * amp * 0.28);
      });
      body.position.y =
        Math.sin(phase * 2) * 0.012 * intensity + Math.sin(time * 1.6) * 0.004;
      body.rotation.z = Math.sin(phase) * 0.025 * intensity;
      body.rotation.x = Math.sin(phase * 2 + 0.6) * 0.008 * intensity;
      head.rotation.x = Math.sin(phase * 2 + 1.1) * 0.02 * intensity;
      cone.visible = showCone;
      coneMaterials.forEach(
        (m, i) =>
          (m.opacity =
            [0.1, 0.16, 0.45][i] * (1 + 0.12 * Math.sin(time * 2.2))),
      );
    },
  };
}
