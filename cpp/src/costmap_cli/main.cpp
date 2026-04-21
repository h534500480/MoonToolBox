#include <exception>
#include <iostream>
#include <string>

#include "ros_tool_suite/perception/costmap_player.hpp"

namespace {

std::string require_value(int& index, int argc, char** argv) {
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value after argument");
    }
    return argv[++index];
}

}  // namespace

int main(int argc, char** argv) {
    ros_tool_suite::perception::CostmapOptions options;
    options.output_dir = "output_costmap";

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--yaml") {
            options.yaml_path = require_value(i, argc, argv);
        } else if (arg == "--output-dir") {
            options.output_dir = require_value(i, argc, argv);
        } else if (arg == "--fps") {
            options.fps = std::stod(require_value(i, argc, argv));
        } else if (arg == "--no-gif") {
            options.export_gif = false;
        }
    }

    try {
        const auto result = ros_tool_suite::perception::process_costmap(options);
        std::cout << "summary_path: " << result.summary_path.string() << "\n";
        std::cout << "frame_count: " << result.frame_count << "\n";
        std::cout << "summary: " << result.summary << "\n";
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << "\n";
        return 2;
    }
}
