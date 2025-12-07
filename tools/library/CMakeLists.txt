add_library(lddecode-library STATIC
    tbc/dropouts.cpp
    tbc/filters.cpp
    tbc/sqliteio.cpp
    tbc/lddecodemetadata.cpp
    tbc/logging.cpp
    tbc/navigation.cpp
    tbc/sourceaudio.cpp
    tbc/sourcevideo.cpp
    tbc/vbidecoder.cpp
    tbc/videoiddecoder.cpp
    tbc/vitcdecoder.cpp
)

target_include_directories(lddecode-library PUBLIC filter tbc)
target_include_directories(lddecode-library PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

target_link_libraries(lddecode-library PRIVATE Qt::Core Qt::Sql)
