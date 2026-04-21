#pragma once

#include <functional>

#include "ros_tool_suite/mapping/pcd_reader.hpp"
#include "ros_tool_suite/mapping/types.hpp"

namespace ros_tool_suite::mapping {

using ProgressCallback = std::function<void(int, const std::string&)>;

GridResult build_grid(const PCDReader& reader, const GridParameters& params, const ProgressCallback& progress_cb);

}  // namespace ros_tool_suite::mapping
