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
        if (value.Type() == IR::Type::F64) return static_cast<float>(value.F64());
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
    case IR::Opcode::FPOrdEqual64:
    case IR::Opcode::FPOrdEqual32: return arg(0) == arg(1);
    case IR::Opcode::FPOrdNotEqual64:
    case IR::Opcode::FPOrdNotEqual32: return !std::isnan(arg(0)) && !std::isnan(arg(1)) && arg(0) != arg(1);
    case IR::Opcode::FPOrdLessThan64:
    case IR::Opcode::FPOrdLessThan32: return arg(0) < arg(1);
    case IR::Opcode::FPOrdLessThanEqual64:
    case IR::Opcode::FPOrdLessThanEqual32: return arg(0) <= arg(1);
    case IR::Opcode::FPOrdGreaterThan64:
    case IR::Opcode::FPOrdGreaterThan32: return arg(0) > arg(1);
    case IR::Opcode::FPOrdGreaterThanEqual64:
    case IR::Opcode::FPOrdGreaterThanEqual32: return arg(0) >= arg(1);
    case IR::Opcode::FPUnordEqual64:
    case IR::Opcode::FPUnordEqual32: return std::isnan(arg(0)) || std::isnan(arg(1)) || arg(0) == arg(1);
    case IR::Opcode::FPUnordNotEqual64:
    case IR::Opcode::FPUnordNotEqual32: return std::isnan(arg(0)) || std::isnan(arg(1)) || arg(0) != arg(1);
    case IR::Opcode::FPUnordLessThan64:
    case IR::Opcode::FPUnordLessThan32: return std::isnan(arg(0)) || std::isnan(arg(1)) || arg(0) < arg(1);
    case IR::Opcode::FPUnordLessThanEqual64:
    case IR::Opcode::FPUnordLessThanEqual32: return std::isnan(arg(0)) || std::isnan(arg(1)) || arg(0) <= arg(1);
    case IR::Opcode::FPUnordGreaterThan64:
    case IR::Opcode::FPUnordGreaterThan32: return std::isnan(arg(0)) || std::isnan(arg(1)) || arg(0) > arg(1);
    case IR::Opcode::FPUnordGreaterThanEqual64:
    case IR::Opcode::FPUnordGreaterThanEqual32: return std::isnan(arg(0)) || std::isnan(arg(1)) || arg(0) >= arg(1);
    case IR::Opcode::FPIsNan64:
    case IR::Opcode::FPIsNan32: return std::isnan(arg(0));
    case IR::Opcode::GetExec: return accumulator;
    case IR::Opcode::LogicalAnd: return arg(0) != 0 && arg(1) != 0;
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

float Translate(Gcn::Opcode opcode, float a, float b = 0, float c = 0,
                bool compare = false, bool wide = false) {
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
    inst.dst[1].field = Gcn::OperandField::ScalarGPR;
    inst.dst[1].code = 2;
    const float values[]{a, b, c};
    for (unsigned i = 0; i < 3; ++i) {
        inst.src[i].field = Gcn::OperandField::LiteralConst;
        inst.src[i].code = wide ? u32(std::bit_cast<u64>(double(values[i])) >> 32)
                                : std::bit_cast<u32>(values[i]);
    }
    translator.EmitVectorAlu(inst);
    for (auto it = block.rbegin(); it != block.rend(); ++it) {
        if (compare && it->GetOpcode() == IR::Opcode::Ballot)
            return Evaluate(it->Arg(0), c);
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
    for (const auto opcode : {Opcode::V_CMP_NGE_F32, Opcode::V_CMP_NGT_F32,
                             Opcode::V_CMP_NLE_F32, Opcode::V_CMP_NEQ_F32,
                             Opcode::V_CMP_NLT_F32, Opcode::V_CMPX_NGE_F32,
                             Opcode::V_CMPX_NLG_F32, Opcode::V_CMPX_NGT_F32,
                             Opcode::V_CMPX_NLE_F32, Opcode::V_CMPX_NEQ_F32,
                             Opcode::V_CMPX_NLT_F32}) {
        assert(Translate(opcode, nan, 1, 1, true) == 1);
        assert(Translate(opcode, 1, nan, 1, true) == 1);
        assert(Translate(opcode, nan, nan, 1, true) == 1);
    }
    for (const auto opcode : {Opcode::V_CMP_LT_F32, Opcode::V_CMP_EQ_F32,
                             Opcode::V_CMP_LE_F32, Opcode::V_CMP_GT_F32,
                             Opcode::V_CMP_LG_F32, Opcode::V_CMP_GE_F32}) {
        assert(Translate(opcode, nan, 1, 1, true) == 0);
        assert(Translate(opcode, 1, nan, 1, true) == 0);
    }
    assert(Translate(Opcode::V_CMPX_TRU_F32, 1, 2, 1, true) == 1);
    assert(Translate(Opcode::V_CMPX_TRU_F32, 1, 2, 0, true) == 0);
    assert(Translate(Opcode::V_CMPX_NGE_F32, nan, 1, 0, true) == 0);
    assert(Translate(Opcode::V_CMP_NGE_F32, 1, 2, 1, true) == 1);
    assert(Translate(Opcode::V_CMP_NGE_F32, 2, 1, 1, true) == 0);
    for (const auto opcode : {Opcode::V_CMP_NGE_F64, Opcode::V_CMP_NGT_F64,
                             Opcode::V_CMP_NLE_F64, Opcode::V_CMP_NEQ_F64,
                             Opcode::V_CMP_NLT_F64}) {
        assert(Translate(opcode, nan, 1, 1, true, true) == 1);
        assert(Translate(opcode, 1, nan, 1, true, true) == 1);
    }
    for (const auto opcode : {Opcode::V_CMP_LT_F64, Opcode::V_CMP_EQ_F64,
                             Opcode::V_CMP_LE_F64, Opcode::V_CMP_GT_F64,
                             Opcode::V_CMP_LG_F64, Opcode::V_CMP_GE_F64}) {
        assert(Translate(opcode, nan, 1, 1, true, true) == 0);
        assert(Translate(opcode, 1, nan, 1, true, true) == 0);
    }
    assert(Translate(Opcode::V_CMP_NGE_F64, 1, 2, 1, true, true) == 1);
    assert(Translate(Opcode::V_CMP_NGE_F64, 2, 1, 1, true, true) == 0);
    assert(Translate(Opcode::V_RSQ_LEGACY_F32, 0) == 0);
    assert(Translate(Opcode::V_RSQ_LEGACY_F32, -0.0f) == 0);
    assert(Translate(Opcode::V_RSQ_LEGACY_F32, 4) == 0.5f);
    assert(std::isnan(Translate(Opcode::V_RSQ_LEGACY_F32, -1)));
    std::puts("order-shader-math-test: passed");
}
