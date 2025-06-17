pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET
    libavcodec
    libavformat
    libavutil
)

add_executable(ld-ldf-reader
  ld-ldf-reader.c)

target_link_libraries(ld-ldf-reader PkgConfig::FFMPEG)

install(TARGETS ld-ldf-reader)
