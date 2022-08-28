message( STATUS "---------Beginning cmake build of ld-library---------")
project( ld-library )

#add_compile_options(-std=c++17
#set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -pthread -O3 -Wall -ftree-vectorize -funroll-loops")

include_directories()

find_package(OpenCV REQUIRED)

add_library(ld-library SHARED
    "filter/deemp.h"
    "filter/firfilter.h"
    "filter/iirfilter.h"
    "tbc/dropouts.h"
    "tbc/filters.h"
    "tbc/jsonio.h"
    "tbc/lddecodemetadata.h"
    "tbc/linenumber.h"
    "tbc/logging.h"
    "tbc/sourceaudio.h"
    "tbc/sourcevideo.h"
    "tbc/vbidecoder.h"
)

target_include_directories(ld-library PUBLIC ./ filter tbc)
target_link_libraries(ld-library ${OpenCV_LIBS})

set_target_properties(ld-library PROPERTIES LINKER_LANGUAGE CXX)
