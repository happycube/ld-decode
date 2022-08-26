message( STATUS "---------Beginning cmake build of ld-ldf-reader---------")

cmake_minimum_required( VERSION 3.22 )
project(ld-ldf-reader)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

set(CMAKE_CXX_STANDARD 17)

set(CMAKE_AUTOUIC_SEARCH_PATHS "${SMAKE_CURRENT_SOURCE_DIR}/ui")

# Include all the paths
message( STATUS "--------- Finding packages---------")

find_package(Qt6 REQUIRED COMPONENTS Core)
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET
    libavcodec
    libavformat
    libavutil
)

# Make the libraries
add_subdirectory(tools/library/tbc)
add_subdirectory(tools/library/filter)

# This makes a library and a tool
add_subdirectory(tools/ld-chroma-decoder)

# Make the tools
add_subdirectory(tools/ld-chroma-decoder/encoder)
add_subdirectory(tools/ld-disc-stacker)
add_subdirectory(tools/ld-discmap)
add_subdirectory(tools/ld-dropout-correct)
add_subdirectory(tools/ld-export-metadata)
add_subdirectory(tools/ld-lds-converter)
add_subdirectory(tools/ld-process-efm)
add_subdirectory(tools/ld-process-vbi)
add_subdirectory(tools/ld-process-vits)

add_subdirectory(tools/ld-analyse)

# ld-ldf-reader executable
add_executable(${PROJECT_NAME} "ld-ldf-reader.c" )

target_link_libraries(${PROJECT_NAME} PkgConfig::LIBAV )
target_link_libraries(${PROJECT_NAME} ld-tbc)
target_link_libraries(${PROJECT_NAME} ld-filter)

install(TARGETS ${PROJECT_NAME} DESTINATION "")

set(OUTPUT ${CMAKE_CURRENT_BINARY_DIR})
set(DEPS "${CMAKE_CURRENT_SOURCE_DIR}/lddecode/__init__.py")

# install Python files

message( STATUS "--------- Installing Python files to ${OUTPUT} ---------")

find_program(PYTHON NAMES python python3)

add_custom_command(
  OUTPUT ${OUTPUT}/timestamp
  COMMAND ${PYTHON} "./setup.py" build
  COMMAND ${CMAKE_COMMAND} -E touch ${OUTPUT}/timestamp
  DEPENDS ${DEPS}
)

add_custom_target(target ALL DEPENDS ${OUTPUT}/timestamp)
