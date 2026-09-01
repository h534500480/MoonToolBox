// 功能说明：为导航测试页生成离线 PCD 地图的轻量预览点云。

#include "ros_tool_suite/mapping/pcd_reader.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

struct Point3 {
    float x = 0.0F;
    float y = 0.0F;
    float z = 0.0F;
};

struct Bounds3 {
    double min_x = std::numeric_limits<double>::infinity();
    double min_y = std::numeric_limits<double>::infinity();
    double min_z = std::numeric_limits<double>::infinity();
    double max_x = -std::numeric_limits<double>::infinity();
    double max_y = -std::numeric_limits<double>::infinity();
    double max_z = -std::numeric_limits<double>::infinity();
};

struct Args {
    std::string pcd_path;
    double voxel_leaf_m = 0.20;
    int max_points = 60000;
};

void print_usage() {
    std::cerr << "Usage: nav_pcd_preview_cli --pcd <map.pcd> [--voxel-leaf <m>] [--max-points <n>]\n";
}

double parse_double(const std::string& value, const std::string& name) {
    char* end = nullptr;
    const double parsed = std::strtod(value.c_str(), &end);
    if (end == value.c_str() || !std::isfinite(parsed)) {
        throw std::runtime_error("invalid " + name + ": " + value);
    }
    return parsed;
}

int parse_int(const std::string& value, const std::string& name) {
    char* end = nullptr;
    const long parsed = std::strtol(value.c_str(), &end, 10);
    if (end == value.c_str() || parsed <= 0) {
        throw std::runtime_error("invalid " + name + ": " + value);
    }
    return static_cast<int>(parsed);
}

Args parse_args(int argc, char** argv) {
    Args args;
    for (int index = 1; index < argc; ++index) {
        const std::string flag = argv[index];
        auto require_value = [&](const std::string& name) -> std::string {
            if (index + 1 >= argc) {
                throw std::runtime_error("missing value for " + name);
            }
            ++index;
            return argv[index];
        };
        if (flag == "--pcd") {
            args.pcd_path = require_value(flag);
        } else if (flag == "--voxel-leaf") {
            args.voxel_leaf_m = parse_double(require_value(flag), flag);
        } else if (flag == "--max-points") {
            args.max_points = parse_int(require_value(flag), flag);
        } else if (flag == "--help" || flag == "-h") {
            print_usage();
            std::exit(0);
        } else {
            throw std::runtime_error("unknown argument: " + flag);
        }
    }
    if (args.pcd_path.empty()) {
        throw std::runtime_error("missing --pcd");
    }
    args.voxel_leaf_m = std::max(0.01, std::min(args.voxel_leaf_m, 5.0));
    args.max_points = std::max(1000, std::min(args.max_points, 300000));
    return args;
}

int voxel_index(double value, double resolution) {
    return static_cast<int>(std::floor(value / resolution));
}

std::int64_t pack_voxel(int x, int y, int z) {
    // 三轴各保留 21 bit；偏移用于稳定表示负坐标体素。
    constexpr std::int64_t offset = 1 << 20;
    return ((static_cast<std::int64_t>(x) + offset) << 42) ^
           ((static_cast<std::int64_t>(y) + offset) << 21) ^
           (static_cast<std::int64_t>(z) + offset);
}

void include_bounds(Bounds3& bounds, double x, double y, double z) {
    bounds.min_x = std::min(bounds.min_x, x);
    bounds.min_y = std::min(bounds.min_y, y);
    bounds.min_z = std::min(bounds.min_z, z);
    bounds.max_x = std::max(bounds.max_x, x);
    bounds.max_y = std::max(bounds.max_y, y);
    bounds.max_z = std::max(bounds.max_z, z);
}

void write_bounds(std::ostream& output, const Bounds3& bounds) {
    const bool valid = std::isfinite(bounds.min_x) && std::isfinite(bounds.max_x);
    output << "{"
           << "\"xmin\":" << (valid ? bounds.min_x : 0.0) << ","
           << "\"xmax\":" << (valid ? bounds.max_x : 0.0) << ","
           << "\"ymin\":" << (valid ? bounds.min_y : 0.0) << ","
           << "\"ymax\":" << (valid ? bounds.max_y : 0.0) << ","
           << "\"zmin\":" << (valid ? bounds.min_z : 0.0) << ","
           << "\"zmax\":" << (valid ? bounds.max_z : 0.0)
           << "}";
}

std::string json_escape(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size() + 8);
    for (const char ch : value) {
        if (ch == '\\' || ch == '"') {
            escaped.push_back('\\');
            escaped.push_back(ch);
        } else if (ch == '\n') {
            escaped += "\\n";
        } else if (ch == '\r') {
            escaped += "\\r";
        } else if (ch == '\t') {
            escaped += "\\t";
        } else {
            escaped.push_back(ch);
        }
    }
    return escaped;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Args args = parse_args(argc, argv);
        ros_tool_suite::mapping::PCDReader reader(args.pcd_path);
        reader.read_header();

        std::unordered_map<std::int64_t, Point3> voxels;
        Bounds3 input_bounds;
        Bounds3 sampled_bounds;
        int input_points = 0;

        reader.for_each_xyz([&](float x, float y, float z) {
            if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
                return;
            }
            ++input_points;
            include_bounds(input_bounds, x, y, z);
            const int vx = voxel_index(x, args.voxel_leaf_m);
            const int vy = voxel_index(y, args.voxel_leaf_m);
            const int vz = voxel_index(z, args.voxel_leaf_m);
            voxels.emplace(pack_voxel(vx, vy, vz), Point3{x, y, z});
        });

        std::vector<Point3> points;
        points.reserve(voxels.size());
        for (const auto& item : voxels) {
            points.push_back(item.second);
        }
        std::sort(points.begin(), points.end(), [](const Point3& left, const Point3& right) {
            if (left.x != right.x) return left.x < right.x;
            if (left.y != right.y) return left.y < right.y;
            return left.z < right.z;
        });
        if (static_cast<int>(points.size()) > args.max_points) {
            std::vector<Point3> limited;
            limited.reserve(static_cast<std::size_t>(args.max_points));
            const double step = static_cast<double>(points.size() - 1) / static_cast<double>(args.max_points - 1);
            for (int index = 0; index < args.max_points; ++index) {
                limited.push_back(points[static_cast<std::size_t>(std::round(index * step))]);
            }
            points.swap(limited);
        }
        for (const auto& point : points) {
            include_bounds(sampled_bounds, point.x, point.y, point.z);
        }

        std::cout << std::fixed << std::setprecision(6);
        std::cout << "{";
        std::cout << "\"path\":\"" << json_escape(args.pcd_path) << "\",";
        std::cout << "\"input_points\":" << input_points << ",";
        std::cout << "\"sampled_count\":" << points.size() << ",";
        std::cout << "\"voxel_leaf_m\":" << args.voxel_leaf_m << ",";
        std::cout << "\"input_bounds\":";
        write_bounds(std::cout, input_bounds);
        std::cout << ",\"sampled_bounds\":";
        write_bounds(std::cout, sampled_bounds);
        std::cout << ",\"points\":[";
        for (std::size_t index = 0; index < points.size(); ++index) {
            if (index > 0) {
                std::cout << ",";
            }
            const auto& point = points[index];
            std::cout << "[" << point.x << "," << point.y << "," << point.z << "]";
        }
        std::cout << "]}";
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << exc.what() << "\n";
        print_usage();
        return 1;
    }
}
