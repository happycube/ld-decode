add_executable(ld-ac3-decode
    ac3_parsing.cpp
    main.cpp
)

target_include_directories(ld-ac3-decode PRIVATE . ../../ld-process-efm)

install(TARGETS ld-ac3-decode)
