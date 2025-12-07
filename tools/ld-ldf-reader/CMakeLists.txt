pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET
    libavcodec
    libavformat
    libavutil
)

add_executable(ld-ldf-reader
    ldfreader.cpp
    main.cpp
)

target_link_libraries(ld-ldf-reader PRIVATE Qt::Core PkgConfig::FFMPEG lddecode-library)

install(TARGETS ld-ldf-reader)
