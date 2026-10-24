// SPDX-License-Identifier: GPL-2.0-or-later
// MUBUF ADDR64 loads must bind the pointer's uniform base as a bounded GPU buffer without DMA.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <span>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#endif

#include "core/emulator_settings.h"
#include "shader_recompiler/info.h"
#include "shader_recompiler/ir/ir_emitter.h"
#include "shader_recompiler/profile.h"
#include "shader_recompiler/recompiler.h"
#include "shader_recompiler/runtime_info.h"

namespace {
using namespace Shader;

void Require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "%s\n", message);
        std::exit(1);
    }
}

// Compute shader: v0 is the thread id, s[4:5] is a 64-bit pointer in user data.
constexpr u32 Token = 0xbeeb03ff;        // s_mov_b32 vcc_hi, <literal>
constexpr u32 MovV1S5 = 0x7e020205;      // v_mov_b32 v1, s5
constexpr u32 MovV1V0 = 0x7e020300;      // v_mov_b32 v1, v0 (lane-varying pointer high word)
constexpr u32 AndV0 = 0x360000bf;        // v_and_b32 v0, 63, v0
constexpr u32 AddLo = 0x4a000004;        // v_add_i32 v0, vcc, s4, v0
constexpr u32 AddcHi = 0x50020280;       // v_addc_u32 v1, vcc, 0, v1, vcc
constexpr u32 LoadAddr64 = 0xe0308000;   // buffer_load_dword v2, v[0:1], s[8:11], 0 addr64
constexpr u32 LoadOperands = 0x80020200; //   vaddr=v0 vdata=v2 srsrc=s[8:11] soffset=0
constexpr u32 EndPgm = 0xbf810000;

struct Result {
    bool uses_dma;
    u32 readconst_buffers;
    u32 readconst_size_bytes;
    u8 load_mask;
    std::array<SharpLocation, 2> locations;
    u32 unlowered_readconsts;
};

Result Translate(std::vector<u32> code, HwStage hw = HwStage::Compute,
                 SwStage sw = SwStage::Compute, bool print = false) {
    static const std::array<u32, ShaderParams::NumShaderUserData> user_data{};
    Pools pools;
    Info info{hw, sw, ShaderParams{.user_data = user_data, .code = code, .hash = 0x1234}};
    RuntimeInfo runtime{};
    runtime.Initialize(hw, sw);
    runtime.props.num_user_data = 16;
    if (hw == HwStage::Fragment) {
        // Unknown interpolants: give every parameter a slot so interpolation translates.
        runtime.hw.fs.num_inputs = 32;
        for (u32 i = 0; i < 32; ++i) {
            runtime.hw.fs.inputs[i].param_index = u8(i);
        }
    }
    Profile profile{};
    profile.supported_spirv = 0x00010600;
    profile.support_int64 = true;
    profile.supports_fragment_shader_barycentric = true;
    profile.subgroup_size = 64;
    const auto program = TranslateProgram(code, pools, info, runtime, profile);

    Result result{.uses_dma = info.uses_dma};
    for (const auto& buffer : info.buffers) {
        if (print) {
            std::printf("  buffer type=%u size=%u mask=%#x loc=%u,%u,%u,%u imm=%#x,%#x,%#x,%#x\n",
                        u32(buffer.buffer_type), buffer.readconst_size_bytes,
                        buffer.sharp_fetch.load_mask, buffer.sharp_fetch.offsets[0],
                        buffer.sharp_fetch.offsets[1], buffer.sharp_fetch.offsets[2],
                        buffer.sharp_fetch.offsets[3], buffer.sharp_fetch.immediates[0],
                        buffer.sharp_fetch.immediates[1], buffer.sharp_fetch.immediates[2],
                        buffer.sharp_fetch.immediates[3]);
        }
        if (buffer.buffer_type != BufferType::ReadConst) {
            continue;
        }
        ++result.readconst_buffers;
        result.readconst_size_bytes = buffer.readconst_size_bytes;
        result.load_mask = buffer.sharp_fetch.load_mask;
        result.locations = {buffer.sharp_fetch.offsets[0], buffer.sharp_fetch.offsets[1]};
    }
    for (const auto* block : program.blocks) {
        for (const auto& inst : *block) {
            if (inst.GetOpcode() == IR::Opcode::ReadConst && inst.Flags<u32>() == 0) {
                ++result.unlowered_readconsts;
            }
        }
    }
    if (print) {
        std::printf("  uses_dma=%d translation_failed=%d readconst_buffers=%u unlowered=%u\n",
                    info.uses_dma, info.translation_failed, result.readconst_buffers,
                    result.unlowered_readconsts);
    }
    return result;
}

#ifdef _WIN32
extern "C" int ps4gpu_handle_fault(void* ucontext, void* address);

// The SRT walker runs at compile time against the probe's zero user data; its fault handler
// patches the faulting load to read zero, as the loader's vectored handler lets it in game.
LONG CALLBACK WalkerFault(EXCEPTION_POINTERS* info) {
    const auto* record = info->ExceptionRecord;
    if (record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && record->NumberParameters >= 2 &&
        ps4gpu_handle_fault(info, reinterpret_cast<void*>(record->ExceptionInformation[1]))) {
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}
#endif

// Probe mode: compile dumped GCN binaries (vs_/fs_/cs_ prefix picks the stage) and print the
// resulting buffer bindings, so a DMA-off compile can be compared with a DMA-on one offline.
int Probe(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IONBF, 0);
#ifdef _WIN32
    AddVectoredExceptionHandler(1, WalkerFault);
#endif
    for (int i = 1; i < argc; ++i) {
        const std::filesystem::path path{argv[i]};
        std::ifstream file{path, std::ios::binary};
        std::vector<char> bytes{std::istreambuf_iterator<char>(file), {}};
        std::vector<u32> code(bytes.size() / sizeof(u32));
        std::memcpy(code.data(), bytes.data(), code.size() * sizeof(u32));
        const auto name = path.filename().string();
        HwStage hw = HwStage::Compute;
        SwStage sw = SwStage::Compute;
        if (name.starts_with("vs_")) {
            hw = HwStage::Vertex;
            sw = SwStage::Vertex;
        } else if (name.starts_with("fs_")) {
            hw = HwStage::Fragment;
            sw = SwStage::Fragment;
        } else if (name.starts_with("ls_")) {
            hw = HwStage::Local;
            sw = SwStage::Vertex;
        } else if (name.starts_with("hs_")) {
            hw = HwStage::Hull;
            sw = SwStage::TessellationControl;
        } else if (name.starts_with("ds_")) {
            hw = HwStage::Vertex;
            sw = SwStage::TessellationEval;
        }
        std::printf("%s (%zu dwords, dma=%d)\n", name.c_str(), code.size(),
                    EmulatorSettings.IsDirectMemoryAccessEnabled());
        Translate(std::move(code), hw, sw, true);
    }
    return 0;
}
} // namespace

int main(int argc, char** argv) {
#ifdef _WIN32
    _set_error_mode(_OUT_TO_STDERR);
#endif
    if (argc > 1) {
        return Probe(argc, argv);
    }
    Require(!EmulatorSettings.IsDirectMemoryAccessEnabled(), "Run with DMA disabled");

    // Unbounded lane offset: the base s[4:5] is bound with the fixed ADDR64 extent.
    auto unbounded = Translate({Token, 0, MovV1S5, AddLo, AddcHi, LoadAddr64, LoadOperands, EndPgm});
    Require(!unbounded.uses_dma, "ADDR64 load must not require DMA");
    Require(unbounded.readconst_buffers == 1, "ADDR64 load must bind one ReadConst buffer");
    Require(unbounded.load_mask == 3 && unbounded.locations == std::array<SharpLocation, 2>{4, 5},
            "ReadConst buffer must fetch its pointer from user data s[4:5]");
    Require(unbounded.readconst_size_bytes == 4_MB, "Unbounded lane offset uses the ADDR64 cap");
    Require(unbounded.unlowered_readconsts == 0, "ADDR64 ReadConst must be lowered to a buffer");

    // Bounded lane byte offset (v0 & 63 -> dword index <= 15): the extent follows the bound.
    auto bounded =
        Translate({Token, 0, MovV1S5, AndV0, AddLo, AddcHi, LoadAddr64, LoadOperands, EndPgm});
    Require(bounded.readconst_buffers == 1 && bounded.readconst_size_bytes == 16 * sizeof(u32),
            "Bounded lane offset sizes the buffer from the index bound");

    // Lane-varying pointer high word: no uniform base, the load reads zero without DMA.
    auto varying = Translate({Token, 0, MovV1V0, AddLo, AddcHi, LoadAddr64, LoadOperands, EndPgm});
    Require(!varying.uses_dma && varying.readconst_buffers == 0 &&
                varying.unlowered_readconsts == 0,
            "Non-uniform ADDR64 base must degrade to zero, not DMA or an assertion");

    std::puts("ADDR64 loads bind bounded ReadConst buffers without DMA");
    return 0;
}
