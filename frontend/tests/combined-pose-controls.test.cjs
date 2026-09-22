// 功能说明：用浏览器实际拖动组合控件，验证平移、旋转、相机锁定和清理。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const b = await chromium.launch({
    headless: true,
    channel: process.env.BROWSER_CHANNEL || "msedge",
  });
  const p = await b.newPage({ viewport: { width: 1000, height: 760 } });
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(
    (process.env.NAV_TEST_URL || "http://localhost:5180") +
      "/tests/combined-pose-controls.html",
  );
  await p.waitForFunction(() => window.poseTest);
  await p.waitForTimeout(300);
  async function find(mode, axis) {
    return p.evaluate(
      ({ mode, axis }) => {
        const { controls, renderer } = poseTest;
        for (let y = 190; y < 570; y += 5)
          for (let x = 300; x < 700; x += 5) {
            renderer.domElement.dispatchEvent(
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
            if (
              controls[mode].axis === axis &&
              !controls[mode === "translate" ? "rotate" : "translate"].axis
            )
              return { x, y };
          }
        throw Error("No handle " + mode + axis);
      },
      { mode, axis },
    );
  }
  async function drag(mode, axis) {
    const pt = await find(mode, axis);
    await p.mouse.move(pt.x, pt.y);
    const before = await p.evaluate(() => poseTest.snapshot());
    await p.mouse.down();
    let during = await p.evaluate(() => poseTest.snapshot());
    assert.equal(during.dragging, true);
    assert.equal(during.enabled, false);
    await p.mouse.move(pt.x + 45, pt.y + 30, { steps: 12 });
    await p.mouse.up();
    const after = await p.evaluate(() => poseTest.snapshot());
    assert.equal(after.dragging, false);
    assert.equal(after.enabled, true);
    assert.ok(
      after.camera.every((v, i) => Math.abs(v - before.camera[i]) < 1e-9),
    );
    assert.deepEqual(after.target, before.target);
    if (mode === "translate") {
      assert.notDeepEqual(after.position, before.position);
      assert.deepEqual(after.rotation, before.rotation);
    } else {
      assert.notDeepEqual(after.rotation, before.rotation);
      assert.deepEqual(after.position, before.position);
    }
    console.log("PASS drag", mode, axis);
  }
  await drag("translate", "X");
  await drag("rotate", "Z");
  await drag("rotate", "X");
  await p.locator("#yaw").click();
  await drag("translate", "Y");
  await drag("rotate", "Z");
  await drag("rotate", "X");
  await drag("rotate", "Y");
  assert.equal(await p.evaluate(() => poseTest.controls.rotate.showX), true);
  assert.equal(await p.evaluate(() => poseTest.controls.rotate.showY), true);
  const pt = await find("translate", "X");
  await p.mouse.move(pt.x, pt.y);
  await p.mouse.down();
  await p.evaluate(() => window.dispatchEvent(new Event("blur")));
  assert.equal(await p.evaluate(() => poseTest.snapshot().enabled), true);
  await p.mouse.up();
  // 放大到四倍观察距离时世界尺寸只增至两倍，屏幕尺寸相应减半。
  const sizes = await p.evaluate(() => {
    const { camera, object, controls } = poseTest;
    const previous = camera.position.clone();
    const values = [12, 48].map((distance) => {
      camera.position
        .copy(object.position)
        .add(previous.clone().normalize().multiplyScalar(distance));
      controls.updateScale();
      return controls.translate.size * distance;
    });
    camera.position.copy(previous);
    controls.updateScale();
    return values;
  });
  assert.ok(Math.abs(sizes[1] / sizes[0] - 2) < 0.001);
  await p.evaluate(() => poseTest.setPointPriority(true));
  await p.mouse.move(pt.x, pt.y);
  await p.mouse.down();
  assert.equal(await p.evaluate(() => poseTest.controls.dragging), false);
  await p.mouse.up();
  await p.evaluate(() => poseTest.setPointPriority(false));
  await p.evaluate(() => poseTest.controls.detach());
  assert.equal(
    await p.evaluate(() => poseTest.controls.getHelper().visible),
    false,
  );
  await p.evaluate(() => poseTest.controls.dispose());
  assert.deepEqual(errors, []);
  console.log(
    "PASS combined handles, all three rotation axes in both modes, blur, detach, dispose, no errors",
  );
  await b.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
