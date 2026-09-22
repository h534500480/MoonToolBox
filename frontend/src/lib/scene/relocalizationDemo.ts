// 功能说明：复用 platform 候选点演示场景；不参与任何真实导出。
import * as THREE from "three";
export interface CandidatePoint {
  id: number;
  x: number;
  y: number;
  z: number;
  yawDeg: number;
  /** 可观测性得分 0~1 */
  score: number;
  hitCount: number;
  source: "auto" | "manual";
  locked: boolean;
  label: string;
  note: string;
}

export const INITIAL_CANDIDATES: CandidatePoint[] = [
  {
    id: 1,
    x: -6.2,
    y: -2.8,
    z: 0.35,
    yawDeg: 45,
    score: 0.93,
    hitCount: 612,
    source: "auto",
    locked: true,
    label: "C001",
    note: "",
  },
  {
    id: 2,
    x: -4.1,
    y: 1.2,
    z: 0.35,
    yawDeg: 130,
    score: 0.88,
    hitCount: 488,
    source: "auto",
    locked: false,
    label: "C002",
    note: "",
  },
  {
    id: 3,
    x: -1.5,
    y: -4.6,
    z: 0.35,
    yawDeg: 10,
    score: 0.76,
    hitCount: 355,
    source: "auto",
    locked: false,
    label: "C003",
    note: "",
  },
  {
    id: 4,
    x: 0.8,
    y: 2.4,
    z: 0.35,
    yawDeg: 200,
    score: 0.91,
    hitCount: 540,
    source: "auto",
    locked: false,
    label: "C004",
    note: "",
  },
  {
    id: 5,
    x: 3.2,
    y: -1.8,
    z: 0.35,
    yawDeg: 60,
    score: 0.64,
    hitCount: 268,
    source: "auto",
    locked: false,
    label: "C005",
    note: "",
  },
  {
    id: 6,
    x: 5.0,
    y: 4.6,
    z: 0.35,
    yawDeg: 150,
    score: 0.87,
    hitCount: 502,
    source: "auto",
    locked: false,
    label: "C006",
    note: "",
  },
  {
    id: 7,
    x: 7.4,
    y: -3.2,
    z: 0.35,
    yawDeg: 300,
    score: 0.72,
    hitCount: 331,
    source: "auto",
    locked: false,
    label: "C007",
    note: "",
  },
  {
    id: 8,
    x: 9.8,
    y: 1.0,
    z: 0.35,
    yawDeg: 20,
    score: 0.85,
    hitCount: 461,
    source: "auto",
    locked: false,
    label: "C008",
    note: "",
  },
  {
    id: 9,
    x: -8.6,
    y: 5.4,
    z: 0.35,
    yawDeg: 250,
    score: 0.69,
    hitCount: 302,
    source: "auto",
    locked: false,
    label: "C009",
    note: "",
  },
  {
    id: 10,
    x: -10.2,
    y: -6.8,
    z: 0.35,
    yawDeg: 90,
    score: 0.58,
    hitCount: 214,
    source: "auto",
    locked: false,
    label: "C010",
    note: "",
  },
  {
    id: 11,
    x: 12.4,
    y: 5.8,
    z: 0.35,
    yawDeg: 320,
    score: 0.81,
    hitCount: 428,
    source: "auto",
    locked: false,
    label: "C011",
    note: "",
  },
  {
    id: 12,
    x: 2.6,
    y: 7.2,
    z: 0.35,
    yawDeg: 180,
    score: 0.74,
    hitCount: 346,
    source: "auto",
    locked: false,
    label: "C012",
    note: "",
  },
  {
    id: 13,
    x: -2.8,
    y: -8.4,
    z: 0.35,
    yawDeg: 340,
    score: 0.66,
    hitCount: 257,
    source: "auto",
    locked: false,
    label: "C013",
    note: "",
  },
  {
    id: 14,
    x: 6.2,
    y: -7.0,
    z: 0.35,
    yawDeg: 110,
    score: 0.79,
    hitCount: 389,
    source: "auto",
    locked: false,
    label: "C014",
    note: "",
  },
  {
    id: 15,
    x: 1.8,
    y: 0.6,
    z: 0.35,
    yawDeg: 0,
    score: 1.0,
    hitCount: 0,
    source: "manual",
    locked: false,
    label: "M-01",
    note: "电梯口补点",
  },
  {
    id: 16,
    x: -5.4,
    y: -0.8,
    z: 0.35,
    yawDeg: 270,
    score: 1.0,
    hitCount: 0,
    source: "manual",
    locked: false,
    label: "M-02",
    note: "走廊拐角补点",
  },
];

interface WallDef {
  x1: number;
  z1: number;
  x2: number;
  z2: number;
  h: number;
}

const WALLS: WallDef[] = [
  { x1: -14, z1: -6, x2: -2, z2: -6, h: 2.4 },
  { x1: 2, z1: -8, x2: 12, z2: -4, h: 2.0 },
  { x1: -12, z1: 4, x2: -4, z2: 9, h: 2.6 },
  { x1: 5, z1: 3, x2: 14, z2: 8, h: 2.2 },
  { x1: -16, z1: -12, x2: 16, z2: -14, h: 1.8 },
  { x1: 10, z1: -10, x2: 15, z2: 0, h: 2.8 },
];

const PILLARS: { x: number; z: number; r: number; h: number }[] = [
  { x: -3, z: 1, r: 0.45, h: 3.0 },
  { x: 3, z: 1, r: 0.45, h: 3.0 },
  { x: 8, z: -2, r: 0.5, h: 2.6 },
  { x: -8, z: -10, r: 0.5, h: 2.6 },
];

export function createRelocalizationDemo() {
  const geometry = (() => {
    const pos: number[] = [];
    const rand = (s: number) => s; // 确定性生成，避免水合抖动
    let seed = 20260908;
    const rnd = () => {
      seed = (seed * 16807) % 2147483647;
      return seed / 2147483647;
    };

    // 地面散点
    for (let i = 0; i < 2200; i++) {
      const a = rnd() * Math.PI * 2;
      const r = 2 + Math.sqrt(rnd()) * 18;
      pos.push(Math.cos(a) * r, rnd() * 0.05, Math.sin(a) * r);
    }
    // 墙面点
    for (const w of WALLS) {
      const len = Math.hypot(w.x2 - w.x1, w.z2 - w.z1);
      const n = Math.round(len * 55);
      for (let i = 0; i < n; i++) {
        const t = rnd();
        const jitterX = (rnd() - 0.5) * 0.12;
        const jitterZ = (rnd() - 0.5) * 0.12;
        pos.push(
          w.x1 + (w.x2 - w.x1) * t + jitterX,
          rnd() * w.h,
          w.z1 + (w.z2 - w.z1) * t + jitterZ,
        );
      }
    }
    // 立柱点
    for (const p of PILLARS) {
      for (let i = 0; i < 260; i++) {
        const a = rnd() * Math.PI * 2;
        const r = p.r * (0.92 + rnd() * 0.16);
        pos.push(p.x + Math.cos(a) * r, rnd() * p.h, p.z + Math.sin(a) * r);
      }
    }
    void rand;

    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    return g;
  })();
  geometry.applyMatrix4(
    new THREE.Matrix4().set(0, 0, -1, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1),
  );
  return new THREE.Points(
    geometry,
    new THREE.PointsMaterial({
      color: "#7d8a96",
      size: 0.05,
      transparent: true,
      opacity: 0.55,
      depthWrite: false,
    }),
  );
}
