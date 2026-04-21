#include "ros_tool_suite/mapping/pcd_reader.hpp"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace ros_tool_suite::mapping {

PCDReader::PCDReader(std::string file_path) : file_path_(std::move(file_path)) {}

int PCDReader::field_index(std::string_view name) const {
    for (std::size_t i = 0; i < fields_.size(); ++i) {
        if (fields_[i] == name) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

void PCDReader::read_header() {
    std::ifstream input(file_path_, std::ios::binary);
    if (!input) {
        throw std::runtime_error("failed to open pcd file");
    }

    fields_.clear();
    sizes_.clear();
    types_.clear();
    counts_.clear();
    field_specs_.clear();
    field_offsets_.clear();
    points_ = 0;
    width_ = 0;
    height_ = 0;
    point_step_ = 0;
    data_offset_ = 0;
    data_type_.clear();

    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        if (line.empty() || line[0] == '#') {
            continue;
        }

        std::istringstream iss(line);
        std::string key;
        iss >> key;
        std::transform(key.begin(), key.end(), key.begin(), [](unsigned char ch) { return static_cast<char>(std::toupper(ch)); });

        if (key == "FIELDS") {
            std::string value;
            while (iss >> value) {
                fields_.push_back(value);
            }
        } else if (key == "SIZE") {
            int value = 0;
            while (iss >> value) {
                sizes_.push_back(value);
            }
        } else if (key == "TYPE") {
            std::string value;
            while (iss >> value) {
                types_.push_back(value);
            }
        } else if (key == "COUNT") {
            int value = 0;
            while (iss >> value) {
                counts_.push_back(value);
            }
        } else if (key == "WIDTH") {
            iss >> width_;
        } else if (key == "HEIGHT") {
            iss >> height_;
        } else if (key == "POINTS") {
            iss >> points_;
        } else if (key == "DATA") {
            iss >> data_type_;
            std::transform(data_type_.begin(), data_type_.end(), data_type_.begin(), [](unsigned char ch) {
                return static_cast<char>(std::tolower(ch));
            });
            data_offset_ = input.tellg();
            break;
        }
    }

    if (fields_.empty() || sizes_.empty()) {
        throw std::runtime_error("pcd missing FIELDS or SIZE");
    }
    if (counts_.empty()) {
        counts_.assign(fields_.size(), 1);
    }
    if (points_ == 0 && width_ > 0 && height_ > 0) {
        points_ = width_ * height_;
    }

    const int x_idx = field_index("x");
    const int y_idx = field_index("y");
    const int z_idx = field_index("z");
    if (x_idx < 0 || y_idx < 0 || z_idx < 0) {
        throw std::runtime_error("pcd must contain x y z fields");
    }
    if (fields_.size() != sizes_.size() || fields_.size() != types_.size() || fields_.size() != counts_.size()) {
        throw std::runtime_error("pcd header malformed");
    }

    int offset = 0;
    for (std::size_t i = 0; i < fields_.size(); ++i) {
        FieldSpec spec;
        spec.name = fields_[i];
        spec.size = sizes_[i];
        spec.count = counts_[i];
        spec.offset = offset;
        field_specs_.push_back(spec);
        field_offsets_[spec.name] = offset;
        offset += spec.size * spec.count;
    }
    point_step_ = offset;
    header_ready_ = true;
}

void PCDReader::for_each_xyz(const std::function<void(float, float, float)>& visitor) const {
    if (!header_ready_) {
        throw std::runtime_error("pcd header not loaded");
    }

    std::ifstream input(file_path_, std::ios::binary);
    if (!input) {
        throw std::runtime_error("failed to open pcd file");
    }
    input.seekg(data_offset_);

    const auto x_it = field_offsets_.find("x");
    const auto y_it = field_offsets_.find("y");
    const auto z_it = field_offsets_.find("z");
    if (x_it == field_offsets_.end() || y_it == field_offsets_.end() || z_it == field_offsets_.end()) {
        throw std::runtime_error("pcd xyz field offsets missing");
    }

    const int x_offset = x_it->second;
    const int y_offset = y_it->second;
    const int z_offset = z_it->second;

    if (data_type_ == "binary") {
        const std::size_t chunk_points = 32768;
        const std::size_t chunk_size = static_cast<std::size_t>(point_step_) * chunk_points;
        std::vector<char> buffer(chunk_size);
        std::vector<char> leftover;

        while (input) {
            input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            const auto read_bytes = static_cast<std::size_t>(input.gcount());
            if (read_bytes == 0) {
                break;
            }

            std::vector<char> data;
            data.reserve(leftover.size() + read_bytes);
            data.insert(data.end(), leftover.begin(), leftover.end());
            data.insert(data.end(), buffer.begin(), buffer.begin() + static_cast<std::ptrdiff_t>(read_bytes));

            const std::size_t usable = (data.size() / static_cast<std::size_t>(point_step_)) * static_cast<std::size_t>(point_step_);
            for (std::size_t start = 0; start < usable; start += static_cast<std::size_t>(point_step_)) {
                float x = 0.0F;
                float y = 0.0F;
                float z = 0.0F;
                std::memcpy(&x, data.data() + static_cast<std::ptrdiff_t>(start) + x_offset, sizeof(float));
                std::memcpy(&y, data.data() + static_cast<std::ptrdiff_t>(start) + y_offset, sizeof(float));
                std::memcpy(&z, data.data() + static_cast<std::ptrdiff_t>(start) + z_offset, sizeof(float));
                visitor(x, y, z);
            }

            leftover.assign(data.begin() + static_cast<std::ptrdiff_t>(usable), data.end());
        }
        return;
    }

    if (data_type_ == "ascii") {
        const int x_idx = field_index("x");
        const int y_idx = field_index("y");
        const int z_idx = field_index("z");
        if (x_idx < 0 || y_idx < 0 || z_idx < 0) {
            throw std::runtime_error("pcd xyz field indexes missing");
        }

        std::string line;
        while (std::getline(input, line)) {
            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }
            if (line.empty()) {
                continue;
            }
            std::istringstream iss(line);
            std::vector<std::string> parts;
            std::string part;
            while (iss >> part) {
                parts.push_back(part);
            }
            if (static_cast<int>(parts.size()) <= std::max({x_idx, y_idx, z_idx})) {
                continue;
            }
            visitor(std::stof(parts[x_idx]), std::stof(parts[y_idx]), std::stof(parts[z_idx]));
        }
        return;
    }

    throw std::runtime_error("unsupported pcd DATA type");
}

}  // namespace ros_tool_suite::mapping
