// 功能说明：发行版将用户偏好同步到本机服务，使切换端口后任务和设置仍可恢复。
function allowed(key: string): boolean {
  return (key.startsWith("ros-platform.") && !key.includes("owner")) ||
    ["moontoolbox.rosNavMobileState", "moontoolbox.rosPlatform.navConfig"].includes(key);
}

/** 只在本机 HTTP 发行服务启用；网页开发和 Android 保持原存储方式。 */
export async function restoreDesktopProfile(): Promise<void> {
  if (location.hostname !== "127.0.0.1" || location.protocol !== "http:") return;
  let active = false;
  const warn = () => {
    if (document.getElementById("desktop-profile-warning")) return;
    const message = document.createElement("div");
    message.id = "desktop-profile-warning";
    message.setAttribute("role", "alert");
    message.textContent = "本机设置同步失败，请导出重要任务备份，并检查数据目录中的 desktop.log。";
    message.style.cssText = "position:fixed;bottom:4px;left:10%;right:10%;z-index:9999;background:#fff0d9;color:#553d22;padding:8px;border-radius:8px;font-size:12px";
    document.body.append(message);
  };
  try {
    const identity = await fetch("/api/desktop/instance", { signal: AbortSignal.timeout(2500) });
    if (!identity.ok || (await identity.json()).product !== "ROSPlatform") return;
    active = true;
    const response = await fetch("/api/desktop/profile", { signal: AbortSignal.timeout(4000) });
    if (!response.ok) throw new Error("无法读取本机设置");
    const values: Record<string, string> = await response.json();
    for (const [key, value] of Object.entries(values)) {
      if (allowed(key) && typeof value === "string") localStorage.setItem(key, value);
    }
    // 串行提交保持同一标签页的编辑顺序，失败时明确提示，避免误认为已备份。
    let pending = Promise.resolve();
    const persist = (key: string, value: string | null) => {
      pending = pending.then(async () => {
        const body = JSON.stringify({ key, value });
        const saved = await fetch("/api/desktop/profile", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body, keepalive: new Blob([body]).size < 60000, signal: AbortSignal.timeout(8000),
        });
        if (!saved.ok) throw new Error("本机设置保存失败");
      }).catch(warn);
    };
    // 新安装首次打开时备份原来源的设置，不同步导航控制租约。
    for (let index = 0; index < localStorage.length; index++) {
      const key = localStorage.key(index)!;
      if (allowed(key) && !(key in values)) persist(key, localStorage.getItem(key));
    }
    const originalSet = Storage.prototype.setItem;
    const originalRemove = Storage.prototype.removeItem;
    Storage.prototype.setItem = function(key: string, value: string) {
      originalSet.call(this, key, value);
      if (this === localStorage && allowed(key)) persist(key, String(value));
    };
    Storage.prototype.removeItem = function(key: string) {
      originalRemove.call(this, key);
      if (this === localStorage && allowed(key)) persist(key, null);
    };
  } catch {
    if (active) warn();
  }
}
