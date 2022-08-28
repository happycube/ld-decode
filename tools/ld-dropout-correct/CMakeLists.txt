message( STATUS "---------Beginning cmake build of ld-dropout-correct ---------")
project( ld-dropout-correct )

#ld-dropout-correct SOURCES
set( SOURCES
	"correctorpool.cpp"
	"main.cpp"
	"dropoutcorrect.cpp"
	"../library/tbc/dropouts.cpp"
	"../library/tbc/filters.cpp"
	"../library/tbc/jsonio.cpp"
	"../library/tbc/lddecodemetadata.cpp"
	"../library/tbc/logging.cpp"
	"../library/tbc/sourcevideo.cpp"
	"../library/tbc/vbidecoder.cpp"
)

#ld-dropout-correct HEADERS
set ( HEADERS
	"correctorpool.h"
	"dropoutcorrect.h"
	"../library/tbc/dropouts.h"
	"../library/tbc/jsonio.h"
	"../library/tbc/lddecodemetadata.h"
	"../library/tbc/logging.h"
	"../library/tbc/sourcevideo.h"
	"../library/tbc/vbidecoder.h"
)

ADD_DEFINITIONS(${QT_DEFINITIONS})

QT_WRAP_CPP(HEADERS_MOC ${HEADERS})

find_package(QT NAMES Qt5 Qt6 REQUIRED COMPONENTS Core)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Core)

# ld-dropout-correct executable

add_executable(${PROJECT_NAME} ${SOURCES} ${HEADERS_MOC})

target_link_libraries(${PROJECT_NAME} PRIVATE Qt::Core ld-library)

set(CMAKE_INCLUDE_CURRENT_DIR ON)

# Link them to the project

install(TARGETS ${PROJECT_NAME} DESTINATION "")