// 功能说明：封装 Android 原生文件选择上传插件，网页环境自动回退到普通文件输入。
import { Capacitor, registerPlugin } from "@capacitor/core";

import type { UploadedToolFileResponse } from "../api/client";
import type { NavOfflineMapPreviewResponse } from "../api/client";

interface NativePickAndUploadOptions {
  uploadUrl: string;
  purpose: string;
}

interface RosFilePickerPlugin {
  pickAndUpload(options: NativePickAndUploadOptions): Promise<UploadedToolFileResponse>;
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
  return Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android";
}

export async function pickAndUploadNativeFile(options: NativePickAndUploadOptions) {
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
