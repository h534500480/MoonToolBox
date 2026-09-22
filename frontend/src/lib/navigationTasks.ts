// 功能说明：导航任务文件协议、坐标校验及待接入的导航传输接口。
export interface TaskPose {
  x: number;
  y: number;
  z: number;
  yaw: number;
  // 兼容旧任务文件：缺失的横滚和俯仰按零处理，新增点保存完整姿态。
  roll?: number;
  pitch?: number;
}
export interface TaskPoint extends TaskPose {
  id: string;
  name: string;
}
/** 用相邻点编号校验插入位置，防止点击期间任务切换或顺序变化。 */
export interface TaskRouteInsertion {
  beforeId: string;
  afterId: string;
  pose: TaskPose;
}
/** 以入段和出段单位切线的角平分线作为默认航向；折返或重合时保留有效趋势。 */
export function routeInsertionYaw(
  before: TaskPose,
  point: TaskPose,
  after: TaskPose,
): number {
  const incoming = { x: point.x - before.x, y: point.y - before.y };
  const outgoing = { x: after.x - point.x, y: after.y - point.y };
  const a = Math.hypot(incoming.x, incoming.y),
    b = Math.hypot(outgoing.x, outgoing.y);
  const x = (a > 1e-6 ? incoming.x / a : 0) + (b > 1e-6 ? outgoing.x / b : 0);
  const y = (a > 1e-6 ? incoming.y / a : 0) + (b > 1e-6 ? outgoing.y / b : 0);
  if (Math.hypot(x, y) > 1e-6) return Math.atan2(y, x);
  return Number.isFinite(point.yaw) ? point.yaw : before.yaw;
}
export interface NavigationTask {
  id: string;
  name: string;
  frame: string;
  kind?: string;
  createdAt: string;
  points: TaskPoint[];
}
let localIdSequence = 0;
/** 局域网 HTTP 不保证提供 randomUUID；本地业务编号不依赖安全上下文。 */
export function createTaskId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function")
    return globalThis.crypto.randomUUID();
  if (typeof globalThis.crypto?.getRandomValues === "function") {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (value) =>
      value.toString(16).padStart(2, "0"),
    ).join("");
  }
  return `local-${Date.now().toString(36)}-${++localIdSequence}-${Math.random().toString(36).slice(2)}`;
}
/** 场景编辑接口只操作候选位姿，不发布 ROS 消息。 */
export interface TaskScene {
  getTaskRobotPose(): TaskPose | null;
  editTaskPose(pose: TaskPose): void;
  focusTaskPose(pose: TaskPose): void;
  clearInitialPoseCandidate(): void;
}
export function validTaskPose(value: any): boolean {
  return (
    !!value &&
    ["x", "y", "z", "yaw"].every(
      (key) => typeof value[key] === "number" && Number.isFinite(value[key]),
    ) &&
    ["roll", "pitch"].every(
      (key) =>
        value[key] === undefined ||
        (typeof value[key] === "number" && Number.isFinite(value[key])),
    )
  );
}
/** 对本地存储和导入文件使用同一校验，避免非法坐标进入三维场景。 */
export function parseTasks(raw: string): NavigationTask[] {
  const data = JSON.parse(raw);
  if (
    !data ||
    data.version !== 1 ||
    !Array.isArray(data.tasks) ||
    data.tasks.length > 200
  )
    throw new Error("任务文件格式无效（需要 version: 1）。");
  const ids = new Set<string>();
  for (const task of data.tasks) {
    if (
      !task ||
      typeof task.id !== "string" ||
      ids.has(task.id) ||
      typeof task.name !== "string" ||
      !task.name.trim() ||
      typeof task.frame !== "string" ||
      !task.frame.trim() ||
      (task.kind !== undefined &&
        (typeof task.kind !== "string" || !task.kind.trim())) ||
      !Number.isFinite(Date.parse(task.createdAt)) ||
      !Array.isArray(task.points) ||
      task.points.length > 1000
    )
      throw new Error("任务名称、坐标系、时间或点位列表无效。");
    ids.add(task.id);
    const pointIds = new Set<string>();
    for (const point of task.points) {
      if (
        !validTaskPose(point) ||
        typeof point.id !== "string" ||
        pointIds.has(point.id) ||
        typeof point.name !== "string" ||
        !point.name.trim()
      )
        throw new Error("点位名称、编号或坐标无效。");
      pointIds.add(point.id);
      point.roll ??= 0;
      point.pitch ??= 0;
    }
  }
  return data.tasks;
}
export function taskDistance(task: NavigationTask): number {
  return task.points.reduce(
    (sum, point, index, points) =>
      index
        ? sum +
          Math.hypot(
            point.x - points[index - 1].x,
            point.y - points[index - 1].y,
            point.z - points[index - 1].z,
          )
        : sum,
    0,
  );
}
