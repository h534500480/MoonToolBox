// 功能说明：复用 platform 的确定性障碍物布局参数。
type Shape = "box" | "wall" | "column" | "ramp" | "strip";

interface ItemDef {
  shape: Shape;
  w: number;
  h: number;
  d: number;
  color: string;
  along: number;
  lat: number;
  ry: number;
}

function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ALONG_RANGE = 26;

export function buildItems(): ItemDef[] {
  const rand = mulberry32(20260908);
  const palette = [
    "#f4f0e6",
    "#f4f0e6",
    "#eae4d6",
    "#eae4d6",
    "#eae4d6",
    "#d9d4c7",
    "#d9d4c7",
    "#c9ccbf",
    "#dfa266",
    "#dfa266",
    "#e0a377",
  ];
  const shapes: Shape[] = [
    "box",
    "box",
    "wall",
    "box",
    "column",
    "box",
    "wall",
    "box",
    "column",
    "box",
    "ramp",
  ];

  const items: ItemDef[] = shapes.map((shape, i) => {
    const lat = (rand() < 0.5 ? -1 : 1) * (2.1 + rand() * 9.5);
    const base = {
      color: palette[i % palette.length],
      along: -ALONG_RANGE + rand() * ALONG_RANGE * 2,
      lat,
      ry: (rand() - 0.5) * 0.5,
    };
    switch (shape) {
      case "wall":
        return {
          ...base,
          shape,
          w: 1.9 + rand() * 0.8,
          h: 0.42 + rand() * 0.2,
          d: 0.3,
        };
      case "column":
        return { ...base, shape, w: 0.24, h: 0.8 + rand() * 0.4, d: 0.24 };
      case "ramp":
        return {
          ...base,
          shape,
          w: 1.1,
          h: 0.34,
          d: 1.0,
          ry: base.ry + (lat > 0 ? 0.6 : -0.6),
        };
      default:
        return {
          ...base,
          shape,
          w: 0.55 + rand() * 0.75,
          h: 0.4 + rand() * 0.6,
          d: 0.55 + rand() * 0.75,
        };
    }
  });

  // 地面区域标线（sage 绿色细条）
  items.push(
    {
      shape: "strip",
      w: 5.2,
      h: 0.016,
      d: 0.46,
      color: "#b9c4ab",
      along: -18,
      lat: 6.2,
      ry: 0,
    },
    {
      shape: "strip",
      w: 4.4,
      h: 0.016,
      d: 0.46,
      color: "#b9c4ab",
      along: -4,
      lat: -7.4,
      ry: 0,
    },
    {
      shape: "strip",
      w: 6.0,
      h: 0.016,
      d: 0.46,
      color: "#b9c4ab",
      along: 12,
      lat: 8.8,
      ry: 0,
    },
    {
      shape: "strip",
      w: 3.6,
      h: 0.016,
      d: 0.42,
      color: "#dfa266",
      along: 20,
      lat: -5.6,
      ry: 0,
    },
  );
  return items;
}
