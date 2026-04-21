#include <exception>
#include <iostream>
#include <string>

#include "ros_tool_suite/network/scanner.hpp"

namespace {

std::string require_value(int& index, int argc, char** argv) {
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value after argument");
    }
    return argv[++index];
}

}  // namespace

int main(int argc, char** argv) {
    ros_tool_suite::network::ScanOptions options;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--prefix") {
            options.prefix = require_value(i, argc, argv);
        } else if (arg == "--start") {
            options.start = std::stoi(require_value(i, argc, argv));
        } else if (arg == "--end") {
            options.end = std::stoi(require_value(i, argc, argv));
        } else if (arg == "--timeout-ms") {
            options.timeout_ms = std::stoi(require_value(i, argc, argv));
        }
    }

    try {
        const auto devices = ros_tool_suite::network::scan_range(options);
        for (const auto& device : devices) {
            std::cout << device.ip << " | " << device.status << " | " << device.note << "\n";
        }
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << "\n";
        return 2;
    }
}
