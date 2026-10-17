# PS4 GPU library for The Order: shadPS4 video core + shader recompiler + Gnm/VideoOut
# drivers, adapted to the native_probe runtime through shims in shim/.
cmake_minimum_required(VERSION 3.24)
project(order1886 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()
# Frame pointers keep the loader's thread dumps (watchdog, SIGUSR2 sampling) walkable.
add_compile_options(-fno-omit-frame-pointer)

# Port: link-time optimization (ORDER1886_LTO, default on) and profile-guided optimization
# (ORDER1886_PGO: off, generate = instrumented build writing into ORDER1886_PGO_DIR, use = build with that
# profile). Covers ps4gpu and the static libraries linked into it. No -march: the same build
# runs on the Steam Deck.
option(ORDER1886_LTO "Link-time optimization of ps4gpu" ON)
set(ORDER1886_PGO "off" CACHE STRING "Profile-guided optimization: off, generate, use")
set(ORDER1886_PGO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../pgo" CACHE PATH "Profile directory")
if (ORDER1886_LTO)
    include(CheckIPOSupported)
    check_ipo_supported(RESULT ps4_ipo_ok OUTPUT ps4_ipo_error)
    if (ps4_ipo_ok)
        set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)
    else()
        message(WARNING "LTO unavailable: ${ps4_ipo_error}")
    endif()
endif()
if (ORDER1886_PGO STREQUAL "generate")
    # Atomic counters: the GPU, recording, preparation and copy threads run the same code.
    add_compile_options(-fprofile-generate=${ORDER1886_PGO_DIR} -fprofile-update=atomic)
    add_link_options(-fprofile-generate=${ORDER1886_PGO_DIR})
    add_compile_definitions(PS4_PGO_GENERATE)
elseif (ORDER1886_PGO STREQUAL "use")
    # Partial training keeps unprofiled code optimized normally; counters from concurrent
    # threads can be slightly inconsistent (correction). Functions changed since the profile
    # (or built differently for it, ps4gpu_init) are compiled without it.
    add_compile_options(-fprofile-use=${ORDER1886_PGO_DIR} -fprofile-partial-training
                        -fprofile-correction -Wno-missing-profile -Wno-coverage-mismatch)
endif()

find_package(Vulkan REQUIRED)
find_package(fmt REQUIRED)
find_package(Boost REQUIRED)
# Windows: MSYS2 has no magic_enum/miniz packages; the submodules are used instead.
find_package(magic_enum QUIET)
if (NOT magic_enum_FOUND)
    add_library(magic_enum INTERFACE)
    add_library(magic_enum::magic_enum ALIAS magic_enum)
    target_include_directories(magic_enum INTERFACE third_party/magic_enum/include
                                                    third_party/magic_enum/include/magic_enum)
endif()
find_package(tsl-robin-map REQUIRED)
find_package(VulkanMemoryAllocator CONFIG QUIET)
if (NOT VulkanMemoryAllocator_FOUND)
    # MSYS2 ships the header (include/vma/vk_mem_alloc.h) without a CMake package.
    find_path(VMA_INCLUDE_DIR vk_mem_alloc.h PATH_SUFFIXES vma REQUIRED)
    add_library(VulkanMemoryAllocator INTERFACE)
    add_library(GPUOpen::VulkanMemoryAllocator ALIAS VulkanMemoryAllocator)
    target_include_directories(VulkanMemoryAllocator INTERFACE ${VMA_INCLUDE_DIR})
endif()
find_package(PkgConfig REQUIRED)
pkg_check_modules(XXHASH REQUIRED IMPORTED_TARGET libxxhash)
pkg_check_modules(SDL3 REQUIRED IMPORTED_TARGET sdl3)
if (NOT WIN32)
    pkg_check_modules(X11 REQUIRED IMPORTED_TARGET x11)
endif()
find_package(miniz QUIET)
if (NOT miniz_FOUND)
    set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(BUILD_FUZZERS OFF CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS OFF)
    set(CMAKE_POLICY_VERSION_MINIMUM 3.5)
    add_subdirectory(third_party/miniz EXCLUDE_FROM_ALL)
    unset(CMAKE_POLICY_VERSION_MINIMUM)
    add_library(miniz::miniz ALIAS miniz)
endif()
find_package(Zydis REQUIRED)
find_program(GLSLANG_COMPILER NAMES glslang glslangValidator REQUIRED)

set(SIRIT_USE_SYSTEM_SPIRV_HEADERS OFF CACHE BOOL "" FORCE)
add_subdirectory(third_party/sirit EXCLUDE_FROM_ALL)

# The Order native-target baseline does not link host temporal reconstruction providers.

# Host shaders -> headers (same scheme as shadPS4's host_shaders/CMakeLists.txt).
set(SHADER_SRC ${CMAKE_CURRENT_SOURCE_DIR}/shadps4/video_core/host_shaders)
set(SHADER_INCLUDE ${CMAKE_CURRENT_BINARY_DIR}/include)
set(SHADER_DIR ${SHADER_INCLUDE}/video_core/host_shaders)
set(SHADER_HEADERS "")
function(add_host_shader FILENAME SHADER_NAME)
    set(OUT ${SHADER_DIR}/${SHADER_NAME}.h)
    string(TOUPPER ${SHADER_NAME} SYMBOL)
    set(DEFINES ${ARGN})
    list(TRANSFORM DEFINES PREPEND "-D")
    add_custom_command(OUTPUT ${OUT}
        COMMAND ${CMAKE_COMMAND} -E make_directory ${SHADER_DIR}
        COMMAND ${GLSLANG_COMPILER} --target-env vulkan1.3 -o ${OUT} --vn ${SYMBOL} ${DEFINES} ${SHADER_SRC}/${FILENAME}
        COMMAND ${CMAKE_COMMAND} "-DHEADER_FILE=${OUT}" -P ${SHADER_SRC}/AddShaderHeaderInclude.cmake
        DEPENDS ${SHADER_SRC}/${FILENAME} VERBATIM)
    set(SHADER_HEADERS ${SHADER_HEADERS} ${OUT} PARENT_SCOPE)
endfunction()
add_host_shader(color_to_ms_depth.frag color_to_ms_depth_frag)
add_host_shader(ms_image_blit.frag ms_image_blit_frag)
add_host_shader(ms_image_blit.frag ms_image_blit_msaa_frag SRC_MSAA=1)
add_host_shader(ms_image_blit.frag ms_image_blit_uint_frag SRC_UINT=1)
add_host_shader(ms_image_blit.frag ms_image_blit_uint_msaa_frag SRC_MSAA=1 SRC_UINT=1)
add_host_shader(fault_buffer_process.comp fault_buffer_process_comp)
add_host_shader(fs_tri.vert fs_tri_vert)
add_host_shader(fsr.comp fsr_easu_comp SAMPLE_EASU=1)
add_host_shader(fsr.comp fsr_rcas_comp SAMPLE_RCAS=1)
add_host_shader(post_process.frag post_process_frag)
add_host_shader(buffer_multi_copy.comp buffer_multi_copy_comp)
foreach(BPP IN ITEMS 8 16 32 64 96 128)
    add_host_shader(tiling.comp tiling_micro_${BPP}_comp BITS_PER_PIXEL=${BPP} IS_MACRO_TILED=0)
    add_host_shader(tiling.comp tiling_macro_${BPP}_comp BITS_PER_PIXEL=${BPP} IS_MACRO_TILED=1)
endforeach()
add_custom_target(host_shaders DEPENDS ${SHADER_HEADERS})

file(GLOB_RECURSE VIDEO_CORE CONFIGURE_DEPENDS shadps4/video_core/*.cpp)
file(GLOB_RECURSE RECOMPILER CONFIGURE_DEPENDS shadps4/shader_recompiler/*.cpp)
list(FILTER VIDEO_CORE EXCLUDE REGEX "renderdoc\\.cpp$")
set(COMMON
    shadps4/common/decoder.cpp shadps4/common/error.cpp
    shadps4/common/io_file.cpp shadps4/common/native_clock.cpp shadps4/common/number_utils.cpp
    shadps4/common/path_util.cpp shadps4/common/rdtsc.cpp shadps4/common/spin_lock.cpp shadps4/common/recursive_lock.cpp
    shadps4/common/string_util.cpp shadps4/common/thread.cpp shadps4/common/signal_context.cpp
    shim/common/logging/log.cpp)
file(GLOB AVPLAYER CONFIGURE_DEPENDS shadps4/core/libraries/avplayer/*.cpp)
pkg_check_modules(FFMPEG REQUIRED IMPORTED_TARGET libavformat libavcodec libavutil libswscale libswresample)
file(GLOB SHIM_SOURCES CONFIGURE_DEPENDS shim/*.cpp shim/*/*.cpp)
# Windows: a DLL cannot leave the runtime_* symbols for order1886-runtime.exe to resolve, so the
# library is static there and linked into the executable.
if (WIN32)
    set(PS4GPU_KIND STATIC)
else()
    set(PS4GPU_KIND SHARED)
endif()
add_library(ps4gpu ${PS4GPU_KIND} ${VIDEO_CORE} ${RECOMPILER} ${COMMON} ${SHIM_SOURCES}
    shadps4/core/libraries/gnmdriver/gnmdriver.cpp
    shadps4/core/libraries/videoout/driver.cpp shadps4/core/libraries/videoout/video_out.cpp
    shadps4/core/libraries/kernel/equeue.cpp ${AVPLAYER}
    shadps4/core/libraries/videodec/video_utils.cpp)
add_dependencies(ps4gpu host_shaders)
# In-game settings menu: Dear ImGui (third_party/imgui, MIT) with its Vulkan backend, and an
# embedded Cyrillic font (third_party/fonts).
target_sources(ps4gpu PRIVATE third_party/imgui/imgui.cpp third_party/imgui/imgui_draw.cpp
    third_party/imgui/imgui_tables.cpp third_party/imgui/imgui_widgets.cpp
    third_party/imgui/backends/imgui_impl_vulkan.cpp)
target_include_directories(ps4gpu PRIVATE third_party/imgui third_party/imgui/backends)
target_compile_definitions(ps4gpu PRIVATE IMGUI_IMPL_VULKAN_NO_PROTOTYPES
    PS4_FONT_PATH="${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/DejaVuSans.ttf")
set_source_files_properties(shim/ps4_overlay.cpp PROPERTIES
    OBJECT_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/fonts/DejaVuSans.ttf)
target_include_directories(ps4gpu PRIVATE shim shadps4 ${SHADER_INCLUDE} third_party/gcn/include third_party/half/include)
target_compile_definitions(ps4gpu PRIVATE BOOST_ASIO_STANDALONE NDEBUG)
target_compile_definitions(ps4gpu PUBLIC ORDER1886_RUNTIME=1)
target_compile_options(ps4gpu PRIVATE -Wno-deprecated-declarations -Wno-missing-field-initializers)
# Runtime symbols (runtime_memory_*, runtime_process_*) resolve against order1886-runtime.
if (NOT WIN32)
    target_link_options(ps4gpu PRIVATE -Wl,--allow-shlib-undefined)
endif()
target_link_libraries(ps4gpu PUBLIC Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum
    tsl::robin_map GPUOpen::VulkanMemoryAllocator PkgConfig::XXHASH PkgConfig::SDL3 PkgConfig::FFMPEG miniz::miniz Zydis::Zydis sirit)
target_include_directories(ps4gpu PRIVATE third_party/xbyak)
if (WIN32)
    # Guest code is entered with the System V ABI; NOMINMAX/WIN32_LEAN_AND_MEAN keep
    # <windows.h> out of the way of std::min/max and the Vulkan/SDL headers.
    target_compile_definitions(ps4gpu PUBLIC NOMINMAX WIN32_LEAN_AND_MEAN)
    target_compile_options(ps4gpu PRIVATE -include ${CMAKE_CURRENT_SOURCE_DIR}/shim/ps4_win_compat.h)
    target_link_libraries(ps4gpu PUBLIC Vulkan::Vulkan ws2_32 bcrypt ntdll synchronization winmm pdh)
else()
    target_link_libraries(ps4gpu PUBLIC PkgConfig::X11)
endif()

# Windows: ps4gpu is a static library there, so the loader and the HLE runtime are
# linked here, where CMake knows its dependencies (build.sh builds them with ninja).
if (WIN32)
    enable_language(RC)
    file(GLOB PS4_RUNTIME CONFIGURE_DEPENDS ../src/runtime*.c)
    file(GLOB PS4_ATRAC9 CONFIGURE_DEPENDS ../third_party/LibAtrac9/C/src/*.c)
    add_library(atrac9 STATIC ${PS4_ATRAC9})
    target_compile_options(atrac9 PRIVATE -w)
    set_target_properties(atrac9 PROPERTIES C_STANDARD 99 INTERPROCEDURAL_OPTIMIZATION OFF)
    add_executable(order1886-runtime ../src/probe.c ${PS4_RUNTIME} ../src/compat_win.c ../src/cpu_check.c ../src/vulkan_smoke.c
        ../src/isa_rewrite.c ../src/isa_emulate.c
        ../packaging/windows/order1886-runtime.rc)
    set_target_properties(order1886-runtime PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_definitions(order1886-runtime PRIVATE ORDER1886_RUNTIME=1)
    target_compile_options(order1886-runtime PRIVATE $<$<COMPILE_LANGUAGE:C>:-Wall -Wextra -Werror>)
    target_include_directories(order1886-runtime PRIVATE .. ../src)
    target_link_libraries(order1886-runtime PRIVATE ps4gpu atrac9 onecore bcrypt ws2_32 -pthread)
    # The PS4 range (64 GiB - 1 TiB) must stay free: no high-entropy ASLR for heaps and stacks.
    # The guest main thread runs on the process stack: 16 MiB, committed (no stack probes).
    target_link_options(order1886-runtime PRIVATE -Wl,--disable-high-entropy-va "SHELL:-Xlinker --stack -Xlinker 16777216,16777216")
    # Port: runtime unit tests (ninja -C out/gpu mp3-test videodec-test services-test).
    add_executable(mp3-test EXCLUDE_FROM_ALL ../tests/test_mp3.c ../src/runtime_mp3.c ../src/compat_win.c)
    add_executable(videodec-test EXCLUDE_FROM_ALL ../tests/test_videodec.c ../src/compat_win.c)
    add_executable(services-test EXCLUDE_FROM_ALL ../tests/test_services.c ../src/compat_win.c)
    add_executable(content-test EXCLUDE_FROM_ALL ../tests/test_content.c ../src/runtime_content.c ../src/compat_win.c)
    set_target_properties(content-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_include_directories(content-test PRIVATE .. ../src)
    target_compile_options(content-test PRIVATE -Wall -Wextra -Werror)
    target_link_libraries(content-test PRIVATE onecore bcrypt -pthread)
    foreach(test runtime-keys event-flag memory-hooks)
        string(REPLACE "-" "_" test_source ${test})
        add_executable(${test}-test EXCLUDE_FROM_ALL ../tests/test_${test_source}.c ../src/compat_win.c)
        set_target_properties(${test}-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
        target_include_directories(${test}-test PRIVATE .. ../src)
        target_compile_options(${test}-test PRIVATE -Wall -Wextra -Werror)
        target_link_libraries(${test}-test PRIVATE onecore bcrypt -pthread)
    endforeach()
    foreach(test mp3-test videodec-test services-test)
        set_target_properties(${test} PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
        target_compile_options(${test} PRIVATE -Wall -Wextra -Werror)
        target_include_directories(${test} PRIVATE .. ../src)
        target_link_libraries(${test} PRIVATE atrac9 PkgConfig::FFMPEG bcrypt -pthread)
    endforeach()
    add_executable(pad-test EXCLUDE_FROM_ALL ../tests/test_pad.c ../src/compat_win.c)
    set_target_properties(pad-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_options(pad-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_include_directories(pad-test PRIVATE .. ../src)
    target_link_libraries(pad-test PRIVATE PkgConfig::SDL3 onecore bcrypt -pthread)
    add_executable(pad-map-test EXCLUDE_FROM_ALL ../tests/test_pad_map.c ../src/compat_win.c)
    set_target_properties(pad-map-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_options(pad-map-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_include_directories(pad-map-test PRIVATE .. ../src)
    target_link_libraries(pad-map-test PRIVATE PkgConfig::SDL3 bcrypt -pthread)
    add_executable(audio-downmix-test EXCLUDE_FROM_ALL ../tests/test_audio_downmix.c ../src/compat_win.c)
    set_target_properties(audio-downmix-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_options(audio-downmix-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_include_directories(audio-downmix-test PRIVATE .. ../src)
    target_link_libraries(audio-downmix-test PRIVATE PkgConfig::SDL3 bcrypt -pthread)
    add_executable(cpu-check-test EXCLUDE_FROM_ALL ../tests/test_cpu_check.c)
    set_target_properties(cpu-check-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_options(cpu-check-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_include_directories(cpu-check-test PRIVATE .. ../src)
    # isa_emulate runs inside guest code: no XMM/YMM. The test runs the real instructions as its oracle.
    add_executable(isa-emulate-test EXCLUDE_FROM_ALL ../tests/test_isa_emulate.c ../src/isa_emulate.c)
    set_source_files_properties(../src/isa_emulate.c PROPERTIES COMPILE_OPTIONS "-mgeneral-regs-only")
    set_source_files_properties(../tests/test_isa_emulate.c PROPERTIES COMPILE_OPTIONS "-mbmi;-mlzcnt;-mmovbe")
    set_target_properties(isa-emulate-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_options(isa-emulate-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_include_directories(isa-emulate-test PRIVATE .. ../src)
    # Stubs and patched sites run for real in an RWX region; the fixture path is the first argument.
    add_executable(isa-stub-test EXCLUDE_FROM_ALL ../tests/test_isa_stub.c ../src/isa_rewrite.c ../src/isa_emulate.c)
    set_source_files_properties(../tests/test_isa_stub.c PROPERTIES COMPILE_OPTIONS "-mbmi;-mlzcnt")
    set_target_properties(isa-stub-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_options(isa-stub-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_include_directories(isa-stub-test PRIVATE .. ../src)
    target_link_libraries(isa-stub-test PRIVATE bcrypt -pthread)
    add_executable(tsc-clock-test EXCLUDE_FROM_ALL ../tests/test_tsc_clock.c ../src/compat_win.c)
    set_target_properties(tsc-clock-test PROPERTIES C_STANDARD 11 C_EXTENSIONS OFF)
    target_compile_options(tsc-clock-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
    target_include_directories(tsc-clock-test PRIVATE .. ../src)
    target_link_libraries(tsc-clock-test PRIVATE bcrypt -pthread)
    add_executable(ps4-gpu-capabilities ../tools/gpu_capabilities.c ../packaging/windows/ps4-gpu-capabilities.rc)
    target_include_directories(ps4-gpu-capabilities PRIVATE shadps4)
    target_link_libraries(ps4-gpu-capabilities PRIVATE Vulkan::Vulkan)
endif()

# Explicit test targets; neither launches the game nor needs a Vulkan device.
add_executable(pipeline-binary-cache-test EXCLUDE_FROM_ALL ../tests/test_pipeline_binary_cache.cpp
    ../tests/test_gpu_runtime_stubs.cpp)
target_compile_definitions(pipeline-binary-cache-test PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_include_directories(pipeline-binary-cache-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(pipeline-binary-cache-test PRIVATE ps4gpu)

add_executable(order-shader-math-test EXCLUDE_FROM_ALL
    ../tests/test_order1886_shader_math.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(order-shader-math-test PRIVATE shim shadps4 third_party/gcn/include)
target_compile_definitions(order-shader-math-test PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_link_libraries(order-shader-math-test PRIVATE ps4gpu)
if(WIN32)
    target_sources(order-shader-math-test PRIVATE ../src/compat_win.c)
    target_compile_definitions(order-shader-math-test PRIVATE sigjmp_buf=ps4_jmp_buf)
    target_compile_options(order-shader-math-test PRIVATE
        -include ${CMAKE_CURRENT_SOURCE_DIR}/../src/compat_win.h)
    target_link_libraries(order-shader-math-test PRIVATE onecore)
endif()
target_compile_options(pipeline-binary-cache-test PRIVATE -fPIC)
if (WIN32)
    target_sources(pipeline-binary-cache-test PRIVATE ../src/compat_win.c)
    target_compile_definitions(pipeline-binary-cache-test PRIVATE sigjmp_buf=ps4_jmp_buf)
    target_compile_options(pipeline-binary-cache-test PRIVATE
        -include ${CMAKE_CURRENT_SOURCE_DIR}/../src/compat_win.h)
    target_link_libraries(pipeline-binary-cache-test PRIVATE onecore)
endif()
add_executable(pipeline-binary-initialization-test EXCLUDE_FROM_ALL
    ../tests/test_pipeline_binary_initialization.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_compile_definitions(pipeline-binary-initialization-test PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
target_include_directories(pipeline-binary-initialization-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(pipeline-binary-initialization-test PRIVATE ps4gpu)
target_compile_options(pipeline-binary-initialization-test PRIVATE -fPIC)
if (WIN32)
    target_sources(pipeline-binary-initialization-test PRIVATE ../src/compat_win.c)
    target_compile_definitions(pipeline-binary-initialization-test PRIVATE sigjmp_buf=ps4_jmp_buf)
    target_compile_options(pipeline-binary-initialization-test PRIVATE
        -include ${CMAKE_CURRENT_SOURCE_DIR}/../src/compat_win.h)
    target_link_libraries(pipeline-binary-initialization-test PRIVATE onecore)
endif()
set_source_files_properties(../tests/test_pipeline_binary_cache.cpp PROPERTIES
    COMPILE_OPTIONS "-fvisibility=hidden;-fvisibility-inlines-hidden")
add_executable(png-decode-test EXCLUDE_FROM_ALL ../tests/test_png_decode.cpp shim/ps4_png.cpp)
target_compile_options(png-decode-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_link_libraries(png-decode-test PRIVATE PkgConfig::FFMPEG)
add_executable(aliasing-test EXCLUDE_FROM_ALL ../tests/test_aliasing.cpp
    shadps4/video_core/texture_cache/aliasing.cpp shadps4/video_core/texture_cache/host_compatibility.cpp)
target_compile_options(aliasing-test PRIVATE -UNDEBUG)
target_include_directories(aliasing-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(aliasing-test PRIVATE Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum)
add_executable(depth-stencil-state-test EXCLUDE_FROM_ALL ../tests/test_depth_stencil_state.cpp)
add_executable(order-render-baseline-test EXCLUDE_FROM_ALL ../tests/test_order1886_render_baseline.cpp)
target_include_directories(order-render-baseline-test PRIVATE shim shadps4 third_party/gcn/include)
target_compile_definitions(order-render-baseline-test PRIVATE ORDER1886_RUNTIME=1)
target_compile_options(order-render-baseline-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_link_libraries(order-render-baseline-test PRIVATE Vulkan::Headers GPUOpen::VulkanMemoryAllocator fmt::fmt Boost::headers magic_enum::magic_enum)
add_executable(srt-descriptor-validation-test EXCLUDE_FROM_ALL ../tests/test_srt_descriptor_validation.cpp)
target_include_directories(srt-descriptor-validation-test PRIVATE shim shadps4 third_party/gcn/include)
target_compile_definitions(srt-descriptor-validation-test PRIVATE ORDER1886_RUNTIME=1 NOMINMAX WIN32_LEAN_AND_MEAN)
target_compile_options(srt-descriptor-validation-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_link_libraries(srt-descriptor-validation-test PRIVATE Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum)
add_executable(async-compiler-test EXCLUDE_FROM_ALL ../tests/test_async_compiler.cpp)
target_compile_options(async-compiler-test PRIVATE -UNDEBUG)
target_include_directories(async-compiler-test PRIVATE shadps4)
add_executable(warmup-inbox-test EXCLUDE_FROM_ALL ../tests/test_warmup_inbox.cpp)
target_compile_options(warmup-inbox-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(warmup-inbox-test PRIVATE shadps4)
add_executable(wave-stats-test EXCLUDE_FROM_ALL ../tests/test_wave_stats.cpp)
target_compile_options(wave-stats-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(wave-stats-test PRIVATE shadps4)
add_executable(pass-census-test EXCLUDE_FROM_ALL ../tests/test_pass_census.cpp)
target_compile_options(pass-census-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(pass-census-test PRIVATE shadps4)
add_executable(frame-capture-test EXCLUDE_FROM_ALL ../tests/test_frame_capture.cpp
    shadps4/video_core/renderer_vulkan/vk_frame_capture.cpp)
target_compile_options(frame-capture-test PRIVATE -UNDEBUG)
target_include_directories(frame-capture-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(frame-capture-test PRIVATE Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum)
add_executable(amd-paths-test EXCLUDE_FROM_ALL ../tests/test_amd_paths.cpp)
target_compile_options(amd-paths-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(amd-paths-test PRIVATE shadps4)
add_executable(async-pipeline-cache-test EXCLUDE_FROM_ALL ../tests/test_async_pipeline_cache.cpp)
target_compile_options(async-pipeline-cache-test PRIVATE -UNDEBUG)
target_include_directories(async-pipeline-cache-test PRIVATE shadps4)
target_link_libraries(async-pipeline-cache-test PRIVATE Vulkan::Vulkan)
add_executable(async-fetch-snapshot-test EXCLUDE_FROM_ALL ../tests/test_async_fetch_snapshot.cpp
    shadps4/shader_recompiler/frontend/fetch_shader.cpp
    shadps4/shader_recompiler/frontend/decode.cpp
    shadps4/shader_recompiler/frontend/format.cpp)
target_compile_options(async-fetch-snapshot-test PRIVATE -UNDEBUG)
target_include_directories(async-fetch-snapshot-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(async-fetch-snapshot-test PRIVATE Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum)
target_compile_options(depth-stencil-state-test PRIVATE -UNDEBUG)
target_include_directories(depth-stencil-state-test PRIVATE shim shadps4 third_party/gcn/include)
target_link_libraries(depth-stencil-state-test PRIVATE Vulkan::Headers fmt::fmt Boost::headers magic_enum::magic_enum)

add_executable(scene-resolution-test EXCLUDE_FROM_ALL ../tests/test_scene_resolution.cpp ../tests/test_gpu_runtime_stubs.cpp)
target_include_directories(scene-resolution-test PRIVATE shim shadps4 third_party/gcn/include)
# The test's Vulkan-Hpp inline methods have a different set of platform extensions
# from vk_platform.cpp. Keep them local and use an explicit dispatcher in the test.
target_compile_options(scene-resolution-test PRIVATE -UNDEBUG -fPIC)
set_source_files_properties(../tests/test_scene_resolution.cpp PROPERTIES
    COMPILE_OPTIONS "-fvisibility=hidden;-fvisibility-inlines-hidden")
target_link_libraries(scene-resolution-test PRIVATE ps4gpu)


add_executable(frame-trace-test EXCLUDE_FROM_ALL ../tests/test_frame_trace.cpp)
target_include_directories(frame-trace-test PRIVATE shim)
target_compile_options(frame-trace-test PRIVATE -UNDEBUG)

add_executable(perf-overlay-test EXCLUDE_FROM_ALL ../tests/test_perf_overlay.cpp
    shim/ps4_settings.cpp)
target_include_directories(perf-overlay-test PRIVATE shim)
target_compile_options(perf-overlay-test PRIVATE -UNDEBUG)
add_executable(readback-queue-test EXCLUDE_FROM_ALL ../tests/test_readback_queue.cpp)
target_include_directories(readback-queue-test PRIVATE shadps4)
target_compile_options(readback-queue-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(wait-diagnostics-test EXCLUDE_FROM_ALL ../tests/test_wait_diagnostics.cpp)
target_include_directories(wait-diagnostics-test PRIVATE shadps4)
target_compile_options(wait-diagnostics-test PRIVATE -UNDEBUG)
add_executable(readback-sources-test EXCLUDE_FROM_ALL ../tests/test_readback_sources.cpp)
target_include_directories(readback-sources-test PRIVATE shadps4)
target_compile_options(readback-sources-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
add_executable(page-state-test EXCLUDE_FROM_ALL ../tests/test_page_state.cpp)
target_include_directories(page-state-test PRIVATE ../tests/stubs shim shadps4)
target_link_libraries(page-state-test PRIVATE Boost::headers)
target_compile_options(page-state-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
