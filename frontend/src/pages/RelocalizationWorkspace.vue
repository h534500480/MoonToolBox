<!-- 功能说明：platform 候选点工作台，补齐点组拖动、姿态编辑、锁定及真实导出。 -->
<script setup lang="ts">
import { ref } from "vue";
import {
  Settings,
  MousePointer2,
  Scan,
  Plus,
  Trash2,
  Undo2,
  Redo2,
  Lock,
  Move,
  Check,
  RotateCcw,
  ArrowLeft,
  X,
} from "@lucide/vue";
import PlatformLauncher from "../components/PlatformLauncher.vue";
import GlassDrawer from "../components/GlassDrawer.vue";
import { useRelocalizationController } from "../composables/useRelocalizationController";
import type { ToolDefinition } from "../types";
const props = defineProps<{
  tool: ToolDefinition;
  loading: boolean;
  summary: string;
  logs: string[];
  resultData: Record<string, any>;
}>();
const emit = defineEmits<{
  run: [values: Record<string, string>];
  clearLogs: [];
}>();
const {
  formValues,
  configValues,
  mountRef,
  demo,
  sceneMessage,
  interactionMode,
  candidates,
  deletedCandidates,
  selectedIds,
  deletionRegions,
  manualLabel,
  manualZ,
  manualUseAutoZ,
  manualYawDeg,
  manualYawExpand,
  manualNote,
  exportPreview,
  exportMessage,
  boxSelectionStyle,
  boxSelecting,
  scene,
  configFields,
  configSections,
  selectedCandidates,
  activeCandidateCount,
  loadedCandidateCount,
  manualCandidateCount,
  lockedCandidateCount,
  canUndo,
  canRedo,
  manualYamlPreview,
  configKey,
  undoEdit,
  redoEdit,
  beginCandidateFieldEdit,
  endCandidateFieldEdit,
  setAxisView,
  browseField,
  loadPointCloudFromPath,
  loadCandidatesFromPath,
  selectCandidate,
  deleteSelectedCandidates,
  restoreCandidate,
  purgeTrash,
  toggleSelectedLocked,
  addDeletionRegionFromSelection,
  refreshExportPreview,
  exportManualEditFile,
  openOutputDir,
  runScaffold,
} = useRelocalizationController(props, emit);
const settingsOpen = ref(true);
const sectionLabels: Record<string, string> = {
  map: "离线配置 · 地图加载",
  candidate_sampling: "离线配置 · 候选点采样",
  virtual_lidar: "离线配置 · 虚拟 LiDAR",
  observability: "离线配置 · 可观测性过滤",
  descriptor: "离线配置 · Scan Context 描述子",
  manual_edit: "离线配置 · 人工编辑策略",
};
</script>
<template>
  <main class="relocalization-workspace">
    <div class="scene-fill">
      <section class="panel global-relocalization-view-panel">
        <div class="global-relocalization-stage">
          <div ref="mountRef" class="global-relocalization-canvas-host"></div>
          <div
            v-if="boxSelecting"
            class="box-selection-rect"
            :style="boxSelectionStyle"
          ></div>
          <div class="viewer-left-tools" aria-label="候选点编辑工具">
            <button
              class="viewer-side-button"
              :class="{ active: interactionMode === 'select' }"
              type="button"
              title="点击选择候选点"
              @click="interactionMode = 'select'"
            >
              S
            </button>
            <button
              class="viewer-side-button"
              :class="{ active: interactionMode === 'box' }"
              type="button"
              title="框选候选点"
              @click="interactionMode = 'box'"
            >
              B
            </button>
            <button
              class="viewer-side-button"
              :class="{ active: interactionMode === 'add' }"
              type="button"
              title="手动加点：点击三维平面新增人工候选点"
              @click="interactionMode = 'add'"
            >
              +
            </button>
            <button
              class="viewer-side-button danger"
              type="button"
              title="删除选中点：按 candidate_id 写入删除列表"
              :disabled="selectedIds.length === 0"
              @click="deleteSelectedCandidates"
            >
              D
            </button>
            <button
              class="viewer-side-button"
              type="button"
              title="锁定保留：后续自动清理或稀疏化时优先保留"
              :disabled="selectedIds.length === 0"
              @click="toggleSelectedLocked"
            >
              L
            </button>
            <button
              class="viewer-side-button warning"
              type="button"
              title="设为禁用区域：用选中点外包矩形创建区域删除规则"
              :disabled="selectedIds.length === 0"
              @click="addDeletionRegionFromSelection"
            >
              R
            </button>
          </div>
          <div class="viewer-corner-tools">
            <div class="history-tool-strip">
              <button
                class="viewer-tool-button"
                type="button"
                title="撤销 Ctrl+Z"
                :disabled="!canUndo"
                @click="undoEdit"
              >
                ↶
              </button>
              <button
                class="viewer-tool-button"
                type="button"
                title="重做 Ctrl+Y"
                :disabled="!canRedo"
                @click="redoEdit"
              >
                ↷
              </button>
            </div>
            <div class="axis-gizmo" aria-label="视图轴向控制">
              <button
                class="axis-button axis-z"
                type="button"
                title="顶视图 Z"
                @click="setAxisView('z')"
              >
                Z
              </button>
              <button
                class="axis-button axis-y"
                type="button"
                title="前视图 Y"
                @click="setAxisView('y')"
              >
                Y
              </button>
              <button
                class="axis-button axis-x"
                type="button"
                title="侧视图 X"
                @click="setAxisView('x')"
              >
                X
              </button>
              <button
                class="axis-button axis-home"
                type="button"
                title="透视视图"
                @click="setAxisView('home')"
              >
                ⌂
              </button>
              <span class="axis-line axis-line-z"></span>
              <span class="axis-line axis-line-y"></span>
              <span class="axis-line axis-line-x"></span>
            </div>
          </div>
        </div>
        <div class="nav-viewer-footer">
          <span class="nav-viewer-status">{{ sceneMessage }}</span>
          <span class="nav-viewer-status">候选 {{ activeCandidateCount }}</span>
          <span class="nav-viewer-status">人工 {{ manualCandidateCount }}</span>
          <span class="nav-viewer-status">锁定 {{ lockedCandidateCount }}</span>
          <span class="nav-viewer-status"
            >回收站 {{ deletedCandidates.length }}</span
          >
        </div>
      </section>
    </div>
    <div class="reloc-topbar">
      <RouterLink to="/" class="glass icon-button" aria-label="返回平台"
        ><ArrowLeft :size="16" /></RouterLink
      ><PlatformLauncher compact />
      <div class="reloc-heading">
        <strong>全局重定位候选点</strong
        ><small>{{
          demo ? "演示场景 · 加载 PCD 开始审核" : "离线点云 · 候选点审核"
        }}</small>
      </div>
    </div>
    <button
      class="glass settings-button icon-button reloc-settings-toggle"
      aria-label="离线生成参数"
      @click="settingsOpen = true"
    >
      <Settings :size="19" />
    </button>
    <aside class="glass-panel candidate-panel">
      <header>
        <strong>候选点审核</strong
        ><span class="glass-chip">{{ candidates.length }}</span>
      </header>
      <div class="segmented">
        <button
          v-for="mode in [
            { key: 'select', icon: MousePointer2, label: '选择' },
            { key: 'box', icon: Scan, label: '框选' },
            { key: 'add', icon: Plus, label: '补点' },
          ]"
          :key="mode.key"
          :class="{ active: interactionMode === mode.key }"
          @click="interactionMode = mode.key as 'select' | 'box' | 'add'"
        >
          <component :is="mode.icon" :size="13" />{{ mode.label }}
        </button>
      </div>
      <div class="candidate-actions">
        <button
          :disabled="!selectedIds.length"
          @click="deleteSelectedCandidates"
        >
          <Trash2 :size="13" />删除</button
        ><button :disabled="!canUndo" title="撤销 Ctrl+Z" @click="undoEdit">
          <Undo2 :size="13" /></button
        ><button :disabled="!canRedo" title="重做 Ctrl+Y" @click="redoEdit">
          <Redo2 :size="13" /></button
        ><button
          :disabled="!selectedIds.length"
          title="锁定/解锁"
          @click="toggleSelectedLocked"
        >
          <Lock :size="13" /></button
        ><button
          :disabled="!selectedIds.length"
          title="设为删除区域"
          @click="addDeletionRegionFromSelection"
        >
          <Scan :size="13" />
        </button>
      </div>
      <small class="feedback"
        >拖动场景中的候选点标记移动点组；锁定点不会移动。</small
      >
      <details v-if="interactionMode === 'add'" open>
        <summary>人工补点</summary>
        <label class="field"
          >标签<input v-model="manualLabel" class="text-field"
        /></label>
        <div class="candidate-edit-grid">
          <label>yaw °<input v-model="manualYawDeg" class="text-field" /></label
          ><label
            >yaw 展开 °<input v-model="manualYawExpand" class="text-field"
          /></label>
        </div>
        <label class="toggle-row"
          >自动地面高度<input v-model="manualUseAutoZ" type="checkbox" /></label
        ><input
          v-if="!manualUseAutoZ"
          v-model="manualZ"
          class="text-field"
          placeholder="ground z"
        /><textarea v-model="manualNote" class="text-field" />
      </details>
      <section class="panel global-relocalization-list-panel">
        <div class="section-head">
          <div>
            <div class="result-title">候选点列表</div>
            <div class="section-subtitle">
              显示 auto / manual_added / locked 状态和观测质量指标。
            </div>
          </div>
          <div class="status-pill success">加载 {{ loadedCandidateCount }}</div>
        </div>
        <div class="candidate-list">
          <button
            v-for="candidate in candidates"
            :key="candidate.candidate_id"
            class="candidate-row"
            :class="{
              selected: selectedIds.includes(candidate.candidate_id),
              manual: candidate.source === 'manual_added',
              locked: candidate.locked,
            }"
            type="button"
            @click="
              selectCandidate(
                candidate.candidate_id,
                $event.shiftKey || $event.ctrlKey,
              )
            "
          >
            <span class="candidate-card-head"
              ><small>#{{ candidate.candidate_id }}</small
              ><b>{{
                candidate.label ||
                "C" + String(candidate.candidate_id).padStart(3, "0")
              }}</b
              ><small class="candidate-source">{{
                candidate.source === "manual_added" ? "人工" : "自动"
              }}</small
              ><Lock v-if="candidate.locked" :size="9" /><span
                class="candidate-score"
                ><i
                  :style="{
                    width:
                      Math.max(0, Math.min(1, candidate.observability_score)) *
                        100 +
                      '%',
                  }" /></span
              ><small>{{
                candidate.observability_score.toFixed(2)
              }}</small></span
            >
            <span class="candidate-coordinates"
              >x {{ candidate.x.toFixed(2) }}　y
              {{ candidate.y.toFixed(2) }}　yaw
              {{ candidate.yaw_deg.toFixed(0) }}°</span
            >
          </button>
          <div v-if="candidates.length === 0" class="section-empty">
            加载 candidates.csv 或 candidates.npy 后显示候选点。
          </div>
        </div>
      </section>
      <details :open="selectedIds.length > 0">
        <summary>选中点位 · 姿态编辑</summary>
        <section class="panel global-relocalization-selected-panel">
          <div class="section-head">
            <div>
              <div class="result-title">选中点位</div>
              <div class="section-subtitle">
                可编辑 yaw / z / roll / pitch；人工点支持 yaw_expand_deg。
              </div>
            </div>
          </div>
          <div class="candidate-detail-list">
            <div
              v-for="candidate in selectedCandidates"
              :key="`selected-${candidate.candidate_id}`"
              class="candidate-detail"
            >
              <strong
                >#{{ candidate.candidate_id }} {{ candidate.label }}</strong
              >
              <div class="candidate-edit-grid">
                <label
                  >x<input
                    v-model.number="candidate.x"
                    class="field-input"
                    @focus="beginCandidateFieldEdit"
                    @blur="endCandidateFieldEdit"
                /></label>
                <label
                  >y<input
                    v-model.number="candidate.y"
                    class="field-input"
                    @focus="beginCandidateFieldEdit"
                    @blur="endCandidateFieldEdit"
                /></label>
                <label
                  >z<input
                    v-model.number="candidate.z"
                    class="field-input"
                    @focus="beginCandidateFieldEdit"
                    @blur="endCandidateFieldEdit"
                /></label>
                <label
                  >yaw<input
                    v-model.number="candidate.yaw_deg"
                    class="field-input"
                    @focus="beginCandidateFieldEdit"
                    @blur="endCandidateFieldEdit"
                /></label>
                <label
                  >roll<input
                    v-model.number="candidate.roll_deg"
                    class="field-input"
                    @focus="beginCandidateFieldEdit"
                    @blur="endCandidateFieldEdit"
                /></label>
                <label
                  >pitch<input
                    v-model.number="candidate.pitch_deg"
                    class="field-input"
                    @focus="beginCandidateFieldEdit"
                    @blur="endCandidateFieldEdit"
                /></label>
              </div>
              <div class="candidate-quality">
                score {{ candidate.observability_score.toFixed(3) }} · hit
                {{ candidate.hit_count }} · ratio
                {{ candidate.hit_ratio.toFixed(3) }} · sectors
                {{ candidate.visible_sector_count }} · nonzero
                {{ candidate.descriptor_nonzero_ratio.toFixed(3) }}
              </div>
            </div>
            <div v-if="selectedCandidates.length === 0" class="section-empty">
              当前未选择候选点。
            </div>
          </div>
        </section>
      </details>
      <details>
        <summary>回收站 · {{ deletedCandidates.length }}</summary>
        <section class="panel global-relocalization-trash-panel">
          <div class="section-head">
            <div>
              <div class="result-title">删除规则 / 回收站</div>
              <div class="section-subtitle">
                删除自动点会写入 deletions.candidate_ids；删除区域会写入
                deletions.regions。
              </div>
            </div>
            <button
              class="secondary-btn small"
              type="button"
              :disabled="deletedCandidates.length === 0"
              @click="purgeTrash"
            >
              清空
            </button>
          </div>
          <div class="candidate-list compact">
            <button
              v-for="candidate in deletedCandidates"
              :key="`trash-${candidate.candidate_id}`"
              class="candidate-row deleted"
              type="button"
              @click="restoreCandidate(candidate.candidate_id)"
            >
              <span class="candidate-id">#{{ candidate.candidate_id }}</span>
              <span>x {{ candidate.x.toFixed(2) }}</span>
              <span>y {{ candidate.y.toFixed(2) }}</span>
              <span>{{ candidate.source }}</span>
              <span>恢复</span>
            </button>
            <div v-if="deletedCandidates.length === 0" class="section-empty">
              回收站为空。
            </div>
          </div>
          <div class="deletion-region-list">
            <div
              v-for="region in deletionRegions"
              :key="region.label"
              class="candidate-detail"
            >
              <strong>{{ region.label }}</strong>
              <span
                >x {{ region.min_x.toFixed(2) }} ~
                {{ region.max_x.toFixed(2) }} / y
                {{ region.min_y.toFixed(2) }} ~
                {{ region.max_y.toFixed(2) }}</span
              >
            </div>
          </div>
        </section>
      </details>
    </aside>
    <div class="platform-bottom-left">
      <button class="glass pill-button" @click="setAxisView('home')">
        <RotateCcw :size="13" />重置视角</button
      ><span>{{ sceneMessage }}</span>
    </div>
    <button
      class="primary-btn confirm-candidates"
      :disabled="loading || demo"
      @click="runScaffold"
    >
      <Check :size="15" />{{ loading ? "生成中…" : "确认候选点" }}
    </button>
    <aside v-show="settingsOpen" class="glass-panel reloc-params">
      <header>
        <strong>离线生成参数</strong
        ><button
          class="icon-button"
          aria-label="关闭参数"
          @click="settingsOpen = false"
        >
          <X :size="14" />
        </button>
      </header>
      <div class="reloc-params-content">
        <details open>
          <summary>路径与文件</summary>
          <div class="global-relocalization-path-grid">
            <label class="field">
              <span class="field-label">输入 PCD</span>
              <div class="field-row">
                <input
                  v-model="formValues.input_pcd"
                  class="field-input"
                  placeholder="G:/path/map.pcd"
                />
                <button
                  class="field-browse-btn"
                  type="button"
                  @click="browseField('input_pcd', 'open_file')"
                >
                  选择
                </button>
                <button
                  class="secondary-btn small"
                  type="button"
                  @click="loadPointCloudFromPath"
                >
                  加载点云
                </button>
              </div>
            </label>
            <label class="field">
              <span class="field-label">候选点文件</span>
              <div class="field-row">
                <input
                  v-model="formValues.candidate_file"
                  class="field-input"
                  placeholder="global_relocalization_db/candidates.csv 或 candidates.npy"
                />
                <button
                  class="field-browse-btn"
                  type="button"
                  @click="browseField('candidate_file', 'open_file')"
                >
                  选择
                </button>
                <button
                  class="secondary-btn small"
                  type="button"
                  @click="loadCandidatesFromPath"
                >
                  加载候选
                </button>
              </div>
            </label>
            <label class="field">
              <span class="field-label">人工编辑文件</span>
              <div class="field-row">
                <input
                  v-model="formValues.manual_file"
                  class="field-input"
                  placeholder="global_relocalization_db/manual_candidates.yaml"
                />
                <button
                  class="field-browse-btn"
                  type="button"
                  @click="browseField('manual_file', 'open_file')"
                >
                  选择
                </button>
              </div>
            </label>
            <label class="field">
              <span class="field-label">输出目录</span>
              <div class="field-row">
                <input
                  v-model="formValues.output_dir"
                  class="field-input"
                  placeholder="global_relocalization_db"
                />
                <button
                  class="field-browse-btn"
                  type="button"
                  @click="browseField('output_dir', 'open_dir')"
                >
                  选择
                </button>
                <button
                  class="secondary-btn small"
                  type="button"
                  @click="openOutputDir"
                >
                  打开
                </button>
              </div>
            </label>
          </div>
          <label class="field"
            >离线配置 YAML<input
              v-model="formValues.config_path"
              class="text-field"
          /></label>
          <div class="button-row">
            <button @click="exportManualEditFile">导出人工编辑</button
            ><button @click="refreshExportPreview">刷新 CSV 预览</button
            ><button @click="emit('clearLogs')">清空日志</button>
          </div>
        </details>
        <details v-for="section in configSections" :key="section">
          <summary>{{ sectionLabels[section] || section }}</summary>
          <label
            v-for="field in configFields.filter(
              (item) => item.section === section,
            )"
            :key="configKey(field)"
            class="field"
            ><span :title="field.help"
              >{{ field.label }} <span class="param-help-icon">?</span></span
            ><input
              v-model="configValues[configKey(field)]"
              class="text-field"
            /><small>{{ field.help }}</small></label
          >
        </details>
        <details>
          <summary>导出预览</summary>
          <section class="panel global-relocalization-export-panel">
            <div class="section-head">
              <div>
                <div class="result-title">导出预览</div>
                <div class="section-subtitle">
                  CSV 预览用于人工检查；最终在线兼容仍由离线工具生成
                  candidates.npy/descriptors.npy/ring_keys.npy。
                </div>
              </div>
            </div>
            <pre class="logs export-preview">{{
              exportPreview || "点击“刷新 CSV 预览”后显示。"
            }}</pre>
            <div class="section-subtitle export-message">
              {{ exportMessage }}
            </div>
            <pre class="logs manual-yaml-preview">{{ manualYamlPreview }}</pre>
          </section>
        </details>
        <details open>
          <summary>执行输出</summary>
          <p>{{ summary }}</p>
          <pre class="logs">{{ logs.join("\n") }}</pre>
          <p class="feedback">{{ exportMessage }}</p>
        </details>
      </div>
    </aside>
  </main>
</template>
