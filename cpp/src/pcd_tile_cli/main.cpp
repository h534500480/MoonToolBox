#include <exception>
#include <iostream>
#include <string>

#include "ros_tool_suite/slicing/tile_splitter.hpp"

namespace {

std::string require_value(int& index, int argc, char** argv) {
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value after argument");
    }
    return argv[++index];
}

}  // namespace

int main(int argc, char** argv) {
    ros_tool_suite::slicing::TileSplitOptions options;
    options.output_dir = "output_tiles";

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--pcd") {
            options.input_pcd = require_value(i, argc, argv);
        } else if (arg == "--output-dir") {
            options.output_dir = require_value(i, argc, argv);
        } else if (arg == "--tile-size") {
            options.tile_size = std::stod(require_value(i, argc, argv));
        } else if (arg == "--overlap") {
            options.overlap = std::stod(require_value(i, argc, argv));
        } else if (arg == "--format") {
            options.format = require_value(i, argc, argv);
        } else if (arg == "--zip-output") {
            options.zip_output = true;
        }
    }

    try {
        const auto result = ros_tool_suite::slicing::split_tiles(options);
        std::cout << "metadata_path: " << result.metadata_path.string() << "\n";
        std::cout << "tile_count: " << result.tile_count << "\n";
        std::cout << "summary: " << result.summary << "\n";
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << "\n";
        return 2;
    }
}
