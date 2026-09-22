<!-- 功能说明：导航任务侧栏与点位草稿编辑；本地任务和真实执行状态分离。 -->
<script setup lang="ts">
import {
  computed,
  ref,
  watch,
  onMounted,
  onBeforeUnmount,
  nextTick,
} from "vue";
import {
  Plus,
  X,
  Pencil,
  Trash2,
  LocateFixed,
  MapPin,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  Download,
  Play,
  Pause,
  Square,
  ArrowUp,
  ArrowDown,
} from "@lucide/vue";
import {
  createTaskId,
  parseTasks,
  taskDistance,
  validTaskPose,
  type NavigationTask,
  type TaskPoint,
  type TaskPose,
  type TaskRouteInsertion,
  type TaskScene,
} from "../lib/navigationTasks";
import {
  NavigationRunner,
  navigationTransport,
  isRunActive,
  runStatusLabels,
  type NavigationTransport,
} from "../lib/navigationRunner";
import type { NavigationConnectionState } from "../lib/rosNavigationTransport";
const props = defineProps<{
  active: boolean;
  frame: string;
  viewer: TaskScene | null;
  transport?: NavigationTransport;
  navigationStatus?: NavigationConnectionState;
}>();
const emit = defineEmits<{
  picking: [value: boolean];
  points: [points: TaskPoint[]];
}>();
const poseHelperHint =
  "拖动箭头或平面移动；红、绿、蓝圆环分别绕 X、Y、Z 轴旋转。";
const storageKey = "ros-platform.navigation-tasks.v1";
const mapHintPreferenceKey = "ros-platform.navigation-map-hint.dismissed";
const mapHint = "在地图上按下并拖动设置方向，松开后可移动、旋转或修改坐标。";
const transientMessages = new Set([
  mapHint,
  "任务已创建，请设置第一个点位。",
  "当前没有可用的真实机器人位姿，请连接定位数据或在地图上打点。",
]);
let mapHintShown = false;
let mapHintDisabled = false;
let messageTimer: ReturnType<typeof setTimeout> | undefined;
const tasks = ref<NavigationTask[]>([]),
  selectedId = ref(""),
  message = ref("");
/** 短提示在新操作前关闭；捕获阶段不干扰本次操作产生的新提示。 */
function dismissTransientMessage(event: Event) {
  if ((event.target as Element | null)?.closest?.("[data-dismiss-map-hint]"))
    return;
  if (transientMessages.has(message.value)) message.value = "";
}
function disableMapHint() {
  mapHintDisabled = true;
  message.value = "";
  try {
    localStorage.setItem(mapHintPreferenceKey, "true");
  } catch (error) {
    message.value = `无法保存“不再提示”设置，本次页面内仍生效：${(error as Error).message}`;
  }
}
watch(
  message,
  (value) => {
    clearTimeout(messageTimer);
    if (transientMessages.has(value)) {
      messageTimer = setTimeout(() => {
        message.value = "";
      }, 2000);
    }
  },
  { flush: "sync" },
);
watch(
  selectedId,
  () => {
    mapHintShown = false;
  },
  { flush: "sync" },
);
watch(
  () => props.active,
  () => {
    if (transientMessages.has(message.value)) message.value = "";
  },
);
onMounted(() => {
  document.addEventListener("pointerdown", dismissTransientMessage, true);
  document.addEventListener("click", dismissTransientMessage, true);
  document.addEventListener("keydown", dismissTransientMessage, true);
});
onBeforeUnmount(() => {
  clearTimeout(messageTimer);
  document.removeEventListener("pointerdown", dismissTransientMessage, true);
  document.removeEventListener("click", dismissTransientMessage, true);
  document.removeEventListener("keydown", dismissTransientMessage, true);
});
const collapsed = ref(false),
  filesOpen = ref(false),
  picking = ref(false);
const draft = ref<TaskPoint | null>(null),
  hasPose = ref(false);
const pointSection = ref<HTMLElement | null>(null);
/** 只滚动任务列表，不触发页面或三维工作区滚动；等待编辑面板布局完成。 */
watch(
  () => draft.value,
  async (point) => {
    const id = point?.id;
    if (!id) return;
    await nextTick();
    requestAnimationFrame(() => {
      const list =
        pointSection.value?.querySelector<HTMLElement>(".task-points");
      const row =
        list &&
        (Array.from(list.children).find(
          (item) => (item as HTMLElement).dataset.pointId === id,
        ) as HTMLElement | undefined);
      if (!list || !row) return;
      const bounds = list.getBoundingClientRect(),
        target = row.getBoundingClientRect();
      list.scrollTo({
        top:
          list.scrollTop +
          target.top -
          bounds.top -
          (list.clientHeight - target.height) / 2,
        behavior: "smooth",
      });
    });
  },
);
const task = computed(() =>
  tasks.value.find((item) => item.id === selectedId.value),
);
const draftIndex = computed(
  () =>
    task.value?.points.findIndex((point) => point.id === draft.value?.id) ?? -1,
);
const choosingPoint = ref(false);
const mapAdding = ref(false);
const deletingTask = ref<NavigationTask | null>(null);
const deleteCancelButton = ref<HTMLButtonElement>();
watch(deletingTask, async (value) => {
  if (value) {
    await nextTick();
    deleteCancelButton.value?.focus();
  }
});
const compatible = computed(() => task.value?.frame === props.frame);
const fileInput = ref<HTMLInputElement>();
const creating = ref(false),
  newName = ref(""),
  newKind = ref("自定义任务");
const nameInput = ref<HTMLInputElement>();
const runner = new NavigationRunner(
  props.transport ?? navigationTransport,
  (state) => {
    execution.value = state;
  },
);
const execution = ref({ ...runner.state });
const running = computed(() => isRunActive(execution.value));
const locked = computed(
  () => running.value && execution.value.taskId === task.value?.id,
);
const selectedRun = computed(() => execution.value.taskId === task.value?.id);
onBeforeUnmount(() => runner.dispose());
async function command(value: "start" | "pause" | "resume" | "cancel") {
  if (value === "start") {
    if (!task.value || draft.value || !compatible.value || running.value)
      return;
    await runner.start(task.value);
  } else await runner.control(value);
  // 执行结果由进度区持续展示，避免同一条消息再遮挡任务进度。
  message.value = execution.value.total ? "" : execution.value.message;
}
async function openCreate() {
  newName.value = `导航任务 ${tasks.value.length + 1}`;
  newKind.value = "自定义任务";
  creating.value = true;
  await nextTick();
  nameInput.value?.focus();
  nameInput.value?.select();
}
try {
  mapHintDisabled = localStorage.getItem(mapHintPreferenceKey) === "true";
  const raw = localStorage.getItem(storageKey);
  if (raw) tasks.value = parseTasks(raw);
} catch (error) {
  message.value = `读取本地任务失败：${(error as Error).message}`;
}
watch(
  tasks,
  (value) => {
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({ version: 1, tasks: value }),
      );
    } catch (error) {
      message.value = `保存任务失败，请导出备份：${(error as Error).message}`;
    }
  },
  { deep: true },
);
watch(
  () => [props.active, props.frame, task.value] as const,
  () => {
    emit(
      "points",
      props.active && compatible.value ? task.value?.points || [] : [],
    );
  },
  { deep: true, immediate: true },
);
watch(
  () => [props.active, props.frame],
  () => {
    cancelEdit();
    creating.value = false;
    deletingTask.value = null;
  },
);
/** 草稿取消不影响已保存点位，也不把任务点发布为初始定位。 */
function cancelEdit() {
  choosingPoint.value = false;
  mapAdding.value = false;
  picking.value = false;
  emit("picking", false);
  props.viewer?.clearInitialPoseCandidate();
  draft.value = null;
  hasPose.value = false;
}
function selectTask(id: string) {
  cancelEdit();
  selectedId.value = id;
}
function createTask() {
  if (!newName.value.trim()) {
    message.value = "请填写任务名称。";
    return;
  }
  if (tasks.value.length >= 200) {
    message.value = "任务数量已达 200，请先导出并删除不需要的任务。";
    return;
  }
  cancelEdit();
  const value: NavigationTask = {
    id: createTaskId(),
    name: newName.value.trim(),
    kind: newKind.value,
    frame: props.frame,
    createdAt: new Date().toISOString(),
    points: [],
  };
  tasks.value.push(value);
  selectedId.value = value.id;
  collapsed.value = false;
  creating.value = false;
  message.value = "任务已创建，请设置第一个点位。";
  choosingPoint.value = true;
}
/** 先选择取点方式，再生成草稿，避免添加空坐标点。 */
function beginAddPoint() {
  if (locked.value || !compatible.value) return;
  cancelEdit();
  choosingPoint.value = true;
}
function editPoint(point?: TaskPoint) {
  if (locked.value) {
    message.value = "执行中的任务不可编辑，请先取消任务。";
    return;
  }
  if (!point && (task.value?.points.length || 0) >= 1000) {
    message.value = "每个任务最多 1000 个点位。";
    return;
  }
  const continuous = mapAdding.value && !!point;
  cancelEdit();
  if (!compatible.value) return;
  mapAdding.value = continuous;
  picking.value = continuous;
  emit("picking", continuous);
  draft.value = point
    ? { ...point }
    : {
        id: createTaskId(),
        name: `点位 ${(task.value?.points.length || 0) + 1}`,
        x: 0,
        y: 0,
        z: 0,
        yaw: 0,
        roll: 0,
        pitch: 0,
      };
  hasPose.value = !!point;
  if (point) props.viewer?.editTaskPose(point);
}
/** 坐标轴只更新选中点；连续地图模式实时保存，普通编辑保留手动确认。 */
function receivePose(pose: TaskPose) {
  if (!draft.value || !validTaskPose(pose)) return;
  Object.assign(draft.value, {
    x: Number(pose.x.toFixed(3)),
    y: Number(pose.y.toFixed(3)),
    z: Number(pose.z.toFixed(3)),
    yaw: Number(pose.yaw.toFixed(4)),
    roll: Number((pose.roll ?? 0).toFixed(4)),
    pitch: Number((pose.pitch ?? 0).toFixed(4)),
  });
  hasPose.value = true;
  persistMapDraft();
}
/** 地图空白处完成点选后直接入列，保留连续打点与当前点坐标轴。 */
function placeMapPoint(pose: TaskPose) {
  if (
    !mapAdding.value ||
    locked.value ||
    !compatible.value ||
    !task.value ||
    !validTaskPose(pose)
  )
    return;
  if (task.value.points.length >= 1000) {
    message.value = "每个任务最多 1000 个点位。";
    return;
  }
  clearEditedResult();
  const point: TaskPoint = {
    ...pose,
    id: createTaskId(),
    name: `点位 ${task.value.points.length + 1}`,
  };
  task.value.points.push(point);
  draft.value = { ...point };
  hasPose.value = true;
}
function persistMapDraft() {
  if (
    !mapAdding.value ||
    !task.value ||
    !draft.value ||
    !validTaskPose(draft.value) ||
    !draft.value.name.trim()
  )
    return;
  const index = task.value.points.findIndex(
    (point) => point.id === draft.value!.id,
  );
  if (index < 0) return;
  clearEditedResult();
  task.value.points[index] = { ...draft.value, name: draft.value.name.trim() };
}
function useRobot() {
  const pose = props.viewer?.getTaskRobotPose();
  if (!pose) {
    message.value =
      "当前没有可用的真实机器人位姿，请连接定位数据或在地图上打点。";
    return;
  }
  editPoint();
  if (!draft.value) return;
  receivePose(pose);
  props.viewer?.editTaskPose(pose);
  message.value = "已复制机器狗当前位置和朝向。";
}
function pickMap() {
  if (locked.value || !compatible.value) return;
  cancelEdit();
  mapAdding.value = true;
  picking.value = true;
  emit("picking", true);
  if (!mapHintDisabled && !mapHintShown) {
    mapHintShown = true;
    message.value = mapHint;
  }
}
function updatePose() {
  if (!draft.value || !validTaskPose(draft.value)) return;
  hasPose.value = true;
  persistMapDraft();
  props.viewer?.editTaskPose(draft.value);
}
function clearEditedResult() {
  if (selectedRun.value && !running.value) runner.clearResult();
}
function savePoint() {
  if (locked.value || !compatible.value) return;
  if (
    !task.value ||
    !draft.value ||
    !hasPose.value ||
    !validTaskPose(draft.value) ||
    !draft.value.name.trim()
  ) {
    message.value = "请填写点位名称并设置有效坐标。";
    return;
  }
  clearEditedResult();
  const index = task.value.points.findIndex(
    (point) => point.id === draft.value!.id,
  );
  const point = { ...draft.value, name: draft.value.name.trim() };
  if (index < 0) task.value.points.push(point);
  else task.value.points[index] = point;
  cancelEdit();
}
function removePoint(id: string) {
  if (locked.value) return;
  if (!task.value) return;
  clearEditedResult();
  if (draft.value?.id === id) {
    const continuous = mapAdding.value;
    cancelEdit();
    mapAdding.value = continuous;
    picking.value = continuous;
    emit("picking", continuous);
  }
  task.value.points = task.value.points.filter((point) => point.id !== id);
}
function movePoint(index: number, offset: number) {
  if (locked.value) return;
  const points = task.value?.points;
  if (!points || index + offset < 0 || index + offset >= points.length) return;
  clearEditedResult();
  points.splice(index + offset, 0, points.splice(index, 1)[0]);
}
const draggedPoint = ref("");
const dropPoint = ref("");
const dropAfter = ref(false);
function endPointDrag() {
  draggedPoint.value = "";
  dropPoint.value = "";
}
watch([selectedId, locked], endPointDrag);
/** 仅在松手时修改顺序，拖动预览不会改变正在编辑的点位身份。 */
function startPointDrag(event: DragEvent, id: string) {
  if (locked.value || (event.target as HTMLElement).closest("button")) {
    event.preventDefault();
    return;
  }
  draggedPoint.value = id;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", id);
  }
}
function previewPointDrop(event: DragEvent, id: string) {
  if (!draggedPoint.value || locked.value) return;
  event.preventDefault();
  const row = event.currentTarget as HTMLElement;
  const rect = row.getBoundingClientRect();
  dropPoint.value = id;
  dropAfter.value = event.clientY > rect.top + rect.height / 2;
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  const list = row.parentElement;
  if (list) {
    const bounds = list.getBoundingClientRect();
    if (event.clientY < bounds.top + 24) list.scrollTop -= 10;
    if (event.clientY > bounds.bottom - 24) list.scrollTop += 10;
  }
}
function dropTaskPoint(event: DragEvent, id: string) {
  previewPointDrop(event, id);
  const points = task.value?.points;
  const from =
    points?.findIndex((point) => point.id === draggedPoint.value) ?? -1;
  const target = points?.findIndex((point) => point.id === id) ?? -1;
  if (!locked.value && points && from >= 0 && target >= 0) {
    const boundary = target + (dropAfter.value ? 1 : 0);
    const to = boundary - (from < boundary ? 1 : 0);
    if (to !== from) movePoint(from, to - from);
  }
  endPointDrag();
}
/** 路线插点立即落盘；编号配对失效时丢弃请求，不追加到其他任务。 */
function insertRoutePoint(insertion: TaskRouteInsertion) {
  if (
    locked.value ||
    !compatible.value ||
    !task.value ||
    !validTaskPose(insertion.pose)
  )
    return;
  const points = task.value.points;
  const index = points.findIndex((point) => point.id === insertion.beforeId);
  if (index < 0 || points[index + 1]?.id !== insertion.afterId) return;
  if (points.length >= 1000) {
    message.value = "每个任务最多保存 1000 个点位。";
    return;
  }
  clearEditedResult();
  const point = {
    ...insertion.pose,
    id: createTaskId(),
    name: `点位 ${points.length + 1}`,
  };
  points.splice(index + 1, 0, point);
  editPoint(point);
}
function deleteTask() {
  if (locked.value) return;
  const target = deletingTask.value;
  if (!target || (running.value && execution.value.taskId === target.id))
    return;
  tasks.value = tasks.value.filter((item) => item.id !== target.id);
  if (selectedId.value === target.id) selectTask("");
  deletingTask.value = null;
}
/** 文件导入采用追加策略并重建任务编号，避免覆盖已有任务。 */
async function importTasks(event: Event) {
  const input = event.target as HTMLInputElement,
    file = input.files?.[0];
  if (!file) return;
  try {
    if (file.size > 5_000_000) throw new Error("文件不能超过 5 MB。");
    const imported = parseTasks(await file.text()).map((item) => ({
      ...item,
      id: createTaskId(),
    }));
    if (tasks.value.length + imported.length > 200)
      throw new Error("任务总数不能超过 200。");
    tasks.value.push(...imported);
    message.value = `已导入 ${imported.length} 个任务。`;
  } catch (error) {
    message.value = `导入失败：${(error as Error).message}`;
  }
  input.value = "";
}
function exportTasks() {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify({ version: 1, tasks: tasks.value }, null, 2)], {
      type: "application/json",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "navigation-tasks.json";
  link.click();
  URL.revokeObjectURL(url);
}
defineExpose({ receivePose, placeMapPoint, editPoint, insertRoutePoint });
</script>

<template>
  <Transition name="task-fade"
    ><div v-show="active" class="navigation-task-ui">
      <aside class="glass-panel task-sidebar" :class="{ collapsed }">
        <header>
          <Transition name="task-fade"
            ><strong v-if="!collapsed"
              >导航任务 <small>{{ tasks.length }}</small></strong
            ></Transition
          ><Transition name="task-fade"
            ><button v-if="!collapsed" @click="openCreate">
              <Plus :size="14" />新建
            </button></Transition
          ><button
            :aria-label="collapsed ? '展开任务列表' : '收起任务列表'"
            @click="collapsed = !collapsed"
          >
            <component
              :is="collapsed ? ChevronRight : ChevronLeft"
              :size="16"
            />
          </button>
        </header>
        <Transition name="task-fade"
          ><div v-show="!collapsed" class="task-sidebar-content">
            <TransitionGroup name="task-fade" tag="div" class="task-list">
              <p key="empty" v-if="!tasks.length" class="task-empty">
                还没有导航任务<br />新建任务后，添加机器狗当前位置或地图点位。
              </p>
              <button
                v-for="item in tasks"
                :key="item.id"
                class="task-card"
                :class="{ selected: selectedId === item.id }"
                @click="selectTask(item.id)"
              >
                <MapPin :size="20" /><span
                  ><strong>{{ item.name }}</strong
                  ><small
                    >{{ item.points.length }} 个点 ·
                    {{ taskDistance(item).toFixed(1) }} m</small
                  ><small>{{
                    new Date(item.createdAt).toLocaleString()
                  }}</small></span
                ><ChevronRight :size="15" />
              </button>
            </TransitionGroup>
            <button
              class="task-files-toggle"
              :aria-expanded="filesOpen"
              @click="filesOpen = !filesOpen"
            >
              <FolderOpen :size="17" />任务文件<ChevronRight
                :size="14"
                class="task-files-arrow"
                :class="{ expanded: filesOpen }"
              />
            </button>
            <Transition name="task-fade"
              ><div v-if="filesOpen" class="task-actions">
                <button @click="fileInput?.click()">导入 JSON</button
                ><button :disabled="!tasks.length" @click="exportTasks">
                  <Download :size="13" />导出全部
                </button>
              </div></Transition
            >
            <input
              ref="fileInput"
              hidden
              type="file"
              accept=".json,application/json"
              @change="importTasks"
            /></div
        ></Transition>
      </aside>
      <Transition name="task-fade"
        ><form
          v-if="creating"
          class="glass-panel task-create-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="task-create-title"
          @submit.prevent="createTask"
          @keydown.esc="creating = false"
        >
          <header>
            <strong id="task-create-title">新建导航任务</strong
            ><button
              type="button"
              aria-label="关闭新建任务"
              @click="creating = false"
            >
              <X :size="16" />
            </button>
          </header>
          <label class="task-create-field"
            ><span>任务名称</span
            ><input
              ref="nameInput"
              v-model="newName"
              class="text-field"
              maxlength="80"
              required
          /></label>
          <label class="task-create-field"
            ><span>任务类型</span
            ><select v-model="newKind" class="text-field">
              <option>自定义任务</option>
              <option>区域巡检</option>
              <option>路线巡检</option>
              <option>前往点位</option>
            </select></label
          >
          <p class="task-create-hint">
            坐标系 <span>{{ frame }}</span>
          </p>
          <footer>
            <button type="button" @click="creating = false">取消</button
            ><button type="submit" class="primary-btn">创建任务</button>
          </footer>
        </form></Transition
      >
      <Transition name="task-fade"
        ><div
          v-if="creating"
          class="task-create-backdrop"
          @click="creating = false"
        ></div
      ></Transition>
      <Transition name="task-fade"
        ><div
          v-if="deletingTask"
          class="task-create-backdrop"
          @click="deletingTask = null"
        ></div
      ></Transition>
      <Transition name="task-fade"
        ><form
          v-if="deletingTask"
          class="glass-panel task-create-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="task-delete-title"
          @submit.prevent="deleteTask"
          @keydown.esc="deletingTask = null"
        >
          <header>
            <strong id="task-delete-title">删除导航任务</strong
            ><button
              type="button"
              aria-label="关闭删除确认"
              @click="deletingTask = null"
            >
              <X :size="16" />
            </button>
          </header>
          <p class="task-delete-copy">
            确定删除“{{ deletingTask.name }}”及其
            {{ deletingTask.points.length }} 个点位？此操作无法撤销。
          </p>
          <footer>
            <button
              ref="deleteCancelButton"
              type="button"
              @click="deletingTask = null"
            >
              取消</button
            ><button type="submit" class="primary-btn task-delete-confirm">
              删除任务
            </button>
          </footer>
        </form></Transition
      >
      <Transition name="task-fade"
        ><aside
          v-if="task"
          class="glass-panel task-details"
          :class="{ 'is-editing': draft || choosingPoint || mapAdding }"
          aria-label="任务详情"
        >
          <header>
            <strong>任务详情</strong
            ><button aria-label="关闭任务详情" @click="selectTask('')">
              <X :size="16" />
            </button>
          </header>
          <section class="task-basics" aria-label="任务基础信息">
            <Transition name="task-fade"
              ><h3 v-show="!draft && !choosingPoint && !mapAdding">
                基础信息
              </h3></Transition
            >
            <label class="task-name"
              >任务名称<input
                v-model="task.name"
                :disabled="locked"
                class="text-field"
                maxlength="80"
                @blur="task.name = task.name.trim() || '未命名任务'"
                @change="clearEditedResult"
            /></label>
            <Transition name="task-fade"
              ><dl v-if="!draft" class="task-metadata">
                <dt>任务类型</dt>
                <dd>{{ task.kind || "自定义任务" }}</dd>
                <dt>创建时间</dt>
                <dd>{{ new Date(task.createdAt).toLocaleString() }}</dd>
                <dt>坐标系</dt>
                <dd>{{ task.frame }}</dd>
                <dt>总点数</dt>
                <dd>{{ task.points.length }}</dd>
                <dt>连线距离</dt>
                <dd>{{ taskDistance(task).toFixed(2) }} m</dd>
                <dt>当前状态</dt>
                <dd>
                  <span
                    class="task-status"
                    :data-status="selectedRun ? execution.status : 'idle'"
                  >
                    {{
                      selectedRun ? runStatusLabels[execution.status] : "待执行"
                    }}</span
                  >
                </dd>
                <template v-if="selectedRun && execution.total"
                  ><dt>已完成</dt>
                  <dd>{{ execution.completed }} / {{ execution.total }}</dd>
                  <dt>当前点位</dt>
                  <dd>{{ execution.pointName }}</dd></template
                >
              </dl></Transition
            >
          </section>
          <Transition name="task-fade"
            ><p v-if="!compatible" class="task-warning">
              当前场景为 {{ frame }}，请切换至 {{ task.frame }} 后编辑点位。
            </p></Transition
          >
          <section
            ref="pointSection"
            class="task-point-section"
            aria-label="任务点列表"
          >
            <div class="task-section-heading">
              <h3>
                任务点列表
                <span class="task-count">{{ task.points.length }}</span>
              </h3>
              <button :disabled="!compatible || locked" @click="beginAddPoint">
                <Plus :size="14" />添加点
              </button>
            </div>
            <Transition name="task-fade"
              ><p v-if="!task.points.length && !draft" class="task-empty">
                添加第一个任务点，开始编排路线。
              </p></Transition
            >
            <TransitionGroup name="task-fade" tag="div" class="task-points">
              <div
                v-for="(point, index) in task.points"
                :key="point.id"
                class="task-point"
                :data-point-id="point.id"
                :draggable="!locked"
                @dragstart="startPointDrag($event, point.id)"
                @dragover="previewPointDrop($event, point.id)"
                @drop="dropTaskPoint($event, point.id)"
                @dragend="endPointDrag"
                :class="{
                  dragging: draggedPoint === point.id,
                  'drop-before':
                    dropPoint === point.id &&
                    !dropAfter &&
                    draggedPoint !== point.id,
                  'drop-after':
                    dropPoint === point.id &&
                    dropAfter &&
                    draggedPoint !== point.id,
                  editing: draft?.id === point.id,
                  reached: selectedRun && index < execution.completed,
                  navigating:
                    selectedRun && running && index === execution.index,
                }"
              >
                <span
                  class="task-number"
                  :title="locked ? undefined : '拖动调整点位顺序'"
                  :class="{
                    first: index === 0,
                    last: index > 0 && index === task.points.length - 1,
                  }"
                  >{{ index + 1 }}</span
                ><strong :title="point.name"
                  >{{ point.name
                  }}<small v-if="selectedRun && index < execution.completed"
                    >已完成</small
                  ><small
                    v-else-if="
                      selectedRun && running && index === execution.index
                    "
                    >{{ runStatusLabels[execution.status] }}</small
                  ></strong
                >
                <div class="task-point-actions">
                  <button
                    :disabled="!compatible"
                    title="定位到点位"
                    :aria-label="`定位到点位：${point.name}`"
                    @click="viewer?.focusTaskPose(point)"
                  >
                    <LocateFixed :size="14" /></button
                  ><button
                    :disabled="!compatible || locked"
                    title="编辑点位"
                    :aria-label="`编辑点位：${point.name}`"
                    @click="editPoint(point)"
                  >
                    <Pencil :size="14" /></button
                  ><button
                    :disabled="locked"
                    title="删除点位"
                    :aria-label="`删除点位：${point.name}`"
                    @click="removePoint(point.id)"
                  >
                    <Trash2 :size="14" />
                  </button>
                </div>
              </div>
            </TransitionGroup>
          </section>
          <Transition name="task-fade"
            ><section
              v-if="choosingPoint || mapAdding"
              class="task-source-picker"
            >
              <h3>{{ mapAdding ? "地图连续打点" : "选择取点方式" }}</h3>
              <Transition name="task-fade" mode="out-in"
                ><div v-if="choosingPoint" key="choose" class="task-actions">
                  <button @click="useRobot">
                    <LocateFixed :size="14" />狗当前位置
                  </button>
                  <button @click="pickMap">
                    <MapPin :size="14" />地图打点
                  </button>
                  <button @click="cancelEdit">取消</button>
                </div>
                <div v-else key="map" class="task-source-active">
                  <small>点击地图新增点位，选中点位可直接调整。</small
                  ><button @click="cancelEdit">完成打点</button>
                </div></Transition
              >
            </section></Transition
          >
          <Transition name="task-fade"
            ><section v-if="draft" class="task-editor">
              <div class="task-editor-heading">
                <h3>
                  {{
                    task.points.some((point) => point.id === draft?.id)
                      ? "编辑点位"
                      : "添加点位"
                  }}
                </h3>
                <div v-if="draftIndex >= 0" class="task-order-actions">
                  <span>第 {{ draftIndex + 1 }} 点</span
                  ><button
                    title="上移"
                    aria-label="上移点位"
                    :disabled="locked || draftIndex === 0"
                    @click="movePoint(draftIndex, -1)"
                  >
                    <ArrowUp :size="12" /></button
                  ><button
                    title="下移"
                    aria-label="下移点位"
                    :disabled="locked || draftIndex === task.points.length - 1"
                    @click="movePoint(draftIndex, 1)"
                  >
                    <ArrowDown :size="12" />
                  </button>
                </div>
              </div>
              <label
                >点位名称<input
                  v-model="draft.name"
                  class="text-field"
                  maxlength="80"
                  @change="persistMapDraft"
              /></label>
              <p>
                {{
                  picking
                    ? "在地图上拖动设置朝向，松开后调整。"
                    : "坐标单位 m；roll、pitch、yaw 使用 XYZ 欧拉角，单位 rad。"
                }}
              </p>
              <div class="task-coordinates">
                <label
                  v-for="key in [
                    'x',
                    'y',
                    'z',
                    'roll',
                    'pitch',
                    'yaw',
                  ] as const"
                  :key="key"
                  >{{ key
                  }}<input
                    v-model.number="draft[key]"
                    class="text-field"
                    type="number"
                    step="0.01"
                    @change="updatePose"
                /></label>
              </div>
              <p v-if="hasPose && !picking">{{ poseHelperHint }}</p>
              <div v-if="!mapAdding" class="task-actions task-editor-actions">
                <button
                  class="primary-btn"
                  :disabled="!hasPose || picking"
                  @click="savePoint"
                >
                  保存点位</button
                ><button @click="cancelEdit">取消编辑</button>
              </div>
            </section></Transition
          >
          <footer class="task-details-footer">
            <small>连线表示顺序，非规划路径</small
            ><button
              :disabled="locked"
              title="删除任务"
              aria-label="删除任务"
              @click="deletingTask = task"
            >
              <Trash2 :size="13" />
            </button>
          </footer></aside
      ></Transition>
      <Transition name="task-fade"
        ><div
          v-if="navigationStatus"
          class="glass task-connection"
          role="status"
        >
          <span :class="{ ready: navigationStatus.ready }">{{
            navigationStatus.ready ? "导航就绪" : navigationStatus.stage
          }}</span>
          <span
            >定位
            {{
              navigationStatus.localization === null
                ? "未知"
                : ["无效", "良好", "可用", "异常"][
                    navigationStatus.localization
                  ]
            }}</span
          >
          <small>{{
            navigationStatus.ready
              ? "状态实时更新"
              : running &&
                  navigationStatus.contextFresh &&
                  navigationStatus.localizationFresh
                ? execution.message
                : navigationStatus.message
          }}</small>
        </div></Transition
      >
      <div class="platform-toolbelt glass task-controls">
        <button
          :disabled="
            !task?.points.length ||
            !!draft ||
            mapAdding ||
            !compatible ||
            running ||
            (navigationStatus && !navigationStatus.ready)
          "
          @click="command('start')"
        >
          <Play :size="14" />{{
            selectedRun &&
            ["completed", "failed", "cancelled"].includes(execution.status)
              ? "重新开始"
              : "开始任务"
          }}
        </button>
        <button
          :disabled="execution.status !== 'paused'"
          @click="command('resume')"
        >
          <Play :size="14" />继续
        </button>
        <button
          :disabled="execution.status !== 'running'"
          @click="command('pause')"
        >
          <Pause :size="14" />暂停
        </button>
        <button
          :disabled="
            !['sending', 'running', 'paused', 'blocked', 'unknown'].includes(
              execution.status,
            )
          "
          @click="command('cancel')"
        >
          <Square :size="14" />取消任务
        </button>
      </div>
      <Transition name="task-fade"
        ><section
          v-if="execution.total"
          class="glass task-execution"
          aria-label="任务执行进度"
        >
          <template v-if="execution.total"
            ><strong
              >{{ execution.taskName }} ·
              {{ runStatusLabels[execution.status] }}</strong
            ><span
              >{{ execution.completed }} / {{ execution.total }} 已完成 ·
              {{ execution.pointName }}</span
            ><progress
              :value="execution.completed"
              :max="execution.total"
            ></progress
            ><small>{{ execution.message }}</small></template
          >
        </section></Transition
      >
      <Transition name="task-fade"
        ><p v-if="message" class="glass task-message" role="status">
          {{ message
          }}<button
            v-if="message === mapHint"
            data-dismiss-map-hint
            @click="disableMapHint"
          >
            不再提示
          </button>
          <button v-else aria-label="关闭提示" @click="message = ''">
            <X :size="13" />
          </button></p
      ></Transition></div
  ></Transition>
</template>

<style scoped>
.task-connection {
  position: absolute;
  left: 50%;
  bottom: 74px;
  transform: translateX(-50%);
  padding: 7px 12px;
  border-radius: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px 12px;
  max-width: 390px;
  font-size: 10px;
  z-index: 13;
}
.task-connection small {
  flex-basis: 100%;
  font-size: 10px;
  color: #79796e;
}
.task-connection .ready {
  color: #61774e;
}
.task-connection ~ .task-execution {
  bottom: 146px;
}
.task-sidebar-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 8px;
}
.task-sidebar {
  transition:
    width 180ms ease,
    padding 180ms ease;
}
.task-fade-enter-active,
.task-fade-leave-active {
  transition: opacity 180ms ease;
}
.task-fade-enter-from,
.task-fade-leave-to {
  opacity: 0;
}
.task-fade-leave-active {
  pointer-events: none;
}
.task-files-arrow {
  transition: transform 180ms ease;
}
.task-files-arrow.expanded {
  transform: rotate(90deg);
}
.task-source-picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--panel-line);
}
.task-source-active {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.task-source-picker small {
  font-size: 10px;
  color: var(--panel-muted);
}
.task-source-picker button {
  padding: 6px 8px;
  border-radius: 7px;
  font-size: 11px;
}
.task-delete-copy {
  margin: 0;
  font-size: 11px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}
.task-create-dialog footer .task-delete-confirm {
  background: #987164;
}

.task-execution {
  position: absolute;
  left: 50%;
  bottom: 76px;
  transform: translateX(-50%);
  z-index: 13;
  width: 360px;
  max-width: calc(100% - 32px);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}
.task-execution small {
  font-size: 11px;
  line-height: 1.5;
  color: #625f59;
}
.task-execution progress {
  width: 100%;
  height: 5px;
  accent-color: #76b933;
}
.task-state-badge {
  color: #d44860 !important;
  font-weight: 600;
}
.task-controls select {
  font-size: 11px;
  max-width: 110px;
  padding: 6px;
}
.task-sidebar {
  position: absolute;
  z-index: 12;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: calc(100% - 260px);
  overflow: auto;
}
.task-sidebar {
  left: 16px;
  top: 160px;
  width: 285px;
  bottom: 85px;
}
.task-sidebar.collapsed {
  width: auto;
  bottom: auto;
  padding: 6px;
}
.task-sidebar header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.task-sidebar header strong {
  flex: 1;
}
.task-list {
  flex: 1;
  overflow: auto;
  min-height: 80px;
}
.task-card {
  display: flex;
  width: 100%;
  gap: 12px;
  text-align: left;
  padding: 14px 10px;
  margin-bottom: 8px;
}
.task-card span {
  flex: 1;
  min-width: 0;
}
.task-card strong,
.task-card small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-card small {
  margin-top: 5px;
  font-size: 10px;
  color: #777;
}
.selected {
  background: rgba(237, 87, 105, 0.1);
  border-color: rgba(237, 87, 105, 0.5);
}
.task-empty {
  font-size: 12px;
  line-height: 1.9;
  color: #777;
  padding: 12px 2px;
}
.task-files-toggle {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
}
.task-actions {
  display: flex;
  gap: 6px;
}
.task-actions button {
  flex: 1;
}
.task-controls {
  align-items: center;
  width: max-content;
}
.task-controls button {
  white-space: nowrap;
  flex-shrink: 0;
}
.task-controls select {
  width: 104px;
  flex-shrink: 0;
}
.task-controls span {
  font-size: 10px;
  padding: 0 8px;
  color: #777;
}
.task-message {
  position: absolute;
  bottom: 230px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 25;
  padding: 10px 14px;
  font-size: 12px;
  max-width: 450px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-warning {
  font-size: 12px;
  color: #ad4e2f;
}
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
}
button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
@media (max-width: 900px) {
  .task-sidebar {
    width: 240px;
  }
  .task-details {
    width: 300px;
  }
  .task-controls {
    left: 16px;
    transform: none;
    bottom: 65px;
  }
  .task-message {
    bottom: 280px;
  }
  .task-execution {
    bottom: 125px;
  }
}
@media (max-width: 650px) {
  .task-sidebar {
    top: 145px;
    width: 210px;
  }
  .task-details {
    top: 145px;
    right: 10px;
    width: calc(100% - 65px);
    z-index: 14;
  }
  .task-controls {
    max-width: calc(100% - 24px);
    flex-wrap: wrap;
  }
  .task-controls span {
    display: none;
  }
  .task-execution {
    z-index: 15;
    bottom: 145px;
  }
}
/* 配置弹窗和详情区独立约束尺寸，避免影响左侧列表及底部控制带。 */
.task-create-dialog,
.task-details {
  --panel-ink: #343830;
  --panel-muted: #777a70;
  --panel-line: rgba(98, 103, 86, 0.12);
  color: var(--panel-ink);
  font-size: 11px;
  line-height: 1.5;
  border: 1px solid rgba(255, 255, 255, 0.48);
  border-radius: 14px;
  box-shadow:
    0 8px 24px rgba(52, 47, 36, 0.07),
    inset 0 1px rgba(255, 255, 255, 0.35);
}
.task-create-dialog {
  position: absolute;
  z-index: 30;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: min(320px, calc(100% - 32px));
  max-height: calc(100% - 32px);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 13px;
  padding: 16px;
  background: rgba(244, 241, 233, 0.93);
}
.task-create-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(42, 39, 30, 0.045);
  z-index: 29;
}
.task-create-dialog header,
.task-details > header,
.task-section-heading,
.task-editor-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.task-create-dialog header strong,
.task-details > header strong {
  font-size: 13px;
  line-height: 20px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.task-create-dialog :is(input, select),
.task-details input {
  height: 30px;
  min-height: 30px;
  padding: 5px 8px;
  border: 1px solid rgba(100, 104, 90, 0.08);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.33);
  font-family: inherit;
  font-size: 11px;
  color: var(--panel-ink);
  box-shadow: none;
}
.task-create-dialog :is(input, select):focus,
.task-details input:focus {
  border-color: rgba(105, 121, 86, 0.45);
  background: rgba(255, 255, 255, 0.55);
  outline: none;
  box-shadow: 0 0 0 2px rgba(105, 121, 86, 0.07);
}
.task-create-field {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
}
.task-create-field > span,
.task-name,
.task-editor label {
  font-size: 10.5px;
  color: var(--panel-muted);
}
.task-create-dialog .task-create-hint {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: -2px 0 0;
  color: var(--panel-muted);
  font-size: 10px;
  line-height: 16px;
}
.task-create-hint span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.task-create-dialog footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--panel-line);
}
.task-create-dialog footer button {
  width: 82px;
  height: 30px;
  padding: 0 10px;
  font-size: 11px;
  border-radius: 7px;
}
.task-create-dialog footer button:not(.primary-btn),
.task-details button {
  background: rgba(255, 255, 255, 0.23);
  border: 1px solid transparent;
  box-shadow: none;
}
.task-create-dialog .primary-btn,
.task-details .primary-btn {
  color: #fff;
  background: #707d61;
  border-color: transparent;
}
.task-create-dialog .primary-btn:hover,
.task-details .primary-btn:hover {
  background: #657355;
}
.task-create-dialog header button,
.task-details > header button,
.task-point-actions button,
.task-order-actions button,
.task-details-footer button {
  width: 24px;
  height: 24px;
  min-width: 24px;
  padding: 0;
  border-radius: 6px;
  border: 1px solid transparent;
  color: #666b60;
  background: transparent;
}
.task-create-dialog header button:hover,
.task-details button:not(.primary-btn):not(:disabled):hover {
  background: rgba(255, 255, 255, 0.55);
  color: #353c30;
}
.task-details {
  position: absolute;
  z-index: 12;
  right: 16px;
  top: 90px;
  width: 310px;
  bottom: auto;
  max-height: calc(100% - 240px);
  overflow: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: rgba(241, 238, 229, 0.76);
}
.task-details h3 {
  margin: 0;
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
}
.task-basics {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.task-basics > h3 {
  color: #646b5d;
}
.task-name {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
}
.task-name input {
  font-size: 12px;
  font-weight: 500;
  text-align: right;
  background: rgba(255, 255, 255, 0.16);
  border-color: transparent;
}
.task-metadata {
  display: grid;
  grid-template-columns: 60px minmax(0, 1fr);
  gap: 7px 16px;
  margin: 0;
  align-items: center;
  font-size: 11px;
  line-height: 17px;
}
.task-metadata dt {
  color: var(--panel-muted);
  font-size: 10.5px;
}
.task-metadata dd {
  margin: 0;
  min-width: 0;
  text-align: right;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
.task-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 19px;
  padding: 1px 6px;
  border-radius: 5px;
  background: rgba(112, 125, 97, 0.11);
  color: #657158;
  font-size: 9.5px;
}
.task-status::before {
  content: "";
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
}
.task-status[data-status="failed"] {
  color: #9d6252;
  background: rgba(157, 98, 82, 0.09);
}
.task-status[data-status="paused"] {
  color: #927346;
  background: rgba(146, 115, 70, 0.1);
}
.task-point-section {
  border-top: 1px solid var(--panel-line);
  padding-top: 11px;
}
.task-section-heading {
  margin-bottom: 8px;
}
.task-section-heading button {
  height: 25px;
  padding: 0 7px;
  font-size: 10px;
  border-radius: 6px;
}
.task-count {
  font-size: 10px;
  color: #8a8d83;
  font-weight: 400;
  margin-left: 4px;
}
.task-points {
  max-height: 250px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.task-point {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 33px;
  padding: 4px 2px;
  border-radius: 6px;
}
.task-point:hover {
  background: rgba(255, 255, 255, 0.15);
}
.task-point[draggable="true"] {
  cursor: grab;
}
.task-point.dragging {
  opacity: 0.4;
}
.task-point.drop-before {
  box-shadow: inset 0 2px #a39379;
}
.task-point.drop-after {
  box-shadow: inset 0 -2px #a39379;
}
.task-fade-move {
  transition: transform 180ms ease;
}
.task-point.editing,
.task-point.navigating {
  background: rgba(112, 125, 97, 0.1);
  outline: none;
}
.task-number {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  border-radius: 5px;
  background: rgba(117, 121, 107, 0.1);
  color: #6d7365;
  font-size: 10px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.task-number.first,
.task-point.reached .task-number {
  background: rgba(112, 133, 88, 0.18);
  color: #596d48;
}
.task-number.last {
  background: rgba(147, 116, 101, 0.12);
  color: #8b7162;
}
.task-point strong {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  line-height: 17px;
  font-weight: 500;
}
.task-point strong small {
  display: block;
  font-size: 9px;
  font-weight: 400;
  color: #737f65;
}
.task-point-actions,
.task-order-actions {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
}
.task-point-actions button[title="删除点位"]:hover {
  color: #a46958;
}
.task-editor {
  border-top: 1px solid var(--panel-line);
  padding-top: 11px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.task-order-actions {
  color: var(--panel-muted);
  font-size: 10px;
}
.task-order-actions button {
  width: 21px;
  min-width: 21px;
  height: 21px;
}
.task-editor label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.task-editor p {
  font-size: 9.5px;
  line-height: 1.5;
  color: var(--panel-muted);
  margin: 0;
}
.task-details .task-actions button {
  height: 28px;
  padding: 0 7px;
  font-size: 10.5px;
  border-radius: 7px;
}
.task-details .task-actions .selected {
  background: rgba(112, 125, 97, 0.14);
  border-color: rgba(112, 125, 97, 0.25);
}
.task-coordinates {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
}
.task-coordinates input {
  width: 100%;
  min-width: 0;
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}
.task-details .task-editor-actions {
  margin-top: 1px;
}
.task-details.is-editing .task-points {
  max-height: 112px;
}
.task-details .task-empty {
  margin: 0;
  padding: 12px 0;
  font-size: 10.5px;
}
.task-details-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  border-top: 1px solid var(--panel-line);
  padding-top: 8px;
}
.task-details-footer small {
  font-size: 9px;
  color: #83877c;
}
.task-details .task-warning {
  font-size: 10.5px;
  line-height: 1.6;
}
@media (max-width: 650px) {
  .task-details {
    top: 145px;
    right: 10px;
    width: min(310px, calc(100% - 65px));
    max-height: calc(100% - 295px);
    z-index: 14;
  }
}
</style>
