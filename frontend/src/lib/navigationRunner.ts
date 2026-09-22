// 功能说明：按任务快照逐点导航，仅当前目标成功反馈可触发下一点。
import {
  createTaskId,
  parseTasks,
  type NavigationTask,
  type TaskPoint,
} from "./navigationTasks";

export type RunStatus =
  | "idle"
  | "sending"
  | "running"
  | "unknown"
  | "blocked"
  | "pausing"
  | "paused"
  | "resuming"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled";
export type GoalResult = "succeeded" | "failed" | "cancelled";
export interface GoalRequest {
  runId: string;
  goalId: string;
  taskId: string;
  frame: string;
  index: number;
  point: TaskPoint;
}
export interface GoalFeedback {
  runId: string;
  goalId: string;
  status: GoalResult;
  message?: string;
}
export interface GoalProgress {
  runId: string;
  goalId: string;
  status: "running" | "paused" | "unknown" | "blocked";
  message: string;
}
export interface CommandResult {
  uncertain?: boolean;
  ok: boolean;
  message: string;
}
/** sendGoal 的确认只代表接受目标；到达结果必须通过订阅反馈携带同一 runId/goalId。 */
export interface NavigationTransport {
  readonly available: boolean;
  readonly unavailableReason?: string;
  subscribeProgress?(listener: (progress: GoalProgress) => void): () => void;
  sendGoal(request: GoalRequest): Promise<CommandResult>;
  control(
    command: "pause" | "resume" | "cancel",
    request: { runId: string; goalId: string },
  ): Promise<CommandResult>;
  subscribe(listener: (feedback: GoalFeedback) => void): () => void;
}
export const navigationTransport: NavigationTransport = {
  available: false,
  async sendGoal() {
    return { ok: false, message: "导航通信尚未接入，任务未下发。" };
  },
  async control() {
    return { ok: false, message: "导航通信尚未接入。" };
  },
  subscribe() {
    return () => {};
  },
};
export interface RunState {
  status: RunStatus;
  runId: string;
  goalId: string;
  taskId: string;
  taskName: string;
  index: number;
  total: number;
  completed: number;
  pointName: string;
  message: string;
}
export const runStatusLabels: Record<RunStatus, string> = {
  idle: "待执行",
  sending: "下发中",
  running: "导航中",
  unknown: "状态未知",
  blocked: "定位等待",
  pausing: "暂停中",
  paused: "已暂停",
  resuming: "继续中",
  cancelling: "取消中",
  completed: "已完成",
  failed: "失败停止",
  cancelled: "已取消",
};
export const isRunActive = (state: RunState) =>
  [
    "sending",
    "running",
    "unknown",
    "blocked",
    "pausing",
    "paused",
    "resuming",
    "cancelling",
  ].includes(state.status);

/** 执行期间固定点位快照；忽略重复、旧目标和旧任务反馈，避免跳点或重复下发。 */
export class NavigationRunner {
  state: RunState;
  private task: NavigationTask | null = null;
  private succeeded = false;
  private earlyFeedback: GoalFeedback | null = null;
  private unsubscribe: () => void;
  private disposed = false;
  private earlyProgress: GoalProgress | null = null;
  private unsubscribeProgress?: () => void;
  private haltAfterCurrent: "pause" | "cancel" | null = null;
  constructor(
    private transport: NavigationTransport,
    private changed: (state: RunState) => void,
  ) {
    this.state = {
      status: "idle",
      runId: "",
      goalId: "",
      taskId: "",
      taskName: "",
      index: 0,
      total: 0,
      completed: 0,
      pointName: "",
      message: "",
    };
    this.unsubscribeProgress = transport.subscribeProgress?.((progress) =>
      this.receiveProgress(progress),
    );
    this.unsubscribe = transport.subscribe((feedback) =>
      this.receive(feedback),
    );
  }
  private update(patch: Partial<RunState>) {
    this.state = { ...this.state, ...patch };
    this.changed({ ...this.state });
  }
  /** 已停止任务发生编辑后清除旧快照结果，避免把历史完成标记套到新点位。 */
  clearResult() {
    if (this.disposed || isRunActive(this.state)) return;
    this.task = null;
    this.succeeded = false;
    this.earlyFeedback = null;
    this.update({
      status: "idle",
      runId: "",
      goalId: "",
      taskId: "",
      taskName: "",
      index: 0,
      total: 0,
      completed: 0,
      pointName: "",
      message: "",
    });
  }
  async start(task: NavigationTask) {
    if (this.disposed || isRunActive(this.state)) return;
    if (!this.transport.available) {
      this.update({
        message:
          this.transport.unavailableReason || "导航通信尚未接入，任务未下发。",
      });
      return;
    }
    try {
      this.task = parseTasks(JSON.stringify({ version: 1, tasks: [task] }))[0];
      if (!this.task.points.length) throw new Error("请先添加任务点位。");
    } catch (error) {
      this.update({ message: (error as Error).message });
      return;
    }
    this.haltAfterCurrent = null;
    this.update({
      runId: createTaskId(),
      taskId: task.id,
      taskName: task.name,
      index: 0,
      total: task.points.length,
      completed: 0,
    });
    await this.dispatch();
  }
  /** 每次仅发送当前索引；接受响应不推进进度，等待终态反馈。 */
  private async dispatch() {
    if (this.disposed || !this.task) return;
    const point = this.task.points[this.state.index];
    if (!point) {
      this.update({
        status: "completed",
        goalId: "",
        message: "全部任务点已完成。",
      });
      return;
    }
    this.succeeded = false;
    this.earlyFeedback = null;
    const runId = this.state.runId,
      goalId = createTaskId();
    this.update({
      status: "sending",
      goalId,
      pointName: point.name,
      message: `正在下发第 ${this.state.index + 1} 个点：${point.name}`,
    });
    try {
      const result = await this.transport.sendGoal({
        runId,
        goalId,
        taskId: this.task.id,
        frame: this.task.frame,
        index: this.state.index,
        point: { ...point },
      });
      if (
        this.disposed ||
        this.state.runId !== runId ||
        this.state.goalId !== goalId ||
        this.state.status !== "sending"
      )
        return;
      this.update({
        status: result.ok ? "running" : result.uncertain ? "unknown" : "failed",
        message: result.message,
      });
      const feedback = this.earlyFeedback;
      this.earlyFeedback = null;
      if (result.ok && this.earlyProgress)
        this.receiveProgress(this.earlyProgress);
      this.earlyProgress = null;
      if (result.ok && feedback) this.receive(feedback);
    } catch (error) {
      if (
        !this.disposed &&
        this.state.runId === runId &&
        this.state.goalId === goalId
      )
        this.update({
          status: "failed",
          message: `目标下发失败：${(error as Error).message}`,
        });
    }
  }
  /** 实时状态只更新当前编号；控制确认期间不覆盖待确认状态。 */
  private receiveProgress(progress: GoalProgress) {
    if (
      this.disposed ||
      !isRunActive(this.state) ||
      progress.runId !== this.state.runId ||
      progress.goalId !== this.state.goalId ||
      this.succeeded
    )
      return;
    if (this.state.status === "sending") {
      this.earlyProgress = progress;
      return;
    }
    if (["pausing", "resuming", "cancelling"].includes(this.state.status)) {
      this.update({ message: progress.message });
      return;
    }
    this.update({ status: progress.status, message: progress.message });
  }
  private advance() {
    // 控制确认丢失时仍保留用户停止队列的意图，不能因迟到的到点消息续发。
    if (this.haltAfterCurrent) {
      this.update({
        status: this.haltAfterCurrent === "cancel" ? "cancelled" : "paused",
        message:
          this.haltAfterCurrent === "cancel"
            ? "当前点已到达，已停止剩余任务点。"
            : "当前点已到达，队列已暂停。",
      });
      return;
    }
    this.update({ index: this.state.index + 1 });
    void this.dispatch();
  }
  /** 暂停或控制确认期间收到成功结果仅记进度，继续确认后再发送下一点。 */
  receive(feedback: GoalFeedback) {
    if (
      this.disposed ||
      !isRunActive(this.state) ||
      feedback.runId !== this.state.runId ||
      feedback.goalId !== this.state.goalId ||
      this.succeeded
    )
      return;
    if (this.state.status === "sending") {
      this.earlyFeedback ??= feedback;
      return;
    }
    if (feedback.status !== "succeeded") {
      this.update({
        status: feedback.status === "failed" ? "failed" : "cancelled",
        message: feedback.message || "当前点未完成，任务已停止，未下发下一点。",
      });
      return;
    }
    this.succeeded = true;
    this.update({
      completed: this.state.index + 1,
      message: `${this.state.pointName} 已完成。`,
    });
    if (this.state.status === "running") this.advance();
  }
  async control(command: "pause" | "resume" | "cancel") {
    if (this.disposed) return;
    const previous = this.state.status;
    const allowed =
      command === "pause"
        ? previous === "running"
        : command === "resume"
          ? previous === "paused"
          : ["sending", "running", "paused", "blocked", "unknown"].includes(
              previous,
            );
    if (!allowed) return;
    if (command === "pause" || command === "cancel")
      this.haltAfterCurrent = command;
    const pending: RunStatus =
      command === "pause"
        ? "pausing"
        : command === "resume"
          ? "resuming"
          : "cancelling";
    const runId = this.state.runId,
      goalId = this.state.goalId;
    this.update({ status: pending });
    try {
      // 已到达但暂停在点间时，没有机器人目标需要继续或取消。
      const result = this.succeeded
        ? { ok: true, message: "" }
        : await this.transport.control(command, { runId, goalId });
      if (
        this.disposed ||
        this.state.runId !== runId ||
        this.state.goalId !== goalId ||
        this.state.status !== pending
      )
        return;
      if (!result.ok) {
        this.update({
          status: result.uncertain ? "unknown" : previous,
          message: result.message,
        });
        if (!result.uncertain && previous === "running" && this.succeeded)
          this.advance();
        return;
      }
      if (command === "resume") this.haltAfterCurrent = null;
      this.update({
        status:
          command === "pause"
            ? "paused"
            : command === "resume"
              ? "running"
              : "cancelled",
        message:
          command === "pause"
            ? "任务已暂停。"
            : command === "resume"
              ? "任务继续执行。"
              : "任务已取消，未下发后续点位。",
      });
      if (command === "resume" && this.succeeded) this.advance();
    } catch (error) {
      if (
        this.disposed ||
        this.state.runId !== runId ||
        this.state.goalId !== goalId ||
        this.state.status !== pending
      )
        return;
      this.update({
        status: previous,
        message: `控制失败：${(error as Error).message}`,
      });
      if (previous === "running" && this.succeeded) this.advance();
    }
  }
  /** 卸载只解除反馈订阅；不把页面退出冒充为机器人取消确认。 */
  dispose() {
    this.disposed = true;
    this.unsubscribe();
    this.unsubscribeProgress?.();
  }
}
