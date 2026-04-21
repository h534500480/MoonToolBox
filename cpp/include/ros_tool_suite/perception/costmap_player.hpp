#pragma once

#include <filesystem>
#include <string>

namespace ros_tool_suite::perception {

struct CostmapOptions {
    std::filesystem::path yaml_path;
    std::filesystem::path output_dir;
    double fps = 2.0;
    bool export_gif = true;
};

struct CostmapResult {
    std::filesystem::path summary_path;
    int frame_count = 0;
    std::string summary;
};

CostmapResult process_costmap(const CostmapOptions& options);

}  // namespace ros_tool_suite::perception
