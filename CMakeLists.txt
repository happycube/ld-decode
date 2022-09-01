cmake_minimum_required(VERSION 3.16)

project(ld-decode-tools)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_LIST_DIR}/cmake_modules")
include(CTest)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Check for dependencies

# When using Qt 6.3, you can replace the code block below with qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)
include(GNUInstallDirs)
set(CMAKE_AUTOUIC ON)

find_package(QT NAMES Qt5 Qt6 REQUIRED COMPONENTS Core)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Gui Widgets)
message(STATUS "Qt Version: ${QT_VERSION}")

# For Qt < 5.15, emulate 5.15's Qt5CoreConfig.cmake, so we don't have to
# specify Qt5/Qt6 elsewhere.
if(QT_VERSION VERSION_LESS 5.15)
    function(qt_add_resources outfiles)
        qt5_add_resources("${outfiles}" ${ARGN})
        set("${outfiles}" "${${outfiles}}" PARENT_SCOPE)
    endfunction()
    foreach(library Core Gui Widgets)
        add_library(Qt::${library} INTERFACE IMPORTED)
        set_target_properties(Qt::${library} PROPERTIES
            INTERFACE_LINK_LIBRARIES "Qt5::${library}")
    endforeach()
endif()

find_package(PkgConfig REQUIRED)

find_package(Qwt REQUIRED)

pkg_check_modules(LIBAV REQUIRED IMPORTED_TARGET
    libavcodec
    libavformat
    libavutil
)
pkg_check_modules(FFTW REQUIRED IMPORTED_TARGET
    fftw3
)

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

# Subdirectories

add_subdirectory(tools/ld-analyse)
add_subdirectory(tools/ld-chroma-decoder)
add_subdirectory(tools/ld-chroma-decoder/encoder)
add_subdirectory(tools/ld-disc-stacker)
add_subdirectory(tools/ld-discmap)
add_subdirectory(tools/ld-dropout-correct)
add_subdirectory(tools/ld-export-metadata)
add_subdirectory(tools/ld-lds-converter)
add_subdirectory(tools/ld-process-efm)
add_subdirectory(tools/ld-process-vbi)
add_subdirectory(tools/ld-process-vits)
add_subdirectory(tools/library)

if(BUILD_TESTING)
    add_subdirectory(tools/library/filter/testfilter)
    add_subdirectory(tools/library/tbc/testlinenumber)
    add_subdirectory(tools/library/tbc/testmetadata)
    add_subdirectory(tools/library/tbc/testvbidecoder)
    include(LdDecodeTests)
endif()

# ld-ldf-reader

add_executable(ld-ldf-reader
    ld-ldf-reader.c)

target_link_libraries(ld-ldf-reader PkgConfig::LIBAV)

install(TARGETS ld-ldf-reader)

# Python library and tools

find_package(Python3 3.6 REQUIRED COMPONENTS Interpreter)

set(OUTPUT ${CMAKE_CURRENT_BINARY_DIR})
set(DEPS ${CMAKE_CURRENT_SOURCE_DIR}/lddecode/__init__.py)

if(0)
    # XXX There must be a better way to do this!
    # XXX This doesn't work when building in a separate object directory
    add_custom_command(
        OUTPUT ${OUTPUT}/timestamp
        COMMAND ${PYTHON} ./setup.py build
        COMMAND ${CMAKE_COMMAND} -E touch ${OUTPUT}/timestamp
        DEPENDS ${DEPS}
    )

    add_custom_target(target ALL DEPENDS ${OUTPUT}/timestamp)
endif()

# XXX Install rule for Python
