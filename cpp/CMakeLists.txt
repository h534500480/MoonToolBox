cmake_minimum_required(VERSION 3.16)
project(ros_tool_suite_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

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

add_executable(network_scan_cli
    src/network_cli/main.cpp
    src/network/scanner.cpp
)
target_include_directories(network_scan_cli PRIVATE ${COMMON_INCLUDE_DIR})

add_executable(costmap_cli
    src/costmap_cli/main.cpp
    src/perception/costmap_player.cpp
)
target_include_directories(costmap_cli PRIVATE ${COMMON_INCLUDE_DIR})

add_executable(ros_tool_suite_gui WIN32
    src/gui/main.cpp
)
target_include_directories(ros_tool_suite_gui PRIVATE ${COMMON_INCLUDE_DIR})
