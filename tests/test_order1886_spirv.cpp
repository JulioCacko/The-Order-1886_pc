// SPDX-License-Identifier: GPL-2.0-or-later
// Inspect real backend output: eager OpSelect must never execute two atomic writes.
#include <bit>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <span>
#include <stdexcept>
#include <vector>

#include <spirv/unified1/GLSL.std.450.h>
#include "shader_recompiler/backend/spirv/emit_spirv_instructions.h"
#include "shader_recompiler/backend/spirv/spirv_emit_context.h"

namespace {
using namespace Shader;
using namespace Shader::Backend::SPIRV;

void Require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

struct Fixture {
    Profile profile{};
    Info info{};
    RuntimeInfo runtime{};
    Backend::Bindings bindings{};
    std::unique_ptr<EmitContext> context;

    explicit Fixture(bool trinary = false) {
        profile.supported_spirv = 0x00010600;
        profile.support_int64 = true;
        profile.supports_trinary_minmax = trinary;
        profile.supports_buffer_fp32_atomic_min_max = false;
        profile.supports_image_fp32_atomic_min_max = false;
        info.hw_stage = HwStage::Compute;
        info.sw_stage = SwStage::Compute;
        info.uses_fp64 = true;
        runtime.Initialize(info.hw_stage, info.sw_stage);
        context = std::make_unique<EmitContext>(profile, runtime, info, bindings);
        context->AddCapability(spv::Capability::Float64);
        context->AddCapability(spv::Capability::Int8);
        context->AddCapability(spv::Capability::Int16);
        context->AddCapability(spv::Capability::Int64);
    }

    void Begin() {
        auto& ctx = *context;
        const auto main = ctx.OpFunction(ctx.void_id, spv::FunctionControlMask::MaskNone,
                                         ctx.TypeFunction(ctx.void_id));
        ctx.AddEntryPoint(spv::ExecutionModel::GLCompute, main, "main", ctx.interfaces);
        ctx.AddExecutionMode(main, spv::ExecutionMode::LocalSize, 1u, 1u, 1u);
        ctx.AddLabel();
    }

    std::vector<u32> Finish() {
        context->OpReturn();
        context->OpFunctionEnd();
        return context->Assemble();
    }
};

struct Instruction {
    spv::Op op;
    u32 block;
    std::span<const u32> words;
};

std::vector<Instruction> Decode(const std::vector<u32>& code) {
    Require(code.size() >= 5 && code[0] == 0x07230203, "Invalid SPIR-V header");
    std::vector<Instruction> instructions;
    u32 block = 0;
    for (size_t offset = 5; offset < code.size();) {
        const size_t count = code[offset] >> 16;
        Require(count != 0 && count <= code.size() - offset, "Invalid instruction length");
        const auto words = std::span(code).subspan(offset, count);
        const auto op = static_cast<spv::Op>(words[0] & 0xffff);
        if (op == spv::Op::OpLabel) {
            block = words[1];
        }
        instructions.push_back({op, block, words});
        offset += count;
    }
    return instructions;
}

const Instruction& Definition(const std::vector<Instruction>& instructions, u32 id) {
    for (const auto& instruction : instructions) {
        switch (instruction.op) {
        case spv::Op::OpConstant:
        case spv::Op::OpExtInst:
        case spv::Op::OpIsNan:
        case spv::Op::OpLogicalOr:
        case spv::Op::OpSelect:
        case spv::Op::OpBitcast:
        case spv::Op::OpINotEqual:
        case spv::Op::OpBitFieldUExtract:
            if (instruction.words[2] == id) {
                return instruction;
            }
            break;
        default:
            break;
        }
    }
    throw std::runtime_error("Missing SSA definition");
}

// Evaluate only the selected SSA expression; FMin/FMax on NaN is deliberately rejected.
double Evaluate(const std::vector<Instruction>& instructions, u32 id) {
    const auto& instruction = Definition(instructions, id);
    const auto w = instruction.words;
    switch (instruction.op) {
    case spv::Op::OpConstant:
        return w.size() == 5 ? std::bit_cast<double>(u64(w[3]) | (u64(w[4]) << 32))
                             : std::bit_cast<float>(w[3]);
    case spv::Op::OpIsNan:
        return std::isnan(Evaluate(instructions, w[3]));
    case spv::Op::OpLogicalOr:
        return Evaluate(instructions, w[3]) || Evaluate(instructions, w[4]);
    case spv::Op::OpSelect:
        return Evaluate(instructions, w[3]) ? Evaluate(instructions, w[4])
                                           : Evaluate(instructions, w[5]);
    case spv::Op::OpExtInst: {
        const auto a = Evaluate(instructions, w[5]);
        const auto b = Evaluate(instructions, w[6]);
        switch (w[4]) {
        case GLSLstd450FMin:
        case GLSLstd450FMax:
            Require(!std::isnan(a) && !std::isnan(b), "Undefined NaN min/max in selected result");
            break;
        default:
            break;
        }
        if (w[4] == GLSLstd450NMin || w[4] == GLSLstd450FMin) {
            return std::fmin(a, b);
        }
        if (w[4] == GLSLstd450NMax || w[4] == GLSLstd450FMax) {
            return std::fmax(a, b);
        }
        throw std::runtime_error("Unexpected math instruction");
    }
    default:
        throw std::runtime_error("Unexpected SSA operation");
    }
}

std::vector<u32> CheckNanMath(bool trinary) {
    Fixture fixture(trinary);
    auto& ctx = *fixture.context;
    fixture.Begin();
    struct Expected {
        Sirit::Id id;
        double value;
    };
    std::vector<Expected> results;
    const auto nan = std::numeric_limits<float>::quiet_NaN();
    const auto infinity = std::numeric_limits<float>::infinity();
    for (float value : {nan, -infinity, -2.0f, -0.0f, 0.25f, 1.0f, 2.0f, infinity}) {
        const auto expected = std::fmin(std::fmax(value, 0.0f), 1.0f);
        results.push_back({EmitFPSaturate32(ctx, ctx.ConstF32(value)), expected});
        results.push_back({EmitFPSaturate64(ctx, ctx.Constant(ctx.F64[1], double(value))), expected});
    }
    for (size_t nan_operand = 0; nan_operand < 4; ++nan_operand) {
        float values[]{3.0f, -2.0f, 1.0f};
        if (nan_operand < 3) {
            values[nan_operand] = nan;
        }
        const auto a = ctx.ConstF32(values[0]);
        const auto b = ctx.ConstF32(values[1]);
        const auto c = ctx.ConstF32(values[2]);
        const auto minimum = std::fmin(values[0], std::fmin(values[1], values[2]));
        const auto maximum = std::fmax(values[0], std::fmax(values[1], values[2]));
        results.push_back({EmitFPMinTri32(ctx, a, b, c), minimum});
        results.push_back({EmitFPMaxTri32(ctx, a, b, c), maximum});
        results.push_back({EmitFPMedTri32(ctx, a, b, c), nan_operand < 3 ? minimum : 1.0f});
    }
    auto code = fixture.Finish();
    const auto instructions = Decode(code);
    for (const auto& expected : results) {
        Require(Evaluate(instructions, expected.id.value) == expected.value,
                "NaN-sensitive generated expression returned the wrong result");
    }
    return code;
}

std::vector<u32> CheckAtomicBranches() {
    Fixture fixture;
    auto& ctx = *fixture.context;
    const auto array = ctx.TypeRuntimeArray(ctx.U32[1]);
    ctx.Decorate(array, spv::Decoration::ArrayStride, 4u);
    const auto structure = ctx.TypeStruct(array);
    ctx.Decorate(structure, spv::Decoration::Block);
    ctx.MemberDecorate(structure, 0, spv::Decoration::Offset, 0u);
    const auto buffer = ctx.AddGlobalVariable(
        ctx.TypePointer(spv::StorageClass::StorageBuffer, structure), spv::StorageClass::StorageBuffer);
    ctx.Decorate(buffer, spv::Decoration::DescriptorSet, 0u);
    ctx.Decorate(buffer, spv::Decoration::Binding, 0u);
    ctx.buffers.emplace_back();
    ctx.buffers.back().Alias(EmitContext::PointerType::U32) = {
        buffer, ctx.TypePointer(spv::StorageClass::StorageBuffer, ctx.U32[1])};
    ctx.interfaces.push_back(buffer);

    const auto image_type = ctx.TypeImage(ctx.U32[1], spv::Dim::Dim2D, false, false, false, 2,
                                         spv::ImageFormat::R32ui);
    const auto image = ctx.AddGlobalVariable(
        ctx.TypePointer(spv::StorageClass::UniformConstant, image_type),
        spv::StorageClass::UniformConstant);
    ctx.Decorate(image, spv::Decoration::DescriptorSet, 0u);
    ctx.Decorate(image, spv::Decoration::Binding, 1u);
    ctx.images.push_back({.id = image});
    ctx.image_u32 = ctx.TypePointer(spv::StorageClass::Image, ctx.U32[1]);
    ctx.interfaces.push_back(image);

    fixture.Begin();
    const auto coords = ctx.ConstantComposite(ctx.S32[2], ctx.Constant(ctx.S32[1], 0),
                                              ctx.Constant(ctx.S32[1], 0));
    using Emitter = Sirit::Id (*)(EmitContext&, IR::Inst*, u32, Sirit::Id, Sirit::Id);
    const Emitter emitters[]{EmitBufferAtomicFMin32, EmitBufferAtomicFMax32,
                              EmitImageAtomicFMin32, EmitImageAtomicFMax32};
    for (size_t i = 0; i < 4; ++i) {
        emitters[i](ctx, nullptr, 0, i < 2 ? ctx.u32_zero_value : coords, ctx.ConstF32(-0.5f));
    }
    auto code = fixture.Finish();
    const auto instructions = Decode(code);
    const spv::Op negative_ops[]{spv::Op::OpAtomicUMax, spv::Op::OpAtomicUMin,
                                spv::Op::OpAtomicUMax, spv::Op::OpAtomicUMin};
    const spv::Op positive_ops[]{spv::Op::OpAtomicSMin, spv::Op::OpAtomicSMax,
                                spv::Op::OpAtomicSMin, spv::Op::OpAtomicSMax};
    size_t selections = 0;
    size_t atomics = 0;
    u32 previous_merge = 0;
    for (size_t i = 0; i < instructions.size(); ++i) {
        const auto& instruction = instructions[i];
        if (instruction.op >= spv::Op::OpAtomicSMin && instruction.op <= spv::Op::OpAtomicUMax) {
            ++atomics;
        }
        if (instruction.op != spv::Op::OpSelectionMerge) {
            continue;
        }
        Require(selections < 4, "Unexpected atomic selection");
        Require(previous_merge == 0 || instruction.block == previous_merge,
                "Consecutive atomic splits must continue in the prior merge block");
        const auto merge = instruction.words[1];
        const auto& branch = instructions.at(i + 1);
        Require(branch.op == spv::Op::OpBranchConditional, "Atomic selection must branch");
        const auto& sign_test = Definition(instructions, branch.words[1]);
        Require(sign_test.op == spv::Op::OpINotEqual,
                "Atomic branch must test the sign bit");
        const auto& sign_extract = Definition(instructions, sign_test.words[3]);
        Require(sign_extract.op == spv::Op::OpBitFieldUExtract &&
                    Definition(instructions, sign_extract.words[4]).words[3] == 31 &&
                    Definition(instructions, sign_extract.words[5]).words[3] == 1 &&
                    Definition(instructions, sign_test.words[4]).words[3] == 0,
                "Atomic branches must distinguish the float sign bit");
        for (size_t arm = 0; arm < 2; ++arm) {
            const auto label = branch.words[2 + arm];
            size_t writes = 0;
            bool joins_merge = false;
            for (const auto& candidate : instructions) {
                if (candidate.block != label) {
                    continue;
                }
                if (candidate.op == (arm == 0 ? negative_ops[selections] : positive_ops[selections])) {
                    ++writes;
                }
                if (candidate.op == spv::Op::OpBranch && candidate.words[1] == merge) {
                    joins_merge = true;
                }
            }
            Require(writes == 1 && joins_merge, "Each exclusive arm must write once and rejoin");
        }
        bool has_phi = false;
        for (const auto& candidate : instructions) {
            if (candidate.block == merge && candidate.op == spv::Op::OpPhi) {
                has_phi = candidate.words.size() == 7 && candidate.words[4] == branch.words[2] &&
                          candidate.words[6] == branch.words[3];
            }
        }
        Require(has_phi, "Atomic result must merge both exclusive predecessor values");
        previous_merge = merge;
        ++selections;
    }
    Require(selections == 4 && atomics == 8, "Every float atomic must use two exclusive arms");
    Require(ctx.last_label.value == previous_merge, "Consecutive fallback splits lost the final label");
    return code;
}

void WriteModule(const std::filesystem::path& path, const std::vector<u32>& code) {
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(code.data()), code.size() * sizeof(u32));
    Require(bool(out), "Could not write validation module");
}
} // namespace

int main(int argc, char** argv) {
#ifdef _WIN32
    _set_error_mode(_OUT_TO_STDERR);
#endif
    try {
        const auto atomics = CheckAtomicBranches();
        const auto math = CheckNanMath(false);
        const auto trinary_math = CheckNanMath(true);
        if (argc > 1) {
            std::filesystem::create_directories(argv[1]);
            WriteModule(std::filesystem::path(argv[1]) / "order-atomics.spv", atomics);
            WriteModule(std::filesystem::path(argv[1]) / "order-nan-math.spv", math);
            WriteModule(std::filesystem::path(argv[1]) / "order-nan-math-trinary.spv", trinary_math);
        }
        std::cout << "Order SPIR-V atomic control flow and NaN math passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
