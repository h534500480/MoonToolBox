// 功能说明：全局重定位离线候选点生成命令行入口，负责解析参数并调用 C++ 候选点生成器。

#include "ros_tool_suite/mapping/global_relocalization.hpp"

#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void print_usage() {
    std::cout
        << "Usage: global_relocalization_cli --map <map.pcd> --output <dir> [--config <yaml>] [--manual <manual_candidates.yaml>] [--candidates <reviewed_candidates.csv>] [--progress-interval <n>]\n"
        << "       Generates v2 place-level candidates.npy/descriptors.npy/ring_keys.npy with Scan Context ray casting from 3D PCD.\n";
}

std::string require_value(int& index, int argc, char** argv) {
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value after argument");
    }
    return argv[++index];
}

}  // namespace

int main(int argc, char** argv) {
    std::string map_path;
    std::string output_dir = "global_relocalization_db";
    std::string config_path;
    std::string manual_path;
    std::string reviewed_candidates_path;
    int progress_interval = 20;
    ros_tool_suite::mapping::GlobalRelocConfig config;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if ((arg == "--map" || arg == "--pcd") && i + 1 < argc) {
            map_path = argv[++i];
        } else if ((arg == "--output" || arg == "--output-dir") && i + 1 < argc) {
            output_dir = argv[++i];
        } else if (arg == "--config" && i + 1 < argc) {
            config_path = argv[++i];
        } else if (arg == "--manual" && i + 1 < argc) {
            manual_path = argv[++i];
        } else if ((arg == "--candidates" || arg == "--reviewed-candidates") && i + 1 < argc) {
            reviewed_candidates_path = argv[++i];
        } else if (arg == "--progress-interval") {
            progress_interval = std::stoi(require_value(i, argc, argv));
        } else if (arg == "--target-base-positions") {
            config.target_base_positions = std::stoi(require_value(i, argc, argv));
        } else if (arg == "--max-base-samples") {
            config.max_base_samples = std::stoi(require_value(i, argc, argv));
        } else if (arg == "--min-candidate-distance") {
            config.min_candidate_distance_m = std::stod(require_value(i, argc, argv));
        } else if (arg == "--yaw-step-deg") {
            config.yaw_step_deg = std::stod(require_value(i, argc, argv));
        } else if (arg == "--help" || arg == "-h") {
            print_usage();
            return 0;
        }
    }

    if (map_path.empty()) {
        print_usage();
        return 1;
    }

    try {
        config = ros_tool_suite::mapping::load_global_reloc_config(config_path, config);
        const auto result = ros_tool_suite::mapping::generate_global_relocalization_candidates(
            map_path,
            output_dir,
            config,
            manual_path,
            progress_interval,
            reviewed_candidates_path);

        std::cout << "metadata_path: " << result.metadata_path << "\n";
        std::cout << "candidates_csv_path: " << result.candidates_csv_path << "\n";
        std::cout << "candidates_npy_path: " << result.candidates_npy_path << "\n";
        std::cout << "descriptors_npy_path: " << result.descriptors_npy_path << "\n";
        std::cout << "ring_keys_npy_path: " << result.ring_keys_npy_path << "\n";
        std::cout << "sector_keys_npy_path: " << result.sector_keys_npy_path << "\n";
        std::cout << "preview_pcd_path: " << result.preview_pcd_path << "\n";
        std::cout << "input_points: " << result.input_points << "\n";
        std::cout << "downsampled_points: " << result.downsampled_points << "\n";
        std::cout << "occupied_voxels: " << result.occupied_voxels << "\n";
        std::cout << "supported_ground_cells: " << result.supported_ground_cells << "\n";
        std::cout << "accepted_base_positions: " << result.accepted_base_positions << "\n";
        std::cout << "accepted_candidates: " << result.accepted_candidates << "\n";
        std::cout << "accepted_places: " << result.accepted_candidates << "\n";
        std::cout << "manual_additions: " << result.manual_additions << "\n";
        std::cout << "manual_deletions: " << result.manual_deletions << "\n";
        std::cout << "rejected_candidates: " << result.rejected_candidates << "\n";
        std::cout << "ray_count: " << result.ray_count << "\n";
    } catch (const std::exception& exc) {
        std::cerr << "error: " << exc.what() << "\n";
        return 2;
    }

    return 0;
}
