add_executable(ld-json-converter
    dropouts.cpp
    jsonio.cpp
    lddecodemetadata.cpp
    jsonconverter.cpp
    main.cpp
)

target_link_libraries(ld-json-converter PRIVATE Qt::Core Qt::Sql lddecode-library)

install(TARGETS ld-json-converter)