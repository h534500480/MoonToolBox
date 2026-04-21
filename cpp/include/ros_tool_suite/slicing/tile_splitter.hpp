#pragma once

#include <filesystem>
#include <string>

namespace ros_tool_suite::slicing {

struct TileSplitOptions {
    std::filesystem::path input_pcd;
    std::filesystem::path output_dir;
    double tile_size = 20.0;
    double overlap = 0.0;
    bool zip_output = false;
    std::string format = "binary";
};

struct TileSplitResult {
    std::filesystem::path metadata_path;
    int tile_count = 0;
    std::string summary;
};

TileSplitResult split_tiles(const TileSplitOptions& options);

}  // namespace ros_tool_suite::slicing
