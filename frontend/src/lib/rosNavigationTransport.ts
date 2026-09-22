// 功能说明：将默认 SCAN 导航话题协议转换为逐点执行器接口，保留请求关联与消息时效。
import type { RosLiveAdapter } from "./ros/liveAdapter";
import type { NavigationOwnership } from "./navigationOwnership";
import type {
  CommandResult,
  GoalFeedback,
  GoalProgress,
  GoalRequest,
  NavigationTransport,
} from "./navigationRunner";

export const NAVIGATION_TOPICS = {
  request: "/nav2_goal_request",
  control: "/nav2_goal_control",
  context: "/nav2_goal_context",
  localization: "/nav_ndt_status",
} as const;
export const NAVIGATION_TIMEOUTS = {
  freshnessMs: 3000,
  acknowledgementMs: 8000,
};
const failures = new Set([
  "planner_server_unavailable",
  "planning_rejected",
  "planning_failed",
  "planning_empty_path",
  "path_transform_failed",
]);
const recovery = new Set([
  "odom_timeout",
  "no_goal_pose",
  "odom_frame_mismatch",
  "scan_exit_not_reached",
]);
const labels: Record<string, string> = {
  idle: "空闲",
  planning: "规划中",
  path_ready: "路径已就绪",
  paused: "人工暂停",
  paused_by_localization: "定位暂停",
  reached: "已到点",
  canceled: "已取消",
  planner_server_unavailable: "规划服务不可用",
  planning_rejected: "规划被拒绝",
  planning_failed: "规划失败",
  planning_empty_path: "规划路径为空",
  path_transform_failed: "路径坐标变换失败",
};
interface GoalContext {
  request_planid: string;
  last_result: string;
  request_completed: boolean;
  goal_active: boolean;
  request_sent: boolean;
  paused_by_user: boolean;
  paused_by_localization: boolean;
  scan_state?: string;
}
export interface NavigationConnectionState {
  connected: boolean;
  ready: boolean;
  contextFresh: boolean;
  localizationFresh: boolean;
  localization: number | null;
  stage: string;
  scanState: string;
  requestId: string;
  message: string;
}
interface Pending {
  kind: "send" | "pause" | "resume" | "cancel";
  connectionEpoch: number;
  finish: (value: CommandResult) => void;
}
/** 接口只发布请求及控制，绝不直接操作速度闸门或借用定位初始化消息。 */
export class RosNavigationTransport implements NavigationTransport {
  private adapter: RosLiveAdapter | null = null;
  private source = "";
  private active: (GoalRequest & { source: string }) | null = null;
  private context: GoalContext | null = null;
  private contextAt = 0;
  private localization: number | null = null;
  private localizationAt = 0;
  private pending: Pending | null = null;
  private unsubscribers: (() => void)[] = [];
  private feedback = new Set<(value: GoalFeedback) => void>();
  private progress = new Set<(value: GoalProgress) => void>();
  private lastProgress = "";
  private protocolError = "";
  private connectionEpoch = 0;
  private timer: ReturnType<typeof setInterval>;
  constructor(
    private changed: (state: NavigationConnectionState) => void,
    private now: () => number = Date.now,
    private timeouts = NAVIGATION_TIMEOUTS,
    private ownership?: NavigationOwnership,
  ) {
    this.timer = setInterval(() => this.refresh(), 250);
  }
  get available() {
    return this.snapshot().ready;
  }
  get unavailableReason() {
    return this.snapshot().message;
  }
  /** 连接切换清空旧时效；运行中请求仍绑定原连接，不能在另一台机器人上恢复或取消。 */
  bind(adapter: RosLiveAdapter | null, source: string) {
    this.unsubscribers.splice(0).forEach((stop) => stop());
    this.adapter = adapter;
    this.source = source;
    this.resetFreshness();
    if (!adapter && !this.active) this.ownership?.dispose();
    if (adapter) {
      this.unsubscribers.push(
        adapter.subscribe(
          NAVIGATION_TOPICS.context,
          "std_msgs/msg/String",
          (message) => this.receiveContext(message),
        ),
      );
      this.unsubscribers.push(
        adapter.subscribe(
          NAVIGATION_TOPICS.localization,
          "std_msgs/msg/UInt8",
          (message) => {
            const value = message?.data;
            this.localization =
              Number.isInteger(value) && value >= 0 && value <= 3
                ? value
                : null;
            this.localizationAt = this.now();
            this.refresh();
          },
        ),
      );
    }
    this.refresh();
  }
  connectionChanged(connected: boolean) {
    if (!connected) this.resetFreshness();
    this.refresh();
  }
  private resetFreshness() {
    this.connectionEpoch++;
    this.context = null;
    this.contextAt = 0;
    this.localization = null;
    this.localizationAt = 0;
    this.lastProgress = "";
    this.protocolError = "";
  }
  snapshot(): NavigationConnectionState {
    const connected = !!this.adapter?.getConnectionSnapshot().connected;
    const contextFresh =
      connected &&
      !!this.context &&
      this.now() - this.contextAt <= this.timeouts.freshnessMs;
    const localizationFresh =
      connected &&
      this.localization !== null &&
      this.now() - this.localizationAt <= this.timeouts.freshnessMs;
    const localized =
      localizationFresh && (this.localization === 1 || this.localization === 2);
    const context = this.context;
    const idle =
      context &&
      !context.goal_active &&
      !context.request_sent &&
      !context.paused_by_user &&
      !context.paused_by_localization &&
      (context.last_result === "idle" ||
        context.last_result === "canceled" ||
        failures.has(context.last_result) ||
        (context.last_result === "reached" && context.request_completed));
    const owned =
      !this.ownership ||
      (this.active
        ? this.ownership.owns(this.source)
        : this.ownership.available(this.source));
    const message = !connected
      ? "请连接 ROS，任务未下发。"
      : !owned
        ? "导航控制权被其他页面占用或浏览器存储不可用。"
        : this.active && this.active.source !== this.source
          ? "连接目标已改变，请切回原导航连接。"
          : !contextFresh
            ? this.protocolError || "导航状态未收到或已超时，队列等待。"
            : !localizationFresh
              ? "定位状态未收到或已超时，队列等待。"
              : !localized
                ? `定位${this.localization === 0 ? "无效" : "异常"}，队列等待。`
                : !idle
                  ? "导航端仍有活动或暂停的目标。"
                  : "导航就绪";
    return {
      connected,
      ready: !!(
        owned &&
        contextFresh &&
        localized &&
        idle &&
        !this.active &&
        !this.pending
      ),
      contextFresh,
      localizationFresh,
      localization: localizationFresh ? this.localization : null,
      stage:
        contextFresh && context
          ? labels[context.last_result] ||
            (recovery.has(context.last_result)
              ? "恢复重规划中"
              : context.last_result)
          : "状态未知",
      scanState: contextFresh ? context?.scan_state || "—" : "—",
      requestId: contextFresh ? context?.request_planid || "" : "",
      message,
    };
  }
  private receiveContext(message: unknown) {
    try {
      const raw = JSON.parse((message as { data: string }).data);
      if (
        !raw ||
        typeof raw.request_planid !== "string" ||
        typeof raw.last_result !== "string" ||
        [
          "request_completed",
          "goal_active",
          "request_sent",
          "paused_by_user",
          "paused_by_localization",
        ].some((key) => typeof raw[key] !== "boolean")
      )
        throw Error("字段不符合 SCAN context 协议");
      this.context = raw;
      this.contextAt = this.now();
      this.protocolError = "";
      this.processContext();
    } catch {
      this.context = null;
      this.protocolError = "导航状态格式异常，请确认使用 SCAN 导航链路。";
    }
    this.refresh();
  }
  private publishProgress(status: GoalProgress["status"], message: string) {
    if (!this.active) return;
    const signature = `${this.active.goalId}:${status}:${message}`;
    if (signature === this.lastProgress) return;
    this.lastProgress = signature;
    const { runId, goalId } = this.active;
    this.progress.forEach((listener) =>
      listener({ runId, goalId, status, message }),
    );
  }
  private refresh() {
    this.ownership?.refresh();
    const state = this.snapshot();
    this.changed(state);
    if (!this.active) return;
    if (
      (this.ownership && !this.ownership.owns(this.source)) ||
      this.active.source !== this.source ||
      !state.connected ||
      !state.contextFresh
    ) {
      this.publishProgress("unknown", state.message);
      return;
    }
    if (this.context?.request_planid !== this.active.goalId) {
      if (this.pending?.kind !== "send")
        this.publishProgress(
          "unknown",
          "导航请求编号已改变，停止队列推进；请核对其他控制端。",
        );
      return;
    }
    if (
      !state.localizationFresh ||
      ![1, 2].includes(state.localization ?? -1)
    ) {
      this.publishProgress("blocked", state.message);
      return;
    }
    this.processContext();
  }
  /** 只有当前请求的明确到点终态才回报成功；恢复原因与 WAIT_TARGET 均不是完成。 */
  private processContext() {
    const context = this.context,
      request = this.active;
    if (
      !context ||
      !request ||
      (this.ownership && !this.ownership.owns(this.source)) ||
      request.source !== this.source ||
      !this.adapter?.getConnectionSnapshot().connected
    )
      return;
    if (context.request_planid !== request.goalId) {
      if (
        this.pending?.kind === "cancel" &&
        this.pending.connectionEpoch === this.connectionEpoch &&
        context.request_planid === "" &&
        context.last_result === "canceled" &&
        !context.goal_active &&
        !context.request_sent
      ) {
        this.pending.finish({ ok: true, message: "导航端已确认取消。" });
        this.finish("cancelled", "导航端已取消当前请求。");
      }
      return;
    }
    if (this.pending?.kind === "send" && context.last_result !== "idle")
      this.pending.finish({ ok: true, message: "导航端已确认当前请求。" });
    if (failures.has(context.last_result)) {
      this.finish("failed", labels[context.last_result]);
      return;
    }
    if (context.last_result === "canceled") {
      this.pending?.finish({
        ok: this.pending.kind === "cancel",
        message: "导航端已取消。",
      });
      this.finish("cancelled", "导航端已取消。");
      return;
    }
    const health = this.snapshot();
    if (
      this.now() - this.contextAt > this.timeouts.freshnessMs ||
      !health.localizationFresh ||
      ![1, 2].includes(health.localization ?? -1)
    )
      return;
    const reached =
      context.request_completed && context.last_result === "reached";
    if (this.pending?.kind === "pause" && context.paused_by_user)
      this.pending.finish({ ok: true, message: "导航端已确认暂停。" });
    if (
      this.pending?.kind === "resume" &&
      !context.paused_by_user &&
      !context.paused_by_localization &&
      (context.request_sent ||
        context.goal_active ||
        reached ||
        context.last_result === "path_ready")
    )
      this.pending.finish({ ok: true, message: "导航端已确认恢复。" });
    if (context.paused_by_user || context.last_result === "paused") {
      this.publishProgress("paused", "已由导航端确认人工暂停。");
      return;
    }
    if (
      context.paused_by_localization ||
      context.last_result === "paused_by_localization"
    ) {
      this.publishProgress("blocked", "导航端因定位异常暂停，等待定位恢复。");
      return;
    }
    if (reached) {
      if (this.pending?.kind === "pause")
        this.pending.finish({
          ok: false,
          message: "当前点已经到达，暂停未执行。",
        });
      if (this.pending?.kind === "cancel")
        this.pending.finish({
          ok: true,
          message: "当前点已经到达，停止后续队列。",
        });
      this.publishProgress("running", "导航端已确认当前点到达。");
      this.finish(
        "succeeded",
        "导航端已确认到点（位置条件，不代表最终朝向达标）。",
      );
      return;
    }
    this.publishProgress(
      "running",
      labels[context.last_result] ||
        (recovery.has(context.last_result)
          ? `恢复重规划中：${context.last_result}`
          : `导航阶段：${context.last_result}`),
    );
  }
  private finish(status: GoalFeedback["status"], message: string) {
    const request = this.active;
    if (!request) return;
    this.pending?.finish({
      ok: status === "cancelled" && this.pending.kind === "cancel",
      message,
    });
    this.active = null;
    this.lastProgress = "";
    this.feedback.forEach((listener) =>
      listener({
        runId: request.runId,
        goalId: request.goalId,
        status,
        message,
      }),
    );
  }
  /** 发布成功不代表接受；等待关联 context，超时按状态未知处理且不自动重发。 */
  private awaitAcknowledgement(
    kind: Pending["kind"],
    publish: () => void,
  ): Promise<CommandResult> {
    return new Promise((resolve) => {
      const timer = setTimeout(
        () =>
          pending.finish({
            ok: false,
            uncertain: true,
            message: "等待导航确认超时，实际状态未知；未重发请求。",
          }),
        this.timeouts.acknowledgementMs,
      );
      const pending: Pending = {
        kind,
        connectionEpoch: this.connectionEpoch,
        finish: (value) => {
          if (this.pending !== pending) return;
          clearTimeout(timer);
          this.pending = null;
          resolve(value);
        },
      };
      this.pending = pending;
      try {
        publish();
      } catch (error) {
        pending.finish({
          ok: false,
          uncertain: true,
          message: `发送结果未知：${(error as Error).message}`,
        });
      }
    });
  }
  async sendGoal(request: GoalRequest): Promise<CommandResult> {
    if (!this.available || !this.adapter)
      return Promise.resolve({ ok: false, message: this.unavailableReason });
    const source = this.source;
    if (this.ownership && !(await this.ownership.acquire(this.source)))
      return { ok: false, message: "未取得导航控制权，目标未发送。" };
    if (source !== this.source)
      return { ok: false, message: "连接目标已改变，目标未发送。" };
    if (!this.available || !this.adapter)
      return { ok: false, message: this.unavailableReason };
    this.active = { ...request, source: this.source };
    const data = JSON.stringify({
      request_planid: request.goalId,
      pose: {
        frame_id: request.frame,
        x: request.point.x,
        y: request.point.y,
        z: request.point.z,
        yaw: request.point.yaw,
      },
      context: {
        task_id: request.taskId,
        run_id: request.runId,
        point_index: request.index + 1,
        point_name: request.point.name,
      },
    });
    return this.awaitAcknowledgement("send", () =>
      this.adapter!.publish(NAVIGATION_TOPICS.request, "std_msgs/msg/String", {
        data,
      }),
    );
  }
  control(
    command: "pause" | "resume" | "cancel",
    request: { runId: string; goalId: string },
  ): Promise<CommandResult> {
    const health = this.snapshot();
    if (
      !this.active ||
      (this.ownership && !this.ownership.owns(this.source)) ||
      this.active.goalId !== request.goalId ||
      this.active.runId !== request.runId ||
      this.active.source !== this.source ||
      !health.contextFresh ||
      this.context?.request_planid !== request.goalId ||
      this.pending ||
      !this.adapter
    )
      return Promise.resolve({
        ok: false,
        message: "无法确认当前目标归属或仍在等待确认，控制未发送。",
      });
    if (
      command === "resume" &&
      (!health.localizationFresh ||
        ![1, 2].includes(health.localization ?? -1) ||
        this.context.paused_by_localization ||
        !this.context.paused_by_user)
    )
      return Promise.resolve({
        ok: false,
        message: "定位未恢复或目标不是人工暂停，不能继续。",
      });
    return this.awaitAcknowledgement(command, () =>
      this.adapter!.publish(NAVIGATION_TOPICS.control, "std_msgs/msg/String", {
        data: JSON.stringify({ command }),
      }),
    );
  }
  subscribe(listener: (value: GoalFeedback) => void) {
    this.feedback.add(listener);
    return () => {
      this.feedback.delete(listener);
    };
  }
  subscribeProgress(listener: (value: GoalProgress) => void) {
    this.progress.add(listener);
    return () => {
      this.progress.delete(listener);
    };
  }
  dispose() {
    this.ownership?.dispose();
    clearInterval(this.timer);
    this.pending?.finish({
      ok: false,
      uncertain: true,
      message: "页面连接已关闭，导航实际状态未知。",
    });
    this.unsubscribers.splice(0).forEach((stop) => stop());
    this.feedback.clear();
    this.progress.clear();
  }
}
