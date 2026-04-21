#include "ros_tool_suite/mapping/exporters.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#include "ros_tool_suite/mapping/map_builder.hpp"
#include "ros_tool_suite/mapping/pcd_reader.hpp"

namespace ros_tool_suite::mapping {

namespace {

std::uint32_t crc32(const std::uint8_t* data, std::size_t size) {
    std::uint32_t crc = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) {
            const bool lsb = (crc & 1u) != 0u;
            crc >>= 1u;
            if (lsb) {
                crc ^= 0xEDB88320u;
            }
        }
    }
    return ~crc;
}

std::uint32_t adler32(const std::vector<std::uint8_t>& data) {
    constexpr std::uint32_t mod = 65521u;
    std::uint32_t a = 1u;
    std::uint32_t b = 0u;
    for (const auto value : data) {
        a = (a + value) % mod;
        b = (b + a) % mod;
    }
    return (b << 16u) | a;
}

void append_be32(std::vector<std::uint8_t>& out, std::uint32_t value) {
    out.push_back(static_cast<std::uint8_t>((value >> 24u) & 0xFFu));
    out.push_back(static_cast<std::uint8_t>((value >> 16u) & 0xFFu));
    out.push_back(static_cast<std::uint8_t>((value >> 8u) & 0xFFu));
    out.push_back(static_cast<std::uint8_t>(value & 0xFFu));
}

void write_chunk(std::ofstream& out, const char* type, const std::vector<std::uint8_t>& data) {
    std::vector<std::uint8_t> buffer;
    buffer.reserve(4 + data.size());
    buffer.push_back(static_cast<std::uint8_t>(type[0]));
    buffer.push_back(static_cast<std::uint8_t>(type[1]));
    buffer.push_back(static_cast<std::uint8_t>(type[2]));
    buffer.push_back(static_cast<std::uint8_t>(type[3]));
    buffer.insert(buffer.end(), data.begin(), data.end());

    const std::uint32_t length = static_cast<std::uint32_t>(data.size());
    const std::uint32_t crc = crc32(buffer.data(), buffer.size());

    std::vector<std::uint8_t> header;
    append_be32(header, length);
    out.write(reinterpret_cast<const char*>(header.data()), static_cast<std::streamsize>(header.size()));
    out.write(reinterpret_cast<const char*>(buffer.data()), static_cast<std::streamsize>(buffer.size()));

    std::vector<std::uint8_t> trailer;
    append_be32(trailer, crc);
    out.write(reinterpret_cast<const char*>(trailer.data()), static_cast<std::streamsize>(trailer.size()));
}

std::vector<std::uint8_t> make_zlib_stored_stream(const std::vector<std::uint8_t>& raw) {
    std::vector<std::uint8_t> out;
    out.push_back(0x78u);
    out.push_back(0x01u);

    std::size_t offset = 0;
    while (offset < raw.size()) {
        const auto chunk = std::min<std::size_t>(65535u, raw.size() - offset);
        const bool final_block = (offset + chunk) >= raw.size();
        out.push_back(final_block ? 0x01u : 0x00u);

        const std::uint16_t len = static_cast<std::uint16_t>(chunk);
        const std::uint16_t nlen = static_cast<std::uint16_t>(~len);
        out.push_back(static_cast<std::uint8_t>(len & 0xFFu));
        out.push_back(static_cast<std::uint8_t>((len >> 8u) & 0xFFu));
        out.push_back(static_cast<std::uint8_t>(nlen & 0xFFu));
        out.push_back(static_cast<std::uint8_t>((nlen >> 8u) & 0xFFu));
        out.insert(out.end(), raw.begin() + static_cast<std::ptrdiff_t>(offset), raw.begin() + static_cast<std::ptrdiff_t>(offset + chunk));
        offset += chunk;
    }

    append_be32(out, adler32(raw));
    return out;
}

std::vector<std::uint8_t> build_overlay_mask(const GridResult& result, const GridParameters& params) {
    std::vector<std::uint8_t> mask(result.grid.size(), 0u);
    for (std::size_t i = 0; i < result.grid.size(); ++i) {
        if (result.grid[i] != static_cast<std::uint8_t>(CellType::Obstacle)) {
            mask[i] = 255u;
        }
    }

    const int radius_cells = std::max(
        0,
        static_cast<int>(std::llround(params.overlay_smooth_radius / std::max(params.resolution, 1e-6))));
    if (radius_cells <= 0) {
        return mask;
    }

    auto dilated = mask;
    for (int row = 0; row < result.height; ++row) {
        for (int col = 0; col < result.width; ++col) {
            const int idx = row * result.width + col;
            if (mask[idx] == 0u) {
                continue;
            }
            for (int dy = -radius_cells; dy <= radius_cells; ++dy) {
                for (int dx = -radius_cells; dx <= radius_cells; ++dx) {
                    if (dx * dx + dy * dy > radius_cells * radius_cells) {
                        continue;
                    }
                    const int nr = row + dy;
                    const int nc = col + dx;
                    if (nr >= 0 && nr < result.height && nc >= 0 && nc < result.width) {
                        const int nidx = nr * result.width + nc;
                        if (result.grid[nidx] != static_cast<std::uint8_t>(CellType::Obstacle)) {
                            dilated[nidx] = 255u;
                        }
                    }
                }
            }
        }
    }

    auto eroded = dilated;
    for (int row = 0; row < result.height; ++row) {
        for (int col = 0; col < result.width; ++col) {
            const int idx = row * result.width + col;
            if (dilated[idx] == 0u) {
                continue;
            }
            for (int dy = -radius_cells; dy <= radius_cells; ++dy) {
                for (int dx = -radius_cells; dx <= radius_cells; ++dx) {
                    if (dx * dx + dy * dy > radius_cells * radius_cells) {
                        continue;
                    }
                    const int nr = row + dy;
                    const int nc = col + dx;
                    if (nr < 0 || nr >= result.height || nc < 0 || nc >= result.width) {
                        eroded[idx] = 0u;
                        break;
                    }
                    const int nidx = nr * result.width + nc;
                    if (result.grid[nidx] == static_cast<std::uint8_t>(CellType::Obstacle) || dilated[nidx] == 0u) {
                        eroded[idx] = 0u;
                        break;
                    }
                }
                if (eroded[idx] == 0u) {
                    break;
                }
            }
        }
    }

    return eroded;
}

void write_pgm(const std::filesystem::path& path, const GridResult& result, const GridParameters& params) {
    std::ofstream out(path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to create pgm");
    }
    out << "P5\n" << result.width << " " << result.height << "\n255\n";
    for (int row = result.height - 1; row >= 0; --row) {
        for (int col = 0; col < result.width; ++col) {
            const auto cell = result.grid[static_cast<std::size_t>(row) * static_cast<std::size_t>(result.width) + static_cast<std::size_t>(col)];
            const std::uint8_t value = (cell == static_cast<std::uint8_t>(CellType::Obstacle))
                ? static_cast<std::uint8_t>(params.obstacle_gray)
                : static_cast<std::uint8_t>(params.free_gray);
            out.write(reinterpret_cast<const char*>(&value), 1);
        }
    }
}

void write_yaml(const std::filesystem::path& path, const std::string& pgm_name, const GridResult& result, const GridParameters& params) {
    std::ofstream out(path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to create yaml");
    }
    out << "image: " << pgm_name << "\n";
    out << "resolution: " << result.resolution << "\n";
    out << "origin: [" << result.origin_x << ", " << result.origin_y << ", 0.0]\n";
    out << "negate: " << params.negate << "\n";
    out << "occupied_thresh: " << params.occupied_thresh << "\n";
    out << "free_thresh: " << params.free_thresh << "\n";
}

void write_rgba_png(
    const std::filesystem::path& path,
    int width,
    int height,
    const std::function<std::array<std::uint8_t, 4>(int, int)>& pixel_fn) {
    std::vector<std::uint8_t> raw;
    raw.reserve(static_cast<std::size_t>(height) * (1u + static_cast<std::size_t>(width) * 4u));

    for (int y = height - 1; y >= 0; --y) {
        raw.push_back(0u);
        for (int x = 0; x < width; ++x) {
            const auto pixel = pixel_fn(x, y);
            raw.insert(raw.end(), pixel.begin(), pixel.end());
        }
    }

    const auto compressed = make_zlib_stored_stream(raw);

    std::ofstream out(path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to create png");
    }

    const std::array<std::uint8_t, 8> signature = {0x89u, 'P', 'N', 'G', '\r', '\n', 0x1Au, '\n'};
    out.write(reinterpret_cast<const char*>(signature.data()), static_cast<std::streamsize>(signature.size()));

    std::vector<std::uint8_t> ihdr;
    append_be32(ihdr, static_cast<std::uint32_t>(width));
    append_be32(ihdr, static_cast<std::uint32_t>(height));
    ihdr.push_back(8u);
    ihdr.push_back(6u);
    ihdr.push_back(0u);
    ihdr.push_back(0u);
    ihdr.push_back(0u);
    write_chunk(out, "IHDR", ihdr);
    write_chunk(out, "IDAT", compressed);
    write_chunk(out, "IEND", {});
}

void write_walkable_overlay_png(const std::filesystem::path& path, const GridResult& result, const GridParameters& params) {
    const auto mask = build_overlay_mask(result, params);
    const auto [r, g, b] = params.walkable_color;
    write_rgba_png(path, result.width, result.height, [&](int x, int y) {
        const auto idx = static_cast<std::size_t>(y) * static_cast<std::size_t>(result.width) + static_cast<std::size_t>(x);
        if (mask[idx] != 0u) {
            return std::array<std::uint8_t, 4>{
                static_cast<std::uint8_t>(r),
                static_cast<std::uint8_t>(g),
                static_cast<std::uint8_t>(b),
                255u,
            };
        }
        return std::array<std::uint8_t, 4>{0u, 0u, 0u, 0u};
    });
}

void write_walkable_preview_png(const std::filesystem::path& path, const GridResult& result, const GridParameters& params) {
    const auto mask = build_overlay_mask(result, params);
    const auto [r, g, b] = params.walkable_color;
    const int max_side = 1200;
    const int scale = std::max(1, static_cast<int>(std::ceil(static_cast<double>(std::max(result.width, result.height)) / max_side)));
    const int preview_width = std::max(1, result.width / scale);
    const int preview_height = std::max(1, result.height / scale);

    write_rgba_png(path, preview_width, preview_height, [&](int x, int y) {
        const int src_x = std::min(result.width - 1, x * scale);
        const int src_y = std::min(result.height - 1, y * scale);
        const auto idx = static_cast<std::size_t>(src_y) * static_cast<std::size_t>(result.width) + static_cast<std::size_t>(src_x);
        if (mask[idx] != 0u) {
            return std::array<std::uint8_t, 4>{
                static_cast<std::uint8_t>(r),
                static_cast<std::uint8_t>(g),
                static_cast<std::uint8_t>(b),
                255u,
            };
        }
        return std::array<std::uint8_t, 4>{0u, 0u, 0u, 0u};
    });
}

}  // namespace

ExportResult export_maps(
    const std::filesystem::path& pcd_path,
    const std::filesystem::path& output_dir,
    const std::string& base_name,
    const GridParameters& params) {
    std::filesystem::create_directories(output_dir);

    PCDReader reader(pcd_path.string());
    reader.read_header();
    const auto result = build_grid(reader, params, nullptr);

    const auto pgm_path = output_dir / (base_name + ".pgm");
    const auto yaml_path = output_dir / (base_name + ".yaml");
    const auto color_path = output_dir / (base_name + "_walkable.png");
    const auto preview_path = output_dir / (base_name + "_walkable_preview.png");

    write_pgm(pgm_path, result, params);
    write_walkable_overlay_png(color_path, result, params);
    write_walkable_preview_png(preview_path, result, params);
    write_yaml(yaml_path, pgm_path.filename().string(), result, params);

    ExportResult export_result;
    export_result.pgm_path = pgm_path.string();
    export_result.yaml_path = yaml_path.string();
    export_result.color_path = color_path.string();
    export_result.preview_path = preview_path.string();
    export_result.width = result.width;
    export_result.height = result.height;
    export_result.origin_x = result.origin_x;
    export_result.origin_y = result.origin_y;
    export_result.point_count = result.point_count;
    export_result.walkable_cells = result.walkable_cells;
    export_result.obstacle_cells = result.obstacle_cells;
    export_result.unknown_cells = result.unknown_cells;
    return export_result;
}

}  // namespace ros_tool_suite::mapping
