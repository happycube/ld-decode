cmake_minimum_required(VERSION 3.16)
project(ld-decode)

# Enable testing
include(CTest)

# Find Python
find_package(Python3 3.6 REQUIRED COMPONENTS Interpreter)

# Generate version file
#
# The base version is read from flake.nix (`version = "..."`), which is the
# single source of truth for the release version; git supplies the branch,
# short commit and dirty state.  Output format (consumed by lddecode/__init__.py,
# decoder.build_sqlite_metadata() and cvbs._write_meta()):
#     branch:base_version+git.<shortrev>[:dirty]
function(generate_version_file)
    set(VERSION_FILE "${CMAKE_SOURCE_DIR}/lddecode/version")

    set(BRANCH "release")
    set(BASE_VERSION "")
    set(SHORTREV "unknown")
    set(DIRTY "")

    # Base version: read from flake.nix; fall back to an exact git tag.
    if(EXISTS "${CMAKE_SOURCE_DIR}/flake.nix")
        file(READ "${CMAKE_SOURCE_DIR}/flake.nix" FLAKE_NIX)
        string(REGEX MATCH "version = \"([^\"]+)\"" _ "${FLAKE_NIX}")
        if(CMAKE_MATCH_1)
            set(BASE_VERSION "${CMAKE_MATCH_1}")
        endif()
    endif()

    # Check if we're in a git repository
    if(EXISTS "${CMAKE_SOURCE_DIR}/.git")
        if(NOT BASE_VERSION)
            execute_process(
                COMMAND git describe --tags --exact-match
                WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
                OUTPUT_VARIABLE GIT_TAG
                ERROR_QUIET
                OUTPUT_STRIP_TRAILING_WHITESPACE
            )

            if(GIT_TAG)
                # Remove 'v' prefix if present
                string(REGEX REPLACE "^v" "" BASE_VERSION "${GIT_TAG}")
            endif()
        endif()

        execute_process(
            COMMAND git rev-parse --short HEAD
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
            OUTPUT_VARIABLE SHORTREV
            ERROR_QUIET
            OUTPUT_STRIP_TRAILING_WHITESPACE
        )

        # Get branch name
        execute_process(
            COMMAND git rev-parse --abbrev-ref HEAD
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
            OUTPUT_VARIABLE GIT_BRANCH
            ERROR_QUIET
            OUTPUT_STRIP_TRAILING_WHITESPACE
        )

        if(GIT_BRANCH AND NOT GIT_BRANCH STREQUAL "HEAD")
            set(BRANCH "${GIT_BRANCH}")
        endif()

        # Check if dirty
        execute_process(
            COMMAND git status --porcelain
            WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
            OUTPUT_VARIABLE GIT_STATUS
            ERROR_QUIET
            OUTPUT_STRIP_TRAILING_WHITESPACE
        )

        if(GIT_STATUS)
            set(DIRTY ":dirty")
        endif()
    endif()

    if(NOT BASE_VERSION)
        set(BASE_VERSION "unknown")
    endif()

    # Generate version string
    set(VERSION_STRING "${BRANCH}:${BASE_VERSION}+git.${SHORTREV}${DIRTY}")

    # Write to version file
    file(WRITE "${VERSION_FILE}" "${VERSION_STRING}\n")

    message(STATUS "Generated version file: ${VERSION_STRING}")
endfunction()

# Generate version file during configuration
generate_version_file()

# Include test definitions
include(cmake_modules/LdDecodeTests.cmake)
