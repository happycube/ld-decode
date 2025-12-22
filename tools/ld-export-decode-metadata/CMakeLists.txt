add_executable(ld-export-decode-metadata
    exportdropouts.cpp
    exportmetadata.cpp
    jsonio.cpp
    main.cpp
    metadataconverter.cpp
)

target_link_libraries(ld-export-decode-metadata PRIVATE Qt::Core lddecode-library)

install(TARGETS ld-export-decode-metadata)