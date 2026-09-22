// 功能说明：位姿控件与任务编号共享距离衰减，避免远距离编辑元素无限放大。
/** 世界尺寸按距离平方根增长；相机拉远时增长率递减，并限制最大世界尺寸。 */
export function poseVisualScale(distance: number): number {
  return Math.min(12, Math.max(0.15, Math.sqrt(Math.max(0, distance) / 12)));
}
