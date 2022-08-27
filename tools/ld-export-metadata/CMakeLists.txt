message( STATUS "---------Beginning cmake build of ld-export-metadata ---------")
project( ld-export-metadata )

#ld-export-metadata SOURCES
set( SOURCES
	"closedcaptions.cpp"
	"csv.cpp"
	"ffmetadata.cpp"
	"main.cpp"
	"../library/tbc/dropouts.cpp"
	"../library/tbc/jsonio.cpp"
	"../library/tbc/lddecodemetadata.cpp"
	"../library/tbc/logging.cpp"
	"../library/tbc/vbidecoder.cpp"
)

#ld-export-metadata HEADERS
set ( HEADERS
	"closedcaptions.h"
	"csv.h"
	"ffmetadata.h"
	"../library/tbc/dropouts.h"
	"../library/tbc/jsonio.h"
	"../library/tbc/lddecodemetadata.h"
	"../library/tbc/logging.h"
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

# ld-export-metadata executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core fftw3 ld-tbc ld-filter)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

set(CMAKE_CXX_STANDARD 17)

set(CMAKE_AUTOUIC_SEARCH_PATHS "${SMAKE_CURRENT_SOURCE_DIR}/ui")

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")