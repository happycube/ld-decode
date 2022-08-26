message( STATUS "---------Beginning cmake build of ld-tbc---------")
project( ld-tbc )

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -pthread -O3 -Wall -ftree-vectorize -ffast-math -funroll-loops")

find_package(OpenCV REQUIRED)

add_library(ld-tbc SHARED
    "dropouts.h"
    "filters.h"
    "jsonio.h"
    "lddecodemetadata.h"
    "linenumber.h"
    "logging.h"
    "sourceaudio.h"
    "sourcevideo.h"
    "vbidecoder.h"
)

target_link_libraries(ld-tbc ${OpenCV_LIBS})
target_include_directories(ld-tbc PUBLIC ./)

set_target_properties(ld-tbc PROPERTIES LINKER_LANGUAGE CXX)
install(TARGETS ld-tbc LIBRARY DESTINATION /usr/lib64 ARCHIVE DESTINATION /usr/lib64)