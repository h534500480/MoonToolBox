#pragma once

#include <cstdint>
#include <string>
#include <tuple>
#include <vector>

namespace ros_tool_suite::mapping {

enum class CellType : std::uint8_t {
    Unknown = 0,
    Walkable = 1,
    Obstacle = 2,
};

struct GridParameters {
    double resolution = 0.05;
    double clip_min_z = -1.0;
    double clip_max_z = 2.0;
    double walkable_min_z = -0.20;
    double walkable_max_z = 0.20;
    double obstacle_min_z = 0.25;
    double obstacle_max_z = 2.0;
    double ground_tolerance = 0.12;
    int min_points_per_cell = 1;
    double obstacle_inflate_radius = 0.10;
    int hole_fill_neighbors = 5;
    double overlay_smooth_radius = 0.0;
    int free_gray = 254;
    int obstacle_gray = 0;
    std::tuple<int, int, int> walkable_color = {0x39, 0xFF, 0x14};
    std::tuple<int, int, int> obstacle_color = {0xFF, 0x5A, 0x36};
    double occupied_thresh = 0.65;
    double free_thresh = 0.25;
    int negate = 0;
};

struct GridResult {
    int width = 0;
    int height = 0;
    double origin_x = 0.0;
    double origin_y = 0.0;
    double resolution = 0.05;
    std::vector<std::uint8_t> grid;
    int obstacle_cells = 0;
    int walkable_cells = 0;
    int unknown_cells = 0;
    int point_count = 0;
};

struct ExportResult {
    std::string pgm_path;
    std::string yaml_path;
    std::string color_path;
    std::string preview_path;
    int width = 0;
    int height = 0;
    double origin_x = 0.0;
    double origin_y = 0.0;
    int point_count = 0;
    int walkable_cells = 0;
    int obstacle_cells = 0;
    int unknown_cells = 0;
};

}  // namespace ros_tool_suite::mapping
