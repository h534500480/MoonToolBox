/**
 * 功能说明：
 * 为导航测试页提供统一的 ROS 实时数据接入层。
 *
 * 设计要点：
 * 1. 前端只依赖这个抽象，不直接散落使用 roslib。
 * 2. 当前实现 rosbridge 和 mock 两种 provider，后续新增 provider 时只需扩展这里。
 * 3. 订阅返回取消函数，便于显示项移除或暂停时释放资源。
 * 4. rosbridge 连接断开后会自动重连，并在重连成功后自动恢复订阅。
 */
import * as ROSLIB from "roslib";

export interface RosLiveConfig {
  provider: string;
  url: string;
  timeoutMs?: number;
  autoReconnect?: boolean;
  reconnectBaseDelayMs?: number;
  reconnectMaxDelayMs?: number;
  reconnectMaxAttempts?: number;
  adapterName?: string;
  sharedKey?: string;
  onStatusChange?: (snapshot: RosConnectionSnapshot) => void;
  onError?: (event: RosAdapterErrorEvent) => void;
}

export interface RosConnectionSnapshot {
  connected: boolean;
  provider: string;
  message: string;
  reconnecting?: boolean;
}

export interface RosAdapterErrorEvent {
  scope: string;
  message: string;
  detail?: string;
  recoverable: boolean;
  attempt?: number;
}

export type RosMessageHandler = (message: any) => void;

export interface RosLiveAdapter {
  connect(): Promise<void>;
  disconnect(): void;
  requestReconnect(reason?: string): Promise<void>;
  subscribe(topicName: string, messageType: string, handler: RosMessageHandler): () => void;
  publish(topicName: string, messageType: string, message: Record<string, unknown>): void;
  callService<T>(serviceName: string, serviceType: string, request: Record<string, unknown>, timeoutMs?: number): Promise<T>;
  getConnectionSnapshot(): RosConnectionSnapshot;
}

export interface SharedRosSessionStats {
  sharedKey: string;
  exists: boolean;
  clientCount: number;
  subscriptionCount: number;
  connected: boolean;
  reconnecting: boolean;
  message: string;
}

interface SharedRosClientRecord {
  id: string;
  config: RosLiveConfig;
  active: boolean;
}

interface SharedSubscriptionRecord {
  topicName: string;
  messageType: string;
  handlers: Map<string, Set<RosMessageHandler>>;
  unsubscribe: (() => void) | null;
}

class SharedRosSession {
  private readonly sharedKey: string;
  private readonly config: RosLiveConfig;
  private readonly baseAdapter: RosLiveAdapter;
  private readonly clients = new Map<string, SharedRosClientRecord>();
  private readonly topicSubscriptions = new Map<string, SharedSubscriptionRecord>();
  private clientSequence = 0;

  constructor(sharedKey: string, config: RosLiveConfig) {
    this.sharedKey = sharedKey;
    this.config = config;
    this.baseAdapter = createRosLiveAdapter({
      ...config,
      sharedKey: undefined,
      adapterName: config.adapterName || "ROS 共享连接",
      onStatusChange: (snapshot) => {
        this.clients.forEach((client) => {
          client.config.onStatusChange?.(snapshot);
        });
      },
      onError: (event) => {
        this.clients.forEach((client) => {
          client.config.onError?.(event);
        });
      },
    });
  }

  createClient(config: RosLiveConfig): RosLiveAdapter {
    const clientId = `shared-client-${this.clientSequence}`;
    this.clientSequence += 1;
    this.clients.set(clientId, {
      id: clientId,
      config,
      active: false,
    });

    return {
      connect: async () => {
        const client = this.clients.get(clientId);
        if (!client) {
          return;
        }
        client.active = true;
        await this.baseAdapter.connect();
      },
      disconnect: () => {
        this.releaseClient(clientId);
      },
      requestReconnect: async (reason?: string) => {
        const client = this.clients.get(clientId);
        if (!client) {
          return;
        }
        client.active = true;
        await this.baseAdapter.requestReconnect(reason);
      },
      subscribe: (topicName: string, messageType: string, handler: RosMessageHandler) =>
        this.subscribe(clientId, topicName, messageType, handler),
      publish: (topicName: string, messageType: string, message: Record<string, unknown>) => {
        this.baseAdapter.publish(topicName, messageType, message);
      },
      callService: async <T>(serviceName: string, serviceType: string, request: Record<string, unknown>, timeoutMs?: number) => {
        return await this.baseAdapter.callService<T>(serviceName, serviceType, request, timeoutMs);
      },
      getConnectionSnapshot: () => this.baseAdapter.getConnectionSnapshot(),
    };
  }

  getStats(): SharedRosSessionStats {
    const snapshot = this.baseAdapter.getConnectionSnapshot();
    return {
      sharedKey: this.sharedKey,
      exists: true,
      clientCount: this.clients.size,
      subscriptionCount: this.topicSubscriptions.size,
      connected: snapshot.connected,
      reconnecting: Boolean(snapshot.reconnecting),
      message: snapshot.message,
    };
  }

  private releaseClient(clientId: string) {
    const client = this.clients.get(clientId);
    if (!client) {
      return;
    }

    this.topicSubscriptions.forEach((record, subscriptionKey) => {
      if (!record.handlers.has(clientId)) {
        return;
      }
      record.handlers.delete(clientId);
      if (record.handlers.size > 0) {
        return;
      }
      record.unsubscribe?.();
      this.topicSubscriptions.delete(subscriptionKey);
    });

    this.clients.delete(clientId);
    if (this.clients.size === 0) {
      this.baseAdapter.disconnect();
      sharedRosSessionMap.delete(this.sharedKey);
      return;
    }

    const hasActiveClient = Array.from(this.clients.values()).some((item) => item.active);
    if (!hasActiveClient) {
      this.baseAdapter.disconnect();
    }
  }

  private subscribe(clientId: string, topicName: string, messageType: string, handler: RosMessageHandler): () => void {
    const subscriptionKey = this.subscriptionKey(topicName, messageType);
    let record = this.topicSubscriptions.get(subscriptionKey);
    if (!record) {
      record = {
        topicName,
        messageType,
        handlers: new Map<string, Set<RosMessageHandler>>(),
        unsubscribe: null,
      };
      this.topicSubscriptions.set(subscriptionKey, record);
    }

    const clientHandlers = record.handlers.get(clientId) ?? new Set<RosMessageHandler>();
    clientHandlers.add(handler);
    record.handlers.set(clientId, clientHandlers);

    if (!record.unsubscribe) {
      record.unsubscribe = this.baseAdapter.subscribe(topicName, messageType, (message) => {
        const latestRecord = this.topicSubscriptions.get(subscriptionKey);
        if (!latestRecord) {
          return;
        }
        latestRecord.handlers.forEach((handlerSet) => {
          handlerSet.forEach((item) => item(message));
        });
      });
    }

    return () => {
      const latestRecord = this.topicSubscriptions.get(subscriptionKey);
      if (!latestRecord) {
        return;
      }
      const latestClientHandlers = latestRecord.handlers.get(clientId);
      if (!latestClientHandlers) {
        return;
      }
      latestClientHandlers.delete(handler);
      if (latestClientHandlers.size > 0) {
        return;
      }
      latestRecord.handlers.delete(clientId);
      if (latestRecord.handlers.size > 0) {
        return;
      }
      latestRecord.unsubscribe?.();
      this.topicSubscriptions.delete(subscriptionKey);
    };
  }

  private subscriptionKey(topicName: string, messageType: string) {
    return `${topicName}::${messageType}`;
  }
}

const sharedRosSessionMap = new Map<string, SharedRosSession>();
const ROSBRIDGE_HANDSHAKE_TIMEOUT_MIN_MS = 8000;

class MockRosLiveAdapter implements RosLiveAdapter {
  private readonly config: RosLiveConfig;

  constructor(config: RosLiveConfig) {
    this.config = config;
  }

  async connect(): Promise<void> {
    this.config.onStatusChange?.(this.getConnectionSnapshot());
    return Promise.resolve();
  }

  disconnect(): void {}

  requestReconnect(): Promise<void> {
    this.config.onStatusChange?.(this.getConnectionSnapshot());
    return Promise.resolve();
  }

  subscribe(topicName: string, messageType: string, handler: RosMessageHandler): () => void {
    const timer = window.setInterval(() => {
      if (messageType === "tf2_msgs/msg/TFMessage") {
        handler({
          transforms: [
            {
              child_frame_id: "base_link",
              transform: {
                translation: { x: 1.2, y: 0.4, z: 0.0 },
                rotation: { x: 0, y: 0, z: 0.32, w: 0.95 },
              },
            },
          ],
        });
        return;
      }
      if (messageType === "nav_msgs/Path") {
        handler({
          poses: Array.from({ length: 18 }, (_, index) => ({
            pose: {
              position: { x: index * 0.25, y: Math.sin(index * 0.3), z: 0 },
              orientation: { x: 0, y: 0, z: 0, w: 1 },
            },
          })),
        });
        return;
      }
      if (messageType === "geometry_msgs/PoseWithCovarianceStamped") {
        handler({
          pose: {
            pose: {
              position: { x: 1.2, y: 0.4, z: 0 },
              orientation: { x: 0, y: 0, z: 0.32, w: 0.95 },
            },
          },
        });
        return;
      }
      if (messageType === "nav_msgs/OccupancyGrid") {
        const width = 40;
        const height = 40;
        const data = Array.from({ length: width * height }, (_, index) => {
          const x = index % width;
          const y = Math.floor(index / width);
          if (x === 0 || y === 0 || x === width - 1 || y === height - 1) {
            return 100;
          }
          return (x + y) % 11 === 0 ? 100 : 0;
        });
        handler({
          info: {
            width,
            height,
            resolution: 0.15,
            origin: {
              position: { x: -3, y: -3, z: 0 },
            },
          },
          data,
        });
      }
    }, 1200);

    return () => window.clearInterval(timer);
  }

  publish(): void {}

  async callService<T>(): Promise<T> {
    return Promise.reject(new Error("mock 数据源不支持服务调用"));
  }

  getConnectionSnapshot(): RosConnectionSnapshot {
    return {
      connected: true,
      provider: this.config.provider,
      message: "当前使用 mock 实时数据源。",
      reconnecting: false,
    };
  }
}

interface SubscriptionRecord {
  id: string;
  topicName: string;
  messageType: string;
  handler: RosMessageHandler;
  topic: ROSLIB.Topic | null;
}

class RosbridgeLiveAdapter implements RosLiveAdapter {
  private readonly config: RosLiveConfig;
  private ros: ROSLIB.Ros | null = null;
  private connected = false;
  private reconnecting = false;
  private message = "尚未连接";
  private manualDisconnect = false;
  private connectPromise: Promise<void> | null = null;
  private reconnectTimer = 0;
  private reconnectAttempt = 0;
  private readonly subscriptions = new Map<string, SubscriptionRecord>();
  private subscriptionSequence = 0;
  private connectionSequence = 0;

  constructor(config: RosLiveConfig) {
    this.config = config;
  }

  connect(): Promise<void> {
    this.manualDisconnect = false;
    if (this.connected) {
      return Promise.resolve();
    }
    if (this.connectPromise) {
      return this.connectPromise;
    }
    this.connectPromise = this.openConnection();
    return this.connectPromise;
  }

  disconnect(): void {
    this.manualDisconnect = true;
    this.clearReconnectTimer();
    this.closeRosSocket();
    this.connectPromise = null;
    this.connected = false;
    this.reconnecting = false;
    this.message = "连接已关闭";
    this.emitStatus();
    this.detachAllTopicHandles();
  }

  requestReconnect(reason = "手动触发重连"): Promise<void> {
    this.reportError({
      scope: this.adapterScope(),
      message: reason,
      detail: this.config.url || "未配置地址",
      recoverable: true,
    });
    this.manualDisconnect = false;
    this.clearReconnectTimer();
    this.closeRosSocket();
    this.connectPromise = null;
    this.connected = false;
    this.reconnecting = false;
    this.detachAllTopicHandles();
    return this.connect();
  }

  subscribe(topicName: string, messageType: string, handler: RosMessageHandler): () => void {
    const id = `sub-${this.subscriptionSequence}`;
    this.subscriptionSequence += 1;
    const record: SubscriptionRecord = {
      id,
      topicName,
      messageType,
      handler,
      topic: null,
    };
    this.subscriptions.set(id, record);
    if (this.connected && this.ros) {
      this.attachSubscription(record);
    }

    return () => {
      const existing = this.subscriptions.get(id);
      if (!existing) {
        return;
      }
      this.detachSubscription(existing);
      this.subscriptions.delete(id);
    };
  }

  publish(topicName: string, messageType: string, message: Record<string, unknown>): void {
    if (!this.ros || !this.connected) {
      throw new Error("rosbridge 尚未连接");
    }

    const topic = new ROSLIB.Topic({
      ros: this.ros,
      name: topicName,
      messageType,
      queue_size: 1,
      throttle_rate: 0,
    });

    topic.publish(message as any);
  }

  async callService<T>(serviceName: string, serviceType: string, request: Record<string, unknown>, timeoutMs?: number): Promise<T> {
    if (!this.ros || !this.connected) {
      throw new Error("rosbridge 尚未连接");
    }
    const service = new ROSLIB.Service({
      ros: this.ros,
      name: serviceName,
      serviceType,
    });
    return await new Promise<T>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        reject(new Error(`调用服务超时: ${serviceName}`));
      }, Math.max(1000, timeoutMs ?? this.config.timeoutMs ?? ROSBRIDGE_HANDSHAKE_TIMEOUT_MIN_MS));
      service.callService(
        request as never,
        (response) => {
          window.clearTimeout(timer);
          resolve(response as T);
        },
        (error) => {
          window.clearTimeout(timer);
          reject(new Error(typeof error === "string" ? error : `调用服务失败: ${serviceName}`));
        }
      );
    });
  }

  getConnectionSnapshot(): RosConnectionSnapshot {
    return {
      connected: this.connected,
      provider: this.config.provider,
      message: this.message,
      reconnecting: this.reconnecting,
    };
  }

  private openConnection(): Promise<void> {
    if (!this.config.url) {
      this.message = "未配置 rosbridge 地址";
      this.emitStatus();
      return Promise.reject(new Error(this.message));
    }

    this.closeRosSocket();
    const connectionId = this.connectionSequence + 1;
    this.connectionSequence = connectionId;
    const ros = new ROSLIB.Ros();
    this.ros = ros;

    return new Promise<void>((resolve, reject) => {
      const timeoutMs = Math.max(ROSBRIDGE_HANDSHAKE_TIMEOUT_MIN_MS, this.config.timeoutMs ?? ROSBRIDGE_HANDSHAKE_TIMEOUT_MIN_MS);
      const timer = window.setTimeout(() => {
        if (!this.isActiveRos(ros, connectionId)) {
          return;
        }
        finish(() => {
          this.message = `连接超时: ${this.config.url}`;
          this.connected = false;
          this.reconnecting = false;
          this.connectPromise = null;
          this.closeActiveRosSocket(ros, connectionId);
          this.emitStatus();
          reject(new Error(this.message));
          this.scheduleReconnect("连接超时");
        });
      }, timeoutMs);
      let settled = false;

      const finish = (callback: () => void) => {
        if (settled) {
          return;
        }
        settled = true;
        window.clearTimeout(timer);
        callback();
      };

      ros.once("connection", () => {
        if (!this.isActiveRos(ros, connectionId)) {
          return;
        }
        finish(() => {
          this.connected = true;
          this.reconnecting = false;
          this.reconnectAttempt = 0;
          this.message = `已连接 ${this.config.url}`;
          this.connectPromise = null;
          this.emitStatus();
          this.restoreSubscriptions();
          resolve();
        });
      });

      ros.on("error", (error: unknown) => {
        if (!this.isActiveRos(ros, connectionId)) {
          return;
        }
        const detail = this.errorDetail(error);
        if (!settled) {
          finish(() => {
            this.connected = false;
            this.reconnecting = false;
            this.message = `连接失败: ${this.config.url}`;
            this.connectPromise = null;
            this.closeActiveRosSocket(ros, connectionId);
            this.emitStatus();
            reject(new Error(detail ? `${this.message} (${detail})` : this.message));
            this.scheduleReconnect("首次连接失败", detail);
          });
          return;
        }
        this.connected = false;
        this.message = detail ? `连接异常: ${detail}` : "连接异常";
        this.emitStatus();
        this.reportError({
          scope: this.adapterScope(),
          message: "rosbridge 连接异常",
          detail,
          recoverable: !this.manualDisconnect,
          attempt: this.reconnectAttempt,
        });
      });

      ros.on("close", () => {
        if (!this.isActiveRos(ros, connectionId)) {
          return;
        }
        this.connected = false;
        this.detachAllTopicHandles();
        if (this.manualDisconnect) {
          this.reconnecting = false;
          this.message = "连接已关闭";
          this.connectPromise = null;
          this.emitStatus();
          return;
        }
        this.message = "连接已断开，准备重连";
        this.emitStatus();
        if (!settled) {
          finish(() => {
            this.connectPromise = null;
            reject(new Error(this.message));
          });
        } else {
          this.connectPromise = null;
        }
        this.scheduleReconnect("连接已断开");
      });

      ros.connect(this.config.url);
    });
  }

  private scheduleReconnect(reason: string, detail = "") {
    if (this.manualDisconnect || this.config.autoReconnect === false || this.reconnectTimer) {
      return;
    }
    const maxAttempts = this.config.reconnectMaxAttempts;
    if (Number.isFinite(maxAttempts) && maxAttempts !== undefined && this.reconnectAttempt >= maxAttempts) {
      this.reconnecting = false;
      this.message = `连接失败，已暂停自动重连（已尝试 ${this.reconnectAttempt} 次）`;
      this.closeRosSocket();
      this.emitStatus();
      this.reportError({
        scope: this.adapterScope(),
        message: "自动重连已暂停",
        detail: detail || this.config.url,
        recoverable: true,
        attempt: this.reconnectAttempt,
      });
      return;
    }
    this.reconnectAttempt += 1;
    const baseDelay = Math.max(500, this.config.reconnectBaseDelayMs ?? 1200);
    const maxDelay = Math.max(baseDelay, this.config.reconnectMaxDelayMs ?? 8000);
    const delayMs = Math.min(maxDelay, baseDelay * Math.pow(1.7, Math.max(0, this.reconnectAttempt - 1)));
    this.reconnecting = true;
    this.message = `连接已断开，${Math.round(delayMs)} ms 后自动重连`;
    this.emitStatus();
    this.reportError({
      scope: this.adapterScope(),
      message: reason,
      detail: detail || this.config.url,
      recoverable: true,
      attempt: this.reconnectAttempt,
    });
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = 0;
      this.requestReconnect(`自动重连第 ${this.reconnectAttempt} 次`).catch((error) => {
          this.reportError({
            scope: this.adapterScope(),
            message: "自动重连失败",
            detail: this.errorDetail(error),
            recoverable: true,
            attempt: this.reconnectAttempt,
          });
      });
    }, delayMs);
  }

  private restoreSubscriptions() {
    this.subscriptions.forEach((record) => this.attachSubscription(record));
  }

  private attachSubscription(record: SubscriptionRecord) {
    if (!this.ros || record.topic) {
      return;
    }
    const topic = new ROSLIB.Topic({
      ros: this.ros,
      name: record.topicName,
      messageType: record.messageType,
      queue_size: 1,
      throttle_rate: 0,
    });
    topic.subscribe(record.handler);
    record.topic = topic;
  }

  private detachSubscription(record: SubscriptionRecord) {
    if (!record.topic) {
      return;
    }
    try {
      record.topic.unsubscribe(record.handler);
    } catch {
      // 订阅已释放时忽略重复取消，避免影响页面。
    }
    record.topic = null;
  }

  private detachAllTopicHandles() {
    this.subscriptions.forEach((record) => {
      record.topic = null;
    });
  }

  private closeRosSocket() {
    if (!this.ros) {
      return;
    }
    const ros = this.ros;
    try {
      ros.close();
    } catch {
      // 保持断开流程可继续，不因重复关闭中断。
    }
    this.ros = null;
  }

  private closeActiveRosSocket(ros: ROSLIB.Ros, connectionId: number) {
    if (!this.isActiveRos(ros, connectionId)) {
      return;
    }
    try {
      ros.close();
    } catch {
      // 连接失败路径中关闭 socket 失败时继续进入重试控制。
    }
    if (this.ros === ros) {
      this.ros = null;
    }
  }

  private isActiveRos(ros: ROSLIB.Ros, connectionId: number) {
    return this.ros === ros && this.connectionSequence === connectionId;
  }

  private clearReconnectTimer() {
    if (!this.reconnectTimer) {
      return;
    }
    window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = 0;
  }

  private emitStatus() {
    this.config.onStatusChange?.(this.getConnectionSnapshot());
  }

  private reportError(event: RosAdapterErrorEvent) {
    this.config.onError?.(event);
  }

  private adapterScope() {
    return this.config.adapterName || "ROS 实时连接";
  }

  private errorDetail(error: unknown) {
    if (error instanceof Error) {
      return error.message;
    }
    return String(error ?? "");
  }
}

export function createRosLiveAdapter(config: RosLiveConfig): RosLiveAdapter {
  if (config.provider === "mock") {
    return new MockRosLiveAdapter(config);
  }
  return new RosbridgeLiveAdapter(config);
}

export function createSharedRosLiveAdapter(config: RosLiveConfig): RosLiveAdapter {
  const sharedKey = (config.sharedKey || "").trim();
  if (!sharedKey) {
    return createRosLiveAdapter(config);
  }
  const existingSession = sharedRosSessionMap.get(sharedKey);
  if (existingSession) {
    return existingSession.createClient(config);
  }
  const nextSession = new SharedRosSession(sharedKey, config);
  sharedRosSessionMap.set(sharedKey, nextSession);
  return nextSession.createClient(config);
}

export function buildSharedRosKey(prefix: string, provider: string, url: string, timeoutMs?: number) {
  return `${prefix}:${provider}:${url}:${timeoutMs ?? ""}`;
}

export function getSharedRosSessionStats(sharedKey: string): SharedRosSessionStats {
  const normalizedKey = sharedKey.trim();
  if (!normalizedKey) {
    return {
      sharedKey: "",
      exists: false,
      clientCount: 0,
      subscriptionCount: 0,
      connected: false,
      reconnecting: false,
      message: "未启用共享连接",
    };
  }
  const session = sharedRosSessionMap.get(normalizedKey);
  if (!session) {
    return {
      sharedKey: normalizedKey,
      exists: false,
      clientCount: 0,
      subscriptionCount: 0,
      connected: false,
      reconnecting: false,
      message: "当前页面还没有建立共享连接",
    };
  }
  return session.getStats();
}
