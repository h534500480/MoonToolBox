#include "ros_tool_suite/slicing/tile_splitter.hpp"

#include <fstream>
#include <sstream>
#include <stdexcept>

namespace ros_tool_suite::slicing {

TileSplitResult split_tiles(const TileSplitOptions& options) {
    if (options.input_pcd.empty()) {
        throw std::runtime_error("input pcd is required");
    }
    std::filesystem::create_directories(options.output_dir);

    const auto metadata_path = options.output_dir / "pointcloud_data_metadata.yaml";
    std::ofstream out(metadata_path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to write metadata");
    }

    out << "input_pcd: " << options.input_pcd.string() << "\n";
    out << "tile_size: " << options.tile_size << "\n";
    out << "overlap: " << options.overlap << "\n";
    out << "format: " << options.format << "\n";
    out << "zip_output: " << (options.zip_output ? "true" : "false") << "\n";
    out << "note: C++ tile splitter skeleton generated this metadata.\n";

    TileSplitResult result;
    result.metadata_path = metadata_path;
    result.tile_count = 0;
    result.summary = "Tile splitter framework is ready; core slicing algorithm is the next step.";
    return result;
}

}  // namespace ros_tool_suite::slicing
