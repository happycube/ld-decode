# Functional tests for ld-decode Python tools
#
# These tests verify that ld-decode can correctly ingest PAL and NTSC files,
# producing expected output (TBC, metadata, audio, etc.)
#
# Most tests expect the ld-decode-testdata repo within the source directory as "testdata".

set(SCRIPTS_DIR ${CMAKE_SOURCE_DIR}/scripts)
set(TESTDATA_DIR ${CMAKE_SOURCE_DIR}/testdata)

# Test that ld-decode can decode NTSC files and produce TBC output
add_test(
    NAME decode-ntsc-basic
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        ${TESTDATA_DIR}/ntsc/ve-snw-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-basic
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)

# Test that ld-decode can decode PAL files and produce TBC output
add_test(
    NAME decode-pal-basic
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --PAL
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-basic
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)

# Test that ld-cut can extract a segment from NTSC file
add_test(
    NAME cut-ntsc-segment
    COMMAND ${CMAKE_SOURCE_DIR}/ld-cut
        -S 30255 -l 4
        ${TESTDATA_DIR}/ntsc/ve-snw-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-cut.ldf
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(cut-ntsc-segment PROPERTIES TIMEOUT 120)

# Test that ld-cut can extract a segment from PAL file
add_test(
    NAME cut-pal-segment
    COMMAND ${CMAKE_SOURCE_DIR}/ld-cut
        --pal -S 760 -l 4
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-cut.ldf
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(cut-pal-segment PROPERTIES TIMEOUT 120)

# Test decode of NTSC cut segment
add_test(
    NAME decode-ntsc-cut
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        ${CMAKE_BINARY_DIR}/testout/ntsc-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-cut-decoded
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-ntsc-cut PROPERTIES DEPENDS cut-ntsc-segment)

# Test decode of PAL cut segment
add_test(
    NAME decode-pal-cut
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --PAL
        ${CMAKE_BINARY_DIR}/testout/pal-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-cut-decoded
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-cut PROPERTIES DEPENDS cut-pal-segment)
