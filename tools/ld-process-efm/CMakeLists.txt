message( STATUS "---------Beginning cmake build of ld-process-efm ---------")
project( ld-process-efm )

#ld-process-efm SOURCES
set( SOURCES
	"efmprocess.cpp"
	"main.cpp"
	"Datatypes/audio.cpp"
	"Datatypes/f1frame.cpp"
	"Datatypes/f2frame.cpp"
	"Datatypes/f3frame.cpp"
	"Datatypes/section.cpp"
	"Datatypes/sector.cpp"
	"Datatypes/tracktime.cpp"
	"Decoders/c1circ.cpp"
	"Decoders/c2circ.cpp"
	"Decoders/c2deinterleave.cpp"
	"Decoders/efmtof3frames.cpp"
	"Decoders/f1toaudio.cpp"
	"Decoders/f1todata.cpp"
	"Decoders/f2tof1frames.cpp"
	"Decoders/f3tof2frames.cpp"
	"Decoders/syncf3frames.cpp"
	"../library/tbc/logging.cpp"
)

#ld-process-efm HEADERS
set ( HEADERS
	"efmprocess.h"
	"Datatypes/audio.h" 
	"Datatypes/f1frame.h" 
	"Datatypes/f2frame.h" 
	"Datatypes/f3frame.h" 
	"Datatypes/section.h" 
	"Datatypes/sector.h" 
	"Datatypes/tracktime.h" 
	"Decoders/c1circ.h" 
	"Decoders/c2circ.h" 
	"Decoders/c2deinterleave.h" 
	"Decoders/efmtof3frames.h" 
	"Decoders/f1toaudio.h" 
	"Decoders/f1todata.h" 
	"Decoders/f2tof1frames.h" 
	"Decoders/f3tof2frames.h" 
	"Decoders/syncf3frames.h" 
	"ezpwd/asserter" 
	"ezpwd/bch" 
	"ezpwd/bch_base" 
	"ezpwd/corrector" 
	"ezpwd/definitions" 
	"ezpwd/ezcod" 
	"ezpwd/output" 
	"ezpwd/rs" 
	"ezpwd/serialize" 
	"ezpwd/serialize_definitions" 
	"ezpwd/timeofday"
	"../library/tbc/logging.h"
)

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

find_package(Qt5 REQUIRED COMPONENTS Core Widgets Gui)

ADD_DEFINITIONS(${QT_DEFINITIONS})

QT_WRAP_CPP(HEADERS_MOC ${HEADERS})

find_library(QWT_LIBRARY_RELEASE NAMES qwt qwt-qt5 qt5-qwt PATH_SUFFIXES lib)
find_package(QT NAMES Qt5 Qt5 qwt-qt6 REQUIRED COMPONENTS Core Gui Widgets HINTS ${QT_LIBRARY_DIR})

# ld-process-efm executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Widgets fftw3 ld-tbc ld-filter)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

set(CMAKE_CXX_STANDARD 17)

set(CMAKE_AUTOUIC_SEARCH_PATHS "${SMAKE_CURRENT_SOURCE_DIR}/ui")

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")