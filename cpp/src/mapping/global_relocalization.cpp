// 功能说明：实现全局重定位候选点 C++ 生成器，避免 Python 逐点/逐候选处理导致离线生成过慢。

#include "ros_tool_suite/mapping/global_relocalization.hpp"

#include "ros_tool_suite/mapping/pcd_reader.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>

namespace ros_tool_suite::mapping {
namespace {

constexpr double kPi = 3.14159265358979323846;

struct Point3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

struct Bounds3 {
    double min_x = std::numeric_limits<double>::infinity();
    double min_y = std::numeric_limits<double>::infinity();
    double min_z = std::numeric_limits<double>::infinity();
    double max_x = -std::numeric_limits<double>::infinity();
    double max_y = -std::numeric_limits<double>::infinity();
    double max_z = -std::numeric_limits<double>::infinity();
};

using Mat3 = std::array<std::array<double, 3>, 3>;

struct GroundCell {
    int count = 0;
    double min_z = std::numeric_limits<double>::infinity();
    double max_z = -std::numeric_limits<double>::infinity();
    double sum_z = 0.0;
    std::vector<double> z_values;
};

struct BasePosition {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    double roll_deg = 0.0;
    double pitch_deg = 0.0;
    double yaw_deg = 0.0;
    std::string source = "auto";
    std::string label;
    bool locked = false;
    bool z_auto = false;
};

struct DeletionRegion {
    std::string label;
    double min_x = 0.0;
    double max_x = 0.0;
    double min_y = 0.0;
    double max_y = 0.0;
};

struct ManualEdit {
    std::vector<BasePosition> additions;
    std::unordered_set<int> deletion_ids;
    std::vector<DeletionRegion> deletion_regions;
};

std::string trim(std::string value) {
    const auto first = value.find_first_not_of(" \t\r\n\"'");
    if (first == std::string::npos) {
        return "";
    }
    const auto last = value.find_last_not_of(" \t\r\n\"'");
    return value.substr(first, last - first + 1);
}

std::string to_lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

std::vector<double> parse_number_list(std::string value) {
    for (char& ch : value) {
        if (ch == '[' || ch == ']' || ch == ',') {
            ch = ' ';
        }
    }
    std::istringstream iss(value);
    std::vector<double> numbers;
    double item = 0.0;
    while (iss >> item) {
        numbers.push_back(item);
    }
    return numbers;
}

std::string strip_yaml_list_marker(const std::string& value) {
    std::string stripped = trim(value);
    if (!stripped.empty() && stripped.front() == '-') {
        stripped = trim(stripped.substr(1));
    }
    return stripped;
}

bool parse_bool(std::string value, bool fallback) {
    value = trim(value);
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    if (value == "true" || value == "1" || value == "yes") {
        return true;
    }
    if (value == "false" || value == "0" || value == "no") {
        return false;
    }
    return fallback;
}

int64_t pack3(int x, int y, int z) {
    // 每个轴保留 21 bit，足够覆盖常见地图体素索引范围；偏移避免负数符号扩散。
    constexpr int64_t offset = 1 << 20;
    return ((static_cast<int64_t>(x) + offset) << 42) ^
           ((static_cast<int64_t>(y) + offset) << 21) ^
           (static_cast<int64_t>(z) + offset);
}

int64_t pack2(int x, int y) {
    return (static_cast<int64_t>(x) << 32) ^ (static_cast<uint32_t>(y));
}

int index_for(double value, double resolution) {
    return static_cast<int>(std::floor(value / resolution));
}

std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> values;
    std::string item;
    std::istringstream iss(line);
    while (std::getline(iss, item, ',')) {
        values.push_back(trim(item));
    }
    return values;
}

double parse_double_or(const std::string& value, double fallback) {
    if (value.empty()) {
        return fallback;
    }
    char* end = nullptr;
    const double parsed = std::strtod(value.c_str(), &end);
    return end == value.c_str() ? fallback : parsed;
}

int parse_int_or(const std::string& value, int fallback) {
    return static_cast<int>(std::round(parse_double_or(value, static_cast<double>(fallback))));
}

double percentile_z(const GroundCell& cell, double percentile) {
    if (cell.z_values.empty()) {
        return std::isfinite(cell.min_z) ? cell.min_z : 0.0;
    }
    auto values = cell.z_values;
    std::sort(values.begin(), values.end());
    const double clamped = std::max(0.0, std::min(1.0, percentile));
    const std::size_t index = static_cast<std::size_t>(std::round(clamped * static_cast<double>(values.size() - 1)));
    return values[std::min(index, values.size() - 1)];
}

std::array<double, 4> quaternion_from_rpy(double roll_deg, double pitch_deg, double yaw_deg);

std::string quantized_place_key(const GlobalRelocCandidate& candidate) {
    // v2 离线库按可站立位置去重，使用毫米级量化避免同一位置的浮点尾差形成重复 place。
    std::ostringstream key;
    key << std::llround(candidate.x * 1000.0) << ':'
        << std::llround(candidate.y * 1000.0) << ':'
        << std::llround(candidate.z * 1000.0);
    return key.str();
}

void apply_canonical_yaw(GlobalRelocCandidate& candidate) {
    // v2 只存 canonical yaw 下的描述子；在线 yaw 初值由 Scan Context sector shift 估计。
    candidate.yaw_deg = 0.0;
    const auto q = quaternion_from_rpy(candidate.roll_deg, candidate.pitch_deg, candidate.yaw_deg);
    candidate.qx = q[0];
    candidate.qy = q[1];
    candidate.qz = q[2];
    candidate.qw = q[3];
}

std::vector<GlobalRelocCandidate> collapse_to_places(const std::vector<GlobalRelocCandidate>& rows) {
    std::vector<GlobalRelocCandidate> places;
    places.reserve(rows.size());
    std::unordered_set<std::string> seen;
    for (auto candidate : rows) {
        const auto key = quantized_place_key(candidate);
        if (seen.find(key) != seen.end()) {
            continue;
        }
        seen.insert(key);
        apply_canonical_yaw(candidate);
        candidate.candidate_id = static_cast<int>(places.size());
        if (candidate.original_candidate_id < 0) {
            candidate.original_candidate_id = candidate.candidate_id;
        }
        places.push_back(candidate);
    }
    return places;
}

Mat3 mat_mul(const Mat3& left, const Mat3& right) {
    Mat3 out{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            out[r][c] = left[r][0] * right[0][c] + left[r][1] * right[1][c] + left[r][2] * right[2][c];
        }
    }
    return out;
}

Point3 mat_vec(const Mat3& mat, const Point3& value) {
    return {
        mat[0][0] * value.x + mat[0][1] * value.y + mat[0][2] * value.z,
        mat[1][0] * value.x + mat[1][1] * value.y + mat[1][2] * value.z,
        mat[2][0] * value.x + mat[2][1] * value.y + mat[2][2] * value.z,
    };
}

Mat3 transpose(const Mat3& mat) {
    Mat3 out{};
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            out[r][c] = mat[c][r];
        }
    }
    return out;
}

Mat3 rpy_to_matrix(double roll_deg, double pitch_deg, double yaw_deg) {
    const double roll = roll_deg * kPi / 180.0;
    const double pitch = pitch_deg * kPi / 180.0;
    const double yaw = yaw_deg * kPi / 180.0;
    const double cr = std::cos(roll);
    const double sr = std::sin(roll);
    const double cp = std::cos(pitch);
    const double sp = std::sin(pitch);
    const double cy = std::cos(yaw);
    const double sy = std::sin(yaw);
    const Mat3 rx{{{1.0, 0.0, 0.0}, {0.0, cr, -sr}, {0.0, sr, cr}}};
    const Mat3 ry{{{cp, 0.0, sp}, {0.0, 1.0, 0.0}, {-sp, 0.0, cp}}};
    const Mat3 rz{{{cy, -sy, 0.0}, {sy, cy, 0.0}, {0.0, 0.0, 1.0}}};
    return mat_mul(mat_mul(rz, ry), rx);
}

Point3 add_point(const Point3& left, const Point3& right) {
    return {left.x + right.x, left.y + right.y, left.z + right.z};
}

Point3 sub_point(const Point3& left, const Point3& right) {
    return {left.x - right.x, left.y - right.y, left.z - right.z};
}

Point3 scale_point(const Point3& value, double scale) {
    return {value.x * scale, value.y * scale, value.z * scale};
}

bool inside_bounds(const Point3& point, const Bounds3& bounds) {
    return point.x >= bounds.min_x && point.x <= bounds.max_x &&
           point.y >= bounds.min_y && point.y <= bounds.max_y &&
           point.z >= bounds.min_z && point.z <= bounds.max_z;
}

std::array<double, 4> quaternion_from_rpy(double roll_deg, double pitch_deg, double yaw_deg) {
    const double roll = roll_deg * kPi / 180.0;
    const double pitch = pitch_deg * kPi / 180.0;
    const double yaw = yaw_deg * kPi / 180.0;
    const double cr = std::cos(roll * 0.5);
    const double sr = std::sin(roll * 0.5);
    const double cp = std::cos(pitch * 0.5);
    const double sp = std::sin(pitch * 0.5);
    const double cy = std::cos(yaw * 0.5);
    const double sy = std::sin(yaw * 0.5);
    return {
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    };
}

void write_npy_header(std::ofstream& output, const std::vector<int>& shape) {
    std::ostringstream dict;
    dict << "{'descr': '<f4', 'fortran_order': False, 'shape': (";
    for (std::size_t i = 0; i < shape.size(); ++i) {
        dict << shape[i];
        if (shape.size() == 1 || i + 1 < shape.size()) {
            dict << ", ";
        }
    }
    dict << "), }";
    std::string header = dict.str();
    const std::size_t prefix_size = 10;
    const std::size_t padded = ((prefix_size + header.size() + 1 + 15) / 16) * 16;
    header.append(padded - prefix_size - header.size() - 1, ' ');
    header.push_back('\n');
    const std::uint16_t header_len = static_cast<std::uint16_t>(header.size());
    output.write("\x93NUMPY", 6);
    output.put(1);
    output.put(0);
    output.write(reinterpret_cast<const char*>(&header_len), sizeof(header_len));
    output.write(header.data(), static_cast<std::streamsize>(header.size()));
}

void write_float32_npy(const std::filesystem::path& path, const std::vector<int>& shape, const std::vector<float>& values) {
    std::ofstream output(path, std::ios::binary);
    if (!output) {
        throw std::runtime_error("failed to write npy file");
    }
    write_npy_header(output, shape);
    if (!values.empty()) {
        output.write(reinterpret_cast<const char*>(values.data()), static_cast<std::streamsize>(values.size() * sizeof(float)));
    }
}

void apply_config_value(GlobalRelocConfig& config, const std::string& section, const std::string& key, const std::string& raw_value) {
    const std::string scoped = section + "." + key;
    const auto numbers = parse_number_list(raw_value);
    auto number = [&](double fallback) { return numbers.empty() ? fallback : numbers.front(); };
    if (scoped == "map.voxel_leaf_m") config.voxel_leaf_m = number(config.voxel_leaf_m);
    else if (scoped == "map.occupancy_resolution_m") config.occupancy_resolution_m = number(config.occupancy_resolution_m);
    else if (scoped == "map.z_min_m") config.z_min_m = number(config.z_min_m);
    else if (scoped == "map.z_max_m") config.z_max_m = number(config.z_max_m);
    else if (scoped == "candidate_sampling.strategy") config.strategy = trim(raw_value);
    else if (scoped == "candidate_sampling.xy_resolution_m") config.xy_resolution_m = number(config.xy_resolution_m);
    else if (scoped == "candidate_sampling.min_candidate_distance_m") config.min_candidate_distance_m = number(config.min_candidate_distance_m);
    else if (scoped == "candidate_sampling.robot_radius_m") config.robot_radius_m = number(config.robot_radius_m);
    else if (scoped == "candidate_sampling.safety_margin_m") config.safety_margin_m = number(config.safety_margin_m);
    else if (scoped == "candidate_sampling.clearance_check_height_m") config.clearance_check_height_m = number(config.clearance_check_height_m);
    else if (scoped == "candidate_sampling.clearance_min_free_ratio") config.clearance_min_free_ratio = number(config.clearance_min_free_ratio);
    else if (scoped == "candidate_sampling.map_boundary_margin_m") config.map_boundary_margin_m = number(config.map_boundary_margin_m);
    else if (scoped == "candidate_sampling.ground_min_points_per_cell") config.ground_min_points_per_cell = static_cast<int>(number(config.ground_min_points_per_cell));
    else if (scoped == "candidate_sampling.ground_support_radius_m") config.ground_support_radius_m = number(config.ground_support_radius_m);
    else if (scoped == "candidate_sampling.ground_min_neighbor_cells") config.ground_min_neighbor_cells = static_cast<int>(number(config.ground_min_neighbor_cells));
    else if (scoped == "candidate_sampling.ground_support_max_delta_z_m") config.ground_support_max_delta_z_m = number(config.ground_support_max_delta_z_m);
    else if (scoped == "candidate_sampling.base_link_height_offset_m") config.base_link_height_offset_m = number(config.base_link_height_offset_m);
    else if (scoped == "candidate_sampling.roll_samples_deg" && !numbers.empty()) config.roll_samples_deg = numbers;
    else if (scoped == "candidate_sampling.pitch_samples_deg" && !numbers.empty()) config.pitch_samples_deg = numbers;
    else if (scoped == "candidate_sampling.yaw_step_deg") config.yaw_step_deg = number(config.yaw_step_deg);
    else if (scoped == "candidate_sampling.random_seed") config.random_seed = static_cast<unsigned int>(number(config.random_seed));
    else if (scoped == "candidate_sampling.target_base_positions") config.target_base_positions = static_cast<int>(number(config.target_base_positions));
    else if (scoped == "candidate_sampling.max_base_samples") config.max_base_samples = static_cast<int>(number(config.max_base_samples));
    else if (scoped == "candidate_sampling.early_stop_window") config.early_stop_window = static_cast<int>(number(config.early_stop_window));
    else if (scoped == "candidate_sampling.early_stop_min_accepts") config.early_stop_min_accepts = static_cast<int>(number(config.early_stop_min_accepts));
    else if (scoped == "candidate_sampling.max_candidates") config.max_candidates = static_cast<int>(number(config.max_candidates));
    else if (scoped == "virtual_lidar.min_range_m") config.virtual_lidar_min_range_m = number(config.virtual_lidar_min_range_m);
    else if (scoped == "virtual_lidar.max_range_m") config.virtual_lidar_max_range_m = number(config.virtual_lidar_max_range_m);
    else if (scoped == "virtual_lidar.horizontal_fov_deg") config.virtual_lidar_horizontal_fov_deg = number(config.virtual_lidar_horizontal_fov_deg);
    else if (scoped == "virtual_lidar.vertical_fov_deg") config.virtual_lidar_vertical_fov_deg = number(config.virtual_lidar_vertical_fov_deg);
    else if (scoped == "virtual_lidar.horizontal_step_deg") config.virtual_lidar_horizontal_step_deg = number(config.virtual_lidar_horizontal_step_deg);
    else if (scoped == "virtual_lidar.vertical_step_deg") config.virtual_lidar_vertical_step_deg = number(config.virtual_lidar_vertical_step_deg);
    else if (scoped == "virtual_lidar.occupancy_inflate_radius_m") config.virtual_lidar_occupancy_inflate_radius_m = number(config.virtual_lidar_occupancy_inflate_radius_m);
    else if (scoped == "virtual_lidar.lidar_to_base_translation_xyz" && numbers.size() >= 3) config.lidar_to_base_translation_xyz = {numbers[0], numbers[1], numbers[2]};
    else if (scoped == "virtual_lidar.lidar_to_base_rpy_deg" && numbers.size() >= 3) config.lidar_to_base_rpy_deg = {numbers[0], numbers[1], numbers[2]};
    else if (scoped == "descriptor.num_rings") config.descriptor_num_rings = static_cast<int>(number(config.descriptor_num_rings));
    else if (scoped == "descriptor.num_sectors") config.descriptor_num_sectors = static_cast<int>(number(config.descriptor_num_sectors));
    else if (scoped == "descriptor.max_radius_m") config.descriptor_max_radius_m = number(config.descriptor_max_radius_m);
    else if (scoped == "descriptor.height_clip_min_m") config.descriptor_height_clip_min_m = number(config.descriptor_height_clip_min_m);
    else if (scoped == "descriptor.height_clip_max_m") config.descriptor_height_clip_max_m = number(config.descriptor_height_clip_max_m);
    else if (scoped == "observability.min_hit_points") config.observability_min_hit_points = static_cast<int>(number(config.observability_min_hit_points));
    else if (scoped == "observability.min_hit_ratio") config.observability_min_hit_ratio = number(config.observability_min_hit_ratio);
    else if (scoped == "observability.min_visible_sector_count") config.observability_min_visible_sector_count = static_cast<int>(number(config.observability_min_visible_sector_count));
    else if (scoped == "observability.min_descriptor_nonzero_ratio") config.observability_min_descriptor_nonzero_ratio = number(config.observability_min_descriptor_nonzero_ratio);
    else if (scoped == "manual_edit.allow_force_add_low_observability") config.allow_force_add_low_observability = parse_bool(raw_value, config.allow_force_add_low_observability);
}

ManualEdit load_manual_edit(const std::string& manual_path) {
    ManualEdit edit;
    if (manual_path.empty() || !std::filesystem::exists(manual_path)) {
        return edit;
    }
    std::ifstream input(manual_path);
    if (!input) {
        throw std::runtime_error("failed to open manual edit yaml");
    }

    std::string mode;
    std::string deletion_mode;
    BasePosition current;
    DeletionRegion current_region;
    bool in_addition = false;
    bool in_region = false;
    std::string line;
    auto finish_addition = [&]() {
        if (in_addition) {
            edit.additions.push_back(current);
            current = {};
            in_addition = false;
        }
    };
    auto finish_region = [&]() {
        if (in_region) {
            edit.deletion_regions.push_back(current_region);
            current_region = {};
            in_region = false;
        }
    };
    while (std::getline(input, line)) {
        const auto hash = line.find('#');
        if (hash != std::string::npos) {
            line = line.substr(0, hash);
        }
        const std::string stripped = trim(line);
        if (stripped.empty()) {
            continue;
        }
        if (stripped == "additions:") {
            finish_region();
            mode = "additions";
            deletion_mode.clear();
            continue;
        }
        if (stripped == "deletions:") {
            finish_addition();
            finish_region();
            mode = "deletions";
            deletion_mode.clear();
            continue;
        }
        if (stripped.rfind("-", 0) == 0 && mode == "additions") {
            const std::string item = strip_yaml_list_marker(stripped);
            const auto colon = item.find(':');
            if (colon == std::string::npos) {
                continue;
            }
            finish_addition();
            current = {};
            current.source = "manual_added";
            current.locked = true;
            in_addition = true;
            const std::string key = trim(item.substr(0, colon));
            const std::string value = trim(item.substr(colon + 1));
            if (key == "label") current.label = value;
            continue;
        }
        if (mode == "deletions" && deletion_mode == "candidate_ids" && stripped.rfind("-", 0) == 0) {
            for (const double id : parse_number_list(strip_yaml_list_marker(stripped))) {
                edit.deletion_ids.insert(static_cast<int>(id));
            }
            continue;
        }
        if (mode == "deletions" && deletion_mode == "regions" && stripped.rfind("-", 0) == 0) {
            finish_region();
            in_region = true;
            const std::string item = strip_yaml_list_marker(stripped);
            const auto colon = item.find(':');
            if (colon != std::string::npos) {
                const std::string key = trim(item.substr(0, colon));
                const std::string value = trim(item.substr(colon + 1));
                if (key == "label") current_region.label = value;
            }
            continue;
        }
        const auto colon = stripped.find(':');
        if (colon == std::string::npos) {
            continue;
        }
        const std::string key = trim(stripped.substr(0, colon));
        const std::string value = trim(stripped.substr(colon + 1));
        if (mode == "additions" && in_addition) {
            if (key == "label") current.label = value;
            else if (key == "x") current.x = std::stod(value);
            else if (key == "y") current.y = std::stod(value);
            else if (key == "z" && value == "null") current.z_auto = true;
            else if (key == "z") current.z = std::stod(value);
            else if (key == "roll_deg") current.roll_deg = std::stod(value);
            else if (key == "pitch_deg") current.pitch_deg = std::stod(value);
            else if (key == "yaw_deg") current.yaw_deg = std::stod(value);
            else if (key == "yaw_expand_deg") current.yaw_deg = parse_number_list(value).empty() ? current.yaw_deg : parse_number_list(value).front();
            else if (key == "locked") current.locked = parse_bool(value, true);
        } else if (mode == "deletions") {
            if (key == "candidate_ids") {
                deletion_mode = "candidate_ids";
                for (const double id : parse_number_list(value)) {
                    edit.deletion_ids.insert(static_cast<int>(id));
                }
            } else if (key == "regions") {
                finish_region();
                deletion_mode = "regions";
            } else if (deletion_mode == "regions" && in_region) {
                if (key == "label") current_region.label = value;
                else if (key == "min_x") current_region.min_x = std::stod(value);
                else if (key == "max_x") current_region.max_x = std::stod(value);
                else if (key == "min_y") current_region.min_y = std::stod(value);
                else if (key == "max_y") current_region.max_y = std::stod(value);
            }
        }
    }
    finish_addition();
    finish_region();
    return edit;
}

std::vector<Point3> build_ray_directions(const GlobalRelocConfig& config) {
    const double hfov = config.virtual_lidar_horizontal_fov_deg * kPi / 180.0;
    const double vfov = config.virtual_lidar_vertical_fov_deg * kPi / 180.0;
    const double h_step = std::max(0.1, config.virtual_lidar_horizontal_step_deg) * kPi / 180.0;
    const double v_step = std::max(0.1, config.virtual_lidar_vertical_step_deg) * kPi / 180.0;
    const int h_count = std::max(1, static_cast<int>(std::ceil(hfov / h_step)));
    const int v_count = std::max(1, static_cast<int>(std::ceil(vfov / v_step)));
    const double h_start = -hfov * 0.5;
    const double v_start = -vfov * 0.5;
    std::vector<Point3> directions;
    directions.reserve(static_cast<std::size_t>((v_count + 1) * h_count));
    for (int vi = 0; vi <= v_count; ++vi) {
        const double v = v_start + static_cast<double>(vi) * (vfov / static_cast<double>(std::max(1, v_count)));
        const double cv = std::cos(v);
        for (int hi = 0; hi < h_count; ++hi) {
            const double h = h_start + static_cast<double>(hi) * (hfov / static_cast<double>(h_count));
            directions.push_back({cv * std::cos(h), cv * std::sin(h), std::sin(v)});
        }
    }
    return directions;
}

bool ray_cast(
    const std::unordered_set<int64_t>& occupied,
    const Bounds3& bounds,
    const GlobalRelocConfig& config,
    const Point3& origin,
    const Point3& direction,
    Point3& hit_lidar,
    const Mat3& lidar_rot_t) {
    const double step = config.occupancy_resolution_m * 0.75;
    const double inflate_radius = std::max(0.0, config.virtual_lidar_occupancy_inflate_radius_m);
    const int inflate_cells = std::max(0, static_cast<int>(std::ceil(inflate_radius / config.occupancy_resolution_m)));
    for (double dist = config.virtual_lidar_min_range_m; dist <= config.virtual_lidar_max_range_m; dist += step) {
        const Point3 point = add_point(origin, scale_point(direction, dist));
        if (!inside_bounds(point, bounds)) {
            continue;
        }
        const int ix = index_for(point.x, config.occupancy_resolution_m);
        const int iy = index_for(point.y, config.occupancy_resolution_m);
        const int iz = index_for(point.z, config.occupancy_resolution_m);
        bool hit = false;
        for (int dz = -inflate_cells; dz <= inflate_cells && !hit; ++dz) {
            for (int dy = -inflate_cells; dy <= inflate_cells && !hit; ++dy) {
                for (int dx = -inflate_cells; dx <= inflate_cells; ++dx) {
                    const double inflate_distance = std::sqrt(static_cast<double>(dx * dx + dy * dy + dz * dz)) * config.occupancy_resolution_m;
                    if (inflate_distance > inflate_radius) {
                        continue;
                    }
                    if (occupied.find(pack3(ix + dx, iy + dy, iz + dz)) != occupied.end()) {
                        hit = true;
                        break;
                    }
                }
            }
        }
        if (!hit) {
            continue;
        }
        const Point3 center{
            (static_cast<double>(ix) + 0.5) * config.occupancy_resolution_m,
            (static_cast<double>(iy) + 0.5) * config.occupancy_resolution_m,
            (static_cast<double>(iz) + 0.5) * config.occupancy_resolution_m,
        };
        hit_lidar = mat_vec(lidar_rot_t, sub_point(center, origin));
        return true;
    }
    return false;
}

void compute_candidate_descriptor(
    GlobalRelocCandidate& candidate,
    const std::unordered_set<int64_t>& occupied,
    const Bounds3& bounds,
    const GlobalRelocConfig& config,
    const std::vector<Point3>& ray_dirs,
    std::vector<float>& descriptor,
    std::vector<float>& ring_key) {
    const int rings = std::max(1, config.descriptor_num_rings);
    const int sectors = std::max(1, config.descriptor_num_sectors);
    descriptor.assign(static_cast<std::size_t>(rings * sectors), 0.0f);
    ring_key.assign(static_cast<std::size_t>(rings), 0.0f);

    const Mat3 base_rot = rpy_to_matrix(candidate.roll_deg, candidate.pitch_deg, candidate.yaw_deg);
    const Mat3 lidar_rot_in_base = rpy_to_matrix(
        config.lidar_to_base_rpy_deg.size() > 0 ? config.lidar_to_base_rpy_deg[0] : 0.0,
        config.lidar_to_base_rpy_deg.size() > 1 ? config.lidar_to_base_rpy_deg[1] : 0.0,
        config.lidar_to_base_rpy_deg.size() > 2 ? config.lidar_to_base_rpy_deg[2] : 0.0);
    const Mat3 lidar_rot = mat_mul(base_rot, lidar_rot_in_base);
    const Mat3 lidar_rot_t = transpose(lidar_rot);
    const Point3 lidar_t{
        config.lidar_to_base_translation_xyz.size() > 0 ? config.lidar_to_base_translation_xyz[0] : 0.0,
        config.lidar_to_base_translation_xyz.size() > 1 ? config.lidar_to_base_translation_xyz[1] : 0.0,
        config.lidar_to_base_translation_xyz.size() > 2 ? config.lidar_to_base_translation_xyz[2] : 0.0,
    };
    const Point3 base_xyz{candidate.x, candidate.y, candidate.z};
    const Point3 origin = add_point(base_xyz, mat_vec(base_rot, lidar_t));

    int hit_count = 0;
    for (const auto& dir_lidar : ray_dirs) {
        const Point3 dir_map = mat_vec(lidar_rot, dir_lidar);
        Point3 hit_lidar;
        if (!ray_cast(occupied, bounds, config, origin, dir_map, hit_lidar, lidar_rot_t)) {
            continue;
        }
        ++hit_count;
        const double radius = std::sqrt(hit_lidar.x * hit_lidar.x + hit_lidar.y * hit_lidar.y);
        if (radius <= 1e-6 || radius > config.descriptor_max_radius_m) {
            continue;
        }
        double angle = std::atan2(hit_lidar.y, hit_lidar.x);
        if (angle < 0.0) {
            angle += 2.0 * kPi;
        }
        const int ring = std::min(rings - 1, std::max(0, static_cast<int>(std::floor(radius / config.descriptor_max_radius_m * rings))));
        const int sector = std::min(sectors - 1, std::max(0, static_cast<int>(std::floor(angle / (2.0 * kPi) * sectors))));
        const double clipped_z = std::min(config.descriptor_height_clip_max_m, std::max(config.descriptor_height_clip_min_m, hit_lidar.z));
        const float height_value = static_cast<float>(clipped_z - config.descriptor_height_clip_min_m);
        auto& bin = descriptor[static_cast<std::size_t>(ring * sectors + sector)];
        bin = std::max(bin, height_value);
    }

    int nonzero = 0;
    int visible_sectors = 0;
    double height_sum = 0.0;
    for (int r = 0; r < rings; ++r) {
        float ring_max = 0.0f;
        for (int s = 0; s < sectors; ++s) {
            const float value = descriptor[static_cast<std::size_t>(r * sectors + s)];
            ring_max = std::max(ring_max, value);
            if (value > 0.0f) {
                ++nonzero;
                height_sum += value;
            }
        }
        ring_key[static_cast<std::size_t>(r)] = ring_max;
    }
    for (int s = 0; s < sectors; ++s) {
        bool any = false;
        for (int r = 0; r < rings; ++r) {
            if (descriptor[static_cast<std::size_t>(r * sectors + s)] > 0.0f) {
                any = true;
                break;
            }
        }
        if (any) {
            ++visible_sectors;
        }
    }

    candidate.hit_count = hit_count;
    candidate.hit_ratio = static_cast<double>(hit_count) / static_cast<double>(std::max<std::size_t>(1, ray_dirs.size()));
    candidate.visible_sector_count = visible_sectors;
    candidate.descriptor_nonzero_ratio = static_cast<double>(nonzero) / static_cast<double>(rings * sectors);
    const double height_energy = nonzero > 0 ? height_sum / static_cast<double>(nonzero) : 0.0;
    candidate.observability_score =
        candidate.hit_ratio * 0.5 +
        candidate.descriptor_nonzero_ratio * 0.3 +
        std::min(1.0, height_energy / std::max(1e-6, config.descriptor_height_clip_max_m - config.descriptor_height_clip_min_m)) * 0.2;
}

std::vector<GlobalRelocCandidate> load_reviewed_candidates(const std::string& path, const GlobalRelocConfig& config) {
    std::vector<GlobalRelocCandidate> candidates;
    if (path.empty()) {
        return candidates;
    }
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("failed to open reviewed candidates csv");
    }
    std::string header_line;
    if (!std::getline(input, header_line)) {
        return candidates;
    }
    const auto headers = split_csv_line(header_line);
    std::unordered_map<std::string, std::size_t> index;
    for (std::size_t i = 0; i < headers.size(); ++i) {
        index[headers[i]] = i;
    }
    auto value = [&](const std::vector<std::string>& row, const std::string& key) -> std::string {
        const auto it = index.find(key);
        if (it == index.end() || it->second >= row.size()) {
            return "";
        }
        return row[it->second];
    };
    std::string line;
    int next_id = 0;
    while (std::getline(input, line)) {
        if (trim(line).empty()) {
            continue;
        }
        const auto row = split_csv_line(line);
        GlobalRelocCandidate candidate;
        candidate.candidate_id = parse_int_or(value(row, "place_id"), next_id++);
        if (value(row, "place_id").empty()) {
            candidate.candidate_id = parse_int_or(value(row, "candidate_id"), candidate.candidate_id);
        }
        candidate.x = parse_double_or(value(row, "x"), 0.0);
        candidate.y = parse_double_or(value(row, "y"), 0.0);
        candidate.z = parse_double_or(value(row, "z"), 0.0);
        candidate.roll_deg = parse_double_or(value(row, "roll_deg"), 0.0);
        candidate.pitch_deg = parse_double_or(value(row, "pitch_deg"), 0.0);
        candidate.yaw_deg = parse_double_or(value(row, "canonical_yaw_deg"), parse_double_or(value(row, "yaw_deg"), 0.0));
        apply_canonical_yaw(candidate);
        candidate.source = value(row, "source").empty() ? "auto" : value(row, "source");
        candidate.label = value(row, "label");
        candidate.locked = parse_bool(value(row, "locked"), false);
        candidate.original_candidate_id = parse_int_or(value(row, "original_candidate_id"), parse_int_or(value(row, "candidate_id"), candidate.candidate_id));
        const std::string z_frame = to_lower_copy(trim(value(row, "z_frame")));
        const bool legacy_reviewed_ground_z =
            z_frame.empty() &&
            candidate.source == "manual_added" &&
            parse_double_or(value(row, "hit_count"), 0.0) == 0.0 &&
            parse_double_or(value(row, "descriptor_nonzero_ratio"), 0.0) == 0.0;
        // 新增人工点在前端三维视图中落在地图地面上，这里统一转成 map 下的 base_link 高度。
        if (z_frame == "ground" || legacy_reviewed_ground_z) {
            candidate.z += config.base_link_height_offset_m;
        }
        candidates.push_back(candidate);
    }
    return collapse_to_places(candidates);
}

}  // namespace

GlobalRelocConfig load_global_reloc_config(const std::string& config_path, GlobalRelocConfig defaults) {
    if (config_path.empty() || !std::filesystem::exists(config_path)) {
        return defaults;
    }
    std::ifstream input(config_path);
    if (!input) {
        throw std::runtime_error("failed to open config yaml");
    }

    std::string section;
    std::string line;
    while (std::getline(input, line)) {
        const auto hash = line.find('#');
        if (hash != std::string::npos) {
            line = line.substr(0, hash);
        }
        if (trim(line).empty()) {
            continue;
        }
        const bool top_level = !line.empty() && line.front() != ' ' && line.front() != '\t';
        const auto colon = line.find(':');
        if (colon == std::string::npos) {
            continue;
        }
        const std::string key = trim(line.substr(0, colon));
        const std::string value = trim(line.substr(colon + 1));
        if (top_level && value.empty()) {
            section = key;
            continue;
        }
        if (!section.empty()) {
            apply_config_value(defaults, section, key, value);
        }
    }
    return defaults;
}

GlobalRelocResult generate_global_relocalization_candidates(
    const std::string& pcd_path,
    const std::string& output_dir,
    const GlobalRelocConfig& config,
    const std::string& manual_path,
    int progress_interval,
    const std::string& reviewed_candidates_path) {
    const auto start_time = std::chrono::steady_clock::now();
    PCDReader reader(pcd_path);
    reader.read_header();

    std::unordered_map<int64_t, Point3> voxel_points;
    std::unordered_set<int64_t> occupied;
    std::unordered_map<int64_t, GroundCell> ground;
    Bounds3 bounds;
    int input_points = 0;

    reader.for_each_xyz([&](float xf, float yf, float zf) {
        const double x = xf;
        const double y = yf;
        const double z = zf;
        if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) || z < config.z_min_m || z > config.z_max_m) {
            return;
        }
        ++input_points;
        bounds.min_x = std::min(bounds.min_x, x);
        bounds.min_y = std::min(bounds.min_y, y);
        bounds.min_z = std::min(bounds.min_z, z);
        bounds.max_x = std::max(bounds.max_x, x);
        bounds.max_y = std::max(bounds.max_y, y);
        bounds.max_z = std::max(bounds.max_z, z);

        const int vx = index_for(x, config.voxel_leaf_m);
        const int vy = index_for(y, config.voxel_leaf_m);
        const int vz = index_for(z, config.voxel_leaf_m);
        voxel_points.emplace(pack3(vx, vy, vz), Point3{x, y, z});

        const int ox = index_for(x, config.occupancy_resolution_m);
        const int oy = index_for(y, config.occupancy_resolution_m);
        const int oz = index_for(z, config.occupancy_resolution_m);
        occupied.insert(pack3(ox, oy, oz));

        const int gx = index_for(x, config.xy_resolution_m);
        const int gy = index_for(y, config.xy_resolution_m);
        auto& cell = ground[pack2(gx, gy)];
        cell.count += 1;
        cell.min_z = std::min(cell.min_z, z);
        cell.max_z = std::max(cell.max_z, z);
        cell.sum_z += z;
        cell.z_values.push_back(z);
    });

    if (input_points <= 0) {
        throw std::runtime_error("no usable pcd points");
    }

    auto has_clearance = [&](const BasePosition& base) {
        const double radius = config.robot_radius_m + config.safety_margin_m;
        const int radius_cells = std::max(1, static_cast<int>(std::ceil(radius / config.occupancy_resolution_m)));
        const int height_cells = std::max(1, static_cast<int>(std::ceil(config.clearance_check_height_m / config.occupancy_resolution_m)));
        const int cx = index_for(base.x, config.occupancy_resolution_m);
        const int cy = index_for(base.y, config.occupancy_resolution_m);
        const double clearance_z = base.z - config.base_link_height_offset_m;
        const int cz = index_for(clearance_z, config.occupancy_resolution_m);
        int total = 0;
        int free_count = 0;
        for (int dz = 0; dz <= height_cells; ++dz) {
            for (int dy = -radius_cells; dy <= radius_cells; ++dy) {
                for (int dx = -radius_cells; dx <= radius_cells; ++dx) {
                    if (dx * dx + dy * dy > radius_cells * radius_cells) {
                        continue;
                    }
                    ++total;
                    if (occupied.find(pack3(cx + dx, cy + dy, cz + dz)) == occupied.end()) {
                        ++free_count;
                    }
                }
            }
        }
        return total > 0 && static_cast<double>(free_count) / static_cast<double>(total) >= config.clearance_min_free_ratio;
    };

    auto far_enough = [&](const BasePosition& base, const std::vector<BasePosition>& accepted) {
        for (const auto& item : accepted) {
            const double dx = base.x - item.x;
            const double dy = base.y - item.y;
            if (std::sqrt(dx * dx + dy * dy) < config.min_candidate_distance_m) {
                return false;
            }
        }
        return true;
    };

    std::vector<GlobalRelocCandidate> candidates;
    std::vector<BasePosition> accepted_bases;
    ManualEdit manual;
    int supported_ground_cell_count = 0;
    auto estimate_ground_z = [&](double x, double y, double fallback_z) {
        const int gx = index_for(x, config.xy_resolution_m);
        const int gy = index_for(y, config.xy_resolution_m);
        const int search_radius_cells = std::max(1, static_cast<int>(std::ceil(config.ground_support_radius_m / config.xy_resolution_m)));
        double best_distance2 = std::numeric_limits<double>::infinity();
        double best_z = fallback_z;
        bool found = false;
        for (int dy = -search_radius_cells; dy <= search_radius_cells; ++dy) {
            for (int dx = -search_radius_cells; dx <= search_radius_cells; ++dx) {
                const auto it = ground.find(pack2(gx + dx, gy + dy));
                if (it == ground.end() || it->second.count < config.ground_min_points_per_cell) {
                    continue;
                }
                const double cell_x = (static_cast<double>(gx + dx) + 0.5) * config.xy_resolution_m;
                const double cell_y = (static_cast<double>(gy + dy) + 0.5) * config.xy_resolution_m;
                const double distance2 = (cell_x - x) * (cell_x - x) + (cell_y - y) * (cell_y - y);
                if (distance2 < best_distance2) {
                    best_distance2 = distance2;
                    best_z = percentile_z(it->second, 0.15);
                    found = true;
                }
            }
        }
        return found ? best_z : fallback_z;
    };
    auto base_link_z_from_ground = [&](double ground_z) {
        return ground_z + config.base_link_height_offset_m;
    };
    if (!reviewed_candidates_path.empty()) {
        candidates = load_reviewed_candidates(reviewed_candidates_path, config);
    } else {
        std::vector<BasePosition> supported_cells;
        supported_cells.reserve(ground.size());
        for (const auto& [key, cell] : ground) {
            if (cell.count < config.ground_min_points_per_cell) {
                continue;
            }
            const int gx = static_cast<int>(key >> 32);
            const int gy = static_cast<int>(static_cast<std::uint32_t>(key));
            // 使用低分位 ground z，比平均值更不容易被墙点、高反射点或稀疏高点抬高 base。
            const double z = percentile_z(cell, 0.15);
            int neighbor_count = 0;
            const int support_radius_cells = std::max(1, static_cast<int>(std::ceil(config.ground_support_radius_m / config.xy_resolution_m)));
            for (int dy = -support_radius_cells; dy <= support_radius_cells; ++dy) {
                for (int dx = -support_radius_cells; dx <= support_radius_cells; ++dx) {
                    const auto it = ground.find(pack2(gx + dx, gy + dy));
                    if (it == ground.end() || it->second.count < config.ground_min_points_per_cell) {
                        continue;
                    }
                    const double neighbor_z = percentile_z(it->second, 0.15);
                    if (std::abs(neighbor_z - z) <= config.ground_support_max_delta_z_m) {
                        ++neighbor_count;
                    }
                }
            }
            if (neighbor_count >= config.ground_min_neighbor_cells) {
                BasePosition base;
                base.x = (static_cast<double>(gx) + 0.5) * config.xy_resolution_m;
                base.y = (static_cast<double>(gy) + 0.5) * config.xy_resolution_m;
                base.z = base_link_z_from_ground(z);
                supported_cells.push_back(base);
            }
        }
        supported_ground_cell_count = static_cast<int>(supported_cells.size());

        std::mt19937 rng(config.random_seed);
        std::shuffle(supported_cells.begin(), supported_cells.end(), rng);
        int checked = 0;
        int accepts_in_window = 0;
        for (const auto& base : supported_cells) {
            if (checked >= config.max_base_samples || static_cast<int>(accepted_bases.size()) >= config.target_base_positions) {
                break;
            }
            ++checked;
            if (base.x < bounds.min_x + config.map_boundary_margin_m || base.x > bounds.max_x - config.map_boundary_margin_m ||
                base.y < bounds.min_y + config.map_boundary_margin_m || base.y > bounds.max_y - config.map_boundary_margin_m) {
                continue;
            }
            if (!far_enough(base, accepted_bases) || !has_clearance(base)) {
                continue;
            }
            accepted_bases.push_back(base);
            ++accepts_in_window;
            if (progress_interval > 0 && checked % progress_interval == 0) {
                std::cout << "accepted_base: " << accepted_bases.size() << " checked: " << checked << "\n";
            }
            if (config.early_stop_window > 0 && checked % config.early_stop_window == 0) {
                if (accepts_in_window < config.early_stop_min_accepts) {
                    break;
                }
                accepts_in_window = 0;
            }
        }

        manual = load_manual_edit(manual_path);
        for (auto& addition : manual.additions) {
            if (addition.z_auto) {
                addition.z = base_link_z_from_ground(estimate_ground_z(addition.x, addition.y, addition.z));
            } else {
                // manual_candidates.yaml 的人工点 z 约定为地图地面高度，生成候选库前转换为 base_link 高度。
                addition.z += config.base_link_height_offset_m;
            }
        }
        accepted_bases.insert(accepted_bases.end(), manual.additions.begin(), manual.additions.end());

        auto in_deleted_region = [&](const GlobalRelocCandidate& candidate) {
            return std::any_of(manual.deletion_regions.begin(), manual.deletion_regions.end(), [&](const DeletionRegion& region) {
                return candidate.x >= region.min_x && candidate.x <= region.max_x &&
                       candidate.y >= region.min_y && candidate.y <= region.max_y;
            });
        };

        const int max_candidates = config.max_candidates <= 0 ? std::numeric_limits<int>::max() : config.max_candidates;
        candidates.reserve(static_cast<std::size_t>(std::min(max_candidates, 200000)));
        int next_id = 0;
        for (const auto& base : accepted_bases) {
            const std::vector<double> roll_values = base.source == "manual_added" ? std::vector<double>{base.roll_deg} : config.roll_samples_deg;
            const std::vector<double> pitch_values = base.source == "manual_added" ? std::vector<double>{base.pitch_deg} : config.pitch_samples_deg;
            for (const double roll : roll_values) {
                for (const double pitch : pitch_values) {
                    if (static_cast<int>(candidates.size()) >= max_candidates) {
                        break;
                    }
                    GlobalRelocCandidate candidate;
                    candidate.candidate_id = next_id++;
                    candidate.x = base.x;
                    candidate.y = base.y;
                    candidate.z = base.z;
                    candidate.roll_deg = roll;
                    candidate.pitch_deg = pitch;
                    apply_canonical_yaw(candidate);
                    candidate.source = base.source;
                    candidate.label = base.label;
                    candidate.locked = base.locked;
                    candidate.original_candidate_id = candidate.candidate_id;
                    if (manual.deletion_ids.find(candidate.candidate_id) == manual.deletion_ids.end() && !in_deleted_region(candidate)) {
                        candidates.push_back(candidate);
                    }
                }
            }
        }
        candidates = collapse_to_places(candidates);
    }

    const auto ray_dirs = build_ray_directions(config);
    const int output_rings = std::max(1, config.descriptor_num_rings);
    const int output_sectors = std::max(1, config.descriptor_num_sectors);
    std::vector<float> descriptor_values;
    std::vector<float> ring_key_values;
    std::vector<float> sector_key_values;
    descriptor_values.reserve(candidates.size() * static_cast<std::size_t>(output_rings * output_sectors));
    ring_key_values.reserve(candidates.size() * static_cast<std::size_t>(output_rings));
    sector_key_values.reserve(candidates.size() * static_cast<std::size_t>(output_sectors));
    std::vector<GlobalRelocCandidate> final_candidates;
    final_candidates.reserve(candidates.size());
    int rejected = 0;
    for (auto candidate : candidates) {
        std::vector<float> descriptor;
        std::vector<float> ring_key;
        compute_candidate_descriptor(candidate, occupied, bounds, config, ray_dirs, descriptor, ring_key);
        const bool observable =
            candidate.hit_count >= config.observability_min_hit_points &&
            candidate.hit_ratio >= config.observability_min_hit_ratio &&
            candidate.visible_sector_count >= config.observability_min_visible_sector_count &&
            candidate.descriptor_nonzero_ratio >= config.observability_min_descriptor_nonzero_ratio;
        // 锁定点代表人工审核后的强制保留；低观测质量只影响评分，不应让点从最终库中消失。
        const bool force_keep = candidate.locked || config.allow_force_add_low_observability;
        if (!observable && !force_keep) {
            ++rejected;
            continue;
        }
        candidate.candidate_id = static_cast<int>(final_candidates.size());
        descriptor_values.insert(descriptor_values.end(), descriptor.begin(), descriptor.end());
        ring_key_values.insert(ring_key_values.end(), ring_key.begin(), ring_key.end());
        for (int sector = 0; sector < output_sectors; ++sector) {
            float sector_max = 0.0f;
            for (int ring = 0; ring < output_rings; ++ring) {
                sector_max = std::max(sector_max, descriptor[static_cast<std::size_t>(ring * output_sectors + sector)]);
            }
            sector_key_values.push_back(sector_max);
        }
        final_candidates.push_back(candidate);
        if (progress_interval > 0 && final_candidates.size() % static_cast<std::size_t>(progress_interval) == 0) {
            std::cout << "processed_place: " << (final_candidates.size() + static_cast<std::size_t>(rejected))
                      << " accepted_place: " << final_candidates.size()
                      << " rejected_place: " << rejected << "\n";
        }
    }
    candidates = std::move(final_candidates);

    const std::filesystem::path out_dir(output_dir.empty() ? "global_relocalization_db" : output_dir);
    std::filesystem::create_directories(out_dir / "debug");
    const auto candidates_csv = out_dir / "candidates.csv";
    const auto preview_pcd = out_dir / "debug" / "preview_candidates.pcd";
    const auto metadata = out_dir / "metadata.yaml";
    const auto candidates_npy = out_dir / "candidates.npy";
    const auto descriptors_npy = out_dir / "descriptors.npy";
    const auto ring_keys_npy = out_dir / "ring_keys.npy";
    const auto sector_keys_npy = out_dir / "sector_keys.npy";

    {
        std::ofstream csv(candidates_csv);
        csv << "place_id,x,y,z,roll_deg,pitch_deg,canonical_yaw_deg,qx,qy,qz,qw,observability_score,hit_count,hit_ratio,visible_sector_count,descriptor_nonzero_ratio,source,label,locked,original_candidate_id\n";
        csv << std::fixed << std::setprecision(6);
        for (const auto& c : candidates) {
            csv << c.candidate_id << ',' << c.x << ',' << c.y << ',' << c.z << ','
                << c.roll_deg << ',' << c.pitch_deg << ',' << c.yaw_deg << ','
                << c.qx << ',' << c.qy << ',' << c.qz << ',' << c.qw << ','
                << c.observability_score << ',' << c.hit_count << ',' << c.hit_ratio << ','
                << c.visible_sector_count << ',' << c.descriptor_nonzero_ratio << ','
                << c.source << ',' << c.label << ',' << (c.locked ? "true" : "false") << ',' << c.original_candidate_id << "\n";
        }
    }

    {
        std::ofstream pcd(preview_pcd);
        pcd << "# .PCD v0.7\nVERSION 0.7\nFIELDS x y z place_id\nSIZE 4 4 4 4\nTYPE F F F I\nCOUNT 1 1 1 1\n";
        pcd << "WIDTH " << candidates.size() << "\nHEIGHT 1\nPOINTS " << candidates.size() << "\nDATA ascii\n";
        pcd << std::fixed << std::setprecision(6);
        for (const auto& c : candidates) {
            pcd << c.x << ' ' << c.y << ' ' << c.z << ' ' << c.candidate_id << "\n";
        }
    }

    std::vector<float> candidate_values;
    candidate_values.reserve(candidates.size() * 16);
    for (const auto& c : candidates) {
        candidate_values.insert(candidate_values.end(), {
            static_cast<float>(c.candidate_id), static_cast<float>(c.x), static_cast<float>(c.y), static_cast<float>(c.z),
            static_cast<float>(c.roll_deg), static_cast<float>(c.pitch_deg), static_cast<float>(c.yaw_deg),
            static_cast<float>(c.qx), static_cast<float>(c.qy), static_cast<float>(c.qz), static_cast<float>(c.qw),
            static_cast<float>(c.observability_score), static_cast<float>(c.hit_count), static_cast<float>(c.hit_ratio),
            static_cast<float>(c.visible_sector_count), static_cast<float>(c.descriptor_nonzero_ratio),
        });
    }
    write_float32_npy(candidates_npy, {static_cast<int>(candidates.size()), 16}, candidate_values);
    write_float32_npy(descriptors_npy, {static_cast<int>(candidates.size()), output_rings, output_sectors}, descriptor_values);
    write_float32_npy(ring_keys_npy, {static_cast<int>(candidates.size()), output_rings}, ring_key_values);
    write_float32_npy(sector_keys_npy, {static_cast<int>(candidates.size()), output_sectors}, sector_key_values);

    const auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start_time).count();
    {
        std::ofstream meta(metadata);
        meta << "format_version: 2\n";
        meta << "format: v2_scan_context_places\n";
        meta << "generator: global_relocalization_cli\n";
        meta << "descriptor_status: scan_context_height_ray_casting\n";
        meta << "candidate_row_model: place_canonical_yaw\n";
        meta << "num_places: " << candidates.size() << "\n";
        meta << "num_rings: " << output_rings << "\n";
        meta << "num_sectors: " << output_sectors << "\n";
        meta << "max_radius_m: " << config.descriptor_max_radius_m << "\n";
        meta << "height_clip_min_m: " << config.descriptor_height_clip_min_m << "\n";
        meta << "height_clip_max_m: " << config.descriptor_height_clip_max_m << "\n";
        meta << "candidate_pose_frame: base_link\n";
        meta << "canonical_yaw_deg: 0.0\n";
        meta << "note: \"v2 每个可站立位置只保留一行，descriptor/ring key 在 canonical yaw=0 下生成，在线 yaw 由 Scan Context sector shift 估计。\"\n";
        meta << "candidate_source: \"" << (reviewed_candidates_path.empty() ? "auto_sampling" : "reviewed_candidates") << "\"\n";
        meta << "synthetic_lidar:\n";
        meta << "  first_return: true\n";
        meta << "  horizontal_fov_deg: " << config.virtual_lidar_horizontal_fov_deg << "\n";
        meta << "  vertical_fov_deg: " << config.virtual_lidar_vertical_fov_deg << "\n";
        meta << "  horizontal_step_deg: " << config.virtual_lidar_horizontal_step_deg << "\n";
        meta << "  vertical_step_deg: " << config.virtual_lidar_vertical_step_deg << "\n";
        meta << "  min_range_m: " << config.virtual_lidar_min_range_m << "\n";
        meta << "  max_range_m: " << config.virtual_lidar_max_range_m << "\n";
        meta << "  occupancy_resolution_m: " << config.occupancy_resolution_m << "\n";
        meta << "  occupancy_inflate_radius_m: " << config.virtual_lidar_occupancy_inflate_radius_m << "\n";
        meta << "  lidar_to_base_translation_xyz: [" << (config.lidar_to_base_translation_xyz.size() > 0 ? config.lidar_to_base_translation_xyz[0] : 0.0)
             << ", " << (config.lidar_to_base_translation_xyz.size() > 1 ? config.lidar_to_base_translation_xyz[1] : 0.0)
             << ", " << (config.lidar_to_base_translation_xyz.size() > 2 ? config.lidar_to_base_translation_xyz[2] : 0.0) << "]\n";
        meta << "  lidar_to_base_rpy_deg: [" << (config.lidar_to_base_rpy_deg.size() > 0 ? config.lidar_to_base_rpy_deg[0] : 0.0)
             << ", " << (config.lidar_to_base_rpy_deg.size() > 1 ? config.lidar_to_base_rpy_deg[1] : 0.0)
             << ", " << (config.lidar_to_base_rpy_deg.size() > 2 ? config.lidar_to_base_rpy_deg[2] : 0.0) << "]\n";
        meta << "scan_context:\n";
        meta << "  descriptor_cell: max_height\n";
        meta << "  ring_key: ring_max\n";
        meta << "  sector_key: sector_max\n";
        meta << "  yaw_from: circular_shift\n";
        meta << "virtual_lidar:\n";
        meta << "  min_range_m: " << config.virtual_lidar_min_range_m << "\n";
        meta << "  max_range_m: " << config.virtual_lidar_max_range_m << "\n";
        meta << "  horizontal_fov_deg: " << config.virtual_lidar_horizontal_fov_deg << "\n";
        meta << "  vertical_fov_deg: " << config.virtual_lidar_vertical_fov_deg << "\n";
        meta << "  horizontal_step_deg: " << config.virtual_lidar_horizontal_step_deg << "\n";
        meta << "  vertical_step_deg: " << config.virtual_lidar_vertical_step_deg << "\n";
        meta << "  occupancy_inflate_radius_m: " << config.virtual_lidar_occupancy_inflate_radius_m << "\n";
        meta << "  lidar_to_base_translation_xyz: [" << (config.lidar_to_base_translation_xyz.size() > 0 ? config.lidar_to_base_translation_xyz[0] : 0.0)
             << ", " << (config.lidar_to_base_translation_xyz.size() > 1 ? config.lidar_to_base_translation_xyz[1] : 0.0)
             << ", " << (config.lidar_to_base_translation_xyz.size() > 2 ? config.lidar_to_base_translation_xyz[2] : 0.0) << "]\n";
        meta << "  lidar_to_base_rpy_deg: [" << (config.lidar_to_base_rpy_deg.size() > 0 ? config.lidar_to_base_rpy_deg[0] : 0.0)
             << ", " << (config.lidar_to_base_rpy_deg.size() > 1 ? config.lidar_to_base_rpy_deg[1] : 0.0)
             << ", " << (config.lidar_to_base_rpy_deg.size() > 2 ? config.lidar_to_base_rpy_deg[2] : 0.0) << "]\n";
        meta << "input_pcd: \"" << pcd_path << "\"\n";
        meta << "manual_file: \"" << manual_path << "\"\n";
        meta << "reviewed_candidates_file: \"" << reviewed_candidates_path << "\"\n";
        meta << "input_points: " << input_points << "\n";
        meta << "downsampled_points: " << voxel_points.size() << "\n";
        meta << "occupied_voxels: " << occupied.size() << "\n";
        meta << "supported_ground_cells: " << supported_ground_cell_count << "\n";
        meta << "base_link_height_offset_m: " << config.base_link_height_offset_m << "\n";
        meta << "accepted_base_positions: " << accepted_bases.size() << "\n";
        meta << "accepted_candidates: " << candidates.size() << "\n";
        meta << "accepted_places: " << candidates.size() << "\n";
        meta << "rejected_candidates: " << rejected << "\n";
        meta << "ray_count: " << ray_dirs.size() << "\n";
        meta << "descriptor_shape: [" << candidates.size() << ", " << output_rings << ", " << output_sectors << "]\n";
        meta << "ring_key_shape: [" << candidates.size() << ", " << output_rings << "]\n";
        meta << "sector_key_shape: [" << candidates.size() << ", " << output_sectors << "]\n";
        meta << "manual_additions_count: " << manual.additions.size() << "\n";
        meta << "manual_deletions_count: " << (manual.deletion_ids.size() + manual.deletion_regions.size()) << "\n";
        meta << "elapsed_ms: " << elapsed_ms << "\n";
    }

    GlobalRelocResult result;
    result.output_dir = out_dir.string();
    result.metadata_path = metadata.string();
    result.candidates_csv_path = candidates_csv.string();
    result.candidates_npy_path = candidates_npy.string();
    result.descriptors_npy_path = descriptors_npy.string();
    result.ring_keys_npy_path = ring_keys_npy.string();
    result.sector_keys_npy_path = sector_keys_npy.string();
    result.preview_pcd_path = preview_pcd.string();
    result.input_points = input_points;
    result.downsampled_points = static_cast<int>(voxel_points.size());
    result.occupied_voxels = static_cast<int>(occupied.size());
    result.supported_ground_cells = supported_ground_cell_count;
    result.accepted_base_positions = static_cast<int>(accepted_bases.size());
    result.accepted_candidates = static_cast<int>(candidates.size());
    result.manual_additions = static_cast<int>(manual.additions.size());
    result.manual_deletions = static_cast<int>(manual.deletion_ids.size() + manual.deletion_regions.size());
    result.rejected_candidates = rejected;
    result.ray_count = static_cast<int>(ray_dirs.size());
    return result;
}

}  // namespace ros_tool_suite::mapping
