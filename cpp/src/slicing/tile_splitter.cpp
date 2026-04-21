#include "ros_tool_suite/slicing/tile_splitter.hpp"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <map>
#include <sstream>
#include <stdexcept>
#include <tuple>
#include <vector>

#include "ros_tool_suite/mapping/pcd_reader.hpp"

namespace ros_tool_suite::slicing {

namespace {

struct PointRecord {
    float x = 0.0F;
    float y = 0.0F;
    float z = 0.0F;
    float intensity = 0.0F;
};

using TileKey = std::pair<double, double>;

double tile_coord(double value, double tile_size) {
    return std::floor(value / tile_size) * tile_size;
}

std::string format_coord(double value) {
    std::ostringstream oss;
    const double rounded = std::round(value);
    if (std::abs(value - rounded) < 1e-6) {
        oss << static_cast<long long>(rounded);
    } else {
        oss << std::fixed << std::setprecision(6) << value;
        auto text = oss.str();
        while (!text.empty() && text.back() == '0') {
            text.pop_back();
        }
        if (!text.empty() && text.back() == '.') {
            text.pop_back();
        }
        return text;
    }
    return oss.str();
}

void write_pcd_ascii(const std::filesystem::path& path, const std::vector<PointRecord>& points) {
    std::ofstream out(path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to write tile pcd");
    }
    out << "# .PCD v0.7 - Point Cloud Data file format\n";
    out << "VERSION 0.7\n";
    out << "FIELDS x y z intensity\n";
    out << "SIZE 4 4 4 4\n";
    out << "TYPE F F F F\n";
    out << "COUNT 1 1 1 1\n";
    out << "WIDTH " << points.size() << "\n";
    out << "HEIGHT 1\n";
    out << "VIEWPOINT 0 0 0 1 0 0 0\n";
    out << "POINTS " << points.size() << "\n";
    out << "DATA ascii\n";
    for (const auto& point : points) {
        out << point.x << " " << point.y << " " << point.z << " " << point.intensity << "\n";
    }
}

void write_pcd_binary(const std::filesystem::path& path, const std::vector<PointRecord>& points) {
    std::ofstream out(path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to write tile pcd");
    }
    out << "# .PCD v0.7 - Point Cloud Data file format\n";
    out << "VERSION 0.7\n";
    out << "FIELDS x y z intensity\n";
    out << "SIZE 4 4 4 4\n";
    out << "TYPE F F F F\n";
    out << "COUNT 1 1 1 1\n";
    out << "WIDTH " << points.size() << "\n";
    out << "HEIGHT 1\n";
    out << "VIEWPOINT 0 0 0 1 0 0 0\n";
    out << "POINTS " << points.size() << "\n";
    out << "DATA binary\n";
    for (const auto& point : points) {
        out.write(reinterpret_cast<const char*>(&point.x), sizeof(float));
        out.write(reinterpret_cast<const char*>(&point.y), sizeof(float));
        out.write(reinterpret_cast<const char*>(&point.z), sizeof(float));
        out.write(reinterpret_cast<const char*>(&point.intensity), sizeof(float));
    }
}

void write_metadata_yaml(
    const std::filesystem::path& path,
    double tile_size,
    const std::vector<std::tuple<std::string, double, double>>& entries) {
    std::ofstream out(path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to write metadata");
    }
    out << "x_resolution: " << format_coord(tile_size) << "\n";
    out << "y_resolution: " << format_coord(tile_size) << "\n";
    for (const auto& entry : entries) {
        out << std::get<0>(entry) << ": [" << format_coord(std::get<1>(entry)) << ", " << format_coord(std::get<2>(entry)) << "]\n";
    }
}

}  // namespace

TileSplitResult split_tiles(const TileSplitOptions& options) {
    if (options.input_pcd.empty()) {
        throw std::runtime_error("input pcd is required");
    }
    if (options.tile_size <= 0.0) {
        throw std::runtime_error("tile_size must be > 0");
    }
    std::filesystem::create_directories(options.output_dir);

    ros_tool_suite::mapping::PCDReader reader(options.input_pcd.string());
    reader.read_header();

    std::map<TileKey, std::vector<PointRecord>> tiles;
    std::size_t point_count = 0;
    reader.for_each_xyz([&](float x, float y, float z) {
        const TileKey key{tile_coord(static_cast<double>(x), options.tile_size), tile_coord(static_cast<double>(y), options.tile_size)};
        tiles[key].push_back(PointRecord{x, y, z, 0.0F});
        ++point_count;
    });

    std::vector<std::tuple<std::string, double, double>> metadata_entries;
    int written_tiles = 0;
    for (const auto& [key, points] : tiles) {
        const std::string file_name = "tile_" + format_coord(key.first) + "_" + format_coord(key.second) + ".pcd";
        const auto tile_path = options.output_dir / file_name;
        if (options.format == "ascii") {
            write_pcd_ascii(tile_path, points);
        } else {
            write_pcd_binary(tile_path, points);
        }
        metadata_entries.emplace_back(file_name, key.first, key.second);
        ++written_tiles;
    }

    const auto metadata_path = options.output_dir / "pointcloud_data_metadata.yaml";
    write_metadata_yaml(metadata_path, options.tile_size, metadata_entries);

    TileSplitResult result;
    result.metadata_path = metadata_path;
    result.tile_count = written_tiles;
    std::ostringstream summary;
    summary << "point_count=" << point_count
            << ", tile_count=" << written_tiles
            << ", format=" << options.format;
    result.summary = summary.str();
    return result;
}

}  // namespace ros_tool_suite::slicing
