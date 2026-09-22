// 功能说明：隔离 WebSocket 的双浏览器位姿回归，并验证路线选点后列表居中。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  const sockets = new Set();
  let x = 4,
    body = false;
  const transform = (child, value) => ({
    header: { frame_id: "map" },
    child_frame_id: child,
    transform: {
      translation: { x: value, y: 2, z: 0.3 },
      rotation: { x: 0, y: 0, z: 0, w: 1 },
    },
  });
  const emit = () => {
    for (const record of sockets)
      if (record.topics.has("/display/tf"))
        record.socket.send(
          JSON.stringify({
            op: "publish",
            topic: "/display/tf",
            msg: {
              transforms: [
                transform("base_link", x),
                ...(body ? [transform("body", x + 10)] : []),
              ],
            },
          }),
        );
  };
  const timer = setInterval(emit, 100);
  try {
    async function open() {
      const context = await browser.newContext({
        viewport: { width: 1440, height: 1000 },
      });
      const page = await context.newPage();
      await page.routeWebSocket("**", (socket) => {
        const record = { socket, topics: new Set() };
        sockets.add(record);
        socket.onClose(() => sockets.delete(record));
        socket.onMessage((raw) => {
          const m = JSON.parse(raw);
          if (m.op === "subscribe") record.topics.add(m.topic);
          if (m.op === "unsubscribe") record.topics.delete(m.topic);
          if (m.op === "call_service")
            socket.send(
              JSON.stringify({
                op: "service_response",
                id: m.id,
                service: m.service,
                result: true,
                values: { topics: [], types: [], values: [], descriptors: [] },
              }),
            );
          assert.notEqual(m.op, "publish", "回归不得发布机器人命令");
        });
      });
      await page.route("**/api/ros/**", (route) =>
        route.fulfill({
          json: route.request().url().endsWith("/data-source")
            ? {
                provider: "rosbridge",
                options: {
                  url: "ws://pose-test.invalid:9090",
                  robot_tf_frame: "body",
                  nav_layout_json:
                    '{"mainDisplays":[],"sidePanels":[],"fullPanels":[]}',
                },
              }
            : { topics: [], nodes: [], groups: [] },
        }),
      );
      await page.addInitScript(() =>
        localStorage.setItem(
          "ros-platform.navigation-tasks.v1",
          JSON.stringify({
            version: 1,
            tasks: [
              {
                id: "scroll",
                name: "列表居中",
                frame: "map",
                createdAt: new Date().toISOString(),
                points: Array.from({ length: 30 }, (_, i) => ({
                  id: `p${i}`,
                  name: `点${i}`,
                  x: i,
                  y: 0,
                  z: 0,
                  yaw: 0,
                })),
              },
            ],
          }),
        ),
      );
      await page.goto(process.env.NAV_TEST_URL || "http://localhost:5180");
      await page.getByRole("button", { name: "平台设置", exact: true }).click();
      await page.getByRole("button", { name: "连接 ROS", exact: true }).click();
      await page.getByRole("button", { name: "关闭面板", exact: true }).click();
      await page.waitForFunction(() =>
        document
          .querySelector(".pose-widget pre")
          ?.textContent.includes("4.000"),
      );
      return { page, context };
    }
    const first = await open(),
      second = await open();
    x = 5;
    for (const { page } of [first, second]) {
      await page.waitForFunction(() =>
        document
          .querySelector(".pose-widget pre")
          ?.textContent.includes("5.000"),
      );
      assert.match(await page.locator(".pose-widget").innerText(), /base_link/);
      const pose = await page.evaluate(() =>
        document
          .querySelector(".nav-viewer-shell")
          .__vueParentComponent.exposed.getTaskRobotPose(),
      );
      assert.equal(pose.x, 5);
    }
    await second.context.close();
    body = true;
    await first.page.waitForFunction(() =>
      document
        .querySelector(".pose-widget pre")
        ?.textContent.includes("15.000"),
    );
    assert.doesNotMatch(
      await first.page.locator(".pose-widget").innerText(),
      /body 暂不可用/,
    );
    const page = first.page;
    await page.getByRole("button", { name: "导航", exact: true }).click();
    await page.locator(".task-card").click();
    for (let i = 0; i < 2; i++) {
      await page.evaluate(() => {
        document.querySelector(".task-points").scrollTop = 0;
        const point = JSON.parse(
          localStorage.getItem("ros-platform.navigation-tasks.v1"),
        ).tasks[0].points[20];
        document
          .querySelector(".nav-viewer-shell")
          .__vueParentComponent.emit("taskPointSelect", point);
      });
      await page.waitForTimeout(600);
      const delta = await page.evaluate(() => {
        const list = document
          .querySelector(".task-points")
          .getBoundingClientRect();
        const row = document
          .querySelector('[data-point-id="p20"]')
          .getBoundingClientRect();
        return Math.abs((row.top + row.bottom - list.top - list.bottom) / 2);
      });
      assert.ok(delta < 3, `选中行应居中，偏差 ${delta}`);
    }
    console.log(
      "PASS two clients, disconnect isolation, base_link fallback, body priority, selected row centering",
    );
  } finally {
    clearInterval(timer);
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
