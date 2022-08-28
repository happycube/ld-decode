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

ADD_DEFINITIONS(${QT_DEFINITIONS})

QT_WRAP_CPP(HEADERS_MOC ${HEADERS})

find_package(QT NAMES Qt5 Qt6 REQUIRED COMPONENTS Core)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core)

# ld-export-metadata executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

set(CMAKE_AUTOUIC_SEARCH_PATHS "${SMAKE_CURRENT_SOURCE_DIR}/ui")

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")