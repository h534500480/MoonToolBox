// 功能说明：拦截所有浏览器 WebSocket，用隔离协议端验证导航 UI；绝不连接现场 ROS。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    channel: process.env.BROWSER_CHANNEL || "msedge",
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [],
    goals = [],
    commands = [],
    sockets = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let context = {
    request_planid: "",
    last_result: "idle",
    request_completed: false,
    request_sent: false,
    goal_active: false,
    paused_by_user: false,
    paused_by_localization: false,
    scan_state: "INIT",
  };
  let contextEnabled = true;
  const emit = () => {
    for (const { socket, topics } of sockets) {
      if (topics.has("/nav_ndt_status"))
        socket.send(
          JSON.stringify({
            op: "publish",
            topic: "/nav_ndt_status",
            msg: { data: 1 },
          }),
        );
      if (contextEnabled && topics.has("/nav2_goal_context"))
        socket.send(
          JSON.stringify({
            op: "publish",
            topic: "/nav2_goal_context",
            msg: { data: JSON.stringify(context) },
          }),
        );
    }
  };
  await page.routeWebSocket("**", (socket) => {
    const topics = new Set();
    sockets.push({ socket, topics });
    socket.onMessage((raw) => {
      const m = JSON.parse(raw);
      if (m.op === "subscribe") {
        topics.add(m.topic);
        emit();
      }
      if (m.op === "unsubscribe") topics.delete(m.topic);
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
      if (m.op === "publish" && m.topic === "/nav2_goal_request") {
        const goal = JSON.parse(m.msg.data);
        goals.push(goal);
        context = {
          ...context,
          request_planid: goal.request_planid,
          last_result: "path_ready",
          request_sent: true,
          goal_active: true,
          request_completed: false,
          paused_by_user: false,
        };
        emit();
      }
      if (m.op === "publish" && m.topic === "/nav2_goal_control") {
        const command = JSON.parse(m.msg.data).command;
        commands.push(command);
        context = {
          ...context,
          last_result:
            command === "pause"
              ? "paused"
              : command === "resume"
                ? "planning"
                : "canceled",
          paused_by_user: command === "pause",
          request_planid: command === "cancel" ? "" : context.request_planid,
          request_sent: command === "resume",
          goal_active: false,
        };
        emit();
      }
    });
  });
  await page.route("**/api/ros/**", (route) => {
    const url = route.request().url();
    route.fulfill({
      json: url.endsWith("/data-source")
        ? {
            provider: "rosbridge",
            options: {
              url: "ws://navigation-test.invalid:9090",
              timeout_ms: "8000",
              nav_layout_json:
                '{"mainDisplays":[],"sidePanels":[],"fullPanels":[]}',
            },
          }
        : {
            provider: "rosbridge",
            topics: [],
            nodes: [],
            groups: [],
            message: "测试数据",
          },
    });
  });
  await page.addInitScript(() =>
    localStorage.setItem(
      "ros-platform.navigation-tasks.v1",
      JSON.stringify({
        version: 1,
        tasks: [
          {
            id: "ui-test",
            name: "协议任务",
            frame: "map",
            createdAt: new Date().toISOString(),
            points: [0, 1, 2].map((i) => ({
              id: "p" + i,
              name: "点" + i,
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
  const timer = setInterval(emit, 150);
  try {
    await page.goto(process.env.NAV_TEST_URL || "http://localhost:5180");
    await page.getByRole("button", { name: "平台设置", exact: true }).click();
    await page.getByRole("button", { name: "连接 ROS", exact: true }).click();
    await page.getByRole("button", { name: "关闭面板", exact: true }).click();
    await page.getByRole("button", { name: "导航", exact: true }).click();
    await page.locator(".task-card").click();
    await page.getByRole("button", { name: "开始任务", exact: true }).click();
    await page.waitForTimeout(300);
    assert.equal(goals.length, 1);
    assert.match(await page.locator(".task-execution").innerText(), /0 \/ 3/);
    context = { ...context, scan_state: "WAIT_TARGET" };
    emit();
    await page.waitForTimeout(200);
    assert.equal(goals.length, 1);
    context = {
      ...context,
      last_result: "reached",
      request_completed: true,
      request_sent: false,
      goal_active: false,
    };
    emit();
    await page.waitForTimeout(300);
    assert.equal(goals.length, 2);
    assert.notEqual(goals[0].request_planid, goals[1].request_planid);
    await page.getByRole("button", { name: "暂停", exact: true }).click();
    await page.waitForTimeout(100);
    assert.match(await page.locator(".task-execution").innerText(), /已暂停/);
    await page.getByRole("button", { name: "继续", exact: true }).click();
    await page.waitForTimeout(100);
    assert.deepEqual(commands, ["pause", "resume"]);
    contextEnabled = false;
    await page.waitForTimeout(3300);
    assert.match(await page.locator(".task-execution").innerText(), /状态未知/);
    assert.equal(goals.length, 2);
    contextEnabled = true;
    emit();
    await page.waitForTimeout(100);
    await page.getByRole("button", { name: "取消任务", exact: true }).click();
    await page.waitForTimeout(100);
    assert.match(await page.locator(".task-execution").innerText(), /已取消/);
    assert.equal(goals.length, 2);
    assert.deepEqual(commands, ["pause", "resume", "cancel"]);
    assert.deepEqual(errors, []);
    console.log(
      "PASS isolated ROS UI: connect, goal, reached-only sequential dispatch, pause/resume, stale status, empty-id cancellation",
    );
  } finally {
    clearInterval(timer);
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
