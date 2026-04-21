#include "ros_tool_suite/perception/costmap_player.hpp"

#include <fstream>
#include <stdexcept>

namespace ros_tool_suite::perception {

CostmapResult process_costmap(const CostmapOptions& options) {
    if (options.yaml_path.empty()) {
        throw std::runtime_error("yaml path is required");
    }
    std::filesystem::create_directories(options.output_dir);

    const auto summary_path = options.output_dir / "costmap_summary.txt";
    std::ofstream out(summary_path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to write summary");
    }

    out << "yaml_path: " << options.yaml_path.string() << "\n";
    out << "fps: " << options.fps << "\n";
    out << "export_gif: " << (options.export_gif ? "true" : "false") << "\n";
    out << "note: C++ costmap framework is ready.\n";

    CostmapResult result;
    result.summary_path = summary_path;
    result.frame_count = 0;
    result.summary = "Costmap framework is ready; YAML parsing and frame rendering are the next step.";
    return result;
}

}  // namespace ros_tool_suite::perception
