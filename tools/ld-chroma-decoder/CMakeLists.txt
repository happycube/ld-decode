message( STATUS "---------Beginning cmake build of ld-chroma-decoder---------")

project( ld-chroma-decoder )
cmake_minimum_required( VERSION 3.22 )

#ld-chroma-decoder SOURCES
set ( SOURCES
	"comb.cpp"
	"componentframe.cpp"
	"decoder.cpp"
	"decoderpool.cpp"
	"framecanvas.cpp"
	"main.cpp"
	"monodecoder.cpp"
	"ntscdecoder.cpp"
	"outputwriter.cpp"
	"palcolour.cpp"
	"paldecoder.cpp"
	"sourcefield.cpp"
	"transformpal.cpp"
	"transformpal2d.cpp"
	"transformpal3d.cpp"
	"../library/tbc/dropouts.cpp"
	"../library/tbc/jsonio.cpp"
	"../library/tbc/lddecodemetadata.cpp"
	"../library/tbc/logging.cpp"
	"../library/tbc/sourcevideo.cpp"
	"../library/tbc/vbidecoder.cpp"
)

#ld-chroma-decoder HEADERS
set ( HEADERS
	"comb.h"
	"componentframe.h"
	"decoder.h"
	"decoderpool.h"
	"framecanvas.h"
	"monodecoder.h"
	"ntscdecoder.h"
	"outputwriter.h"
	"palcolour.h"
	"paldecoder.h"
	"sourcefield.h"
	"transformpal.h"
	"transformpal2d.h"
	"transformpal3d.h"
	"../library/filter/deemp.h"
	"../library/filter/firfilter.h"
	"../library/filter/iirfilter.h"
	"../library/tbc/dropouts.h"
	"../library/tbc/jsonio.h"
	"../library/tbc/lddecodemetadata.h"
	"../library/tbc/logging.h"
	"../library/tbc/sourcevideo.h"
	"../library/tbc/vbidecoder.h"
)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

set(CMAKE_CXX_STANDARD 17)

# Get the current working branch
execute_process(
	COMMAND git rev-parse --abbrev-ref HEAD
	WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
	OUTPUT_VARIABLE GIT_BRANCH
	OUTPUT_STRIP_TRAILING_WHITESPACE
)

# Get the latest abbreviated commit hash of the working branch
execute_process(
	COMMAND git log -1 --format=%h
	WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
	OUTPUT_VARIABLE GIT_COMMIT_HASH
	OUTPUT_STRIP_TRAILING_WHITESPACE
)

# Pass it on to the source code
add_definitions(-DAPP_BRANCH="\""+${GIT_BRANCH}+"\"" -DAPP_COMMIT="\""+${GIT_COMMIT_HASH}+"\"")

message( STATUS "--------- Git branch: ${GIT_BRANCH} ---------")
message( STATUS "--------- Git commit: ${GIT_COMMIT_HASH} ---------")

set(CMAKE_AUTOUIC_SEARCH_PATHS "${SMAKE_CURRENT_SOURCE_DIR}/ui")

ADD_DEFINITIONS(${QT_DEFINITIONS})

QT_WRAP_CPP(HEADERS_MOC ${HEADERS})

# ld-chroma-decoder executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core fftw3 ld-tbc ld-filter)

install(TARGETS ${PROJECT_NAME} DESTINATION "")

# Make a library for ld-analyse to use

project( ld-chroma-lib )

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -pthread -O3 -Wall -ftree-vectorize -ffast-math -funroll-loops")

add_library(ld-chroma-lib SHARED
	"comb.h"
    "palcolour.h"
)

target_include_directories(ld-chroma-lib PUBLIC ./)

set_target_properties(ld-chroma-lib PROPERTIES LINKER_LANGUAGE CXX)
install(TARGETS ld-chroma-lib LIBRARY DESTINATION /usr/lib64 ARCHIVE DESTINATION /usr/lib64)