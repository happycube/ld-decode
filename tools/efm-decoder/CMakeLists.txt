cmake_minimum_required(VERSION 3.10)

# Set the project name
project(efm-tools)

# Handle Qt version selection - default to Qt5 for backward compatibility
if(NOT DEFINED USE_QT_VERSION)
    set(USE_QT_VERSION 5)
endif()

# Find Qt components based on version
if(USE_QT_VERSION EQUAL 6)
    find_package(Qt6 REQUIRED COMPONENTS Core Widgets)
    # Create aliases for compatibility
    if(NOT TARGET Qt::Core AND TARGET Qt6::Core)
        add_library(Qt::Core ALIAS Qt6::Core)
    endif()
    if(NOT TARGET Qt::Widgets AND TARGET Qt6::Widgets)
        add_library(Qt::Widgets ALIAS Qt6::Widgets)
    endif()
    set(QT_VERSION_MAJOR 6)
else()
    find_package(Qt5 REQUIRED COMPONENTS Core Widgets)
    # Create aliases for modern CMake target names
    if(NOT TARGET Qt::Core AND TARGET Qt5::Core)
        add_library(Qt::Core ALIAS Qt5::Core)
    endif()
    if(NOT TARGET Qt::Widgets AND TARGET Qt5::Widgets)
        add_library(Qt::Widgets ALIAS Qt5::Widgets)
    endif()
    set(QT_VERSION_MAJOR 5)
endif()

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