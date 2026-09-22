// 功能说明：使用隔离消息源验证 ROS 协议关联、逐点队列、控制确认与断流保护。
import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import ts from "typescript";
const compile = (source) =>
  `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText).toString("base64")}`;
const tasks = compile(
  await readFile(
    new URL("../src/lib/navigationTasks.ts", import.meta.url),
    "utf8",
  ),
);
const runnerCode = (
  await readFile(
    new URL("../src/lib/navigationRunner.ts", import.meta.url),
    "utf8",
  )
).replace(/from ["']\.\/navigationTasks["']/, `from '${tasks}'`);
const { NavigationRunner } = await import(compile(runnerCode));
const { RosNavigationTransport } = await import(
  compile(
    await readFile(
      new URL("../src/lib/rosNavigationTransport.ts", import.meta.url),
      "utf8",
    ),
  )
);
const tick = () => new Promise((resolve) => setImmediate(resolve));
const goalContext = (id, result = "path_ready", extra = {}) => ({
  request_planid: id,
  last_result: result,
  goal_active: result === "path_ready",
  request_sent: result === "planning" || result === "path_ready",
  request_completed: result === "reached",
  paused_by_user: false,
  paused_by_localization: false,
  ...extra,
});
function harness() {
  let now = 10000,
    connected = true;
  const listeners = new Map(),
    sent = [];
  const adapter = {
    getConnectionSnapshot: () => ({ connected }),
    subscribe: (topic, type, cb) => {
      listeners.set(topic, cb);
      return () => listeners.delete(topic);
    },
    publish: (topic, type, msg) =>
      sent.push({ topic, type, data: JSON.parse(msg.data) }),
  };
  const transport = new RosNavigationTransport(
    () => {},
    () => now,
    { freshnessMs: 3000, acknowledgementMs: 40 },
  );
  transport.bind(adapter, "robot-a");
  const context = (id, result, extra) =>
    listeners.get("/nav2_goal_context")({
      data: JSON.stringify(goalContext(id, result, extra)),
    });
  const loc = (value) => listeners.get("/nav_ndt_status")({ data: value });
  loc(1);
  context("", "idle");
  const runner = new NavigationRunner(transport, () => {});
  const task = {
    id: "task",
    name: "任务",
    frame: "map",
    createdAt: new Date().toISOString(),
    points: [0, 1, 2].map((i) => ({
      id: `p${i}`,
      name: `点${i}`,
      x: i,
      y: 1,
      z: 0.3,
      roll: 0.2,
      pitch: 0.1,
      yaw: 0.5,
    })),
  };
  return {
    transport,
    runner,
    task,
    sent,
    context,
    loc,
    advance: (t) => {
      now += t;
      transport.connectionChanged(connected);
    },
    disconnect: () => {
      connected = false;
      transport.connectionChanged(false);
    },
    reconnect: () => {
      connected = true;
      transport.connectionChanged(true);
    },
    dispose: () => {
      runner.dispose();
      transport.dispose();
    },
    id: () =>
      sent.filter((m) => m.topic === "/nav2_goal_request").at(-1)?.data
        .request_planid,
  };
}
{
  const h = harness();
  const starting = h.runner.start(h.task);
  assert.equal(h.runner.state.status, "sending");
  assert.equal(h.sent.length, 1);
  const first = h.id();
  assert.deepEqual(h.sent[0].data.pose, {
    frame_id: "map",
    x: 0,
    y: 1,
    z: 0.3,
    yaw: 0.5,
  });
  assert.equal(h.sent[0].data.context.point_index, 1);
  h.context("old", "reached");
  assert.equal(h.sent.length, 1);
  h.context(first, "planning");
  await starting;
  assert.equal(h.runner.state.status, "running");
  h.context(first, "path_ready", { scan_state: "WAIT_TARGET" });
  h.context(first, "reached", { request_completed: false });
  assert.equal(h.sent.length, 1);
  h.context(first, "odom_timeout");
  assert.equal(h.runner.state.status, "running");
  h.loc(0);
  h.context(first, "reached");
  assert.equal(h.runner.state.status, "blocked");
  assert.equal(h.sent.length, 1);
  h.loc(1);
  await tick();
  assert.equal(h.sent.length, 2);
  assert.equal(h.runner.state.completed, 1);
  const second = h.id();
  assert.notEqual(second, first);
  h.context(first, "reached");
  assert.equal(h.sent.length, 2);
  h.context(second, "path_ready");
  await tick();
  h.advance(3100);
  assert.equal(h.runner.state.status, "unknown");
  assert.equal(h.sent.length, 2);
  h.context(second, "reached");
  assert.equal(h.sent.length, 2);
  h.loc(2);
  await tick();
  assert.equal(h.sent.length, 3);
  h.context(h.id(), "planning_failed");
  await tick();
  assert.equal(h.runner.state.status, "failed");
  assert.equal(h.runner.state.completed, 2);
  h.dispose();
}
{
  const h = harness();
  const start = h.runner.start(h.task);
  const id = h.id();
  h.context(id);
  await start;
  const pause = h.runner.control("pause");
  assert.equal(h.runner.state.status, "pausing");
  assert.deepEqual(h.sent.at(-1).data, { command: "pause" });
  h.context(id, "paused", { paused_by_user: true });
  await pause;
  assert.equal(h.runner.state.status, "paused");
  const resume = h.runner.control("resume");
  h.context(id, "planning");
  await resume;
  assert.equal(h.runner.state.status, "running");
  const cancel = h.runner.control("cancel");
  h.context("", "canceled");
  await cancel;
  assert.equal(h.runner.state.status, "cancelled");
  assert.equal(h.runner.state.completed, 0);
  assert.equal(
    h.sent.filter((m) => m.topic === "/nav2_goal_request").length,
    1,
  );
  h.dispose();
}
{
  const h = harness();
  await h.runner.start(h.task);
  assert.equal(h.runner.state.status, "unknown");
  assert.equal(h.sent.length, 1);
  const id = h.id();
  h.context(id, "path_ready");
  assert.equal(h.runner.state.status, "running");
  h.context("external", "path_ready");
  assert.equal(h.runner.state.status, "unknown");
  await h.runner.control("cancel");
  assert.equal(h.sent.length, 1);
  h.context(id, "path_ready");
  h.disconnect();
  assert.equal(h.runner.state.status, "unknown");
  h.reconnect();
  assert.equal(h.transport.available, false);
  h.loc(1);
  h.context(id, "reached");
  await tick();
  assert.equal(h.sent.length, 1);
  assert.equal(h.runner.state.status, "cancelled");
  h.dispose();
}
{
  const h = harness();
  h.loc(3);
  await h.runner.start(h.task);
  assert.equal(h.sent.length, 0);
  h.loc(1);
  h.context("external", "paused", { paused_by_user: true });
  await h.runner.start(h.task);
  assert.equal(h.sent.length, 0);
  h.dispose();
}
{
  const h = harness();
  const start = h.runner.start(h.task);
  const id = h.id();
  h.context(id);
  await start;
  const cancel = h.runner.control("cancel");
  h.disconnect();
  h.reconnect();
  h.loc(1);
  h.context("", "canceled");
  await cancel;
  assert.equal(h.runner.state.status, "unknown");
  assert.equal(h.runner.state.completed, 0);
  assert.equal(
    h.sent.filter((m) => m.topic === "/nav2_goal_request").length,
    1,
  );
  h.dispose();
}
{
  const h = harness();
  const start = h.runner.start(h.task);
  const id = h.id();
  h.context(id);
  await start;
  const cancel = h.runner.control("cancel");
  h.context(id, "reached");
  await cancel;
  assert.equal(h.runner.state.status, "cancelled");
  assert.equal(h.runner.state.completed, 1);
  assert.equal(
    h.sent.filter((m) => m.topic === "/nav2_goal_request").length,
    1,
  );
  h.dispose();
}
{
  const code = (
    await readFile(
      new URL("../src/lib/navigationOwnership.ts", import.meta.url),
      "utf8",
    )
  ).replace(/from ["']\.\/navigationTasks["']/, `from '${tasks}'`);
  const { createNavigationOwnership } = await import(compile(code));
  const values = new Map();
  globalThis.localStorage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const first = createNavigationOwnership(),
    second = createNavigationOwnership();
  assert.equal(await first.acquire("robot"), true);
  assert.equal(await second.acquire("robot"), false);
  first.dispose();
  assert.equal(await second.acquire("robot"), true);
  assert.equal(first.owns("robot"), false);
  second.dispose();
  delete globalThis.localStorage;
}
for (const command of ["pause", "cancel"]) {
  const h = harness();
  const start = h.runner.start(h.task);
  const id = h.id();
  h.context(id);
  await start;
  await h.runner.control(command);
  assert.equal(h.runner.state.status, "unknown");
  h.context(id, "reached");
  await tick();
  assert.equal(
    h.runner.state.status,
    command === "cancel" ? "cancelled" : "paused",
  );
  assert.equal(
    h.sent.filter((m) => m.topic === "/nav2_goal_request").length,
    1,
  );
  h.dispose();
}
console.log(
  "ROS navigation protocol tests passed: correlation, acceptance, completion, sequential dispatch, recovery, localization, stale status, pause/resume/cancel, timeout and foreign goal protection.",
);
