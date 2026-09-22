// 功能说明：封装 Android 原生文件选择上传插件，网页环境自动回退到普通文件输入。
import { registerPlugin } from "@capacitor/core";
import { interaction } from "../platform/interaction";

import type { NavOfflineMapPreviewResponse } from "../api/client";

interface UploadedToolFileResponse {
  path: string;
  original_name: string;
  size_bytes: number;
  content_type: string;
}

interface NativePickAndUploadOptions {
  uploadUrl: string;
  purpose: string;
}

interface RosFilePickerPlugin {
  readTaskText(): Promise<{ cancelled?: boolean; text?: string }>;
  saveTaskText(options: {
    text: string;
    name: string;
  }): Promise<{ cancelled?: boolean }>;
  pickAndUpload(
    options: NativePickAndUploadOptions,
  ): Promise<UploadedToolFileResponse>;
  pickLocalFile(options: { kind: string }): Promise<UploadedToolFileResponse>;
  buildOfflineMapPreview(options: {
    pcdPath: string;
    yamlPath?: string;
    pgmPath?: string;
    voxelLeafM: number;
    occupancyVoxelM: number;
    maxPoints: number;
    maxVoxels: number;
  }): Promise<NavOfflineMapPreviewResponse>;
}

const RosFilePicker = registerPlugin<RosFilePickerPlugin>("RosFilePicker");

export function canUseNativeRosFilePicker() {
  return interaction.android;
}
/** 任务文本走系统文档选择器，取消与读取失败分别处理。 */
export const pickNativeTaskText = () => RosFilePicker.readTaskText();
export const saveNativeTaskText = (text: string) =>
  RosFilePicker.saveTaskText({ text, name: "navigation-tasks.json" });

export async function pickAndUploadNativeFile(
  options: NativePickAndUploadOptions,
) {
  return RosFilePicker.pickAndUpload(options);
}

export async function pickNativeLocalFile(kind: string) {
  return RosFilePicker.pickLocalFile({ kind });
}

export async function buildNativeOfflineMapPreview(options: {
  pcdPath: string;
  yamlPath?: string;
  pgmPath?: string;
  voxelLeafM: number;
  occupancyVoxelM: number;
  maxPoints: number;
  maxVoxels: number;
}) {
  return RosFilePicker.buildOfflineMapPreview(options);
}
