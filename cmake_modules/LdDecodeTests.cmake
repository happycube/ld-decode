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
set_tests_properties(decode-ntsc-basic PROPERTIES FIXTURES_SETUP ntsc-tbc)

# Test that ld-decode can decode PAL files and produce TBC output
add_test(
    NAME decode-pal-basic
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --PAL
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-basic
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-basic PROPERTIES FIXTURES_SETUP pal-tbc)

# Threaded decode (-t) runs block demodulation on a prefetching thread
# pool; the computation is identical per block, so the output must be
# bit-identical to the serial decode.  Any divergence is a real
# concurrency bug (stale cache entry, shared-state race).
add_test(
    NAME decode-ntsc-parallel
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode -t 8
        ${TESTDATA_DIR}/ntsc/ve-snw-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-parallel
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-ntsc-parallel PROPERTIES FIXTURES_SETUP ntsc-parallel)

add_test(
    NAME decode-pal-parallel
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode -t 8 --PAL
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-parallel
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-parallel PROPERTIES FIXTURES_SETUP pal-parallel)

foreach(ext tbc pcm efm)
    add_test(
        NAME compare-ntsc-parallel-${ext}
        COMMAND ${CMAKE_COMMAND} -E compare_files
            ${CMAKE_BINARY_DIR}/testout/ntsc-parallel.${ext}
            ${CMAKE_BINARY_DIR}/testout/ntsc-basic.${ext}
    )
    set_tests_properties(compare-ntsc-parallel-${ext} PROPERTIES
        FIXTURES_REQUIRED "ntsc-parallel;ntsc-tbc")
endforeach()

foreach(ext tbc efm)
    add_test(
        NAME compare-pal-parallel-${ext}
        COMMAND ${CMAKE_COMMAND} -E compare_files
            ${CMAKE_BINARY_DIR}/testout/pal-parallel.${ext}
            ${CMAKE_BINARY_DIR}/testout/pal-basic.${ext}
    )
    set_tests_properties(compare-pal-parallel-${ext} PROPERTIES
        FIXTURES_REQUIRED "pal-parallel;pal-tbc")
endforeach()

# Verify test patterns in the decoded output.  The analyzer detects which
# patterns are present (line 19 VITS, staircase, colour bars, PAL ITS) and
# only measures those; the pass regex asserts the patterns this test disc
# is known to carry were detected and measured.
add_test(
    NAME analyze-ntsc-patterns
    COMMAND ${Python3_EXECUTABLE} ${SCRIPTS_DIR}/differential_phase.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-basic.tbc
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(analyze-ntsc-patterns PROPERTIES
    FIXTURES_REQUIRED ntsc-tbc
    PASS_REGULAR_EXPRESSION "Line 19 VITS \\(70 IRE bar\\): first fields"
)

# CVBS output mode: decode to spec-compliant .composite/.meta and verify
# against cvbs-file-format-specification (exact frame sizing, protected
# values, sync lattice, metadata, WAV audio).
add_test(
    NAME decode-ntsc-cvbs
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --cvbs -l 6
        ${TESTDATA_DIR}/ntsc/ve-snw-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-ntsc-cvbs PROPERTIES FIXTURES_SETUP ntsc-cvbs)

add_test(
    NAME verify-ntsc-cvbs
    COMMAND ${Python3_EXECUTABLE} ${SCRIPTS_DIR}/cvbs_verify.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs.composite
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(verify-ntsc-cvbs PROPERTIES
    FIXTURES_REQUIRED ntsc-cvbs
    PASS_REGULAR_EXPRESSION "CVBS VERIFY: PASS"
)

# PAL CVBS exercises the non-line-locked 4fsc lattice (1135.0064
# samples/line, 4-sample slip per 709,379-sample frame).
add_test(
    NAME decode-pal-cvbs
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --cvbs --PAL -l 6
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-cvbs PROPERTIES FIXTURES_SETUP pal-cvbs)

add_test(
    NAME verify-pal-cvbs
    COMMAND ${Python3_EXECUTABLE} ${SCRIPTS_DIR}/cvbs_verify.py
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs.composite
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(verify-pal-cvbs PROPERTIES
    FIXTURES_REQUIRED pal-cvbs
    PASS_REGULAR_EXPRESSION "CVBS VERIFY: PASS"
)

# Round-trip through decode-orc's chroma decoder: renders one frame from
# the CVBS output and one from the TBC output through the same sink and
# asserts they match (parity-balanced diff, zero shift).  This is the
# check that catches field-placement geometry errors the analysis-only
# checks cannot see.  Skips when orc-cli is not installed (ORC_CLI env
# var or ~/ld-decode/decode-orc/result/bin/orc-cli).
add_test(
    NAME roundtrip-ntsc-orc
    COMMAND ${Python3_EXECUTABLE} ${SCRIPTS_DIR}/cvbs_orc_roundtrip.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs
        ${CMAKE_BINARY_DIR}/testout/ntsc-basic
        NTSC
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(roundtrip-ntsc-orc PROPERTIES
    FIXTURES_REQUIRED "ntsc-cvbs;ntsc-tbc"
    PASS_REGULAR_EXPRESSION "ORC ROUNDTRIP: PASS"
    SKIP_REGULAR_EXPRESSION "ORC ROUNDTRIP: SKIPPED"
)

add_test(
    NAME roundtrip-pal-orc
    COMMAND ${Python3_EXECUTABLE} ${SCRIPTS_DIR}/cvbs_orc_roundtrip.py
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs
        ${CMAKE_BINARY_DIR}/testout/pal-basic
        PAL
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(roundtrip-pal-orc PROPERTIES
    FIXTURES_REQUIRED "pal-cvbs;pal-tbc"
    PASS_REGULAR_EXPRESSION "ORC ROUNDTRIP: PASS"
    SKIP_REGULAR_EXPRESSION "ORC ROUNDTRIP: SKIPPED"
)

# The NTSC test disc carries broadcast-style NTC-7 VITS: composite on first
# fields, combination (multiburst + modulated pedestal) on second fields.
add_test(
    NAME analyze-ntsc-ntc7
    COMMAND ${Python3_EXECUTABLE} ${SCRIPTS_DIR}/differential_phase.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-basic.tbc
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(analyze-ntsc-ntc7 PROPERTIES
    FIXTURES_REQUIRED ntsc-tbc
    PASS_REGULAR_EXPRESSION "NTC-7 combination \\(line 20, 6-packet multiburst \\+ modulated pedestal\\): second fields"
)

add_test(
    NAME analyze-pal-patterns
    COMMAND ${Python3_EXECUTABLE} ${SCRIPTS_DIR}/differential_phase.py
        ${CMAKE_BINARY_DIR}/testout/pal-basic.tbc
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(analyze-pal-patterns PROPERTIES
    FIXTURES_REQUIRED pal-tbc
    PASS_REGULAR_EXPRESSION "ITS staircase with chroma"
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
