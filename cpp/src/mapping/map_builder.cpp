#include "ros_tool_suite/mapping/map_builder.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace ros_tool_suite::mapping {

namespace {

struct CellStats {
    int count = 0;
    double min_z = std::numeric_limits<double>::infinity();
    double max_z = -std::numeric_limits<double>::infinity();
    int walkable_count = 0;
    double walkable_min_z = std::numeric_limits<double>::infinity();
    double walkable_max_z = -std::numeric_limits<double>::infinity();
    int obstacle_count = 0;
};

template <typename T>
T clamp_value(T value, T low, T high) {
    return std::max(low, std::min(high, value));
}

void advance_progress(
    const ProgressCallback& progress_cb,
    int processed,
    int total,
    int max_percent,
    const std::string& message,
    int& last_percent) {
    if (!progress_cb || total <= 0) {
        return;
    }
    const int percent = std::min(max_percent, static_cast<int>((static_cast<long long>(processed) * max_percent) / total));
    if (percent != last_percent) {
        last_percent = percent;
        progress_cb(percent, message);
    }
}

void inflate_obstacles(std::vector<std::uint8_t>& grid, int width, int height, double radius_m, double resolution) {
    const int radius_cells = std::max(0, static_cast<int>(std::ceil(radius_m / resolution)));
    if (radius_cells <= 0) {
        return;
    }
    const auto original = grid;
    for (int row = 0; row < height; ++row) {
        for (int col = 0; col < width; ++col) {
            const int idx = row * width + col;
            if (original[idx] != static_cast<std::uint8_t>(CellType::Obstacle)) {
                continue;
            }
            for (int dy = -radius_cells; dy <= radius_cells; ++dy) {
                for (int dx = -radius_cells; dx <= radius_cells; ++dx) {
                    if (dx * dx + dy * dy > radius_cells * radius_cells) {
                        continue;
                    }
                    const int nr = row + dy;
                    const int nc = col + dx;
                    if (nr >= 0 && nr < height && nc >= 0 && nc < width) {
                        grid[nr * width + nc] = static_cast<std::uint8_t>(CellType::Obstacle);
                    }
                }
            }
        }
    }
}

void fill_walkable_holes(std::vector<std::uint8_t>& grid, int width, int height, int min_neighbors) {
    if (min_neighbors <= 0) {
        return;
    }
    const auto original = grid;
    for (int row = 0; row < height; ++row) {
        for (int col = 0; col < width; ++col) {
            const int idx = row * width + col;
            if (original[idx] != static_cast<std::uint8_t>(CellType::Unknown)) {
                continue;
            }
            int neighbors = 0;
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    if (dx == 0 && dy == 0) {
                        continue;
                    }
                    const int nr = row + dy;
                    const int nc = col + dx;
                    if (nr >= 0 && nr < height && nc >= 0 && nc < width) {
                        if (original[nr * width + nc] == static_cast<std::uint8_t>(CellType::Walkable)) {
                            ++neighbors;
                        }
                    }
                }
            }
            if (neighbors >= min_neighbors) {
                grid[idx] = static_cast<std::uint8_t>(CellType::Walkable);
            }
        }
    }
}

}  // namespace

GridResult build_grid(const PCDReader& reader, const GridParameters& params, const ProgressCallback& progress_cb) {
    if (progress_cb) {
        progress_cb(0, "正在扫描点云范围");
    }

    double min_x = std::numeric_limits<double>::infinity();
    double min_y = std::numeric_limits<double>::infinity();
    double max_x = -std::numeric_limits<double>::infinity();
    double max_y = -std::numeric_limits<double>::infinity();
    int kept_points = 0;
    int processed = 0;
    int last_percent = -1;
    const int total_points = std::max(1, static_cast<int>(reader.points()));

    reader.for_each_xyz([&](float x, float y, float z) {
        ++processed;
        if (z >= params.clip_min_z && z <= params.clip_max_z) {
            ++kept_points;
            min_x = std::min(min_x, static_cast<double>(x));
            min_y = std::min(min_y, static_cast<double>(y));
            max_x = std::max(max_x, static_cast<double>(x));
            max_y = std::max(max_y, static_cast<double>(y));
        }
        advance_progress(progress_cb, processed, total_points, 35, "正在扫描点云范围", last_percent);
    });

    if (kept_points <= 0) {
        throw std::runtime_error("no usable points inside clip range");
    }

    const int width = std::max(1, static_cast<int>(std::ceil((max_x - min_x) / params.resolution)) + 1);
    const int height = std::max(1, static_cast<int>(std::ceil((max_y - min_y) / params.resolution)) + 1);
    std::vector<CellStats> cells(static_cast<std::size_t>(width) * static_cast<std::size_t>(height));

    processed = 0;
    last_percent = -1;
    reader.for_each_xyz([&](float x, float y, float z) {
        ++processed;
        if (z < params.clip_min_z || z > params.clip_max_z) {
            advance_progress(progress_cb, processed, total_points, 70, "正在构建栅格", last_percent);
            return;
        }

        const int col = clamp_value(static_cast<int>((static_cast<double>(x) - min_x) / params.resolution), 0, width - 1);
        const int row = clamp_value(static_cast<int>((static_cast<double>(y) - min_y) / params.resolution), 0, height - 1);
        auto& cell = cells[static_cast<std::size_t>(row) * static_cast<std::size_t>(width) + static_cast<std::size_t>(col)];
        cell.count += 1;
        cell.min_z = std::min(cell.min_z, static_cast<double>(z));
        cell.max_z = std::max(cell.max_z, static_cast<double>(z));

        if (z >= params.walkable_min_z && z <= params.walkable_max_z) {
            cell.walkable_count += 1;
            cell.walkable_min_z = std::min(cell.walkable_min_z, static_cast<double>(z));
            cell.walkable_max_z = std::max(cell.walkable_max_z, static_cast<double>(z));
        }
        if (z >= params.obstacle_min_z && z <= params.obstacle_max_z) {
            cell.obstacle_count += 1;
        }
        advance_progress(progress_cb, processed, total_points, 70, "正在构建栅格", last_percent);
    });

    GridResult result;
    result.width = width;
    result.height = height;
    result.origin_x = min_x;
    result.origin_y = min_y;
    result.resolution = params.resolution;
    result.grid.assign(static_cast<std::size_t>(width) * static_cast<std::size_t>(height), static_cast<std::uint8_t>(CellType::Unknown));
    result.point_count = kept_points;

    if (progress_cb) {
        progress_cb(75, "正在分类栅格");
    }

    for (std::size_t idx = 0; idx < cells.size(); ++idx) {
        const auto& cell = cells[idx];
        if (cell.count < params.min_points_per_cell) {
            result.grid[idx] = static_cast<std::uint8_t>(CellType::Unknown);
            result.unknown_cells += 1;
            continue;
        }

        const bool is_walkable =
            cell.walkable_count >= params.min_points_per_cell &&
            (cell.walkable_max_z - cell.walkable_min_z) <= params.ground_tolerance;
        const bool is_obstacle = cell.obstacle_count > 0;

        if (is_walkable && !is_obstacle) {
            result.grid[idx] = static_cast<std::uint8_t>(CellType::Walkable);
            result.walkable_cells += 1;
        } else {
            result.grid[idx] = static_cast<std::uint8_t>(CellType::Obstacle);
            result.obstacle_cells += 1;
        }
    }

    if (progress_cb) {
        progress_cb(82, "正在膨胀障碍物");
    }
    inflate_obstacles(result.grid, width, height, params.obstacle_inflate_radius, params.resolution);

    if (progress_cb) {
        progress_cb(88, "正在填补可行走空洞");
    }
    fill_walkable_holes(result.grid, width, height, params.hole_fill_neighbors);

    result.obstacle_cells = 0;
    result.walkable_cells = 0;
    result.unknown_cells = 0;
    for (const auto cell : result.grid) {
        if (cell == static_cast<std::uint8_t>(CellType::Obstacle)) {
            ++result.obstacle_cells;
        } else if (cell == static_cast<std::uint8_t>(CellType::Walkable)) {
            ++result.walkable_cells;
        } else {
            ++result.unknown_cells;
        }
    }

    if (progress_cb) {
        progress_cb(90, "栅格构建完成");
    }
    return result;
}

}  // namespace ros_tool_suite::mapping
