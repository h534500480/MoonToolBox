#pragma once

// 功能说明：从 3D PCD 地图生成全局重定位候选位姿和 Scan Context 离线数据库。

#include <string>
#include <vector>

namespace ros_tool_suite::mapping {

struct GlobalRelocConfig {
    double voxel_leaf_m = 0.20;
    double occupancy_resolution_m = 0.25;
    double z_min_m = -3.0;
    double z_max_m = 5.0;
    std::string strategy = "adaptive_random";
    double xy_resolution_m = 0.50;
    double min_candidate_distance_m = 0.80;
    double robot_radius_m = 0.63;
    double safety_margin_m = 0.05;
    double clearance_check_height_m = 0.80;
    double clearance_min_free_ratio = 0.65;
    double map_boundary_margin_m = 1.0;
    int ground_min_points_per_cell = 4;
    double ground_support_radius_m = 0.80;
    int ground_min_neighbor_cells = 4;
    double ground_support_max_delta_z_m = 0.35;
    double base_link_height_offset_m = 0.35;
    std::vector<double> roll_samples_deg{0.0};
    std::vector<double> pitch_samples_deg{0.0};
    double yaw_step_deg = 45.0;
    unsigned int random_seed = 7;
    int target_base_positions = 120;
    int max_base_samples = 2500;
    int early_stop_window = 500;
    int early_stop_min_accepts = 5;
    int max_candidates = 200000;
    int descriptor_num_rings = 20;
    int descriptor_num_sectors = 60;
    double virtual_lidar_min_range_m = 0.30;
    double virtual_lidar_max_range_m = 30.0;
    double virtual_lidar_horizontal_fov_deg = 360.0;
    double virtual_lidar_vertical_fov_deg = 59.0;
    double virtual_lidar_horizontal_step_deg = 2.0;
    double virtual_lidar_vertical_step_deg = 2.0;
    double virtual_lidar_occupancy_inflate_radius_m = 0.15;
    std::vector<double> lidar_to_base_translation_xyz{0.0, 0.0, 0.0};
    std::vector<double> lidar_to_base_rpy_deg{0.0, 0.0, 0.0};
    double descriptor_max_radius_m = 30.0;
    double descriptor_height_clip_min_m = -3.0;
    double descriptor_height_clip_max_m = 5.0;
    int observability_min_hit_points = 80;
    double observability_min_hit_ratio = 0.03;
    int observability_min_visible_sector_count = 12;
    double observability_min_descriptor_nonzero_ratio = 0.03;
    bool allow_force_add_low_observability = false;
};

struct GlobalRelocCandidate {
    int candidate_id = 0;
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    double roll_deg = 0.0;
    double pitch_deg = 0.0;
    double yaw_deg = 0.0;
    double qx = 0.0;
    double qy = 0.0;
    double qz = 0.0;
    double qw = 1.0;
    double observability_score = 0.0;
    int hit_count = 0;
    double hit_ratio = 0.0;
    int visible_sector_count = 0;
    double descriptor_nonzero_ratio = 0.0;
    std::string source = "auto";
    std::string label;
    bool locked = false;
    int original_candidate_id = -1;
};

struct GlobalRelocResult {
    std::string output_dir;
    std::string metadata_path;
    std::string candidates_csv_path;
    std::string candidates_npy_path;
    std::string descriptors_npy_path;
    std::string ring_keys_npy_path;
    std::string sector_keys_npy_path;
    std::string preview_pcd_path;
    int input_points = 0;
    int downsampled_points = 0;
    int occupied_voxels = 0;
    int supported_ground_cells = 0;
    int accepted_base_positions = 0;
    int accepted_candidates = 0;
    int manual_additions = 0;
    int manual_deletions = 0;
    int rejected_candidates = 0;
    int ray_count = 0;
};

GlobalRelocConfig load_global_reloc_config(const std::string& config_path, GlobalRelocConfig defaults = {});

GlobalRelocResult generate_global_relocalization_candidates(
    const std::string& pcd_path,
    const std::string& output_dir,
    const GlobalRelocConfig& config,
    const std::string& manual_path,
    int progress_interval,
    const std::string& reviewed_candidates_path = "");

}  // namespace ros_tool_suite::mapping
