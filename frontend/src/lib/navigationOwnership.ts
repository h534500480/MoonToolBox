// 功能说明：同浏览器同来源的导航控制租约，避免多个页面同时操作全局控制话题。
import { createTaskId } from "./navigationTasks";
export interface NavigationOwnership {
  available(source: string): boolean;
  acquire(source: string): Promise<boolean>;
  owns(source: string): boolean;
  refresh(): void;
  dispose(): void;
}
/** 跨来源和其他设备仍需导航端仲裁；租约丢失时禁止本页面继续发送控制。 */
export function createNavigationOwnership(): NavigationOwnership {
  const owner = createTaskId();
  let source = "";
  const key = (value: string) => `ros-platform.navigation-owner:${value}`;
  const read = (value: string) =>
    JSON.parse(localStorage.getItem(key(value)) || "null") as {
      owner: string;
      expires: number;
    } | null;
  const owns = (value: string) => {
    try {
      const lease = read(value);
      return lease?.owner === owner && lease.expires > Date.now();
    } catch {
      return false;
    }
  };
  return {
    available(value) {
      try {
        const lease = read(value);
        return !lease || lease.owner === owner || lease.expires <= Date.now();
      } catch {
        return false;
      }
    },
    async acquire(value) {
      if (!this.available(value)) return false;
      try {
        if (source && source !== value) this.dispose();
        source = value;
        localStorage.setItem(
          key(source),
          JSON.stringify({ owner, expires: Date.now() + 5000 }),
        );
        // 给并发页面的写入留出观察窗口，再确认租约归属。
        await new Promise((resolve) => setTimeout(resolve, 80));
        return owns(value);
      } catch {
        return false;
      }
    },
    owns,
    refresh() {
      try {
        if (source && read(source)?.owner === owner)
          localStorage.setItem(
            key(source),
            JSON.stringify({ owner, expires: Date.now() + 5000 }),
          );
      } catch {
        /* 存储失效后由归属检查阻止继续发送。 */
      }
    },
    dispose() {
      try {
        if (source && read(source)?.owner === owner)
          localStorage.removeItem(key(source));
      } catch {
        /* 无法移除时等待短租约自然失效。 */
      } finally {
        source = "";
      }
    },
  };
}
