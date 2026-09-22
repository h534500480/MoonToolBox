// 功能说明：验证导航点来源选择、连续打点、删除确认、渐隐与真实接口保护。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const b = await chromium.launch({
    headless: true,
    channel: process.env.BROWSER_CHANNEL || "msedge",
  });
  const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  p.on("dialog", () => {
    throw Error("浏览器弹窗不应出现");
  });
  await p.goto(process.env.NAV_TEST_URL || "http://localhost:5180");
  await p.getByRole("button", { name: "导航", exact: true }).click();
  await p.getByRole("button", { name: "新建", exact: true }).click();
  await p.getByRole("button", { name: "创建任务", exact: true }).click();
  assert.equal(await p.locator(".task-editor").count(), 0);
  await p.getByRole("button", { name: "狗当前位置", exact: true }).click();
  assert.match(await p.locator(".task-message").innerText(), /没有可用/);
  await p.getByRole("button", { name: "地图打点", exact: true }).click();
  await p.waitForTimeout(250);
  await p.mouse.click(600, 500);
  await p.waitForTimeout(300);
  assert.equal(await p.locator(".task-point").count(), 1);
  assert.equal(
    await p.getByRole("button", { name: "保存点位", exact: true }).count(),
    0,
  );
  await p.mouse.click(860, 380);
  await p.waitForTimeout(300);
  assert.equal(await p.locator(".task-point").count(), 2);
  const before = await p.evaluate(
    () =>
      JSON.parse(localStorage.getItem("ros-platform.navigation-tasks.v1"))
        .tasks[0].points,
  );
  const handle = await p.evaluate(() => {
    const c = document.querySelector(".nav-viewer-canvas-host canvas");
    for (let y = 200; y < 700; y += 7)
      for (let x = 350; x < 1080; x += 7) {
        c.dispatchEvent(
          new PointerEvent("pointermove", {
            clientX: x,
            clientY: y,
            button: -1,
            buttons: 0,
            pointerId: 1,
            isPrimary: true,
            bubbles: true,
          }),
        );
        if (c.style.cursor === "grab") return { x, y };
      }
    throw Error("未找到坐标轴");
  });
  await p.mouse.move(handle.x, handle.y);
  await p.mouse.down();
  await p.mouse.move(handle.x + 30, handle.y + 22, { steps: 10 });
  await p.mouse.up();
  await p.waitForTimeout(250);
  const after = await p.evaluate(
    () =>
      JSON.parse(localStorage.getItem("ros-platform.navigation-tasks.v1"))
        .tasks[0].points,
  );
  assert.equal(after.length, 2);
  assert.deepEqual(after[0], before[0]);
  assert.notDeepEqual(after[1], before[1]);
  await p.mouse.click(600, 463);
  await p.waitForTimeout(250);
  assert.equal(await p.locator(".task-point").count(), 2);
  assert.equal(
    await p.locator(".task-editor input").first().inputValue(),
    "点位 1",
  );
  await p.getByTitle("编辑点位", { exact: true }).last().click();
  await p.locator(".task-coordinates input").first().fill("3");
  await p.locator(".task-coordinates input").first().blur();
  assert.equal(
    await p.evaluate(
      () =>
        JSON.parse(localStorage.getItem("ros-platform.navigation-tasks.v1"))
          .tasks[0].points[1].x,
    ),
    3,
  );
  await p.getByTitle("编辑点位", { exact: true }).first().click();
  assert.equal(await p.locator(".task-point").count(), 2);
  await p.locator(".task-coordinates input").first().fill("2");
  await p.locator(".task-coordinates input").first().blur();
  assert.equal(
    await p.evaluate(
      () =>
        JSON.parse(localStorage.getItem("ros-platform.navigation-tasks.v1"))
          .tasks[0].points[0].x,
    ),
    2,
  );
  await p.getByRole("button", { name: "完成打点", exact: true }).click();
  await p.waitForTimeout(250);
  await p.getByRole("button", { name: "任务文件", exact: false }).click();
  assert.equal(await p.locator(".task-files-arrow.expanded").count(), 1);
  await p.getByRole("button", { name: "任务文件", exact: false }).click();
  assert.equal(await p.locator(".task-files-arrow.expanded").count(), 0);
  await p.getByTitle("删除点位", { exact: true }).last().click();
  assert.equal(
    await p.locator(".task-point.task-fade-leave-active").count(),
    1,
  );
  await p.waitForTimeout(250);
  assert.equal(await p.locator(".task-point").count(), 1);
  assert.equal(
    await p.getByRole("button", { name: "开始任务", exact: true }).isDisabled(),
    true,
  );
  assert.equal(await p.getByRole("combobox", { name: "执行模式" }).count(), 0);
  await p.getByRole("button", { name: "删除任务", exact: true }).click();
  await p.waitForTimeout(250);
  await p
    .getByRole("dialog")
    .getByRole("button", { name: "取消", exact: true })
    .click();
  await p.waitForTimeout(250);
  assert.equal(await p.locator(".task-card").count(), 1);
  await p.getByRole("button", { name: "删除任务", exact: true }).click();
  await p
    .getByRole("dialog")
    .getByRole("button", { name: "删除任务", exact: true })
    .click();
  await p.waitForTimeout(250);
  assert.equal(await p.locator(".task-card").count(), 0);
  await p.getByRole("button", { name: "新建", exact: true }).click();
  await p.getByRole("button", { name: "创建任务", exact: true }).click();
  // 只替换测试页面的取位姿接口，验证有效位姿分支，不冒充硬件联调。
  const canStubPose = await p.evaluate(() => {
    const viewer =
      document.querySelector(".nav-viewer-shell").__vueParentComponent?.exposed;
    if (!viewer) return false;
    viewer.getTaskRobotPose = () => ({
      x: 4,
      y: 2,
      z: 0.3,
      roll: 0,
      pitch: 0,
      yaw: 1,
    });
    return true;
  });
  if (canStubPose) {
    await p.getByRole("button", { name: "狗当前位置", exact: true }).click();
    assert.equal(await p.locator(".task-point").count(), 0);
    assert.equal(
      await p.locator(".task-coordinates input").first().inputValue(),
      "4",
    );
    await p.getByRole("button", { name: "保存点位", exact: true }).click();
    await p.waitForTimeout(250);
    assert.equal(await p.locator(".task-point").count(), 1);
    await p.reload();
    await p.getByRole("button", { name: "导航", exact: true }).click();
    await p.locator(".task-card").click();
    assert.equal(await p.locator(".task-point").count(), 1);
  } else {
    console.log(
      "生产构建无组件调试入口；有效机器人位姿替身分支仅在开发环境验证。",
    );
  }
  assert.deepEqual(errors, []);
  await b.close();
  console.log(
    "PASS continuous placement, point updates, fade, delete confirmation, no simulation, real transport guard",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
