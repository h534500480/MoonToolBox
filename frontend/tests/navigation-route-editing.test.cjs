// 功能说明：通过真实浏览器验证列表拖动、路线插点、持久化及视角拖动防误触。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(process.env.NAV_TEST_URL || "http://localhost:5180");
    await page.getByRole("button", { name: "导航", exact: true }).click();
    await page.getByRole("button", { name: "新建", exact: true }).click();
    await page.getByRole("button", { name: "创建任务", exact: true }).click();
    await page.getByRole("button", { name: "地图打点", exact: true }).click();
    await page.mouse.click(600, 500);
    await page.waitForTimeout(300);
    await page.mouse.click(860, 380);
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: "完成打点", exact: true }).click();
    await page.waitForTimeout(250);
    const read = () =>
      page.evaluate(
        () =>
          JSON.parse(localStorage.getItem("ros-platform.navigation-tasks.v1"))
            .tasks[0].points,
      );
    const original = await read();
    assert.equal(original.length, 2);
    await page.mouse.click(730, 440);
    await page.waitForTimeout(300);
    const inserted = await read();
    assert.equal(inserted.length, 3, "点击路线应插入点位");
    assert.equal(inserted[0].id, original[0].id);
    assert.equal(inserted[2].id, original[1].id);
    const a = original[0],
      b = original[1],
      c = inserted[1];
    assert.ok(
      Math.abs((c.x - a.x) * (b.y - a.y) - (c.y - a.y) * (b.x - a.x)) < 0.001,
    );
    await page.getByRole("button", { name: "保存点位", exact: true }).click();
    await page.waitForTimeout(250);
    const rows = page.locator(".task-point");
    await rows
      .first()
      .dragTo(rows.last(), { targetPosition: { x: 70, y: 28 } });
    await page.waitForTimeout(250);
    assert.deepEqual(
      (await read()).map((p) => p.id),
      [inserted[1].id, inserted[2].id, inserted[0].id],
    );
    await rows.last().dragTo(rows.first(), { targetPosition: { x: 70, y: 2 } });
    await page.waitForTimeout(250);
    assert.deepEqual(
      (await read()).map((p) => p.id),
      inserted.map((p) => p.id),
    );
    // 路线上的拖动用于调整视角，不能当成单击插点。
    await page.mouse.move(665, 470);
    await page.mouse.down();
    await page.mouse.move(695, 490, { steps: 8 });
    await page.mouse.up();
    assert.equal((await read()).length, 3);
    await page.reload();
    await page.getByRole("button", { name: "导航", exact: true }).click();
    await page.locator(".task-card").click();
    assert.deepEqual(
      (await read()).map((p) => p.id),
      inserted.map((p) => p.id),
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS route insertion, drag reorder both directions, persistence, orbit guard",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
