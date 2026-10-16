// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "shader_recompiler/frontend/control_flow_graph.h"
#include "shader_recompiler/ir/passes/sampled_image_uniform_guard_pass.h"
#include "shader_recompiler/ir/program.h"
#include "shader_recompiler/ir/reg.h"

namespace Shader::Optimization {
namespace {
using Gates = std::vector<UniformResourceGuard>;
struct GateKey {
    const IR::Inst* inst;
    bool positive;
    bool operator==(const GateKey&) const = default;
};
struct GateHash {
    size_t operator()(const GateKey& key) const {
        return std::hash<const IR::Inst*>{}(key.inst) ^ size_t(key.positive);
    }
};
struct GateMemo {
    std::unordered_map<GateKey, Gates, GateHash> results;
    u32 visited{};
    bool exhausted{};
};

std::optional<SharpLocation> SourceLocation(const IR::Value& value) {
    if (value.IsEmpty() || value.IsImmediate()) return std::nullopt;
    const auto* inst = value.Inst();
    if (inst->GetOpcode() == IR::Opcode::GetUserData) {
        const auto reg = u32(inst->Arg(0).ScalarReg());
        if (reg < NUM_USER_DATA_REGS) return SharpLocation(reg);
    } else if (inst->GetOpcode() == IR::Opcode::ReadConst) {
        const auto location = inst->Flags<SharpLocation>();
        // Zero is the unflattened dynamic path, not a usable uniform snapshot slot.
        if (location != 0 && location != UNKNOWN_LOCATION) return location;
    }
    return std::nullopt;
}

void Append(Gates& out, Gates values) {
    for (const auto& gate : values) {
        if (std::ranges::find(out, gate) == out.end()) out.push_back(gate);
    }
}

// Necessary conditions for this value to be nonzero/true. Unknown leaves are opaque:
// AND(unknown, zero) still proves zero, without evaluating the unknown expression.
Gates RequiredGates(IR::Value value, bool positive = true, u32 depth = 0, GateMemo* memo = nullptr) {
    if (!memo) {
        GateMemo state;
        auto result = RequiredGates(value, positive, depth, &state);
        return state.exhausted ? Gates{} : result;
    }
    if (depth > 64 || value.IsEmpty() || value.IsImmediate()) return {};
    const auto* inst = value.Inst();
    const GateKey key{inst, positive};
    if (const auto found = memo->results.find(key); found != memo->results.end()) return found->second;
    if (memo->exhausted || ++memo->visited > 4096) { memo->exhausted = true; return {}; }
    const auto op = inst->GetOpcode();
    const auto compute = [&]() -> Gates {
    if (op == IR::Opcode::ConditionRef) {
        return RequiredGates(inst->Arg(0), positive, depth + 1, memo);
    }
    if (op == IR::Opcode::LogicalNot) {
        return RequiredGates(inst->Arg(0), !positive, depth + 1, memo);
    }
    if (!positive) return {};
    if (op == IR::Opcode::LogicalAnd || op == IR::Opcode::BitwiseAnd64) {
        auto result = RequiredGates(inst->Arg(0), true, depth + 1, memo);
        Append(result, RequiredGates(inst->Arg(1), true, depth + 1, memo));
        return result;
    }
    if (op == IR::Opcode::Ballot || op == IR::Opcode::InverseBallot) {
        return RequiredGates(inst->Arg(0), true, depth + 1, memo);
    }
    if (op == IR::Opcode::SelectU64 && inst->Arg(2).IsImmediate() &&
        inst->Arg(2).U64() == 0) {
        auto result = RequiredGates(inst->Arg(0), true, depth + 1, memo);
        Append(result, RequiredGates(inst->Arg(1), true, depth + 1, memo));
        return result;
    }
    if (op != IR::Opcode::ULessThan32 || !inst->Arg(0).IsImmediate()) return {};
    UniformResourceGuard gate{};
    gate.threshold = inst->Arg(0).U32();
    gate.enabled = true;
    if (inst->Arg(1).IsImmediate()) {
        gate.count.immediates[0] = inst->Arg(1).U32();
    } else if (const auto source = SourceLocation(inst->Arg(1))) {
        gate.count.load_mask = 1;
        gate.count.offsets[0] = *source;
    } else {
        return {};
    }
    return {gate};
    };
    auto result = compute();
    memo->results.emplace(key, result);
    return result;
}

using Reachable = std::unordered_set<const IR::Block*>;
Reachable Reach(IR::Block* entry, const IR::Block* omit_from = nullptr,
                const IR::Block* omit_to = nullptr) {
    Reachable result;
    std::vector<const IR::Block*> queue{entry};
    while (!queue.empty()) {
        const auto* block = queue.back();
        queue.pop_back();
        if (!result.insert(block).second) continue;
        for (const auto* next : block->ImmSuccessors()) {
            if (block != omit_from || next != omit_to) queue.push_back(next);
        }
    }
    return result;
}

struct EdgeProof { Reachable without_edge; Gates gates; };

std::optional<SharpFetch<AmdGpu::Image>> ImageRecipe(const SharpReference& sharp) {
    if (sharp.num_dwords < 4 || sharp.num_dwords > 8) return std::nullopt;
    SharpFetch<AmdGpu::Image> fetch{};
    fetch.offsets.fill(UNKNOWN_LOCATION);
    for (u32 i = 0; i < sharp.num_dwords; ++i) {
        if (sharp.dwords[i].IsImmediate()) {
            fetch.immediates[i] = sharp.dwords[i].U32();
        } else if (const auto source = SourceLocation(sharp.dwords[i])) {
            fetch.load_mask |= u8(1u << i);
            fetch.offsets[i] = *source;
        } else {
            if (i < 4) return std::nullopt;
            fetch.load_mask |= u8(1u << i); // retain unresolved shared-contract aliases
        }
    }
    return fetch;
}

bool SamePrefix(const SharpFetch<AmdGpu::Image>& a, const SharpFetch<AmdGpu::Image>& b) {
    // A four-word/full-width alias is an incompatible shared contract, not a new group.
    for (u32 i = 0; i < 4; ++i) {
        const bool a_load = (a.load_mask >> i) & 1, b_load = (b.load_mask >> i) & 1;
        if (a_load != b_load || (a_load ? a.offsets[i] != b.offsets[i]
                                      : a.immediates[i] != b.immediates[i])) return false;
    }
    return true;
}

bool Eligible(const ResourceDiscovery& use) {
    if (use.user->GetOpcode() != IR::Opcode::ImageSampleRaw || use.sharps[0].num_dwords != 8 ||
        use.sharps[0].post_op != SharpFetchPostOp::None ||
        use.sharps[1].post_op != SharpFetchPostOp::None) return false;
    const auto flags = use.user->Flags<IR::TextureInstInfo>();
    return !flags.is_depth && !flags.is_r128;
}
} // namespace

void AnalyzeSampledImageUniformGuards(std::span<IR::Block* const> blocks,
                                     ResourceDiscoveryList& resources) {
    for (auto& use : resources) use.uniform_guard = {};
    if (blocks.empty() || blocks.size() > 4096) return;
    const auto reachable = Reach(blocks.front());
    std::vector<EdgeProof> edges;
    for (auto* block : blocks) {
        const auto* cfg = block->cfg_block;
        if (!cfg || !cfg->branch_true || !cfg->branch_false ||
            cfg->branch_true == cfg->branch_false || block->ImmSuccessors().size() != 2) continue;
        for (bool positive : {false, true}) {
            auto* next = (positive ? cfg->branch_true : cfg->branch_false)->ir_block;
            if (std::ranges::find(block->ImmSuccessors(), next) == block->ImmSuccessors().end()) continue;
            auto gates = RequiredGates(block->branch_cond, positive);
            if (!gates.empty()) edges.push_back({Reach(blocks.front(), block, next), std::move(gates)});
        }
    }
    struct Group {
        SharpFetch<AmdGpu::Image> recipe;
        bool array{};
        bool valid{true};
        Gates common;
        std::vector<ResourceDiscovery*> uses;
    };
    std::vector<Group> groups;
    for (auto& use : resources) {
        if (!IsImageInstruction(*use.user)) continue;
        const auto recipe = ImageRecipe(use.sharps[0]);
        if (!recipe) continue;
        const auto flags = use.user->Flags<IR::TextureInstInfo>();
        auto found = std::ranges::find_if(groups, [&](const Group& g) { return SamePrefix(g.recipe, *recipe); });
        Gates gates;
        if (reachable.contains(use.user->GetParent())) {
            for (const auto& edge : edges) {
                if (!edge.without_edge.contains(use.user->GetParent())) Append(gates, edge.gates);
            }
        }
        const bool eligible = Eligible(use) && !recipe->UnresolvedDword(UNKNOWN_LOCATION);
        if (found == groups.end()) {
            groups.push_back({*recipe, bool(flags.is_array), eligible, gates, {&use}});
        } else {
            found->valid &= eligible && found->recipe == *recipe && found->array == bool(flags.is_array);
            std::erase_if(found->common, [&](const auto& gate) { return std::ranges::find(gates, gate) == gates.end(); });
            found->uses.push_back(&use);
        }
    }
    // A sampler post-op that reads image LOD information can affect other uses of a
    // shared sampler. Refuse this optimization for every image sharing that sampler.
    for (auto& group : groups) {
        if (!group.valid || group.common.empty() || group.uses.size() > 65535) continue;
        for (const auto* use : group.uses) {
            const auto sampler = ImageRecipe(use->sharps[1]);
            if (!sampler) { group.valid = false; break; }
            for (const auto& other : resources) {
                if (other.user->GetOpcode() != IR::Opcode::ImageSampleRaw) continue;
                const auto other_sampler = ImageRecipe(other.sharps[1]);
                if (other_sampler && SamePrefix(*sampler, *other_sampler) &&
                    other.sharps[1].post_op != SharpFetchPostOp::None) group.valid = false;
            }
        }
        if (group.valid) {
            auto guard = group.common.front();
            for (const auto& candidate : group.common) {
                if (candidate.count == guard.count && candidate.threshold > guard.threshold) guard = candidate;
            }
            guard.proven_uses = static_cast<u16>(group.uses.size());
            for (auto* use : group.uses) use->uniform_guard = guard;
        }
    }
}

void SampledImageUniformGuardPass(IR::Program& program, ResourceDiscoveryList& resources) {
    AnalyzeSampledImageUniformGuards(program.blocks, resources);
}
} // namespace Shader::Optimization
