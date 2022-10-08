add_executable(ac3_decode main.cpp QPSKFramer.hpp Blocker.hpp Corrector.hpp AC3Framer.hpp ac3_parsing.hpp ../logger.hpp ac3_parsing.cpp)

target_include_directories(ac3_decode PRIVATE .)
