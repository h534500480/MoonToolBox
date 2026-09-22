// 功能说明：运行真实发行程序，验证切换端口后的任务/布局恢复和深层页面静态资源。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");

(async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "ros-profile-"));
  const executable = path.resolve(process.argv[2]);
  let server;
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const stop = async () => {
    if (server && server.exitCode === null) {
      const ended = new Promise(resolve => server.once("exit", resolve));
      server.kill();
      await ended;
    }
    await fs.rm(path.join(directory, "instance.json"), { force: true });
  };
  const start = async () => {
    server = spawn(executable, ["--headless", "--no-browser", "--data-dir", directory, "--port", "0"], { windowsHide: true, stdio: "ignore" });
    for (let attempt = 0; attempt < 300; attempt++) {
      assert.equal(server.exitCode, null, "发行服务不应提前退出");
      try {
        const state = JSON.parse(await fs.readFile(path.join(directory, "instance.json"), "utf8"));
        return `http://127.0.0.1:${state.port}`;
      } catch { await new Promise(resolve => setTimeout(resolve, 100)); }
    }
    throw new Error("发行服务启动超时");
  };
  try {
    const first = await start();
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(first);
    await page.getByRole("button", { name: "平台设置", exact: true }).click();
    await page.getByRole("combobox", { name: "分辨率 / 布局预设" }).selectOption("wide-3200");
    await page.evaluate(() => localStorage.setItem("ros-platform.navigation-tasks.v1", JSON.stringify({ version: 1, tasks: [{ id: "deployment-test", name: "跨端口保留任务", frame: "map", createdAt: new Date().toISOString(), points: [] }] })));
    await page.waitForFunction(async () => {
      const profile = await (await fetch("/api/desktop/profile")).json();
      return profile["ros-platform.layout-preset.v1"] === "wide-3200" && profile["ros-platform.navigation-tasks.v1"]?.includes("跨端口保留任务");
    });
    await stop();
    const second = await start();
    assert.notEqual(second, first);
    await page.goto(second);
    await page.getByRole("button", { name: "导航", exact: true }).click();
    await page.getByText("跨端口保留任务", { exact: true }).waitFor();
    assert.equal(await page.locator("html").getAttribute("data-layout"), "wide-3200");
    await page.goto(second + "/tools/imu-calibration");
    await page.waitForFunction(() => document.querySelector("#app")?.childElementCount > 0);
    assert.equal(await page.locator("#desktop-profile-warning").count(), 0);
    assert.deepEqual(errors, []);
    console.log("PASS: 真实发行版跨端口任务/布局恢复、深层页面加载、浏览器无异常");
  } finally {
    await browser.close();
    await stop();
    await fs.rm(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
