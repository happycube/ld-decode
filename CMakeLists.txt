message( STATUS "---------Beginning cmake build of ld-ldf-reader---------")

cmake_minimum_required( VERSION 3.16 )
project(ld-ldf-reader)

#list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_LIST_DIR}/cmake_modules")

set(CMAKE_INCLUDE_CURRENT_DIR ON)

set(CMAKE_CXX_STANDARD 17)

# Include all the paths
message( STATUS "--------- Finding packages---------")

# Set up AUTOMOC and some sensible defaults for runtime executionGui
# When using Qt 6.3, you can replace the code block below with
#qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)
include(GNUInstallDirs)
set(CMAKE_AUTOUIC ON)

find_library(QWT_LIBRARY_RELEASE NAMES qwt qwt-qt5 qt5-qwt PATH_SUFFIXES lib)
find_package(QT NAMES Qt5 Qt6 REQUIRED COMPONENTS Core Gui Widgets)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core Gui Widgets)

find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET
    libavcodec
    libavformat
    libavutil
    fftw3
)

# Get the current working branch
execute_process(
	COMMAND git rev-parse --abbrev-ref HEAD
	WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
	OUTPUT_VARIABLE GIT_BRANCH
	OUTPUT_STRIP_TRAILING_WHITESPACE
)

# Get the latest abbreviated commit hash of the working branch
execute_process(
	COMMAND git log -1 --format=%h
	WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
	OUTPUT_VARIABLE GIT_COMMIT_HASH
	OUTPUT_STRIP_TRAILING_WHITESPACE
)

# Pass it on to the source code
add_compile_definitions(APP_BRANCH)#=${GIT_BRANCH})
add_compile_definitions(APP_COMMIT)#=${GIT_COMMIT_HASH})

message( STATUS "--------- Git branch: ${GIT_BRANCH} ---------")
message( STATUS "--------- Git commit: ${GIT_COMMIT_HASH} ---------")

# Make the library
add_subdirectory(tools/library)

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

install(TARGETS ${PROJECT_NAME} DESTINATION "")

set(OUTPUT ${CMAKE_CURRENT_BINARY_DIR})
set(DEPS "${CMAKE_CURRENT_SOURCE_DIR}/lddecode/__init__.py")

# install Python files (there might be a better way to do it)

message( STATUS "--------- Installing Python files to ${OUTPUT} ---------")

find_package(Python3 3.6 REQUIRED COMPONENTS Interpreter)

add_custom_command(
  OUTPUT ${OUTPUT}/timestamp
  COMMAND ${PYTHON} "./setup.py" build
  COMMAND ${CMAKE_COMMAND} -E touch ${OUTPUT}/timestamp
  DEPENDS ${DEPS}
)

add_custom_target(target ALL DEPENDS ${OUTPUT}/timestamp)
