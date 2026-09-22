# 功能说明：只构建平台四模块依赖的计算程序。
cmake_minimum_required(VERSION 3.16)
project(ros_tool_suite_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 多配置生成器与后端约定同一可执行文件位置。
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE ${CMAKE_BINARY_DIR})
if(MSVC)
    add_compile_options(/utf-8)
endif()

set(COMMON_INCLUDE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/include)

add_executable(pcd_map_cli
    src/pcd_map_cli/main.cpp
    src/mapping/pcd_reader.cpp
    src/mapping/map_builder.cpp
    src/mapping/exporters.cpp
)

target_include_directories(pcd_map_cli PRIVATE ${COMMON_INCLUDE_DIR})

add_executable(pcd_tile_cli
    src/pcd_tile_cli/main.cpp
    src/slicing/tile_splitter.cpp
    src/mapping/pcd_reader.cpp
)
target_include_directories(pcd_tile_cli PRIVATE ${COMMON_INCLUDE_DIR})

add_executable(global_relocalization_cli
    src/global_relocalization_cli/main.cpp
    src/mapping/global_relocalization.cpp
    src/mapping/pcd_reader.cpp
)
target_include_directories(global_relocalization_cli PRIVATE ${COMMON_INCLUDE_DIR})

add_executable(nav_pcd_preview_cli
    src/nav_pcd_preview_cli/main.cpp
    src/mapping/pcd_reader.cpp
)
target_include_directories(nav_pcd_preview_cli PRIVATE ${COMMON_INCLUDE_DIR})
