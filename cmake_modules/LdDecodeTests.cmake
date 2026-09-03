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
#   vits        The VITS conformance sweep across disc radius, and the
#               decodes that feed it.  A subset of "functional", carried as
#               its own label so CI can run the sweep as a separate job.
#
#   ctest -L unit --output-on-failure          # while iterating
#   ctest -L functional --output-on-failure    # the contracts
#   ctest -L vits --output-on-failure          # the radius sweep alone
#   ctest -LE vits --output-on-failure         # everything but the sweep
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
#   jason-tbc           decode-jason-testpattern  -> efm-quality-jason-testpattern
#   jason-pll-tbc       decode-jason-pll          -> efm-quality-jason-pll,
#                                                    compare-jason-pll-parallel-*
#   jason-pll-parallel  decode-jason-pll-parallel -> compare-jason-pll-parallel-*
#   issue176-tbc        decode-issue176           -> efm-quality-issue176
#   ntsc-cut-ldf        cut-ntsc-segment          -> decode-ntsc-cut
#   pal-cut-ldf         cut-pal-segment           -> decode-pal-cut
#   ntsc-cut-lds        cut-ntsc-lds              -> decode-ntsc-lds,
#                                                    roundtrip-lds-bytes,
#                                                    compress-lds-round-trip
#   <cut>-cvbs          decode-<cut>-cvbs         -> conformance-<cut>-vits
#                                                    one pair per radius cut,
#                                                    and one per whole capture
#                                                    the conformance lane
#                                                    judges; see the sweep below
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
    # CVBS output defaults to the confidence-packed .efm (T_VALUE_CONF_U8),
    # so verify-ntsc-cvbs exercises the extension format's encoding
    # declaration and efm-quality-ntsc-cvbs scores with --packed.
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

# VITS level, differential-level and multiburst frequency-response
# conformance.  Each check is judged against the specification's own
# tolerance plus the decoder allowance in analysis/vits_reference.py, and
# names the clause it enforces.  A JSON sidecar is written beside the
# capture for CI artefact upload.
#
# NTSC passes today.  PAL does not, on six counts: it loses the top
# multiburst packet (-7.1 dB at 5.8 MHz, which also fails that packet's
# absolute level), leaves 1.1-1.4 IRE on the two lines the standard requires
# blanked, fails differential gain on the modulated staircase, and overshoots
# the second-field 2T pulse by 2.7 IRE against its own bar.  Those are real
# decoder faults, recorded in
# docs-planning/vits-conformance-testing-plan.md.
#
# The 2T overshoot is the newest and the most marginal: this capture is six
# fields, which is fewer than any of the servos needs to settle, so whichever
# loop moves last decides the pulse.  Publishing the multiburst's chroma-band
# ceiling on its own schedule (decoder.py _publish_imtf_flat_band) made that
# last mover the burst servo adopting a capped 0.200 after the 2T servo had
# already settled, and the pulse went from 0.83x of its band to 1.06x.  The
# same change recovers fourteen checks on the radius cut that motivated it
# and three more across the sweep, against this one and one other; see
# docs/technical/vits-servos.md.
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
    # 6 -> 5 with the two-sided inverse-MTF chroma bound: pulse_2t on the
    # second-field ITS came back inside its band.  The capture is six
    # frames, fewer than any servo needs to settle, so what remains is
    # packet_6 (twice), the two blanked-line checks, and single-field
    # differential gain (0.152 measured, noise-inflated - the pooled
    # figure on this capture is under the band).
    PASS_REGULAR_EXPRESSION "VITS CONFORMANCE: FAIL \\(5 of 46 checks failed"
    TIMEOUT 300
)

# ---------------------------------------------------------------------------
# VITS conformance across disc radius
# ---------------------------------------------------------------------------

# The modulation transfer function of a LaserDisc changes with radius, so a
# decoder can pass every conformance check at one radius and fail at another,
# and a suite that only ever sees one radius cannot tell a correct decoder
# from a decoder tuned to one part of one disc.  testdata/radius/ holds
# eighteen cuts - six discs at 5 %, 50 % and 95 % of their recorded band -
# plus domesday-ds1-community-north-outer, kept as a regression sample because
# its multiburst finds the chroma band already flat and so declines the video
# EQ servo's adoption, which is the path that once let the burst servo wind
# unbounded.  See docs/technical/vits-radius-baseline.md.
#
# The sixth disc and the second GGV1069 capture are there so that no gate
# rests on one disc image.  ggv1069-side1-ldv4300d-* is the same pressing as
# ggv1069-side1-* read on a different player years apart, which is the only
# way to separate a fault of the decoder from a fault of one capture;
# industrial-lv-side1-* is a non-Domesday PAL pressing, and the first in
# testdata/ carrying the PAL_MULTIBURST_IEC frequency set that
# analysis/vits_reference.py says real discs may use.
#
# Each cut is judged against testdata/vits-manifest.json, the surveyed record
# of what the disc carries, so a capture is only ever asked for the checks it
# can carry and a decode that loses a signal the disc has is a failure rather
# than a shorter report.  The faults the decoder is already known to have are
# listed in analysis/vits_known_deviations.toml and report KNOWN; that list
# fails the build the moment it stops being true, so this lane goes red for a
# new fault while carrying the old ones.  See analysis/vits_deviations.py.
#
# The decodes take the default CVBS encoding (CVBS_U10_4FSC) rather than
# forcing CVBS_U16_4FSC, so the encoding users actually get is the encoding
# under test.
#
# They do force --exact-speculation, which is not the default, because
# without it the decode is not reproducible between machines.  The thread
# count defaults to min(max(cpu_count - 2, 1), 10) - 10 on a 16-core
# developer machine, 2 on a 4-core CI runner - and the speculation
# acceptance path makes the CVBS bytes depend on it.  The first CI run of
# this sweep failed on exactly that: two known deviations on
# domesday-ds2-community-north-middle were recorded at 10 threads (1.389 and
# 1.267 dB) and CI read them at 2 (1.543 and 1.482 dB), over their ceilings.
# With the flag, -t 2 and -t 10 produce byte-identical output, and the
# reading matches the loose 2-thread one to 0.001 dB - so this pins which
# decode is measured rather than moving the measurement to a different
# regime.  A gate that answers differently per core count cannot gate.
# analysis/vits_known_deviations.toml is recorded from these decodes.
#
# Both halves carry the "vits" label, so "ctest -L vits" is the whole sweep
# and "ctest -LE vits" is everything else - which is how the CI workflow runs
# them as two jobs without decoding anything twice.

function(add_vits_radius_cut label system)
    set(system_flag "")
    if(system STREQUAL "PAL")
        set(system_flag "--PAL")
    endif()

    add_test(
        NAME decode-${label}-cvbs
        COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
            --cvbs ${system_flag} --exact-speculation
            ${TESTDATA_DIR}/radius/${label}.ldf
            ${CMAKE_BINARY_DIR}/testout/${label}
        WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
    )
    set_tests_properties(decode-${label}-cvbs PROPERTIES
        LABELS "functional;slow;vits"
        FIXTURES_SETUP ${label}-cvbs
        TIMEOUT 1800
    )

    add_test(
        NAME conformance-${label}-vits
        COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/vits_conformance.py
            ${CMAKE_BINARY_DIR}/testout/${label}.cvbs
            --manifest ${TESTDATA_DIR}/vits-manifest.json
            --known-deviations ${ANALYSIS_DIR}/vits_known_deviations.toml
            --json ${CMAKE_BINARY_DIR}/testout/${label}.conformance.json
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
    # SKIPPED is a pass because a cut the manifest records as carrying no
    # measurable VITS has nothing to prove; a cut that carries them and loses
    # them fails on the manifest's presence checks instead, which is the
    # distinction the regex has to keep.
    set_tests_properties(conformance-${label}-vits PROPERTIES
        LABELS "functional;vits"
        FIXTURES_REQUIRED ${label}-cvbs
        PASS_REGULAR_EXPRESSION "VITS CONFORMANCE: (PASS|SKIPPED)"
        TIMEOUT 600
    )
endfunction()

set(VITS_RADIUS_PAL_CUTS
    ggv1011-side1-inner
    ggv1011-side1-middle
    ggv1011-side1-outer
    domesday-ds2-community-north-inner
    domesday-ds2-community-north-middle
    domesday-ds2-community-north-outer
    domesday-ds1-community-north-outer
    industrial-lv-side1-inner
    industrial-lv-side1-middle
    industrial-lv-side1-outer
)

set(VITS_RADIUS_NTSC_CUTS
    ggv1069-side1-inner
    ggv1069-side1-middle
    ggv1069-side1-outer
    ggv1069-side1-ldv4300d-inner
    ggv1069-side1-ldv4300d-middle
    ggv1069-side1-ldv4300d-outer
    dolby-surround-side1-inner
    dolby-surround-side1-middle
    dolby-surround-side1-outer
)

foreach(cut IN LISTS VITS_RADIUS_PAL_CUTS)
    add_vits_radius_cut(${cut} PAL)
endforeach()

foreach(cut IN LISTS VITS_RADIUS_NTSC_CUTS)
    add_vits_radius_cut(${cut} NTSC)
endforeach()

# ---------------------------------------------------------------------------
# VITS conformance on whole captures
# ---------------------------------------------------------------------------

# The radius cuts above are the only captures the conformance runner sees, so
# a signal only one of them carries puts a whole family of checks behind a
# single disc image.  The FCC multiburst was in that position: of everything
# in testdata/ only the GGV NTSC pressings carry it, and only at the inner
# radius, so multiburst_flatness and multiburst_out_of_band_response on NTSC
# were each measured on one cut and said nothing about anything else.
#
# These two whole captures were already in testdata/ntsc/ with no conformance
# test reading them.  Judging them costs no new capture data and gives the
# NTSC gates a second and third image: ggv-ntsc-mb-v2800 is a third FCC
# multiburst reading, and ve-monitor decodes to 178 fields - more than four
# times any radius cut - which is the only capture here long enough to show
# what the servos settle to rather than what they reach inside 20 frames.
#
# They are cuts of a disc rather than of a radius, so they carry "functional"
# and "vits" but say nothing about radius; the sweep above remains the thing
# that speaks to that.
function(add_vits_capture_conformance label system capture)
    set(system_flag "")
    if(system STREQUAL "PAL")
        set(system_flag "--PAL")
    endif()

    add_test(
        NAME decode-${label}-cvbs
        COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
            --cvbs ${system_flag} --exact-speculation
            ${TESTDATA_DIR}/${capture}
            ${CMAKE_BINARY_DIR}/testout/${label}
        WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
    )
    set_tests_properties(decode-${label}-cvbs PROPERTIES
        LABELS "functional;slow;vits"
        FIXTURES_SETUP ${label}-cvbs
        TIMEOUT 1800
    )

    add_test(
        NAME conformance-${label}-vits
        COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/vits_conformance.py
            ${CMAKE_BINARY_DIR}/testout/${label}.cvbs
            --manifest ${TESTDATA_DIR}/vits-manifest.json
            --known-deviations ${ANALYSIS_DIR}/vits_known_deviations.toml
            --json ${CMAKE_BINARY_DIR}/testout/${label}.conformance.json
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
    set_tests_properties(conformance-${label}-vits PROPERTIES
        LABELS "functional;vits"
        FIXTURES_REQUIRED ${label}-cvbs
        PASS_REGULAR_EXPRESSION "VITS CONFORMANCE: (PASS|SKIPPED)"
        TIMEOUT 600
    )
endfunction()

add_vits_capture_conformance(ggv-ntsc-mb-v2800 NTSC ntsc/ggv-ntsc-mb-v2800.ldf)
add_vits_capture_conformance(ve-monitor NTSC ntsc/ve-monitor.ldf)

# Raw input-format coverage - converting the NTSC CI capture to .s16/.u16/
# .u8/.rf/.lds/.r30, reading each back exactly through make_loader, and
# decoding the packed conversions end-to-end - now runs as part of
# python-functional-tests above (tests/functional/test_input_formats.py).
# It needs no CTest entry of its own.

# ---------------------------------------------------------------------------
# EFM T-value quality
# ---------------------------------------------------------------------------

# analysis/efm_quality.py scores a .efm stream by its own frame structure
# (IEC 60908: T11-T11 sync pairs every 588 channel bits), so the RF -> .efm
# path is gated without any downstream EFM decoder.  Each threshold below is
# set just under the capture's measured baseline - recorded in
# docs/technical/efm-decoding.md - so the gate fails on regression while
# tolerating float-level environment wobble.  Captures that carry no EFM
# (the GGV pressings, industrial-lv, kagemusha-leadout) have nothing to
# gate; the Domesday *outer* radius cuts land in one of that disc's
# analogue-audio gaps between EFM sections and are left ungated for the
# same reason.
#
# Gates on radius-cut and whole-capture decodes carry the "vits" label
# alongside "functional": their fixtures are the VITS sweep's decodes, and
# sharing the label keeps those decodes in the sweep's CI job instead of
# forcing "ctest -LE vits" to repeat them.

# jason-testpattern is the PAL EFM gate: a short, clean capture the default
# (timing-recovery) demodulator frames perfectly (sync_rate 1.0,
# frame_588_fraction 1.0), so it is pinned at (near) perfection.  The
# decode also opts in to confidence-packed .efm output (off by default in
# TBC mode), making this the test that holds the T_VALUE_CONF_U8 packing to
# its contract: the low nibbles must still score perfectly.
add_test(
    NAME decode-jason-testpattern
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --tbc --PAL
        ${TESTDATA_DIR}/pal/jason-testpattern.ldf
        ${CMAKE_BINARY_DIR}/testout/jason-testpattern
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-jason-testpattern PROPERTIES
    LABELS "functional"
    ENVIRONMENT "LDDECODE_EFM_EMITCONF=1"
    FIXTURES_SETUP jason-tbc
    TIMEOUT 600
)

add_test(
    NAME efm-quality-jason-testpattern
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/efm_quality.py
        ${CMAKE_BINARY_DIR}/testout/jason-testpattern.efm
        --packed
        --min-sync-rate 0.999 --min-frame-588 0.999
        --max-invalid-t 0 --min-t-values 143000
        --json ${CMAKE_BINARY_DIR}/testout/jason-testpattern.efm-quality.json
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(efm-quality-jason-testpattern PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED jason-tbc
    PASS_REGULAR_EXPRESSION "EFM QUALITY: PASS"
    TIMEOUT 120
)

# issue176 is the NTSC CLV movie-disc gate, also currently framing
# perfectly.
add_test(
    NAME decode-issue176
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --tbc
        ${TESTDATA_DIR}/ntsc/issue176.ldf
        ${CMAKE_BINARY_DIR}/testout/issue176
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-issue176 PROPERTIES
    LABELS "functional"
    FIXTURES_SETUP issue176-tbc
    TIMEOUT 600
)

add_test(
    NAME efm-quality-issue176
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/efm_quality.py
        ${CMAKE_BINARY_DIR}/testout/issue176.efm
        --min-sync-rate 0.999 --min-frame-588 0.999
        --max-invalid-t 0 --min-t-values 116000
        --json ${CMAKE_BINARY_DIR}/testout/issue176.efm-quality.json
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(efm-quality-issue176 PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED issue176-tbc
    PASS_REGULAR_EXPRESSION "EFM QUALITY: PASS"
    TIMEOUT 120
)

# The previous run-length PLL stays available behind --efm_demod pll (the
# timing-recovery demodulator is the default); this chain keeps the PLL
# gated at its own measured performance (with confidence-packed output, so
# the packing is covered on this path too), and checks the serial/threaded
# .efm bit-identity guarantee with the non-default selector - the packed
# stream carries the confidences, so the compare covers those as well.
add_test(
    NAME decode-jason-pll
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --tbc --PAL --efm_demod pll
        ${TESTDATA_DIR}/pal/jason-testpattern.ldf
        ${CMAKE_BINARY_DIR}/testout/jason-pll
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-jason-pll PROPERTIES
    LABELS "functional"
    ENVIRONMENT "LDDECODE_EFM_EMITCONF=1"
    FIXTURES_SETUP jason-pll-tbc
    TIMEOUT 600
)

add_test(
    NAME efm-quality-jason-pll
    COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/efm_quality.py
        ${CMAKE_BINARY_DIR}/testout/jason-pll.efm
        --packed
        --min-sync-rate 0.999 --min-frame-588 0.999
        --max-invalid-t 0 --min-t-values 143000
        --json ${CMAKE_BINARY_DIR}/testout/jason-pll.efm-quality.json
    WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
)
set_tests_properties(efm-quality-jason-pll PROPERTIES
    LABELS "functional"
    FIXTURES_REQUIRED jason-pll-tbc
    PASS_REGULAR_EXPRESSION "EFM QUALITY: PASS"
    TIMEOUT 120
)

add_test(
    NAME decode-jason-pll-parallel
    COMMAND ${CMAKE_SOURCE_DIR}/ld-decode
        --tbc --PAL --efm_demod pll -t 4 --exact-speculation
        ${TESTDATA_DIR}/pal/jason-testpattern.ldf
        ${CMAKE_BINARY_DIR}/testout/jason-pll-parallel
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
)
set_tests_properties(decode-jason-pll-parallel PROPERTIES
    LABELS "functional"
    ENVIRONMENT "LDDECODE_EFM_EMITCONF=1"
    FIXTURES_SETUP jason-pll-parallel
    TIMEOUT 600
)

foreach(ext efm)
    add_test(
        NAME compare-jason-pll-parallel-${ext}
        COMMAND ${CMAKE_COMMAND} -E compare_files
            ${CMAKE_BINARY_DIR}/testout/jason-pll-parallel.${ext}
            ${CMAKE_BINARY_DIR}/testout/jason-pll.${ext}
    )
    set_tests_properties(compare-jason-pll-parallel-${ext} PROPERTIES
        LABELS "functional"
        FIXTURES_REQUIRED "jason-pll-parallel;jason-pll-tbc"
        TIMEOUT 120
    )
endforeach()

# The remaining gates ride on decodes that already run: the basic NTSC TBC
# and CVBS decodes (ve-snw-cut carries digital audio), and the EFM-bearing
# VITS captures.  add_efm_quality(<label> <fixture> <labels> <efm-file>
# <min-sync-rate> <min-frame-588> <min-t-values>) keeps each threshold set
# next to the capture it measures.
function(add_efm_quality label fixture test_labels efm_file min_sync min_588 min_t)
    # Pass PACKED after the required arguments when the fixture writes the
    # confidence-packed encoding (T_VALUE_CONF_U8 - the CVBS-mode default).
    set(packed_arg "")
    if("PACKED" IN_LIST ARGN)
        set(packed_arg "--packed")
    endif()
    add_test(
        NAME efm-quality-${label}
        COMMAND ${Python3_EXECUTABLE} ${ANALYSIS_DIR}/efm_quality.py
            ${CMAKE_BINARY_DIR}/testout/${efm_file} ${packed_arg}
            --min-sync-rate ${min_sync} --min-frame-588 ${min_588}
            --max-invalid-t 0 --min-t-values ${min_t}
            --json ${CMAKE_BINARY_DIR}/testout/${label}.efm-quality.json
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
    )
    set_tests_properties(efm-quality-${label} PROPERTIES
        LABELS "${test_labels}"
        FIXTURES_REQUIRED ${fixture}
        PASS_REGULAR_EXPRESSION "EFM QUALITY: PASS"
        TIMEOUT 120
    )
endfunction()

add_efm_quality(ntsc-basic ntsc-tbc "functional"
    ntsc-basic.efm 0.999 0.997 860000)
add_efm_quality(ntsc-cvbs ntsc-cvbs "functional"
    ntsc-cvbs.efm 0.999 0.995 178000 PACKED)
add_efm_quality(ve-monitor ve-monitor-cvbs "functional;vits"
    ve-monitor.efm 0.998 0.995 2610000 PACKED)
add_efm_quality(dolby-surround-side1-inner dolby-surround-side1-inner-cvbs
    "functional;vits" dolby-surround-side1-inner.efm 0.998 0.994 594000 PACKED)
add_efm_quality(dolby-surround-side1-middle dolby-surround-side1-middle-cvbs
    "functional;vits" dolby-surround-side1-middle.efm 0.998 0.995 564000 PACKED)
add_efm_quality(dolby-surround-side1-outer dolby-surround-side1-outer-cvbs
    "functional;vits" dolby-surround-side1-outer.efm 0.998 0.995 594000 PACKED)
add_efm_quality(domesday-ds2-community-north-inner
    domesday-ds2-community-north-inner-cvbs "functional;vits"
    domesday-ds2-community-north-inner.efm 0.999 0.995 891000 PACKED)
add_efm_quality(domesday-ds2-community-north-middle
    domesday-ds2-community-north-middle-cvbs "functional;vits"
    domesday-ds2-community-north-middle.efm 0.999 0.995 1034000 PACKED)

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
