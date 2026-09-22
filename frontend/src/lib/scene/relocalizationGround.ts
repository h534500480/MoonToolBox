// 功能说明：复用 platform 候选点页的地面纹理及照明，世界坐标采用 ROS 的 Z 轴向上。
import * as THREE from "three";

/** 与参考页保持相同的网格密度、材质与光照；纹理由场景统一释放。 */
export function addRelocalizationGround(scene: THREE.Scene) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#e8e4da";
  ctx.fillRect(0, 0, 128, 128);
  ctx.strokeStyle = "rgba(97,94,84,.12)";
  ctx.beginPath();
  ctx.moveTo(0.5, 0);
  ctx.lineTo(0.5, 128);
  ctx.moveTo(0, 0.5);
  ctx.lineTo(128, 0.5);
  ctx.stroke();
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(60, 60);
  texture.colorSpace = THREE.SRGBColorSpace;
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(60, 60),
    new THREE.MeshStandardMaterial({ map: texture, roughness: 1 }),
  );
  ground.position.z = -0.04;
  const sky = new THREE.HemisphereLight("#fdfbf5", "#d8d2c2", 0.6);
  sky.position.set(0, 0, 1);
  const sun = new THREE.DirectionalLight("#fff2dd", 1.2);
  sun.position.set(-8, -6, 12);
  scene.add(ground, sky, sun, new THREE.AmbientLight("#fff6e8", 0.45));
  return ground;
}
