# Test registration for ld-decode.
#
# CTest is the outer driver.  Its labels mirror the pytest markers so the same
# slice can be requested from either side (see TESTING.md):
#
#   unit        The hermetic pytest lane (tests/unit/).  No capture data, no
#               external tools, no subprocesses.  Runs in seconds.
#   functional  Decode, comparison, analysis, cut and compress tests over
#               testdata/, plus the pytest suites that need real data.
#   slow        Functional tests exceeding roughly 60 s.
#
#   ctest -L unit --output-on-failure          # while iterating
#   ctest -L functional --output-on-failure    # the contracts
#
# Every test below carries exactly one of "unit" or "functional" and an
# explicit TIMEOUT, so a hang fails the run rather than stalling it.
#
# Tests that produce inputs for other tests declare FIXTURES_SETUP; consumers
# declare FIXTURES_REQUIRED.  That is what makes a filtered run (ctest -R)
# build what it needs instead of reading a stale or missing artefact.
#
# Fixtures defined here, as "name  producer -> consumers":
#   ntsc-tbc            decode-ntsc-basic         -> compare-ntsc-parallel-*,
#                                                    roundtrip-ntsc-orc
#   pal-tbc             decode-pal-basic          -> compare-pal-parallel-*,
#                                                    roundtrip-pal-orc
#   ntsc-parallel       decode-ntsc-parallel      -> compare-ntsc-parallel-*
#   pal-parallel        decode-pal-parallel       -> compare-pal-parallel-*
#   ntsc-cvbs           decode-ntsc-cvbs          -> verify-ntsc-cvbs,
#                                                    analyze-ntsc-patterns,
#                                                    analyze-ntsc-ntc7,
#                                                    identify-ntsc-vits,
#                                                    conformance-ntsc-vits,
#                                                    roundtrip-ntsc-orc
#   pal-cvbs            decode-pal-cvbs           -> verify-pal-cvbs,
#                                                    analyze-pal-patterns,
#                                                    identify-pal-vits,
#                                                    conformance-pal-vits,
#                                                    compare-pal-cvbs-parallel-*,
#                                                    roundtrip-pal-orc
#   pal-cvbs-parallel   decode-pal-cvbs-parallel  -> compare-pal-cvbs-parallel-*
#   ntsc-cut-ldf        cut-ntsc-segment          -> decode-ntsc-cut
#   pal-cut-ldf         cut-pal-segment           -> decode-pal-cut
#   ntsc-cut-lds        cut-ntsc-lds              -> decode-ntsc-lds,
#                                                    roundtrip-lds-bytes,
#                                                    compress-lds-round-trip
#
# No test both sets up and requires a fixture, so "ctest -R <name>" pulls in
# exactly the producers listed above and nothing else.
#
# Most tests expect the ld-decode-testdata repo within the source directory as
# "testdata".

set(ANALYSIS_DIR ${CMAKE_SOURCE_DIR}/analysis)
set(TESTDATA_DIR ${CMAKE_SOURCE_DIR}/testdata)

# Every decode below writes here.  Created at configure time so that "ctest"
# in a fresh build directory works on its own; the CI workflows' "mkdir -p
# build/testout" predates this and is now redundant rather than required.
file(MAKE_DIRECTORY ${CMAKE_BINARY_DIR}/testout)

# ---------------------------------------------------------------------------
# pytest lanes
# ---------------------------------------------------------------------------

# The fast lane.  Invoked as "python -m pytest" so the working tree is used
# rather than any installed copy of lddecode.  It runs tests/unit/ only, which
# is what keeps it hermetic: it must pass with the testdata submodule absent
# and no external tools installed.
add_test(
    NAME python-unit-tests
    COMMAND ${Python3_EXECUTABLE} -m pytest -q ${CMAKE_SOURCE_DIR}/tests/unit
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(python-unit-tests PROPERTIES
    LABELS "unit"
    TIMEOUT 300
)

# The pytest suites that need real capture data or an external tool.  Guarded
# on the directory being populated so configuring against a tree where the
# lane is still empty does not register a test that collects nothing.
file(GLOB PYTEST_FUNCTIONAL_SUITES CONFIGURE_DEPENDS
    ${CMAKE_SOURCE_DIR}/tests/functional/test_*.py)

if(PYTEST_FUNCTIONAL_SUITES)
    add_test(
        NAME python-functional-tests
        COMMAND ${Python3_EXECUTABLE} -m pytest -q ${CMAKE_SOURCE_DIR}/tests/functional
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
    set_tests_properties(python-functional-tests PROPERTIES
        LABELS "functional;slow"
        TIMEOUT 1800
    )
endif()

# Suites still sitting directly in tests/, not yet sorted into a lane.  They
# are run as "functional" because the set includes suites that shell out and
# suites that read testdata/, and running them all in the fast lane is exactly
# what the split above exists to stop.  This entry disappears on its own once
# tests/ holds no test_*.py of its own.
file(GLOB PYTEST_UNSORTED_SUITES CONFIGURE_DEPENDS
    ${CMAKE_SOURCE_DIR}/tests/test_*.py)

if(PYTEST_UNSORTED_SUITES)
    add_test(
        NAME python-unsorted-tests
        COMMAND ${Python3_EXECUTABLE} -m pytest -q ${PYTEST_UNSORTED_SUITES}
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
    set_tests_properties(python-unsorted-tests PROPERTIES
        LABELS "functional;slow"
        TIMEOUT 1800
    )
endif()

# ---------------------------------------------------------------------------
# Decode contracts
# ---------------------------------------------------------------------------

# Test that ld-decode can decode NTSC files and produce TBC output
# (CVBS is the default output; --tbc selects the legacy path these
# comparison and analysis fixtures are built on)
add_test(
    NAME decode-ntsc-basic
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --tbc
        ${TESTDATA_DIR}/ntsc/ve-snw-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-basic
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-ntsc-basic PROPERTIES
    LABELS "functional;slow"
    FIXTURES_SETUP ntsc-tbc
    TIMEOUT 1800
)

# Test that ld-decode can decode PAL files and produce TBC output
add_test(
    NAME decode-pal-basic
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --tbc --PAL
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-basic
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-basic PROPERTIES
    LABELS "functional;slow"
    FIXTURES_SETUP pal-tbc
    TIMEOUT 1800
)

# Threaded decode (-t) must be bit-identical to the serial decode; any
# divergence is a real concurrency bug (stale cache entry, shared-state
# race, speculation accepted wrongly).  --exact-speculation pins the
# strict acceptance rules so the comparison holds even across mid-run
# parameter adoptions.
add_test(
    NAME decode-ntsc-parallel
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode --tbc -t 8 --exact-speculation
        ${TESTDATA_DIR}/ntsc/ve-snw-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-parallel
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-ntsc-parallel PROPERTIES
    LABELS "functional;slow"
    FIXTURES_SETUP ntsc-parallel
    TIMEOUT 1800
)

add_test(
    NAME decode-pal-parallel
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode --tbc -t 8 --PAL --exact-speculation
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-parallel
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-parallel PROPERTIES
    LABELS "functional;slow"
    FIXTURES_SETUP pal-parallel
    TIMEOUT 1800
)

foreach(ext tbc pcm efm)
    add_test(
        NAME compare-ntsc-parallel-${ext}
        COMMAND ${CMAKE_COMMAND} -E compare_files
            ${CMAKE_BINARY_DIR}/testout/ntsc-parallel.${ext}
            ${CMAKE_BINARY_DIR}/testout/ntsc-basic.${ext}
    )
    set_tests_properties(compare-ntsc-parallel-${ext} PROPERTIES
        LABELS "functional"
        FIXTURES_REQUIRED "ntsc-parallel;ntsc-tbc"
        TIMEOUT 120
    )
endforeach()

# The same three outputs as NTSC above.  Video, analogue audio and EFM each
# come off a separate path through the threaded decode, so a race in one
# would not show up in the others.
foreach(ext tbc pcm efm)
    add_test(
        NAME compare-pal-parallel-${ext}
        COMMAND ${CMAKE_COMMAND} -E compare_files
            ${CMAKE_BINARY_DIR}/testout/pal-parallel.${ext}
            ${CMAKE_BINARY_DIR}/testout/pal-basic.${ext}
    )
    set_tests_properties(compare-pal-parallel-${ext} PROPERTIES
        LABELS "functional"
        FIXTURES_REQUIRED "pal-parallel;pal-tbc"
        TIMEOUT 120
    )
endforeach()

# ---------------------------------------------------------------------------
# Signal-quality analysis
# ---------------------------------------------------------------------------

# Verify test patterns in the decoded output.  The analyzer detects which
# patterns are present (line 19 VITS, staircase, colour bars, PAL ITS) and
# only measures those; the pass regex asserts the patterns this test disc
# is known to carry were detected and measured.
#
# These run on the .cvbs output, not the .tbc: .cvbs is the format the
# measurement work is standardising on, and it is the only way CI exercises
# CVBS_U10_4FSC, the sample encoding ld-decode writes by default for PAL.
# Neither decode passes --cvbs-encoding, so each system is analysed in the
# encoding its users actually get.
add_test(
    NAME analyze-ntsc-patterns
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/differential_phase.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs.cvbs
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(analyze-ntsc-patterns PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED ntsc-cvbs
    PASS_REGULAR_EXPRESSION "Line 19 VITS \\(70 IRE bar\\): first fields"
    TIMEOUT 300
)

# ---------------------------------------------------------------------------
# CVBS format conformance
# ---------------------------------------------------------------------------

# CVBS output mode: decode to spec-compliant .cvbs/.meta and verify
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
set_tests_properties(decode-ntsc-cvbs PROPERTIES
    LABELS "functional;slow"
    FIXTURES_SETUP ntsc-cvbs
    TIMEOUT 1800
)

add_test(
    NAME verify-ntsc-cvbs
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/cvbs_verify.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs.cvbs
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(verify-ntsc-cvbs PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED ntsc-cvbs
    PASS_REGULAR_EXPRESSION "CVBS VERIFY: PASS"
    TIMEOUT 300
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
set_tests_properties(decode-pal-cvbs PROPERTIES
    LABELS "functional;slow"
    FIXTURES_SETUP pal-cvbs
    TIMEOUT 1800
)

add_test(
    NAME verify-pal-cvbs
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/cvbs_verify.py
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs.cvbs
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(verify-pal-cvbs PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED pal-cvbs
    PASS_REGULAR_EXPRESSION "CVBS VERIFY: PASS"
    TIMEOUT 300
)

# The CVBS writer sits on the output path, so a threaded decode has to
# produce the same file as a serial one.  PAL is the case worth spending a
# decode on: its 4fsc lattice is not line-locked (1135.0064 samples/line), so
# the writer carries a running sample slip that a threaded run could
# resynchronise differently.  The metadata sidecar is compared too - it
# records the per-frame lock state and sequence, which the threaded path
# could get wrong while the samples stayed right.
add_test(
    NAME decode-pal-cvbs-parallel
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --cvbs --PAL -l 6 -t 8 --exact-speculation
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs-parallel
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-cvbs-parallel PROPERTIES
    LABELS "functional;slow"
    FIXTURES_SETUP pal-cvbs-parallel
    TIMEOUT 1800
)

foreach(ext cvbs meta efm)
    add_test(
        NAME compare-pal-cvbs-parallel-${ext}
        COMMAND ${CMAKE_COMMAND} -E compare_files
            ${CMAKE_BINARY_DIR}/testout/pal-cvbs-parallel.${ext}
            ${CMAKE_BINARY_DIR}/testout/pal-cvbs.${ext}
    )
    set_tests_properties(compare-pal-cvbs-parallel-${ext} PROPERTIES
        LABELS "functional"
        FIXTURES_REQUIRED "pal-cvbs-parallel;pal-cvbs"
        TIMEOUT 120
    )
endforeach()

# In CVBS mode the analogue audio goes to a WAV sidecar rather than to .pcm,
# so it needs its own comparison rather than another pass of the loop above.
add_test(
    NAME compare-pal-cvbs-parallel-audio
    COMMAND ${CMAKE_COMMAND} -E compare_files
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs-parallel_audio_0.wav
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs_audio_0.wav
)
set_tests_properties(compare-pal-cvbs-parallel-audio PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED "pal-cvbs-parallel;pal-cvbs"
    TIMEOUT 120
)

# Round-trip through decode-orc's chroma decoder: renders one frame from
# the CVBS output and one from the TBC output through the same sink and
# asserts they match (parity-balanced diff, zero shift).  This is the
# check that catches field-placement geometry errors the analysis-only
# checks cannot see.  Skips when orc-cli is not installed (ORC_CLI env
# var or ~/ld-decode/decode-orc/result/bin/orc-cli).
add_test(
    NAME roundtrip-ntsc-orc
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/cvbs_orc_roundtrip.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs
        ${CMAKE_BINARY_DIR}/testout/ntsc-basic
        NTSC
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(roundtrip-ntsc-orc PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED "ntsc-cvbs;ntsc-tbc"
    PASS_REGULAR_EXPRESSION "ORC ROUNDTRIP: PASS"
    SKIP_REGULAR_EXPRESSION "ORC ROUNDTRIP: SKIPPED"
    TIMEOUT 600
)

add_test(
    NAME roundtrip-pal-orc
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/cvbs_orc_roundtrip.py
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs
        ${CMAKE_BINARY_DIR}/testout/pal-basic
        PAL
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(roundtrip-pal-orc PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED "pal-cvbs;pal-tbc"
    PASS_REGULAR_EXPRESSION "ORC ROUNDTRIP: PASS"
    SKIP_REGULAR_EXPRESSION "ORC ROUNDTRIP: SKIPPED"
    TIMEOUT 600
)

# The NTSC test disc carries broadcast-style NTC-7 VITS: composite on first
# fields, combination (multiburst + modulated pedestal) on second fields.
add_test(
    NAME analyze-ntsc-ntc7
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/differential_phase.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs.cvbs
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(analyze-ntsc-ntc7 PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED ntsc-cvbs
    PASS_REGULAR_EXPRESSION "NTC-7 combination \\(line 20, 6-packet multiburst \\+ modulated pedestal\\): second fields"
    TIMEOUT 300
)

add_test(
    NAME analyze-pal-patterns
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/differential_phase.py
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs.cvbs
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(analyze-pal-patterns PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED pal-cvbs
    PASS_REGULAR_EXPRESSION "ITS staircase with chroma"
    TIMEOUT 300
)

# VITS conformance: locate the test signals each disc carries and measure
# every element of them against analysis/vits_reference.py.  The identifier
# scores measured content, never the line number, so these also assert that
# a disc which moved its signal is still found where it actually is.
#
# The regexes pin the one claim per system that matters most; the rest of
# the behaviour is covered hermetically by tests/unit/test_vits_measure.py.
#
# IEC 60857-1986 9.1.3 makes the VIRS on lines 19 and 282 the only VITS any
# LaserDisc standard mandates, so that is what the NTSC disc is held to.
add_test(
    NAME identify-ntsc-vits
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/vits_identify.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs.cvbs
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(identify-ntsc-vits PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED ntsc-cvbs
    PASS_REGULAR_EXPRESSION "line +19 +ntsc-virs-field1"
    TIMEOUT 300
)

# The PAL disc (GGV) carries its multiburst on frame line 13, the
# alternative IEC 60856-1986 9.1.3 Amendment 2 permits, and carries the ITU
# frequency set rather than the IEC one.  Matching it on line 13 is only
# possible by content, which is what this asserts.
add_test(
    NAME identify-pal-vits
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/vits_identify.py
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs.cvbs
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(identify-pal-vits PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED pal-cvbs
    PASS_REGULAR_EXPRESSION "line +13 +pal-multiburst-field1"
    TIMEOUT 300
)

# VITS level and differential-level conformance.  Each check is judged
# against the specification's own tolerance plus the decoder allowance in
# analysis/vits_reference.py, and names the clause it enforces.  A JSON
# sidecar is written beside the capture for CI artefact upload.
#
# NTSC passes today.  PAL does not: its chrominance runs about 25% hot,
# which fails the chrominance levels, the saturation ceiling, the
# chrominance/luminance gain ratio and differential gain, and its multiburst
# loses the top of the band.  Those are real decoder faults, recorded in
# docs-planning/vits-conformance-testing-plan.md and scheduled for Phase 8.
#
# Rather than mark it WILL_FAIL, which would swallow a new PAL regression
# alongside the known ones, the PAL entry pins the exact failure count.
# CTest's PASS_REGULAR_EXPRESSION takes precedence over the exit status, so
# this passes on today's known-bad state and goes red both if PAL improves
# (update the count, or drop the pin once it reaches zero) and if it
# regresses.  Either way the change gets looked at.
add_test(
    NAME conformance-ntsc-vits
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/vits_conformance.py
        ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs.cvbs
        --json ${CMAKE_BINARY_DIR}/testout/ntsc-cvbs.conformance.json
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(conformance-ntsc-vits PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED ntsc-cvbs
    PASS_REGULAR_EXPRESSION "VITS CONFORMANCE: PASS"
    TIMEOUT 300
)

add_test(
    NAME conformance-pal-vits
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/vits_conformance.py
        ${CMAKE_BINARY_DIR}/testout/pal-cvbs.cvbs
        --json ${CMAKE_BINARY_DIR}/testout/pal-cvbs.conformance.json
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(conformance-pal-vits PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED pal-cvbs
    PASS_REGULAR_EXPRESSION "VITS CONFORMANCE: FAIL \\(13 of 37 checks failed"
    TIMEOUT 300
)

# Raw input-format coverage - converting the NTSC CI capture to .s16/.u16/
# .u8/.rf/.lds/.r30, reading each back exactly through make_loader, and
# decoding the packed conversions end-to-end - now runs as part of
# python-functional-tests above (tests/functional/test_input_formats.py).
# It needs no CTest entry of its own.

# ---------------------------------------------------------------------------
# ld-cut and ld-compress
# ---------------------------------------------------------------------------

# Test that ld-cut can extract a segment from NTSC file
add_test(
    NAME cut-ntsc-segment
    COMMAND ${CMAKE_SOURCE_DIR}/ld-cut
        -S 30255 -l 4
        ${TESTDATA_DIR}/ntsc/ve-snw-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-cut.ldf
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(cut-ntsc-segment PROPERTIES
    LABELS "functional"
    FIXTURES_SETUP ntsc-cut-ldf
    TIMEOUT 120
)

# Test that ld-cut can extract a segment from PAL file
add_test(
    NAME cut-pal-segment
    COMMAND ${CMAKE_SOURCE_DIR}/ld-cut
        --pal -S 760 -l 4
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-cut.ldf
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(cut-pal-segment PROPERTIES
    LABELS "functional"
    FIXTURES_SETUP pal-cut-ldf
    TIMEOUT 120
)

# Test decode of NTSC cut segment
add_test(
    NAME decode-ntsc-cut
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        ${CMAKE_BINARY_DIR}/testout/ntsc-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-cut-decoded
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-ntsc-cut PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED ntsc-cut-ldf
    TIMEOUT 600
)

# Test decode of PAL cut segment
add_test(
    NAME decode-pal-cut
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --PAL
        ${CMAKE_BINARY_DIR}/testout/pal-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/pal-cut-decoded
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-pal-cut PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED pal-cut-ldf
    TIMEOUT 600
)

# Test that ld-cut can write packed .lds output
add_test(
    NAME cut-ntsc-lds
    COMMAND ${CMAKE_SOURCE_DIR}/ld-cut
        -S 30255 -l 4
        ${TESTDATA_DIR}/ntsc/ve-snw-cut.ldf
        ${CMAKE_BINARY_DIR}/testout/ntsc-cut.lds
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(cut-ntsc-lds PROPERTIES
    LABELS "functional"
    FIXTURES_SETUP ntsc-cut-lds
    TIMEOUT 120
)

# Test that the .lds ld-cut produced is actually decodable
add_test(
    NAME decode-ntsc-lds
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        ${CMAKE_BINARY_DIR}/testout/ntsc-cut.lds
        ${CMAKE_BINARY_DIR}/testout/ntsc-lds-decoded
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-ntsc-lds PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED ntsc-cut-lds
    TIMEOUT 600
)

# The bare .lds converter must be lossless over real capture data: unpack to
# 16-bit, repack, and not a byte may change.  compress-lds-round-trip below
# drives the same packing through ld-compress, with flac and PyAV in between;
# this isolates the converter, so a failure names which of the two is at
# fault.
add_test(
    NAME roundtrip-lds-bytes
    COMMAND ${CMAKE_COMMAND}
        -DPYTHON=${Python3_EXECUTABLE}
        -DSOURCE_DIR=${CMAKE_SOURCE_DIR}
        -DSOURCE_LDS=${CMAKE_BINARY_DIR}/testout/ntsc-cut.lds
        -DWORK_DIR=${CMAKE_BINARY_DIR}/testout/lds-bytes-round-trip
        -P ${CMAKE_SOURCE_DIR}/cmake_modules/LdsBytesRoundTrip.cmake
)
set_tests_properties(roundtrip-lds-bytes PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED ntsc-cut-lds
    TIMEOUT 300
)

# Test that ld-compress can compress and uncompress a .lds file without
# changing a single byte.  flac is the one external program ld-compress still
# needs - everything else it does is in process - so skip if it is missing.
find_program(FLAC_EXECUTABLE NAMES flac)

if(FLAC_EXECUTABLE)
    add_test(
        NAME compress-lds-round-trip
        COMMAND ${CMAKE_COMMAND}
            -DPYTHON=${Python3_EXECUTABLE}
            -DLD_COMPRESS=${CMAKE_SOURCE_DIR}/ld-compress
            -DSOURCE_LDS=${CMAKE_BINARY_DIR}/testout/ntsc-cut.lds
            -DWORK_DIR=${CMAKE_BINARY_DIR}/testout/lds-round-trip
            -P ${CMAKE_SOURCE_DIR}/cmake_modules/LdsRoundTrip.cmake
    )
    set_tests_properties(compress-lds-round-trip PROPERTIES
        LABELS "functional"
        FIXTURES_REQUIRED ntsc-cut-lds
        TIMEOUT 300
    )
else()
    message(STATUS "Skipping compress-lds-round-trip test (flac not found)")
endif()
