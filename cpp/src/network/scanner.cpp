#include "ros_tool_suite/network/scanner.hpp"

#include <algorithm>

namespace ros_tool_suite::network {

std::vector<DeviceInfo> scan_range(const ScanOptions& options) {
    std::vector<DeviceInfo> devices;
    const int clamped_end = std::max(options.start, options.end);
    for (int i = options.start; i <= clamped_end && static_cast<int>(devices.size()) < 8; ++i) {
        DeviceInfo info;
        info.ip = options.prefix + "." + std::to_string(i);
        info.status = (i == options.start) ? "reachable" : "pending";
        info.note = "C++ scanner skeleton";
        devices.push_back(info);
    }
    return devices;
}

}  // namespace ros_tool_suite::network
