// 功能说明：验证触屏草稿确认、取消、组合输入、紧凑面板与原有桌面输入分流。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  try {
    const page = await browser.newPage({
      viewport: { width: 915, height: 412 },
      hasTouch: true,
      isMobile: true,
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(process.env.NAV_TEST_URL || "http://localhost:5180");
    await page.getByRole("button", { name: "导航", exact: true }).click();
    await page.getByRole("button", { name: "新建", exact: true }).click();
    const original = page.locator(".task-create-dialog input").first();
    const initial = await original.inputValue();
    await page.locator(".mobile-input-panel input").fill("不应保存的草稿");
    assert.equal(await original.inputValue(), initial);
    await page
      .locator(".mobile-input-panel")
      .getByRole("button", { name: "取消", exact: true })
      .click();
    await page.waitForTimeout(180);
    assert.equal(await original.inputValue(), initial);
    await original.click();
    await page.evaluate(() =>
      window.dispatchEvent(
        new CustomEvent("ros-window-insets", { detail: { imeOverlap: 180 } }),
      ),
    );
    const floating = await page.locator(".mobile-input-panel").boundingBox();
    assert.ok(
      floating.y + floating.height <= 412 - 180,
      "输入层必须位于键盘上方",
    );
    await page.evaluate(() =>
      window.dispatchEvent(
        new CustomEvent("ros-window-insets", { detail: { imeOverlap: 0 } }),
      ),
    );
    await page.waitForTimeout(180);
    assert.equal(await original.inputValue(), initial);
    await original.click();
    await page.locator(".mobile-input-panel input").fill("触屏巡检");
    await page
      .locator(".mobile-input-panel input")
      .dispatchEvent("keydown", { key: "Enter", isComposing: true });
    assert.equal(await original.inputValue(), initial);
    await page
      .locator(".mobile-input-panel")
      .getByRole("button", { name: "确定", exact: true })
      .click();
    await page.waitForTimeout(180);
    assert.equal(await original.inputValue(), "触屏巡检");
    await page.getByRole("button", { name: "创建任务", exact: true }).click();
    assert.equal(await page.locator(".task-sidebar").isVisible(), false);
    await page.getByRole("button", { name: "地图打点", exact: true }).click();
    await page.touchscreen.tap(420, 230);
    await page.waitForTimeout(300);
    assert.equal(await page.locator(".task-point").count(), 1);
    await page.touchscreen.tap(510, 160);
    await page.waitForTimeout(300);
    assert.equal(await page.locator(".task-point").count(), 2);
    // 连续打点的坐标仍只在悬浮输入确认后保存。
    const coordinate = page.locator(".task-coordinates input").first();
    await coordinate.click();
    const read = () =>
      page.evaluate(
        () =>
          JSON.parse(localStorage.getItem("ros-platform.navigation-tasks.v1"))
            .tasks[0].points,
      );
    const before = await read();
    await page.locator(".mobile-input-panel input").fill("-1.25");
    assert.deepEqual(await read(), before);
    await page
      .locator(".mobile-input-panel")
      .getByRole("button", { name: "确定", exact: true })
      .click();
    await page.waitForTimeout(200);
    assert.equal((await read())[1].x, -1.25);
    await page.getByRole("button", { name: "完成打点", exact: true }).click();
    await page.waitForTimeout(180);
    await page.locator(".task-details").evaluate((element) => {
      element.scrollTop +=
        element.querySelector(".task-number").getBoundingClientRect().top -
        element.getBoundingClientRect().top -
        60;
    });
    const rows = page.locator(".task-number");
    const first = await rows.first().boundingBox(),
      second = await rows.last().boundingBox();
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [
        { x: first.x + first.width / 2, y: first.y + first.height / 2 },
      ],
    });
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [
        { x: second.x + second.width / 2, y: second.y + second.height - 2 },
      ],
    });
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchEnd",
      touchPoints: [],
    });
    await page.waitForTimeout(250);
    assert.equal((await read())[1].id, before[0].id, "触屏编号手柄应调整顺序");
    const controls = await page.locator(".task-controls").boundingBox();
    assert.ok(
      controls.y + controls.height <= 412,
      "横屏底部控件不能落到屏幕外",
    );
    await page.screenshot({
      path:
        process.env.MOBILE_SCREENSHOT ||
        "C:/Users/Admin/AppData/Local/Temp/ros-mobile-interaction.png",
    });
    assert.deepEqual(errors, []);
    const desktop = await browser.newPage({
      viewport: { width: 915, height: 650 },
    });
    await desktop.goto(process.env.NAV_TEST_URL || "http://localhost:5180");
    await desktop.getByRole("button", { name: "导航", exact: true }).click();
    await desktop.getByRole("button", { name: "新建", exact: true }).click();
    assert.equal(await desktop.locator(".mobile-input-panel").count(), 0);
    await desktop
      .locator(".task-create-dialog input")
      .first()
      .fill("桌面直接输入");
    const offline = await browser.newPage();
    await offline.route("**/api/tools", (route) => route.abort());
    await offline.goto(
      (process.env.NAV_TEST_URL || "http://localhost:5180") + "/tools/pcd-map",
    );
    await offline.getByRole("link", { name: "返回定位与导航" }).click();
    await offline.getByRole("button", { name: "导航", exact: true }).waitFor();
    console.log(
      "PASS mobile draft/confirm/cancel/IME, touch placement, autosave boundary, compact panel and desktop routing",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
