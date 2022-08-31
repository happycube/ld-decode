message(STATUS "---------Beginning cmake build of ld-library---------")
project(ld-library)

add_library(ld-library SHARED
    filter/deemp.h
    filter/firfilter.h
    filter/iirfilter.h
    tbc/dropouts.h
    tbc/filters.h
    tbc/jsonio.h
    tbc/lddecodemetadata.h
    tbc/linenumber.h
    tbc/logging.h
    tbc/sourceaudio.h
    tbc/sourcevideo.h
    tbc/vbidecoder.h
)

target_include_directories(ld-library PUBLIC ./ filter tbc)

set_target_properties(ld-library PROPERTIES LINKER_LANGUAGE CXX)

# XXX Build and run tests
# tbc/testmetadata/testmetadata.cpp
# tbc/testvbidecoder/testvbidecoder.cpp
# tbc/testlinenumber/testlinenumber.cpp
# filter/testfilter/testfilter.cpp
