// 功能说明：同时显示平移箭头与旋转环，并为两组控件统一仲裁指针事件。
import { Group, Vector3, type Camera, type Object3D } from "three";
import { poseVisualScale } from "./poseVisualScale";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";

/** 初始化与导航点均保留三轴旋转；回调沿用上层候选位姿链路。 */
export class CombinedPoseControls {
  private translate: TransformControls;
  private rotate: TransformControls;
  private helper = new Group();
  private active: TransformControls | null = null;
  private pointerId: number | null = null;
  private oldCursor: string;
  private oldTouchAction: string;

  constructor(
    private camera: Camera,
    private element: HTMLElement,
    private onDraggingChange: (dragging: boolean) => void,
    private onObjectChange: () => void,
    private prioritisePoint: (event: PointerEvent) => boolean = () => false,
  ) {
    this.oldCursor = element.style.cursor;
    this.oldTouchAction = element.style.touchAction;
    this.translate = new TransformControls(camera, element);
    this.rotate = new TransformControls(camera, element);
    // 只使用控件的公开指针方法，避免两个实例及 OrbitControls 同时处理一次拖动。
    for (const control of [this.translate, this.rotate]) {
      control.disconnect();
      control.setSpace("local");
      control.addEventListener("objectChange", onObjectChange);
      this.helper.add(control.getHelper());
    }
    this.translate.setMode("translate");
    this.translate.setSize(0.85);
    this.rotate.setMode("rotate");
    this.rotate.setSize(1.65);
    // 自由旋转的中心球会遮住平移手柄；组合控件只保留有明确轴向的旋转环。
    this.rotate.getHelper().traverse((node) => {
      if (node.name === "E" || node.name === "XYZE") node.layers.disableAll();
    });
    this.helper.name = "combined-pose-controls";
    this.translate.getHelper().name = "pose-translation-helper";
    this.rotate.getHelper().name = "pose-rotation-helper";
    this.helper.visible = false;
    this.helper.traverse((node) => {
      node.renderOrder = node instanceof Group ? 0 : 100;
    });
    element.style.touchAction = "none";
    element.addEventListener("pointerdown", this.pointerDown, true);
    element.addEventListener("pointermove", this.pointerMove, true);
    element.addEventListener("pointerup", this.pointerUp, true);
    element.addEventListener("pointercancel", this.pointerCancel, true);
    element.addEventListener("lostpointercapture", this.pointerCancel, true);
    element.addEventListener("pointerleave", this.pointerLeave);
    window.addEventListener("blur", this.blur);
  }
  get dragging() {
    return this.active !== null;
  }
  get axis() {
    return this.translate.axis || this.rotate.axis;
  }
  getHelper() {
    return this.helper;
  }
  /** 抵消 TransformControls 内建的线性距离缩放，保留递减的放大趋势。 */
  updateScale() {
    const object = this.translate.object;
    if (!object) return;
    const distance = this.camera
      .getWorldPosition(new Vector3())
      .distanceTo(object.getWorldPosition(new Vector3()));
    const factor = Math.min(
      1,
      (poseVisualScale(distance) * 12) / Math.max(distance, 0.01),
    );
    this.translate.setSize(0.55 * factor);
    this.rotate.setSize(0.95 * factor);
  }

  /** 两组控件绑定同一个候选对象，不复制点云或发布任何消息。 */
  attach(object: Object3D, worldSpace = false) {
    this.finishDrag();
    this.translate.setSpace(worldSpace ? "world" : "local");
    this.rotate.setSpace(worldSpace ? "world" : "local");
    this.rotate.showX = true;
    this.rotate.showY = true;
    this.translate.attach(object);
    this.rotate.attach(object);
    this.helper.visible = true;
    this.updateScale();
  }
  detach() {
    this.finishDrag();
    this.translate.detach();
    this.rotate.detach();
    this.clearHover();
    this.helper.visible = false;
  }
  /** TransformControls 的公开方法接收归一化指针；类型声明仍写作 DOM PointerEvent。 */
  private pointer(event: PointerEvent, button = event.button): PointerEvent {
    const bounds = this.element.getBoundingClientRect();
    return {
      x: ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      y: (-(event.clientY - bounds.top) / bounds.height) * 2 + 1,
      button,
    } as unknown as PointerEvent;
  }
  private clearHover() {
    this.translate.axis = null;
    this.rotate.axis = null;
    this.element.style.cursor = this.oldCursor;
  }
  private hover(event: PointerEvent) {
    if (!this.helper.visible) return null;
    if (this.prioritisePoint(event)) {
      this.clearHover();
      return null;
    }
    this.updateScale();
    this.helper.updateMatrixWorld(true);
    const pointer = this.pointer(event);
    this.translate.pointerHover(pointer);
    this.rotate.pointerHover(pointer);
    // 箭头优先，旋转环放大到外侧；重叠处始终只高亮并选中一个操作。
    const picked = this.translate.axis
      ? this.translate
      : this.rotate.axis
        ? this.rotate
        : null;
    if (picked === this.translate) this.rotate.axis = null;
    else this.translate.axis = null;
    this.element.style.cursor = picked ? "grab" : this.oldCursor;
    return picked;
  }
  private pointerDown = (event: PointerEvent) => {
    if (this.active || event.button !== 0 || !event.isPrimary) return;
    const picked = this.hover(event);
    if (!picked) return;
    picked.getHelper().updateMatrixWorld(true);
    picked.pointerDown(this.pointer(event, 0));
    if (!picked.dragging) return;
    this.active = picked;
    this.pointerId = event.pointerId;
    this.element.setPointerCapture(event.pointerId);
    this.element.style.cursor = "grabbing";
    this.onDraggingChange(true);
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  private pointerMove = (event: PointerEvent) => {
    if (!this.active) {
      if (event.buttons === 0) this.hover(event);
      return;
    }
    if (event.pointerId !== this.pointerId) return;
    this.active.pointerMove(this.pointer(event, -1));
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  private pointerUp = (event: PointerEvent) => {
    if (
      !this.active ||
      event.pointerId !== this.pointerId ||
      event.button !== 0
    )
      return;
    this.finishDrag();
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  private pointerCancel = (event: PointerEvent) => {
    if (event.pointerId === this.pointerId) this.finishDrag();
  };
  private pointerLeave = () => {
    if (!this.active) this.clearHover();
  };
  private blur = () => this.finishDrag();
  /** 松开、失焦、取消预览和释放控件都恢复相机，避免拖出画布后卡住。 */
  private finishDrag() {
    const active = this.active,
      pointerId = this.pointerId;
    this.active = null;
    this.pointerId = null;
    if (active) {
      active.pointerUp(null);
      this.onDraggingChange(false);
    }
    if (pointerId !== null && this.element.hasPointerCapture(pointerId))
      this.element.releasePointerCapture(pointerId);
    this.clearHover();
  }
  dispose() {
    this.detach();
    this.element.removeEventListener("pointerdown", this.pointerDown, true);
    this.element.removeEventListener("pointermove", this.pointerMove, true);
    this.element.removeEventListener("pointerup", this.pointerUp, true);
    this.element.removeEventListener("pointercancel", this.pointerCancel, true);
    this.element.removeEventListener(
      "lostpointercapture",
      this.pointerCancel,
      true,
    );
    this.element.removeEventListener("pointerleave", this.pointerLeave);
    window.removeEventListener("blur", this.blur);
    for (const control of [this.translate, this.rotate]) {
      control.removeEventListener("objectChange", this.onObjectChange);
      control.dispose();
    }
    this.element.style.touchAction = this.oldTouchAction;
    this.element.style.cursor = this.oldCursor;
    this.helper.removeFromParent();
  }
}
