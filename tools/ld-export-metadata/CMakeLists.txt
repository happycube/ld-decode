add_executable(ld-export-metadata
    closedcaptions.cpp
    csv.cpp
    ffmetadata.cpp
    main.cpp
)

target_link_libraries(ld-export-metadata PRIVATE Qt::Core lddecode-library)

install(TARGETS ld-export-metadata)
