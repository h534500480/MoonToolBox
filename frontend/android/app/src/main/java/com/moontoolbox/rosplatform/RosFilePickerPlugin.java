package com.moontoolbox.rosplatform;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.util.Base64;

import androidx.activity.result.ActivityResult;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * 功能说明：
 * Android 离线地图本地能力插件。系统文件管理器返回 content:// URI，前端不能稳定
 * 直接读取，因此这里复制到 App 私有缓存，并在 APK 内完成 PCD 预览和占据 voxel 生成。
 */
@CapacitorPlugin(name = "RosFilePicker")
public class RosFilePickerPlugin extends Plugin {
    private static final int BUFFER_SIZE = 1024 * 1024;

    @PluginMethod
    public void pickLocalFile(PluginCall call) {
        if (getActivity() != null) {
            getActivity().setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
        }
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        startActivityForResult(call, intent, "handlePickedLocalFile");
    }

    @ActivityCallback
    private void handlePickedLocalFile(PluginCall call, ActivityResult result) {
        restoreLandscapeOrientation();
        if (call == null) {
            return;
        }
        if (result.getResultCode() != Activity.RESULT_OK || result.getData() == null) {
            call.reject("未选择文件");
            return;
        }
        Uri uri = result.getData().getData();
        if (uri == null) {
            call.reject("文件选择器未返回 URI");
            return;
        }
        new Thread(() -> copyPickedFile(call, uri)).start();
    }

    private void restoreLandscapeOrientation() {
        if (getActivity() != null) {
            getActivity().setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
        }
    }

    @PluginMethod
    public void buildOfflineMapPreview(PluginCall call) {
        new Thread(() -> {
            try {
                String pcdPath = call.getString("pcdPath", "");
                String yamlPath = call.getString("yamlPath", "");
                String pgmPath = call.getString("pgmPath", "");
                double voxelLeafM = clamp(call.getDouble("voxelLeafM", 0.20), 0.01, 5.0);
                double occupancyVoxelM = clamp(call.getDouble("occupancyVoxelM", 0.30), 0.05, 2.0);
                int maxPoints = Math.max(1000, Math.min(300000, call.getInt("maxPoints", 60000)));
                int maxVoxels = Math.max(1000, Math.min(200000, call.getInt("maxVoxels", 60000)));

                PcdPreview pcd = parsePcdPreview(new File(pcdPath), voxelLeafM, maxPoints);
                JSObject payload = new JSObject();
                payload.put("pcd", pcd.toJson());
                payload.put("occupancy", buildOccupancyPayload(pcd.points, occupancyVoxelM, maxVoxels));
                payload.put("map", yamlPath.trim().isEmpty() ? JSONObject.NULL : parseMapYaml(new File(yamlPath), pgmPath));
                call.resolve(payload);
            } catch (Exception exception) {
                call.reject("安卓本地离线地图加载失败: " + exception.getMessage(), exception);
            }
        }).start();
    }

    private void copyPickedFile(PluginCall call, Uri uri) {
        ContentResolver resolver = getContext().getContentResolver();
        String kind = call.getString("kind", "tool");
        String filename = safeFilename(resolveDisplayName(resolver, uri));
        File targetDir = new File(getContext().getCacheDir(), "ros_offline_map/" + safeFilename(kind));
        if (!targetDir.exists() && !targetDir.mkdirs()) {
            call.reject("无法创建本地缓存目录");
            return;
        }
        File target = new File(targetDir, UUID.randomUUID().toString().substring(0, 10) + "-" + filename);
        try (InputStream input = new BufferedInputStream(resolver.openInputStream(uri));
             FileOutputStream output = new FileOutputStream(target)) {
            if (input == null) {
                call.reject("无法读取已选择文件");
                return;
            }
            byte[] buffer = new byte[BUFFER_SIZE];
            int read;
            long total = 0;
            while ((read = input.read(buffer)) != -1) {
                output.write(buffer, 0, read);
                total += read;
            }
            JSObject payload = new JSObject();
            payload.put("path", target.getAbsolutePath());
            payload.put("original_name", filename);
            payload.put("size_bytes", total);
            payload.put("content_type", resolver.getType(uri) == null ? "" : resolver.getType(uri));
            call.resolve(payload);
        } catch (Exception exception) {
            call.reject("复制已选择文件失败: " + exception.getMessage(), exception);
        }
    }

    private String resolveDisplayName(ContentResolver resolver, Uri uri) {
        try (Cursor cursor = resolver.query(uri, new String[] { OpenableColumns.DISPLAY_NAME }, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (nameIndex >= 0) {
                    String displayName = cursor.getString(nameIndex);
                    if (displayName != null && !displayName.trim().isEmpty()) {
                        return displayName;
                    }
                }
            }
        } catch (Exception ignored) {
            // 部分文件管理器不提供 DISPLAY_NAME，此时用 URI 尾段兜底。
        }
        String tail = uri.getLastPathSegment();
        return tail == null || tail.trim().isEmpty() ? "selected-file" : tail;
    }

    private String safeFilename(String name) {
        String cleaned = name == null ? "selected-file" : name.replaceAll("[^A-Za-z0-9._-]", "_");
        cleaned = cleaned.replaceAll("^[._]+|[._]+$", "");
        return cleaned.isEmpty() ? "selected-file" : cleaned;
    }

    private PcdPreview parsePcdPreview(File file, double voxelLeafM, int maxPoints) throws Exception {
        if (!file.exists() || !file.isFile()) {
            throw new IllegalArgumentException("PCD 文件不存在: " + file.getAbsolutePath());
        }
        byte[] raw = readAllBytes(file);
        int headerEnd = findHeaderEnd(raw);
        String headerText = new String(raw, 0, headerEnd, StandardCharsets.UTF_8);
        Map<String, String> header = parseHeader(headerText);
        String[] fields = splitHeaderList(header.get("FIELDS"));
        int[] sizes = parseIntList(header.get("SIZE"), fields.length, 4);
        String[] types = splitHeaderList(header.get("TYPE"));
        int[] counts = parseIntList(header.get("COUNT"), fields.length, 1);
        int pointCount = Integer.parseInt(header.getOrDefault("POINTS", header.getOrDefault("WIDTH", "0")));
        String dataMode = header.getOrDefault("DATA", "ascii").toLowerCase(Locale.US);
        FieldLayout layout = buildFieldLayout(fields, sizes, types, counts);

        ArrayList<double[]> sampled = new ArrayList<>();
        Set<String> occupied = new HashSet<>();
        Bounds inputBounds = new Bounds();
        Bounds sampledBounds = new Bounds();
        if ("binary".equals(dataMode)) {
            parseBinaryPoints(raw, headerEnd, pointCount, layout, voxelLeafM, maxPoints, sampled, occupied, inputBounds, sampledBounds);
        } else if ("ascii".equals(dataMode)) {
            parseAsciiPoints(raw, headerEnd, layout, voxelLeafM, maxPoints, sampled, occupied, inputBounds, sampledBounds);
        } else {
            throw new IllegalArgumentException("暂不支持 PCD DATA " + dataMode);
        }
        if (sampled.isEmpty()) {
            throw new IllegalArgumentException("PCD 中没有可用 x/y/z 点");
        }
        return new PcdPreview(file.getAbsolutePath(), pointCount > 0 ? pointCount : inputBounds.count, voxelLeafM, sampled, inputBounds, sampledBounds);
    }

    private void parseBinaryPoints(byte[] raw, int offset, int pointCount, FieldLayout layout, double voxelLeafM, int maxPoints, ArrayList<double[]> sampled, Set<String> occupied, Bounds inputBounds, Bounds sampledBounds) {
        int available = Math.max(0, raw.length - offset);
        int count = pointCount > 0 ? Math.min(pointCount, available / layout.pointStep) : available / layout.pointStep;
        for (int index = 0; index < count; index += 1) {
            int base = offset + index * layout.pointStep;
            double x = readNumber(raw, base + layout.xOffset, layout.xSize, layout.xType);
            double y = readNumber(raw, base + layout.yOffset, layout.ySize, layout.yType);
            double z = readNumber(raw, base + layout.zOffset, layout.zSize, layout.zType);
            addPoint(x, y, z, voxelLeafM, maxPoints, sampled, occupied, inputBounds, sampledBounds);
        }
    }

    private void parseAsciiPoints(byte[] raw, int offset, FieldLayout layout, double voxelLeafM, int maxPoints, ArrayList<double[]> sampled, Set<String> occupied, Bounds inputBounds, Bounds sampledBounds) throws Exception {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(new java.io.ByteArrayInputStream(raw, offset, raw.length - offset), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String trimmed = line.trim();
                if (trimmed.isEmpty()) {
                    continue;
                }
                String[] parts = trimmed.split("\\s+");
                if (parts.length <= Math.max(layout.xFieldIndex, Math.max(layout.yFieldIndex, layout.zFieldIndex))) {
                    continue;
                }
                addPoint(Double.parseDouble(parts[layout.xFieldIndex]), Double.parseDouble(parts[layout.yFieldIndex]), Double.parseDouble(parts[layout.zFieldIndex]), voxelLeafM, maxPoints, sampled, occupied, inputBounds, sampledBounds);
            }
        }
    }

    private void addPoint(double x, double y, double z, double voxelLeafM, int maxPoints, ArrayList<double[]> sampled, Set<String> occupied, Bounds inputBounds, Bounds sampledBounds) {
        if (!Double.isFinite(x) || !Double.isFinite(y) || !Double.isFinite(z)) {
            return;
        }
        inputBounds.add(x, y, z);
        if (sampled.size() >= maxPoints) {
            return;
        }
        String key = voxelKey(x, y, z, voxelLeafM);
        if (!occupied.add(key)) {
            return;
        }
        sampled.add(new double[] { x, y, z });
        sampledBounds.add(x, y, z);
    }

    private JSObject buildOccupancyPayload(ArrayList<double[]> points, double voxelM, int maxVoxels) throws Exception {
        HashMap<String, double[]> centers = new HashMap<>();
        for (double[] point : points) {
            String key = voxelKey(point[0], point[1], point[2], voxelM);
            if (!centers.containsKey(key)) {
                centers.put(key, voxelCenter(point[0], point[1], point[2], voxelM));
            }
        }
        JSArray voxels = new JSArray();
        int displayed = 0;
        for (double[] center : centers.values()) {
            if (displayed >= maxVoxels) {
                break;
            }
            voxels.put(pointArray(center));
            displayed += 1;
        }
        JSObject payload = new JSObject();
        payload.put("voxel_m", voxelM);
        payload.put("occupied_count", centers.size());
        payload.put("displayed_count", displayed);
        payload.put("truncated", displayed < centers.size());
        payload.put("voxels", voxels);
        return payload;
    }

    private JSONObject parseMapYaml(File yamlFile, String pgmPathOverride) throws Exception {
        if (!yamlFile.exists() || !yamlFile.isFile()) {
            throw new IllegalArgumentException("map.yaml 不存在: " + yamlFile.getAbsolutePath());
        }
        Map<String, String> values = new HashMap<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(new FileInputStream(yamlFile), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                int comment = line.indexOf("#");
                String clean = (comment >= 0 ? line.substring(0, comment) : line).trim();
                int colon = clean.indexOf(":");
                if (colon > 0) {
                    values.put(clean.substring(0, colon).trim(), clean.substring(colon + 1).trim());
                }
            }
        }
        double resolution = Double.parseDouble(values.getOrDefault("resolution", "0.05"));
        double[] origin = parseOrigin(values.getOrDefault("origin", "[0, 0, 0]"));
        File pgmFile = pgmPathOverride == null || pgmPathOverride.trim().isEmpty()
            ? new File(yamlFile.getParentFile(), values.getOrDefault("image", ""))
            : new File(pgmPathOverride);
        int[] size = pgmFile.exists() ? readPgmSize(pgmFile) : new int[] { 0, 0 };
        JSONObject bounds = new JSONObject();
        bounds.put("xmin", origin[0]);
        bounds.put("xmax", origin[0] + size[0] * resolution);
        bounds.put("ymin", origin[1]);
        bounds.put("ymax", origin[1] + size[1] * resolution);
        bounds.put("zmin", 0.0);
        bounds.put("zmax", 0.0);
        JSONObject map = new JSONObject();
        map.put("yaml_path", yamlFile.getAbsolutePath());
        map.put("image_path", pgmFile.getAbsolutePath());
        if (pgmFile.exists()) {
            map.put("image_data_url", buildPgmDataUrl(pgmFile));
        }
        map.put("resolution", resolution);
        map.put("origin", pointArray(origin));
        map.put("width", size[0]);
        map.put("height", size[1]);
        map.put("bounds", bounds);
        return map;
    }

    private String buildPgmDataUrl(File file) throws Exception {
        PgmImage image = readPgmImage(file);
        Bitmap bitmap = Bitmap.createBitmap(image.width, image.height, Bitmap.Config.ARGB_8888);
        for (int y = 0; y < image.height; y += 1) {
            for (int x = 0; x < image.width; x += 1) {
                int gray = image.pixels[y * image.width + x] & 0xff;
                // 保持和后端 PGM 转 PNG 的像素顺序一致，贴图坐标翻转交给 Three.js 处理。
                bitmap.setPixel(x, y, Color.argb(255, gray, gray, gray));
            }
        }
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        bitmap.compress(Bitmap.CompressFormat.PNG, 100, output);
        bitmap.recycle();
        return "data:image/png;base64," + Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP);
    }

    private PgmImage readPgmImage(File file) throws Exception {
        byte[] raw = readAllBytes(file);
        ArrayList<String> tokens = new ArrayList<>();
        int cursor = 0;
        while (cursor < raw.length && tokens.size() < 4) {
            cursor = skipWhitespaceAndComments(raw, cursor);
            StringBuilder token = new StringBuilder();
            while (cursor < raw.length && !Character.isWhitespace((char) (raw[cursor] & 0xff))) {
                token.append((char) (raw[cursor] & 0xff));
                cursor += 1;
            }
            if (token.length() > 0) {
                tokens.add(token.toString());
            }
        }
        cursor = skipWhitespaceAndComments(raw, cursor);
        if (tokens.size() < 4) {
            throw new IllegalArgumentException("PGM 头部无效: " + file.getAbsolutePath());
        }
        String magic = tokens.get(0);
        int width = Integer.parseInt(tokens.get(1));
        int height = Integer.parseInt(tokens.get(2));
        int maxValue = Math.max(1, Integer.parseInt(tokens.get(3)));
        byte[] pixels = new byte[width * height];
        if ("P5".equals(magic)) {
            int bytesPerPixel = maxValue > 255 ? 2 : 1;
            for (int index = 0; index < pixels.length; index += 1) {
                int rawIndex = cursor + index * bytesPerPixel;
                if (rawIndex >= raw.length) {
                    break;
                }
                int value = bytesPerPixel == 1
                    ? raw[rawIndex] & 0xff
                    : ((raw[rawIndex] & 0xff) << 8) | (raw[Math.min(rawIndex + 1, raw.length - 1)] & 0xff);
                pixels[index] = (byte) Math.round(Math.min(255.0, Math.max(0.0, value * 255.0 / maxValue)));
            }
        } else if ("P2".equals(magic)) {
            String text = new String(raw, cursor, raw.length - cursor, StandardCharsets.UTF_8);
            String[] parts = text.replaceAll("(?m)#.*$", "").trim().split("\\s+");
            for (int index = 0; index < pixels.length && index < parts.length; index += 1) {
                int value = Integer.parseInt(parts[index]);
                pixels[index] = (byte) Math.round(Math.min(255.0, Math.max(0.0, value * 255.0 / maxValue)));
            }
        } else {
            throw new IllegalArgumentException("暂不支持 PGM 格式: " + magic);
        }
        return new PgmImage(width, height, pixels);
    }

    private int skipWhitespaceAndComments(byte[] raw, int cursor) {
        while (cursor < raw.length) {
            char ch = (char) (raw[cursor] & 0xff);
            if (Character.isWhitespace(ch)) {
                cursor += 1;
                continue;
            }
            if (ch == '#') {
                while (cursor < raw.length && raw[cursor] != '\n' && raw[cursor] != '\r') {
                    cursor += 1;
                }
                continue;
            }
            break;
        }
        return cursor;
    }

    private int[] readPgmSize(File file) throws Exception {
        byte[] raw = readAllBytes(file);
        ArrayList<String> tokens = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        boolean comment = false;
        for (byte item : raw) {
            char ch = (char) (item & 0xff);
            if (comment) {
                if (ch == '\n' || ch == '\r') {
                    comment = false;
                }
                continue;
            }
            if (ch == '#') {
                comment = true;
                continue;
            }
            if (Character.isWhitespace(ch)) {
                if (current.length() > 0) {
                    tokens.add(current.toString());
                    current.setLength(0);
                    if (tokens.size() >= 3) {
                        break;
                    }
                }
            } else {
                current.append(ch);
            }
        }
        if (tokens.size() < 3 || !tokens.get(0).startsWith("P")) {
            return new int[] { 0, 0 };
        }
        return new int[] { Integer.parseInt(tokens.get(1)), Integer.parseInt(tokens.get(2)) };
    }

    private byte[] readAllBytes(File file) throws Exception {
        try (InputStream input = new BufferedInputStream(new FileInputStream(file)); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[BUFFER_SIZE];
            int read;
            while ((read = input.read(buffer)) != -1) {
                output.write(buffer, 0, read);
            }
            return output.toByteArray();
        }
    }

    private int findHeaderEnd(byte[] raw) {
        byte[] marker = "\nDATA".getBytes(StandardCharsets.UTF_8);
        for (int index = 0; index <= raw.length - marker.length; index += 1) {
            boolean matched = true;
            for (int inner = 0; inner < marker.length; inner += 1) {
                if (raw[index + inner] != marker[inner]) {
                    matched = false;
                    break;
                }
            }
            if (matched) {
                int cursor = index + 1;
                while (cursor < raw.length && raw[cursor] != '\n') {
                    cursor += 1;
                }
                return Math.min(raw.length, cursor + 1);
            }
        }
        return raw.length;
    }

    private Map<String, String> parseHeader(String headerText) {
        Map<String, String> header = new HashMap<>();
        for (String line : headerText.split("\\r?\\n")) {
            String trimmed = line.trim();
            if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                continue;
            }
            String[] parts = trimmed.split("\\s+", 2);
            if (parts.length == 2) {
                header.put(parts[0].toUpperCase(Locale.US), parts[1].trim());
            }
        }
        return header;
    }

    private String[] splitHeaderList(String raw) {
        return raw == null || raw.trim().isEmpty() ? new String[0] : raw.trim().split("\\s+");
    }

    private int[] parseIntList(String raw, int length, int defaultValue) {
        int[] values = new int[length];
        String[] parts = splitHeaderList(raw);
        for (int index = 0; index < length; index += 1) {
            values[index] = index < parts.length ? Integer.parseInt(parts[index]) : defaultValue;
        }
        return values;
    }

    private FieldLayout buildFieldLayout(String[] fields, int[] sizes, String[] types, int[] counts) {
        FieldLayout layout = new FieldLayout();
        int offset = 0;
        for (int index = 0; index < fields.length; index += 1) {
            String field = fields[index].toLowerCase(Locale.US);
            if ("x".equals(field)) {
                layout.xOffset = offset;
                layout.xSize = sizes[index];
                layout.xType = types.length > index ? types[index] : "F";
                layout.xFieldIndex = index;
            } else if ("y".equals(field)) {
                layout.yOffset = offset;
                layout.ySize = sizes[index];
                layout.yType = types.length > index ? types[index] : "F";
                layout.yFieldIndex = index;
            } else if ("z".equals(field)) {
                layout.zOffset = offset;
                layout.zSize = sizes[index];
                layout.zType = types.length > index ? types[index] : "F";
                layout.zFieldIndex = index;
            }
            offset += sizes[index] * Math.max(1, counts[index]);
        }
        layout.pointStep = offset;
        if (layout.xFieldIndex < 0 || layout.yFieldIndex < 0 || layout.zFieldIndex < 0) {
            throw new IllegalArgumentException("PCD 缺少 x/y/z 字段");
        }
        return layout;
    }

    private double readNumber(byte[] raw, int offset, int size, String type) {
        ByteBuffer buffer = ByteBuffer.wrap(raw, offset, size).order(ByteOrder.LITTLE_ENDIAN);
        String normalizedType = type == null ? "F" : type.toUpperCase(Locale.US);
        if ("F".equals(normalizedType)) {
            return size == 8 ? buffer.getDouble() : buffer.getFloat();
        }
        if ("U".equals(normalizedType)) {
            if (size == 1) return raw[offset] & 0xff;
            if (size == 2) return buffer.getShort() & 0xffff;
            return buffer.getInt() & 0xffffffffL;
        }
        if (size == 1) return raw[offset];
        if (size == 2) return buffer.getShort();
        return buffer.getInt();
    }

    private String voxelKey(double x, double y, double z, double voxelM) {
        return (long) Math.floor(x / voxelM) + ":" + (long) Math.floor(y / voxelM) + ":" + (long) Math.floor(z / voxelM);
    }

    private double[] voxelCenter(double x, double y, double z, double voxelM) {
        return new double[] {
            (Math.floor(x / voxelM) + 0.5) * voxelM,
            (Math.floor(y / voxelM) + 0.5) * voxelM,
            (Math.floor(z / voxelM) + 0.5) * voxelM,
        };
    }

    private JSArray pointArray(double[] values) throws Exception {
        JSArray array = new JSArray();
        for (double value : values) {
            array.put(value);
        }
        return array;
    }

    private double[] parseOrigin(String raw) {
        String[] parts = raw.replace("[", "").replace("]", "").split(",");
        double[] origin = new double[] { 0.0, 0.0, 0.0 };
        for (int index = 0; index < Math.min(3, parts.length); index += 1) {
            origin[index] = Double.parseDouble(parts[index].trim());
        }
        return origin;
    }

    private double clamp(double value, double min, double max) {
        if (!Double.isFinite(value)) {
            return min;
        }
        return Math.max(min, Math.min(max, value));
    }

    private static class FieldLayout {
        int xFieldIndex = -1;
        int yFieldIndex = -1;
        int zFieldIndex = -1;
        int xOffset = 0;
        int yOffset = 0;
        int zOffset = 0;
        int xSize = 4;
        int ySize = 4;
        int zSize = 4;
        String xType = "F";
        String yType = "F";
        String zType = "F";
        int pointStep = 0;
    }

    private class Bounds {
        int count = 0;
        double xmin = Double.POSITIVE_INFINITY;
        double xmax = Double.NEGATIVE_INFINITY;
        double ymin = Double.POSITIVE_INFINITY;
        double ymax = Double.NEGATIVE_INFINITY;
        double zmin = Double.POSITIVE_INFINITY;
        double zmax = Double.NEGATIVE_INFINITY;

        void add(double x, double y, double z) {
            count += 1;
            xmin = Math.min(xmin, x);
            xmax = Math.max(xmax, x);
            ymin = Math.min(ymin, y);
            ymax = Math.max(ymax, y);
            zmin = Math.min(zmin, z);
            zmax = Math.max(zmax, z);
        }

        JSObject toJson() throws Exception {
            JSObject json = new JSObject();
            json.put("xmin", count == 0 ? 0.0 : xmin);
            json.put("xmax", count == 0 ? 0.0 : xmax);
            json.put("ymin", count == 0 ? 0.0 : ymin);
            json.put("ymax", count == 0 ? 0.0 : ymax);
            json.put("zmin", count == 0 ? 0.0 : zmin);
            json.put("zmax", count == 0 ? 0.0 : zmax);
            return json;
        }
    }

    private class PcdPreview {
        final String path;
        final int inputPoints;
        final double voxelLeafM;
        final ArrayList<double[]> points;
        final Bounds inputBounds;
        final Bounds sampledBounds;

        PcdPreview(String path, int inputPoints, double voxelLeafM, ArrayList<double[]> points, Bounds inputBounds, Bounds sampledBounds) {
            this.path = path;
            this.inputPoints = inputPoints;
            this.voxelLeafM = voxelLeafM;
            this.points = points;
            this.inputBounds = inputBounds;
            this.sampledBounds = sampledBounds;
        }

        JSObject toJson() throws Exception {
            JSArray pointArray = new JSArray();
            for (double[] point : points) {
                pointArray.put(RosFilePickerPlugin.this.pointArray(point));
            }
            JSObject json = new JSObject();
            json.put("path", path);
            json.put("input_points", inputPoints);
            json.put("sampled_count", points.size());
            json.put("voxel_leaf_m", voxelLeafM);
            json.put("input_bounds", inputBounds.toJson());
            json.put("sampled_bounds", sampledBounds.toJson());
            json.put("points", pointArray);
            return json;
        }
    }

    private static class PgmImage {
        final int width;
        final int height;
        final byte[] pixels;

        PgmImage(int width, int height, byte[] pixels) {
            this.width = width;
            this.height = height;
            this.pixels = pixels;
        }
    }
}
