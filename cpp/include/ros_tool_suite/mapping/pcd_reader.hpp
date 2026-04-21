#pragma once

#include <cstdint>
#include <cstddef>
#include <functional>
#include <ios>
#include <string_view>
#include <string>
#include <unordered_map>
#include <vector>

namespace ros_tool_suite::mapping {

class PCDReader {
public:
    explicit PCDReader(std::string file_path);

    [[nodiscard]] const std::string& file_path() const noexcept { return file_path_; }
    [[nodiscard]] std::size_t points() const noexcept { return points_; }
    [[nodiscard]] bool header_ready() const noexcept { return header_ready_; }

    void read_header();
    void for_each_xyz(const std::function<void(float, float, float)>& visitor) const;

private:
    struct FieldSpec {
        std::string name;
        int size = 0;
        int count = 1;
        int offset = 0;
    };

    [[nodiscard]] int field_index(std::string_view name) const;

    std::string file_path_;
    std::size_t points_ = 0;
    std::size_t width_ = 0;
    std::size_t height_ = 0;
    std::string data_type_;
    std::streamoff data_offset_ = 0;
    int point_step_ = 0;
    bool header_ready_ = false;
    std::vector<std::string> fields_;
    std::vector<int> sizes_;
    std::vector<std::string> types_;
    std::vector<int> counts_;
    std::vector<FieldSpec> field_specs_;
    std::unordered_map<std::string, int> field_offsets_;
};

}  // namespace ros_tool_suite::mapping
