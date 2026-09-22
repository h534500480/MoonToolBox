// 功能说明：验证导航任务文件边界、点位距离及未接入传输的拒绝语义。
import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import ts from "typescript";
const source = await readFile(
  new URL("../src/lib/navigationTasks.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
});
const { parseTasks, taskDistance, createTaskId, routeInsertionYaw } =
  await import(
    `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
  );
const task = {
  id: "task",
  name: "巡检",
  frame: "map",
  createdAt: "2026-09-18T00:00:00Z",
  points: [
    { id: "a", name: "起点", x: 0, y: 0, z: 0, yaw: 0 },
    { id: "b", name: "终点", x: 3, y: 4, z: 0, yaw: 1 },
  ],
};
const encode = (tasks) => JSON.stringify({ version: 1, tasks });
assert.deepEqual(parseTasks(encode([task])), [
  {
    ...task,
    points: task.points.map((point) => ({ ...point, roll: 0, pitch: 0 })),
  },
]);
const tilted = {
  ...task,
  points: task.points.map((point) => ({ ...point, roll: 0.3, pitch: -0.2 })),
};
assert.deepEqual(parseTasks(encode([tilted])), [tilted]);
assert.throws(() =>
  parseTasks(
    encode([{ ...task, points: [{ ...task.points[0], roll: null }] }]),
  ),
);
assert.equal(taskDistance(task), 5);
assert.equal(taskDistance({ ...task, points: [] }), 0);
assert.throws(() => parseTasks(encode([task, task])));
assert.throws(() =>
  parseTasks(encode([{ ...task, points: [task.points[0], task.points[0]] }])),
);
assert.throws(() =>
  parseTasks(encode([{ ...task, points: [{ ...task.points[0], x: null }] }])),
);
assert.throws(() => parseTasks(encode([{ ...task, frame: "" }])));
assert.throws(() => parseTasks('{"version":2,"tasks":[]}'));
assert.throws(() => parseTasks("null"));
const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
Object.defineProperty(globalThis, "crypto", {
  configurable: true,
  value: {
    getRandomValues: originalCrypto.get
      .call(globalThis)
      .getRandomValues.bind(originalCrypto.get.call(globalThis)),
  },
});
assert.equal(new Set(Array.from({ length: 1000 }, createTaskId)).size, 1000);
Object.defineProperty(globalThis, "crypto", {
  configurable: true,
  value: undefined,
});
assert.notEqual(createTaskId(), createTaskId());
Object.defineProperty(globalThis, "crypto", originalCrypto);
console.log("导航任务协议回归通过。");
const pose = (x, y, yaw = 0) => ({ x, y, z: 0, yaw });
assert.ok(
  Math.abs(
    routeInsertionYaw(pose(0, 0), pose(1, 0), pose(1, 1)) - Math.PI / 4,
  ) < 1e-9,
);
assert.ok(
  Math.abs(
    Math.abs(routeInsertionYaw(pose(1, 0.01), pose(0, 0), pose(-1, 0.01))) -
      Math.PI,
  ) < 1e-9,
);
assert.equal(routeInsertionYaw(pose(0, 0), pose(1, 0, 1.2), pose(0, 0)), 1.2);
assert.equal(routeInsertionYaw(pose(0, 0), pose(0, 0, 1.2), pose(0, 0)), 1.2);
console.log("插点方向：转弯、跨正负 π、折返及重合点通过。");
