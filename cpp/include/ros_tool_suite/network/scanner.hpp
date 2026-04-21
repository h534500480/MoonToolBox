#pragma once

#include <string>
#include <vector>

namespace ros_tool_suite::network {

struct ScanOptions {
    std::string prefix = "192.168.1";
    int start = 1;
    int end = 32;
    int timeout_ms = 400;
};

struct DeviceInfo {
    std::string ip;
    std::string status;
    std::string note;
};

std::vector<DeviceInfo> scan_range(const ScanOptions& options);

}  // namespace ros_tool_suite::network
