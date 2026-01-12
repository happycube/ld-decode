cmake_minimum_required(VERSION 3.16)

# Enforce out-of-source builds before project() to catch issues early
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
    message(FATAL_ERROR "In-source builds are not allowed. Please create a build directory and run:
    mkdir build
    cd build
    cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..")
endif()

# Also prevent building directly in subdirectories of the source tree
# Exception: Allow 'build' and 'build-*' directories as they are gitignored
get_filename_component(REAL_SOURCE_DIR "${CMAKE_SOURCE_DIR}" REALPATH)
get_filename_component(REAL_BINARY_DIR "${CMAKE_BINARY_DIR}" REALPATH)
get_filename_component(BUILD_DIR_NAME "${CMAKE_BINARY_DIR}" NAME)
file(RELATIVE_PATH REL_PATH "${REAL_SOURCE_DIR}" "${REAL_BINARY_DIR}")

# Check if build directory is inside source tree (rel path doesn't start with ..)
# but allow 'build' or 'build-*' directory names
if(NOT REL_PATH MATCHES "^\\.\\." AND 
   NOT BUILD_DIR_NAME STREQUAL "build" AND 
   NOT BUILD_DIR_NAME MATCHES "^build-")
    message(FATAL_ERROR "Building within the source tree (except 'build/' or 'build-*/') is not allowed.
    Build directory: ${REAL_BINARY_DIR}
    Source directory: ${REAL_SOURCE_DIR}
    
    Please use one of these approaches:
    
    1. Standard build directory (recommended):
       mkdir build
       cd build
       cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
    
    2. Named build directory:
       mkdir build-release
       cd build-release
       cmake -DCMAKE_BUILD_TYPE=Release ..
    
    3. Out-of-tree build:
       mkdir ../ld-decode-build
       cd ../ld-decode-build
       cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ../ld-decode")
endif()

project(ld-decode-tools)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_LIST_DIR}/cmake_modules")
include(CTest)

set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Options that can be specified with -D



# Needed for ezpwd as it uses alternative operators
if(MSVC)
    add_compile_options(/permissive-)
endif()

option(BUILD_LDF_READER
    "build ld_ldf_reader"
    ON
)

option(BUILD_PYTHON
    "Build and install ld-decode's Python library and tools"
    ON
)

# Check for dependencies

# When using Qt 6.3, you can replace the code block below with qt_standard_project_setup()
set(CMAKE_AUTOMOC ON)
include(GNUInstallDirs)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Sql)
message(STATUS "Qt Version: ${QT_VERSION}")

find_package(PkgConfig REQUIRED)

if(NOT MSVC)
    pkg_check_modules(FFTW IMPORTED_TARGET fftw3)
    if(FFTW_FOUND)
        # .....
        set(FFTW_INCLUDE_DIR ${FFTW_INCLUDE_DIRS})
        set(FFTW_LIBRARY PkgConfig::FFTW)
    else()
        find_package(FFTW REQUIRED)
    endif()
else()
    # pkg-config seems to
    # result in trying to link to m.lib
    # which breaks build on
    # MSVC, so just use the cmake.config from
    # the vcpkg install instead.
    find_package(FFTW3 REQUIRED)
    set(FFTW_INCLUDE_DIR ${FFTW3_INCLUDE_DIRS})
    find_library(FFTW_LIBRARY ${FFTW3_LIBRARIES} ${FFTW3_LIBRARY_DIRS})
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

# Subdirectories

add_subdirectory(tools/ld-analyse)
add_subdirectory(tools/ld-chroma-decoder)
add_subdirectory(tools/ld-chroma-decoder/encoder)
add_subdirectory(tools/ld-disc-stacker)
add_subdirectory(tools/ld-discmap)
add_subdirectory(tools/ld-dropout-correct)
add_subdirectory(tools/ld-export-decode-metadata)
add_subdirectory(tools/ld-export-metadata)
add_subdirectory(tools/ld-json-converter)
add_subdirectory(tools/ld-lds-converter)
add_subdirectory(tools/ld-process-vbi)
add_subdirectory(tools/ld-process-vits)
add_subdirectory(tools/library)
add_subdirectory(tools/efm-decoder)

if(BUILD_TESTING)
    add_subdirectory(tools/library/filter/testfilter)
    add_subdirectory(tools/library/tbc/testlinenumber)
    add_subdirectory(tools/library/tbc/testmetadata)
    add_subdirectory(tools/library/tbc/testvbidecoder)
    add_subdirectory(tools/library/tbc/testvitcdecoder)
    include(LdDecodeTests)
endif()

if(BUILD_LDF_READER)
    add_subdirectory(tools/ld-ldf-reader)
endif()

# Python library and tools

if(BUILD_PYTHON)
    find_package(Python3 3.6 REQUIRED COMPONENTS Interpreter)

    set(PYTHON_BUILD_DIR ${CMAKE_CURRENT_BINARY_DIR}/python-build)

    # python setup.py install seems to behave differently if prefix
    # is supplied, requiring setting pythonpath after install.
    # If a custom prefix is not set, don't supply prefix at allocate_lock
    # /usr/local is the default on linux.
    # Install not really tested on windows as of yet.
    if(${CMAKE_INSTALL_PREFIX} STREQUAL "/usr/local")
        set(PYTHON_PREFIX_LINE "")
    else()
        message(STATUS "Custom install prefix supplied - you may have to manually specify PYTHONPATH")
        set(PYTHON_PREFIX_LINE "--prefix ${CMAKE_INSTALL_PREFIX}")
    endif()

    # Build Python package during make (as user, not root)
    add_custom_target(python-build ALL
        COMMAND ${CMAKE_COMMAND} -E make_directory ${PYTHON_BUILD_DIR}
        COMMAND ${PYTHON} ./setup.py --quiet
            build --build-base ${PYTHON_BUILD_DIR}
            egg_info --egg-base ${CMAKE_CURRENT_BINARY_DIR}
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        COMMENT "Building Python package"
    )

    # Install only - reuses build artifacts from python-build target
    install(CODE "
        if(NOT DEFINED ENV{DESTDIR})
            set(ENV{DESTDIR} /)
        endif()
        message(STATUS \"Installing Python package\")
        execute_process(
            COMMAND ${PYTHON} ./setup.py --quiet
                build --build-base ${PYTHON_BUILD_DIR}
                egg_info --egg-base ${CMAKE_CURRENT_BINARY_DIR}
                install ${PYTHON_PREFIX_LINE}
                        --root \$ENV{DESTDIR}
                        --skip-build
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            RESULT_VARIABLE _install_result
        )
        if(NOT _install_result EQUAL 0)
            message(FATAL_ERROR \"Python package installation failed\")
        endif()
    ")
endif()
