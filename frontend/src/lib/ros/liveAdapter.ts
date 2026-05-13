/**
 * 功能说明：
 * 为导航测试页提供统一的 ROS 实时数据接入层。
 *
 * 设计要点：
 * 1. 前端只依赖这个抽象，不直接散落使用 roslib。
 * 2. 当前实现 rosbridge 和 mock 两种 provider，后续新增 provider 时只需扩展这里。
 * 3. 订阅返回取消函数，便于显示项移除或暂停时释放资源。
 */
import * as ROSLIB from "roslib";

export interface RosLiveConfig {
  provider: string;
  url: string;
  timeoutMs?: number;
}

export interface RosConnectionSnapshot {
  connected: boolean;
  provider: string;
  message: string;
}

export type RosMessageHandler = (message: any) => void;

export interface RosLiveAdapter {
  connect(): Promise<void>;
  disconnect(): void;
  subscribe(topicName: string, messageType: string, handler: RosMessageHandler): () => void;
  publish(topicName: string, messageType: string, message: Record<string, unknown>): void;
  getConnectionSnapshot(): RosConnectionSnapshot;
}

class MockRosLiveAdapter implements RosLiveAdapter {
  private readonly config: RosLiveConfig;

  constructor(config: RosLiveConfig) {
    this.config = config;
  }

  async connect(): Promise<void> {
    return Promise.resolve();
  }

  disconnect(): void {}

  subscribe(topicName: string, messageType: string, handler: RosMessageHandler): () => void {
    const timer = window.setInterval(() => {
      if (messageType === "tf2_msgs/TFMessage") {
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

  getConnectionSnapshot(): RosConnectionSnapshot {
    return {
      connected: true,
      provider: this.config.provider,
      message: "当前使用 mock 实时数据源。",
    };
  }
}

class RosbridgeLiveAdapter implements RosLiveAdapter {
  private readonly config: RosLiveConfig;
  private ros: ROSLIB.Ros | null = null;
  private connected = false;
  private message = "尚未连接";

  constructor(config: RosLiveConfig) {
    this.config = config;
  }

  connect(): Promise<void> {
    if (this.ros && this.connected) {
      return Promise.resolve();
    }

    this.disconnect();
    this.ros = new ROSLIB.Ros();

    return new Promise<void>((resolve, reject) => {
      const timeoutMs = Math.max(500, this.config.timeoutMs ?? 3000);
      const timer = window.setTimeout(() => {
        this.message = `连接超时: ${this.config.url}`;
        reject(new Error(this.message));
      }, timeoutMs);

      const cleanup = () => window.clearTimeout(timer);

      this.ros?.once("connection", () => {
        cleanup();
        this.connected = true;
        this.message = `已连接 ${this.config.url}`;
        resolve();
      });

      this.ros?.once("error", () => {
        cleanup();
        this.connected = false;
        this.message = `连接失败: ${this.config.url}`;
        reject(new Error(this.message));
      });

      this.ros?.once("close", () => {
        this.connected = false;
        this.message = "连接已关闭";
      });

      this.ros?.connect(this.config.url);
    });
  }

  disconnect(): void {
    if (this.ros) {
      try {
        this.ros.close();
      } catch {
        // 保持断开流程可继续，不因重复关闭中断。
      }
    }
    this.ros = null;
    this.connected = false;
  }

  subscribe(topicName: string, messageType: string, handler: RosMessageHandler): () => void {
    if (!this.ros) {
      return () => {};
    }

    const topic = new ROSLIB.Topic({
      ros: this.ros,
      name: topicName,
      messageType,
      queue_size: 1,
      throttle_rate: 0,
    });

    topic.subscribe(handler);

    return () => {
      try {
        topic.unsubscribe(handler);
      } catch {
        // 订阅已释放时忽略重复取消，避免影响页面。
      }
    };
  }

  publish(topicName: string, messageType: string, message: Record<string, unknown>): void {
    if (!this.ros) {
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

  getConnectionSnapshot(): RosConnectionSnapshot {
    return {
      connected: this.connected,
      provider: this.config.provider,
      message: this.message,
    };
  }
}

export function createRosLiveAdapter(config: RosLiveConfig): RosLiveAdapter {
  if (config.provider === "mock") {
    return new MockRosLiveAdapter(config);
  }
  return new RosbridgeLiveAdapter(config);
}
