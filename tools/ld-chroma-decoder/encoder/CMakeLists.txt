add_executable(ld-chroma-encoder
    main.cpp
    encoder.cpp
    ntscencoder.cpp
    palencoder.cpp
)

target_link_libraries(ld-chroma-encoder PRIVATE Qt::Core ld-library)

install(TARGETS ld-chroma-encoder)
