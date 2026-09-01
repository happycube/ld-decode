# Check that a real .lds capture survives an unpack/repack cycle byte for byte.
# Run with cmake -P; expects PYTHON, SOURCE_DIR, SOURCE_LDS and WORK_DIR.
#
# This isolates the bare converter (lddecode.lds, run as a module so the
# in-tree package is used).  compress-lds-round-trip covers the same packing
# arithmetic, but with flac and PyAV in between, so a fault in either could
# mask or be mistaken for one in the other.  tests/unit/test_lds_packing.py
# covers the arithmetic on synthetic vectors; what is added here is real
# capture data, whose sample distribution is nothing like a uniform draw.

foreach(var PYTHON SOURCE_DIR SOURCE_LDS WORK_DIR)
    if(NOT DEFINED ${var})
        message(FATAL_ERROR "${var} must be set")
    endif()
endforeach()

if(NOT EXISTS "${SOURCE_LDS}")
    message(FATAL_ERROR "Source capture ${SOURCE_LDS} does not exist")
endif()

file(REMOVE_RECURSE "${WORK_DIR}")
file(MAKE_DIRECTORY "${WORK_DIR}")

set(UNPACKED "${WORK_DIR}/unpacked.s16")
set(REPACKED "${WORK_DIR}/repacked.lds")

# Run from the source tree so "-m lddecode.lds" resolves to the working copy
# rather than to an installed one.
function(run_converter)
    execute_process(
        COMMAND "${PYTHON}" -m lddecode.lds ${ARGN}
        WORKING_DIRECTORY "${SOURCE_DIR}"
        RESULT_VARIABLE result
    )
    if(NOT result EQUAL 0)
        message(FATAL_ERROR "ld-lds-converter-py ${ARGN} failed with status ${result}")
    endif()
endfunction()

run_converter(--unpack --input "${SOURCE_LDS}" --output "${UNPACKED}")
run_converter(--pack --input "${UNPACKED}" --output "${REPACKED}")

# Four 10-bit samples per five bytes become four 16-bit samples per eight, so
# a correct unpack is exactly 8/5 of the input.  Asserted separately from the
# byte comparison because a converter that dropped the whole stream would
# repack to an empty file that no longer matches anyway, and this says which
# of the two steps went wrong.
file(SIZE "${SOURCE_LDS}" source_size)
file(SIZE "${UNPACKED}" unpacked_size)
math(EXPR expected_size "${source_size} / 5 * 8")

if(NOT unpacked_size EQUAL expected_size)
    message(FATAL_ERROR
        "Unpacked size is wrong:\n"
        "  source:   ${source_size} bytes\n"
        "  unpacked: ${unpacked_size} bytes, expected ${expected_size}")
endif()

file(MD5 "${SOURCE_LDS}" source_md5)
file(MD5 "${REPACKED}" repacked_md5)

if(NOT source_md5 STREQUAL repacked_md5)
    file(SIZE "${REPACKED}" repacked_size)
    message(FATAL_ERROR
        "Unpack/repack changed the data:\n"
        "  source:   ${source_size} bytes, md5 ${source_md5}\n"
        "  repacked: ${repacked_size} bytes, md5 ${repacked_md5}")
endif()

message(STATUS
    "lds unpack/repack is byte-identical (${source_size} bytes, md5 ${source_md5})")
