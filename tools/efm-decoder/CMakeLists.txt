cmake_minimum_required(VERSION 3.10)

# Set the project name
project(efm-tools)

# Specify the C++ standard
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Get the Git branch and revision
execute_process(
    COMMAND git rev-parse --abbrev-ref HEAD
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_BRANCH
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
execute_process(
    COMMAND git log -1 --format=%h
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_COMMIT_HASH
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
add_compile_definitions(APP_BRANCH=\"${GIT_BRANCH}\")
add_compile_definitions(APP_COMMIT=\"${GIT_COMMIT_HASH}\")

# Add subdirectories
add_subdirectory(libs/efm)
add_subdirectory(tools/efm-decoder-f2)
add_subdirectory(tools/efm-decoder-d24)
add_subdirectory(tools/efm-decoder-audio)
add_subdirectory(tools/efm-decoder-data)
add_subdirectory(tools/efm-stacker-f2)
add_subdirectory(tools/vfs-verifier)