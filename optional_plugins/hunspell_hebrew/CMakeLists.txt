cmake_minimum_required(VERSION 3.15)
project(hebrew_spelling_worker LANGUAGES CXX)
# No externally downloaded binaries or runtime Python are needed.
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
add_subdirectory("${HUNSPELL_SOURCE}" hunspell)
add_executable(hebrew-spelling-worker worker.cpp)
target_link_libraries(hebrew-spelling-worker PRIVATE hunspell)
target_compile_features(hebrew-spelling-worker PRIVATE cxx_std_14)
