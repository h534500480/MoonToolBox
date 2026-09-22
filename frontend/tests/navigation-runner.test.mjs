// 功能说明：验证逐点调度、反馈去重、暂停竞态、失败停止及取消后的迟到消息。
import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
import ts from "typescript";
const compile = (source) =>
  `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText).toString("base64")}`;
const taskModule = compile(
  await readFile(
    new URL("../src/lib/navigationTasks.ts", import.meta.url),
    "utf8",
  ),
);
const runnerSource = (
  await readFile(
    new URL("../src/lib/navigationRunner.ts", import.meta.url),
    "utf8",
  )
).replace(/from ['"]\.\/navigationTasks['"]/, `from '${taskModule}'`);
const { NavigationRunner, navigationTransport } = await import(
  compile(runnerSource)
);
const makeTask = () => ({
  id: "task-1",
  name: "巡检",
  frame: "map",
  createdAt: new Date().toISOString(),
  points: [0, 1, 2].map((index) => ({
    id: `p${index}`,
    name: `点${index}`,
    x: index,
    y: 0,
    z: 0,
    yaw: 0,
  })),
});
const tick = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
function harness(options = {}) {
  const sent = [],
    controls = [];
  let listener;
  const transport = {
    available: true,
    async sendGoal(request) {
      sent.push(request);
      return options.send
        ? options.send(request)
        : { ok: true, message: "接受" };
    },
    async control(command, request) {
      controls.push({ command, ...request });
      return options.control
        ? options.control(command)
        : { ok: true, message: "确认" };
    },
    subscribe(callback) {
      listener = callback;
      return () => {
        listener = null;
      };
    },
  };
  const runner = new NavigationRunner(transport, () => {});
  const feedback = (request = sent.at(-1), status = "succeeded") =>
    listener?.({ runId: request.runId, goalId: request.goalId, status });
  return { runner, sent, controls, feedback };
}
{
  const h = harness(),
    task = makeTask();
  task.points[0].roll = 0.3;
  task.points[0].pitch = -0.2;
  await h.runner.start(task);
  assert.equal(h.sent[0].point.roll, 0.3);
  assert.equal(h.sent[0].point.pitch, -0.2);
  assert.equal(h.sent.length, 1);
  assert.equal(h.runner.state.completed, 0);
  task.points[1].x = 999;
  const first = h.sent[0];
  h.feedback(first);
  await tick();
  assert.equal(h.sent.length, 2);
  assert.equal(h.sent[1].point.x, 1);
  h.feedback(first);
  h.feedback({ ...first, runId: "old" });
  await tick();
  assert.equal(h.sent.length, 2);
  h.feedback();
  await tick();
  assert.equal(h.sent.length, 3);
  h.feedback();
  await tick();
  assert.equal(h.runner.state.status, "completed");
  assert.equal(h.runner.state.completed, 3);
}
{
  const h = harness();
  await h.runner.start(makeTask());
  await h.runner.control("pause");
  h.feedback();
  await tick();
  assert.equal(h.sent.length, 1);
  assert.equal(h.runner.state.status, "paused");
  await h.runner.control("resume");
  await tick();
  assert.equal(h.sent.length, 2);
  const second = h.sent[1];
  await h.runner.control("cancel");
  h.feedback(second);
  await tick();
  assert.equal(h.runner.state.status, "cancelled");
  assert.equal(h.sent.length, 2);
  await h.runner.start(makeTask());
  h.feedback(second);
  await tick();
  assert.equal(h.sent.length, 3);
}
{
  const ack = deferred(),
    h = harness({ control: () => ack.promise });
  await h.runner.start(makeTask());
  const pause = h.runner.control("pause");
  h.feedback();
  await tick();
  assert.equal(h.sent.length, 1);
  ack.resolve({ ok: true, message: "暂停" });
  await pause;
  assert.equal(h.runner.state.status, "paused");
  await h.runner.control("resume");
  await tick();
  assert.equal(h.sent.length, 2);
}
{
  const h = harness();
  await h.runner.start(makeTask());
  h.feedback(undefined, "failed");
  await tick();
  assert.equal(h.sent.length, 1);
  assert.equal(h.runner.state.status, "failed");
  h.feedback();
  assert.equal(h.sent.length, 1);
}
{
  const ack = deferred(),
    h = harness({ send: () => ack.promise });
  const start = h.runner.start(makeTask());
  h.feedback();
  await tick();
  assert.equal(h.sent.length, 1);
  ack.resolve({ ok: true, message: "接受" });
  await start;
  await tick();
  assert.equal(h.sent.length, 2);
}
{
  const h = harness({ send: () => ({ ok: false, message: "拒绝" }) });
  await h.runner.start(makeTask());
  assert.equal(h.runner.state.status, "failed");
  assert.equal(h.sent.length, 1);
  const r = new NavigationRunner(navigationTransport, () => {});
  await r.start(makeTask());
  assert.equal(r.state.status, "idle");
  assert.match(r.state.message, /未下发/);
}
{
  const h = harness({
    control: () => {
      throw new Error("连接断开");
    },
  });
  await h.runner.start(makeTask());
  await h.runner.control("pause");
  assert.equal(h.runner.state.status, "running");
  assert.match(h.runner.state.message, /控制失败/);
  h.runner.dispose();
  h.feedback();
  assert.equal(h.sent.length, 1);
}
console.log(
  "逐点执行回归通过：确认不推进、到达后续发、重复/过期反馈、快照、暂停竞态、取消、失败与未接入保护。",
);
