// SPDX-License-Identifier: GPL-2.0-or-later
// Exercise the real GCN translator and evaluate its emitted scalar IR on the CPU.
#undef NDEBUG
#include <cassert>
#include <bit>
#include <cmath>
#include <cstdio>
#include <limits>
#include "shader_recompiler/frontend/opcodes.h"
#include "shader_recompiler/frontend/translate/translate.h"
#include "shader_recompiler/profile.h"

namespace {
using namespace Shader;
float Evaluate(const IR::Value& value, float accumulator) {
    if (value.IsImmediate()) {
        if (value.Type() == IR::Type::U32) return std::bit_cast<float>(value.U32());
        if (value.Type() == IR::Type::U1) return value.U1() ? 1.0f : 0.0f;
        return value.F32();
    }
    const auto* inst = value.Inst();
    const auto arg = [&](unsigned i) { return Evaluate(inst->Arg(i), accumulator); };
    switch (inst->GetOpcode()) {
    case IR::Opcode::BitCastU32F32:
    case IR::Opcode::BitCastF32U32: return arg(0);
    case IR::Opcode::GetVectorRegister: return accumulator;
    case IR::Opcode::FPMul32: return arg(0) * arg(1);
    case IR::Opcode::FPAdd32: return arg(0) + arg(1);
    case IR::Opcode::FPFma32: return std::fma(arg(0), arg(1), arg(2));
    case IR::Opcode::FPOrdEqual32: return arg(0) == arg(1);
    case IR::Opcode::FPOrdLessThan32: return arg(0) < arg(1);
    case IR::Opcode::LogicalOr: return arg(0) != 0 || arg(1) != 0;
    case IR::Opcode::SelectF32: return arg(0) != 0 ? arg(1) : arg(2);
    case IR::Opcode::FPIsInf32: return std::isinf(arg(0));
    case IR::Opcode::FPRecip32: return 1.0f / arg(0);
    case IR::Opcode::FPRecipSqrt32: return 1.0f / std::sqrt(arg(0));
    case IR::Opcode::FPLog2: return std::log2(arg(0));
    default: std::fprintf(stderr, "Unexpected IR opcode %u\n", unsigned(inst->GetOpcode()));
        std::abort();
    }
}

float Translate(Gcn::Opcode opcode, float a, float b = 0, float c = 0) {
    Common::ObjectPool<IR::Inst> pool;
    IR::Block block{pool};
    Info info{};
    info.hw_stage = HwStage::Compute;
    info.sw_stage = SwStage::Compute;
    RuntimeInfo runtime{};
    runtime.hw_stage = HwStage::Compute;
    Profile profile{};
    Gcn::Translator translator{info, runtime, profile};
    translator.EmitPrologue(&block);
    Gcn::GcnInst inst{};
    inst.opcode = opcode;
    inst.dst[0].field = Gcn::OperandField::VectorGPR;
    inst.dst[0].code = 0;
    const float values[]{a, b, c};
    for (unsigned i = 0; i < 3; ++i) {
        inst.src[i].field = Gcn::OperandField::LiteralConst;
        inst.src[i].code = std::bit_cast<u32>(values[i]);
    }
    translator.EmitVectorAlu(inst);
    for (auto it = block.rbegin(); it != block.rend(); ++it) {
        if (it->GetOpcode() == IR::Opcode::SetVectorRegister)
            return Evaluate(it->Arg(1), c);
    }
    std::abort();
}
} // namespace

int main() {
#ifdef _WIN32
    _set_error_mode(_OUT_TO_STDERR);
#endif
    using Shader::Gcn::Opcode;
    const float inf = std::numeric_limits<float>::infinity();
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float max = std::numeric_limits<float>::max();
    for (const auto opcode : {Opcode::V_MAC_LEGACY_F32, Opcode::V_MAD_LEGACY_F32}) {
        for (const float exceptional : {inf, -inf, nan}) {
            assert(Translate(opcode, 0, exceptional, 7) == 7);
            assert(Translate(opcode, exceptional, -0.0f, 7) == 7);
        }
        assert(Translate(opcode, 2, 3, 7) == 13);
    }
    assert(Translate(Opcode::V_MUL_LEGACY_F32, 0, inf) == 0);
    assert(std::isnan(Translate(Opcode::V_MAD_F32, 0, inf, 7)));
    assert(Translate(Opcode::V_LOG_CLAMP_F32, 0) == -max);
    assert(Translate(Opcode::V_RCP_CLAMP_F32, 0) == max);
    assert(Translate(Opcode::V_RCP_CLAMP_F32, -0.0f) == -max);
    assert(Translate(Opcode::V_RSQ_CLAMP_F32, 0) == max);
    assert(Translate(Opcode::V_RCP_CLAMP_F32, 2) == 0.5f);
    assert(Translate(Opcode::V_RSQ_CLAMP_F32, 4) == 0.5f);
    assert(std::isnan(Translate(Opcode::V_RSQ_CLAMP_F32, -1)));
    assert(std::isnan(Translate(Opcode::V_LOG_CLAMP_F32, nan)));
    assert(std::isinf(Translate(Opcode::V_LOG_F32, 0)));
    std::puts("order-shader-math-test: passed");
}
