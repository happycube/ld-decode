message( STATUS "---------Beginning cmake build of ld-filter---------")
project( ld-filter )

#add_compile_options(-std=c++17
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -pthread -O3 -Wall -ftree-vectorize -ffast-math -funroll-loops")

find_package(OpenCV REQUIRED)

add_library(ld-filter SHARED
    "deemp.h"
    "firfilter.h"
    "iirfilter.h"
)

target_link_libraries(ld-filter ${OpenCV_LIBS})
target_include_directories(ld-filter PUBLIC ./)

set_target_properties(ld-filter PROPERTIES LINKER_LANGUAGE CXX)
install(TARGETS ld-filter LIBRARY DESTINATION /usr/lib64 ARCHIVE DESTINATION /usr/lib64)