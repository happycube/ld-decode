add_executable(ld-process-vbi
    closedcaption.cpp
    decoderpool.cpp
    main.cpp
    fmcode.cpp
    vbilinedecoder.cpp
    whiteflag.cpp
)

target_link_libraries(ld-process-vbi PRIVATE Qt::Core ld-library)

install(TARGETS ld-process-vbi)
