// 功能说明：验证物理分辨率与 CSS 视口不同情况下，三种工作模式的边界、滚动和预设持久化。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  try {
    for (const config of [
      { width: 800, height: 360, dpr: 4, preset: "wide-3200" },
      { width: 1280, height: 576, dpr: 2.5, preset: "wide-3200" },
      { width: 3200, height: 1440, dpr: 1, preset: "wide-3200" },
      { width: 915, height: 412, dpr: 2.625, preset: "phone" },
      { width: 390, height: 844, dpr: 3, preset: "phone" },
    ]) {
      const page = await browser.newPage({ viewport: { width: config.width, height: config.height }, deviceScaleFactor: config.dpr, hasTouch: true, isMobile: true });
      const errors = []; page.on("pageerror", e => errors.push(e.message));
      await page.addInitScript(preset => {
        localStorage.setItem("ros-platform.layout-preset.v1", preset);
        localStorage.setItem("ros-platform.navigation-tasks.v1", JSON.stringify({ version: 1, tasks: Array.from({ length: 6 }, (_, i) => ({ id: `t${i}`, name: `巡检 ${i + 1}`, frame: "map", createdAt: new Date().toISOString(), points: [] })) }));
      }, config.preset);
      await page.goto(process.env.NAV_TEST_URL || "http://localhost:5180");
      await page.getByRole("button", { name: "平台设置", exact: true }).click();
      assert.equal(await page.getByRole("combobox", { name: "分辨率 / 布局预设" }).inputValue(), config.preset);
      await page.getByRole("button", { name: "关闭面板", exact: true }).click();
      for (const mode of ["定位", "导航", "建图"]) {
        await page.getByRole("button", { name: mode, exact: true }).click();
        await page.waitForTimeout(250);
        const selectors = mode === "定位" ? [".monitor-dock", ".topics-drawer", ".platform-toolbelt", ".pose-widget"] : mode === "导航" ? [".task-sidebar", ".task-controls", ".task-connection", ".pose-widget"] : [".mapping-source-panel", ".mapping-output-panel", ".mapping-control-bar", ".pose-widget"];
        selectors.push(".platform-top-left");
        const boxes = await page.evaluate(selectors => selectors.flatMap(selector => {
          const element = document.querySelector(selector);
          if (!element || !element.checkVisibility({ visibilityProperty: true })) return [];
          const r = element.getBoundingClientRect();
          return [{ selector, x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height }];
        }), selectors);
        for (const r of boxes) {
          assert.ok(r.x >= -1 && r.y >= -1 && r.right <= config.width + 1 && r.bottom <= config.height + 1 && r.height > 20, `${config.width} ${mode} 越界 ${JSON.stringify(r)}`);
        }
        for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
          const a = boxes[i], b = boxes[j];
          const overlap = Math.min(a.right,b.right)-Math.max(a.x,b.x) > 2 && Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>2;
          assert.ok(!overlap, `${config.width} ${mode} 遮挡 ${a.selector} / ${b.selector}`);
        }
        if (mode === "定位") {
          const dock = page.locator(".monitor-dock");
          await dock.evaluate(el => { el.scrollTop = el.scrollHeight; });
          if (await dock.isVisible()) assert.ok(await dock.evaluate(el => el.scrollHeight <= el.clientHeight || el.scrollTop > 0), "监控内容应可滚动");
        }
        if (mode === "建图" && config.preset === "phone") {
          await page.locator(".mapping-mobile-switch").getByText("地图产物", { exact: true }).click();
          assert.equal(await page.locator(".mapping-source-panel").isVisible(), false);
          assert.equal(await page.locator(".mapping-output-panel").isVisible(), true);
          await page.getByRole("button", { name: "建图配置", exact: true }).click();
        }
        if (config.width === 800) await page.screenshot({ path: `C:/Users/Admin/AppData/Local/Temp/layout-3200-${mode}.png`, scale: "css" });
        if (mode === "导航") {
          await page.locator(".task-card").first().click();
          const details = await page.locator(".task-details").boundingBox();
          assert.ok(details && details.y >= 0 && details.x >= 0 && details.x + details.width <= config.width + 1 && details.y + details.height <= config.height - 100, "任务详情应保持在面板安全区内");
        }
      }
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`PASS ${config.width}x${config.height} DPR ${config.dpr} ${config.preset}`);
    }
    const page = await browser.newPage({ viewport: { width: 800, height: 360 }, hasTouch: true, deviceScaleFactor: 4 });
    await page.goto(process.env.NAV_TEST_URL || "http://localhost:5180");
    await page.locator('html[data-layout]').waitFor();
    assert.equal(await page.locator("html").getAttribute("data-layout"), "wide-3200");
    await page.getByRole("button", { name: "平台设置", exact: true }).click();
    await page.getByRole("combobox", { name: "分辨率 / 布局预设" }).selectOption("phone");
    await page.reload();
    await page.locator('html[data-layout]').waitFor();
    assert.equal(await page.locator("html").getAttribute("data-layout"), "phone");
    console.log("PASS automatic 3200 detection, settings switch and persistence");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
