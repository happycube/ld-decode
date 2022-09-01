add_executable(ld-lds-converter
    dataconverter.cpp
    main.cpp
)

target_link_libraries(ld-lds-converter PRIVATE Qt::Core ld-library)

install(TARGETS ld-lds-converter)
