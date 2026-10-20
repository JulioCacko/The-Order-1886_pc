// SPDX-License-Identifier: GPL-2.0-or-later
//
// A compute shader with shared memory needs barriers. GCN waves share LDS without explicit
// barriers only because they run in lockstep; a host compiler may reorder those accesses. This tree
// used to return early unless the workgroup was exactly one wave, which left such shaders with no
// barrier at all. The pass now emits subgroup-scoped barriers instead, and this drives it with a
// write followed by a read in one block.
//
// Adapted from upstream shadPS4 (GPL-2.0-or-later, same licence).

#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>

#include "common/logging/log.h"
#include "common/object_pool.h"
#include "shader_recompiler/ir/ir_emitter.h"
#include "shader_recompiler/ir/passes/ir_passes.h"
#include "shader_recompiler/ir/program.h"
#include "shader_recompiler/profile.h"
#include "shader_recompiler/runtime_info.h"

// The pass reaches the logging and assertion helpers; the other native tests stub them the same way.
void assert_fail_impl() {
    std::abort();
}
[[noreturn]] void unreachable_impl() {
    std::abort();
}
namespace Common::Log {
bool ShouldLog(Level) {
    return false;
}
void Write(std::string_view, Level, const char*, int, const char*, std::string&&) {}
} // namespace Common::Log

namespace {


using Shader::IR::Opcode;

enum class Body {
    WriteThenRead,
    ReadThenWrite,
    ReadOnly,
};

struct Fixture {
    Common::ObjectPool<Shader::IR::Inst> pool;
    Shader::IR::Block block{pool};
    Shader::Info info{};
    Shader::IR::Program program{info};
    Shader::RuntimeInfo runtime{};
    Shader::Profile profile{};

    explicit Fixture(Body body) {
        // Program keeps its own copy of the info, so it is the one the pass reads.
        program.info.hw_stage = Shader::HwStage::Compute;
        program.info.sw_stage = Shader::SwStage::Compute;
        runtime.Initialize(info.hw_stage, info.sw_stage);
        runtime.hw.cs.shared_memory_size = 0x1000;
        runtime.hw.cs.workgroup_size = {128, 1, 1};
        profile.supported_spirv = 0x00010600;
        profile.needs_lds_barriers = true;

        Shader::IR::IREmitter ir(block);
        const auto zero = ir.Imm32(0);
        const auto address = ir.Imm32(0x100);
        switch (body) {
        case Body::WriteThenRead:
            (void)ir.WriteShared(32, zero, address);
            (void)ir.LoadShared(32, false, address, false);
            break;
        case Body::ReadThenWrite:
            (void)ir.LoadShared(32, false, address, false);
            (void)ir.WriteShared(32, zero, address);
            break;
        case Body::ReadOnly:
            (void)ir.LoadShared(32, false, address, false);
            break;
        }
        ir.Epilogue();

        program.blocks.push_back(&block);
        program.syntax_list.push_back({.data = {.block = &block},
                                       .type = Shader::IR::AbstractSyntaxNode::Type::Block});
        program.syntax_list.push_back({.type = Shader::IR::AbstractSyntaxNode::Type::Return});
    }

    std::size_t count(Opcode wanted) const {
        std::size_t total = 0;
        for (const auto& inst : block.Instructions()) {
            if (inst.GetOpcode() == wanted) {
                ++total;
            }
        }
        return total;
    }

    void run() {
        Shader::Optimization::SharedMemoryBarrierPass(program, runtime, profile);
    }
};

} // Anonymous namespace

int main() {
    // A workgroup larger than one wave keeps its LDS order pinned by a subgroup barrier.
    {
        Fixture fixture{Body::WriteThenRead};
        fixture.run();
        if (fixture.count(Opcode::SubgroupBarrier) == 0) {
            std::puts("a multi-wave workgroup must gain subgroup barriers");
            return EXIT_FAILURE;
        }
        if (fixture.count(Opcode::Barrier) != 0) {
            std::puts("a multi-wave workgroup must not gain a workgroup barrier here");
            return EXIT_FAILURE;
        }
    }

    // A single-wave workgroup keeps the ordinary barrier, as before.
    {
        Fixture fixture{Body::WriteThenRead};
        fixture.runtime.hw.cs.workgroup_size = {64, 1, 1};
        fixture.run();
        if (fixture.count(Opcode::Barrier) == 0) {
            std::puts("a single-wave workgroup must keep the ordinary barrier");
            return EXIT_FAILURE;
        }
        if (fixture.count(Opcode::SubgroupBarrier) != 0) {
            std::puts("a single-wave workgroup must not gain a subgroup barrier");
            return EXIT_FAILURE;
        }
    }

    // Without shared memory there is nothing to order.
    {
        Fixture fixture{Body::WriteThenRead};
        fixture.runtime.hw.cs.shared_memory_size = 0;
        fixture.run();
        if (fixture.count(Opcode::Barrier) + fixture.count(Opcode::SubgroupBarrier) != 0) {
            std::puts("a shader without shared memory must gain no barrier");
            return EXIT_FAILURE;
        }
    }


    std::puts("Shared memory barriers: subgroup-scoped when the workgroup is wider than a wave");
    return EXIT_SUCCESS;
}
