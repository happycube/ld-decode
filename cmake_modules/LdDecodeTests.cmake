# Tests for the ld-decode tools.

# Most of the tests expect that you have cloned (or symlinked) the
# ld-decode-testdata repo within the source directory as "testdata".

# Chroma tests run sequentially to avoid file conflicts

set(SCRIPTS_DIR ${CMAKE_SOURCE_DIR}/scripts)
set(TESTDATA_DIR ${CMAKE_SOURCE_DIR}/testdata)

add_test(
    NAME chroma-ntsc-rgb
    COMMAND ${SCRIPTS_DIR}/test-chroma
        --build ${CMAKE_BINARY_DIR}
        --system ntsc
        --expect-psnr 25
        --expect-psnr-range 0.5
)

add_test(
    NAME chroma-ntsc-ycbcr
    COMMAND ${SCRIPTS_DIR}/test-chroma
        --build ${CMAKE_BINARY_DIR}
        --system ntsc
        --expect-psnr 25
        --expect-psnr-range 0.5
        --input-format yuv
)
set_tests_properties(chroma-ntsc-ycbcr PROPERTIES DEPENDS chroma-ntsc-rgb)

add_test(
    NAME chroma-pal-rgb
    COMMAND ${SCRIPTS_DIR}/test-chroma
        --build ${CMAKE_BINARY_DIR}
        --system pal
        --expect-psnr 25
        --expect-psnr-range 0.5
)
set_tests_properties(chroma-pal-rgb PROPERTIES DEPENDS chroma-ntsc-ycbcr)

add_test(
    NAME chroma-pal-ycbcr
    COMMAND ${SCRIPTS_DIR}/test-chroma
        --build ${CMAKE_BINARY_DIR}
        --system pal
        --expect-psnr 25
        --expect-psnr-range 0.5
        --input-format yuv
)
set_tests_properties(chroma-pal-ycbcr PROPERTIES DEPENDS chroma-pal-rgb)

add_test(
    NAME ld-cut-ntsc
    COMMAND ${SCRIPTS_DIR}/test-decode
        --source ${CMAKE_SOURCE_DIR}
        --build ${CMAKE_BINARY_DIR}
        --cut-seek 30255
        --cut-length 4
        --expect-frames 4
        --expect-vbi 9151563,15925845,15925845
        ${TESTDATA_DIR}/ve-snw-cut.lds
)

add_test(
    NAME ld-cut-pal
    COMMAND ${SCRIPTS_DIR}/test-decode
        --source ${CMAKE_SOURCE_DIR}
        --build ${CMAKE_BINARY_DIR}
        --pal
        --no-efm  # GGV discs do not contain EFM data
        --cut-seek 760
        --cut-length 4
        --expect-frames 4
        --expect-vbi 9152512,15730528,15730528
        ${TESTDATA_DIR}/pal/ggv-mb-1khz.ldf
)

add_test(
    NAME decode-ntsc-cav
    COMMAND ${SCRIPTS_DIR}/test-decode
        --source ${CMAKE_SOURCE_DIR}
        --build ${CMAKE_BINARY_DIR}
        --decoder mono --decoder ntsc2d --decoder ntsc3d
        --expect-frames 29
        --expect-bpsnr 43.3
        --expect-vbi 9151563,15925840,15925840
        --expect-efm-samples 40572
        ${TESTDATA_DIR}/ve-snw-cut.lds
)

add_test(
    NAME decode-ntsc-clv
    COMMAND ${SCRIPTS_DIR}/test-decode
        --source ${CMAKE_SOURCE_DIR}
        --build ${CMAKE_BINARY_DIR}
        --no-efm-timecodes
        --expect-frames 4
        --expect-bpsnr 37.6
        --expect-vbi 9167913,15785241,15785241
        ${TESTDATA_DIR}/issues/176/issue176.lds
)

add_test(
    NAME decode-pal-cav
    COMMAND ${SCRIPTS_DIR}/test-decode --pal
        --source ${CMAKE_SOURCE_DIR}
        --build ${CMAKE_BINARY_DIR}
        --decoder mono --decoder pal2d --decoder transform2d --decoder transform3d
        --expect-frames 4
        --expect-bpsnr 38.4
        --expect-vbi 9151527,16065688,16065688
        --expect-vitc 2,10,8,13,4,3,0,1
        --expect-efm-samples 5292
        ${TESTDATA_DIR}/pal/jason-testpattern.lds
)

add_test(
    NAME decode-pal-clv
    COMMAND ${SCRIPTS_DIR}/test-decode --pal --no-efm
        --source ${CMAKE_SOURCE_DIR}
        --build ${CMAKE_BINARY_DIR}
        --expect-frames 9
        --expect-bpsnr 30.3
        --expect-vbi 0,8449774,8449774
        ${TESTDATA_DIR}/pal/kagemusha-leadout-cbar.ldf
)

add_test(
    NAME ldf-reader-full
    COMMAND ${SCRIPTS_DIR}/test-ldf-reader
        --build ${CMAKE_BINARY_DIR}
        --testdata ${TESTDATA_DIR}
        --input ggv-ntsc-mb-v2800.ldf
        --full-sha256 0984ab9a4e66b49426b61e2d4de266e7783801dc48f566ed805257bc596098ec
        --offset 1000000
        --partial-bytes 1000000
        --partial-sha256 7dae0f342b4b365d5d607676961ca28b39ef78c71b7b0be11f77c303a7ac50f7
)
