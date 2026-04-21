#pragma once

#include <filesystem>

#include "ros_tool_suite/mapping/types.hpp"

namespace ros_tool_suite::mapping {

ExportResult export_maps(
    const std::filesystem::path& pcd_path,
    const std::filesystem::path& output_dir,
    const std::string& base_name,
    const GridParameters& params);

}  // namespace ros_tool_suite::mapping
