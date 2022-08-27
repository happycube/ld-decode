message( STATUS "---------Beginning cmake build of ld-process-vbi ---------")
project( ld-process-vbi )

#ld-process-vbi SOURCES
set( SOURCES
	"closedcaption.cpp"
	"decoderpool.cpp"
	"main.cpp"
	"fmcode.cpp"
	"vbilinedecoder.cpp"
	"whiteflag.cpp"
	"../library/tbc/dropouts.cpp"
	"../library/tbc/jsonio.cpp"
	"../library/tbc/lddecodemetadata.cpp"
	"../library/tbc/logging.cpp"
	"../library/tbc/sourcevideo.cpp"
	"../library/tbc/vbidecoder.cpp"
)

#ld-process-vbi HEADERS
set ( HEADERS
	"closedcaption.h"
	"decoderpool.h"
	"fmcode.h"
	"vbilinedecoder.h"
	"whiteflag.h"
	"../library/tbc/dropouts.h"
	"../library/tbc/jsonio.h"
	"../library/tbc/lddecodemetadata.h"
	"../library/tbc/logging.h"
	"../library/tbc/sourcevideo.h"
	"../library/tbc/vbidecoder.h"
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

# ld-process-vbi executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core fftw3 ld-tbc ld-filter)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

set(CMAKE_CXX_STANDARD 17)

set(CMAKE_AUTOUIC_SEARCH_PATHS "${SMAKE_CURRENT_SOURCE_DIR}/ui")

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")