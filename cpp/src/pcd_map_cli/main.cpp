#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>

#include "ros_tool_suite/mapping/exporters.hpp"

namespace {

void print_usage() {
    std::cout
        << "Usage: pcd_map_cli --pcd <file> [--output-dir <dir>] [--base-name <name>] [--resolution <m>] ...\n";
}

std::string require_value(int& index, int argc, char** argv) {
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value after argument");
    }
    return argv[++index];
}

}  // namespace

int main(int argc, char** argv) {
    std::string pcd_path;
    std::string output_dir = "output";
    std::string base_name = "map";
    ros_tool_suite::mapping::GridParameters params;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--pcd" && i + 1 < argc) {
            pcd_path = argv[++i];
        } else if (arg == "--output-dir" && i + 1 < argc) {
            output_dir = argv[++i];
        } else if (arg == "--base-name" && i + 1 < argc) {
            base_name = argv[++i];
        } else if (arg == "--resolution") {
            params.resolution = std::stod(require_value(i, argc, argv));
        } else if (arg == "--clip-min-z") {
            params.clip_min_z = std::stod(require_value(i, argc, argv));
        } else if (arg == "--clip-max-z") {
            params.clip_max_z = std::stod(require_value(i, argc, argv));
        } else if (arg == "--walkable-min-z") {
            params.walkable_min_z = std::stod(require_value(i, argc, argv));
        } else if (arg == "--walkable-max-z") {
            params.walkable_max_z = std::stod(require_value(i, argc, argv));
        } else if (arg == "--obstacle-min-z") {
            params.obstacle_min_z = std::stod(require_value(i, argc, argv));
        } else if (arg == "--obstacle-max-z") {
            params.obstacle_max_z = std::stod(require_value(i, argc, argv));
        } else if (arg == "--ground-tolerance") {
            params.ground_tolerance = std::stod(require_value(i, argc, argv));
        } else if (arg == "--min-points-per-cell") {
            params.min_points_per_cell = std::stoi(require_value(i, argc, argv));
        } else if (arg == "--obstacle-inflate-radius") {
            params.obstacle_inflate_radius = std::stod(require_value(i, argc, argv));
        } else if (arg == "--hole-fill-neighbors") {
            params.hole_fill_neighbors = std::stoi(require_value(i, argc, argv));
        } else if (arg == "--overlay-smooth-radius") {
            params.overlay_smooth_radius = std::stod(require_value(i, argc, argv));
        } else if (arg == "--help" || arg == "-h") {
            print_usage();
            return 0;
        }
    }

    if (pcd_path.empty()) {
        print_usage();
        return 1;
    }

    try {
        const auto result = ros_tool_suite::mapping::export_maps(
            pcd_path,
            output_dir,
            base_name,
            params);
        std::cout << "pgm_path: " << result.pgm_path << "\n";
        std::cout << "yaml_path: " << result.yaml_path << "\n";
        std::cout << "color_path: " << result.color_path << "\n";
        std::cout << "preview_path: " << result.preview_path << "\n";
        std::cout << "width: " << result.width << "\n";
        std::cout << "height: " << result.height << "\n";
        std::cout << "origin_x: " << result.origin_x << "\n";
        std::cout << "origin_y: " << result.origin_y << "\n";
        std::cout << "point_count: " << result.point_count << "\n";
        std::cout << "walkable_cells: " << result.walkable_cells << "\n";
        std::cout << "obstacle_cells: " << result.obstacle_cells << "\n";
        std::cout << "unknown_cells: " << result.unknown_cells << "\n";
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << "\n";
        return 2;
    }

    return 0;
}
