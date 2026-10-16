#include <array>
#include <cassert>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <span>
#include <vector>
#include "common/object_pool.h"
#include "shader_recompiler/frontend/control_flow_graph.h"
#include "shader_recompiler/ir/passes/sampled_image_uniform_guard_pass.h"
#include "shader_recompiler/ir/reg.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-variable"
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wreorder"
#include "shader_recompiler/specialization.h"
#pragma GCC diagnostic pop

// Windows CRT assertions can open a dialog; fixtures must fail without leaving a helper alive.
#undef assert
#define assert(condition) do { if (!(condition)) { \
    std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); std::_Exit(87); \
} } while (false)

namespace Common::Log {
bool ShouldLog(Level) { return false; }
void Write(std::string_view, Level, const char*, int, const char*, std::string&&) {}
}
void assert_fail_impl() { std::_Exit(86); }
[[noreturn]] void unreachable_impl() { std::_Exit(86); }

using namespace Shader;
using namespace Shader::Optimization;
namespace IR = Shader::IR;

struct Graph {
    Common::ObjectPool<IR::Inst> pool{128};
    std::vector<std::unique_ptr<IR::Block>> storage;
    std::vector<std::unique_ptr<Gcn::Block>> cfg;
    std::vector<IR::Block*> blocks;
    ResourceDiscoveryList resources;

    explicit Graph(u32 count = 4) {
        for (u32 i = 0; i < count; ++i) {
            storage.push_back(std::make_unique<IR::Block>(pool));
            cfg.push_back(std::make_unique<Gcn::Block>());
            blocks.push_back(storage.back().get());
            blocks.back()->cfg_block = cfg.back().get();
            cfg.back()->ir_block = blocks.back();
        }
    }
    IR::Value Emit(u32 block, IR::Opcode op, std::initializer_list<IR::Value> args, u32 flags = 0) {
        auto* b = blocks[block];
        auto it = b->PrependNewInst(b->end(), op, args, flags);
        return IR::Value{&*it};
    }
    IR::Value Count(u32 slot = 37) {
        auto root = Emit(0, IR::Opcode::CompositeConstructU32x2, {IR::Value{u32{0}}, IR::Value{u32{0}}});
        return Emit(0, IR::Opcode::ReadConst, {root, IR::Value{u32{325}}}, slot);
    }
    void Guard(IR::Value count, bool execz = true, bool opaque_and = true, u32 threshold = 9) {
        auto predicate = Emit(0, IR::Opcode::ULessThan32, {IR::Value{threshold}, count});
        auto unknown = Emit(0, IR::Opcode::Phi, {}, u32(IR::Type::U1));
        auto unknown_mask = Emit(0, IR::Opcode::Ballot, {unknown});
        auto selected = Emit(0, IR::Opcode::SelectU64, {predicate, unknown_mask, IR::Value{u64{0}}});
        auto mask = opaque_and ? Emit(0, IR::Opcode::BitwiseAnd64, {unknown_mask, selected}) : selected;
        auto exec = Emit(0, IR::Opcode::InverseBallot, {mask});
        auto cond = execz ? Emit(0, IR::Opcode::LogicalNot, {exec}) : exec;
        auto ref = Emit(0, IR::Opcode::ConditionRef, {cond});
        blocks[0]->branch_cond = IR::U1{ref};
        cfg[0]->branch_true = cfg[execz ? 2 : 1].get();
        cfg[0]->branch_false = cfg[execz ? 1 : 2].get();
        blocks[0]->AddBranch(cfg[0]->branch_true->ir_block);
        blocks[0]->AddBranch(cfg[0]->branch_false->ir_block);
        blocks[1]->AddBranch(blocks[3]);
        blocks[2]->AddBranch(blocks[3]);
    }
    void Image(u32 block = 1, u32 first = 8, IR::Opcode op = IR::Opcode::ImageSampleRaw,
               bool depth = false, bool r128 = false, bool sampler_postop = false) {
        IR::TextureInstInfo flags{};
        flags.is_depth.Assign(depth);
        flags.is_r128.Assign(r128);
        auto inst = Emit(block, op, {IR::Value{u32{0}}, IR::Value{u32{0}}, IR::Value{u32{0}},
                                    IR::Value{u32{0}}, IR::Value{u32{0}}, IR::Value{u32{0}}}, flags.raw);
        ResourceDiscovery use{};
        use.user = inst.Inst();
        use.sharps[0].num_dwords = r128 ? 4 : 8;
        use.sharps[1].num_dwords = 4;
        if (sampler_postop) use.sharps[1].post_op = SharpFetchPostOp::DisableAnisoIfSingleLod;
        for (u32 i = 0; i < use.sharps[0].num_dwords; ++i) {
            use.sharps[0].dwords[i] = Emit(0, IR::Opcode::GetUserData, {IR::Value{IR::ScalarReg{first + i}}});
        }
        for (u32 i = 0; i < 4; ++i) use.sharps[1].dwords[i] = IR::Value{u32{0}};
        resources.push_back(use);
    }
    void Analyze() { AnalyzeSampledImageUniformGuards(blocks, resources); }
};

struct Snapshot {
    std::array<u32, 64> data{};
    size_t size = data.size();
    std::span<const u32> FlatUserData() const { return {data.data(), size}; }
    bool IsImageBaseMapped(VAddr) const { return true; }
};

int main(int argc, char** argv) {
    // Actual EXECZ shape, opaque Phi, and backedge: the mandatory edge remains valid.
    Graph g;
    g.Guard(g.Count()); g.Image(); g.blocks[3]->AddBranch(g.blocks[0]); g.Analyze();
    assert(g.resources[0].uniform_guard.enabled);
    assert(g.resources[0].uniform_guard.count.offsets[0] == 37);
    Snapshot snapshot;
    snapshot.data[37] = 9;
    assert(g.resources[0].uniform_guard.IsInactive(snapshot));
    snapshot.data[37] = 10;
    assert(!g.resources[0].uniform_guard.IsInactive(snapshot));
    snapshot.size = 37;
    assert(!g.resources[0].uniform_guard.IsInactive(snapshot));
    snapshot.size = 64;
    auto unknown = g.resources[0].uniform_guard;
    unknown.count.offsets[0] = UNKNOWN_LOCATION;
    assert(!unknown.IsInactive(snapshot));
    if (argc > 1) {
        ImageResource invalid{};
        invalid.uniform_guard = g.resources[0].uniform_guard;
        invalid.sharp_fetch.load_mask = 0xff;
        invalid.sharp_fetch.offsets.fill(UNKNOWN_LOCATION);
        snapshot.data[37] = 10;
        if (std::strcmp(argv[1], "missing-count") == 0) snapshot.size = 0;
        (void)invalid.GetSharp(snapshot);
        return 99; // Active or unknown guards must retain required-source failure.
    }

    Graph polarity;
    polarity.Guard(polarity.Count(41), false); polarity.Image(); polarity.Analyze();
    assert(polarity.resources[0].uniform_guard.enabled);
    assert(polarity.resources[0].uniform_guard.count.offsets[0] == 41);
    Graph wrong;
    wrong.Guard(wrong.Count()); wrong.Image(2); wrong.Analyze();
    assert(!wrong.resources[0].uniform_guard.enabled);
    Graph alternate;
    alternate.Guard(alternate.Count()); alternate.blocks[2]->AddBranch(alternate.blocks[1]);
    alternate.Image(); alternate.Analyze();
    assert(!alternate.resources[0].uniform_guard.enabled);
    Graph shared;
    shared.Guard(shared.Count()); shared.Image(); shared.Image(3); shared.Analyze();
    assert(!shared.resources[0].uniform_guard.enabled && !shared.resources[1].uniform_guard.enabled);
    Graph compatible;
    compatible.Guard(compatible.Count()); compatible.Image(); compatible.Image(); compatible.Analyze();
    assert(compatible.resources[0].uniform_guard.enabled && compatible.resources[1].uniform_guard.enabled);
    Graph incompatible;
    incompatible.Guard(incompatible.Count()); incompatible.Image(); incompatible.Image(1, 8, IR::Opcode::ImageSampleRaw, true);
    incompatible.Analyze(); assert(!incompatible.resources[0].uniform_guard.enabled);
    Graph unresolved;
    unresolved.Guard(unresolved.Count()); unresolved.Image(); unresolved.Image();
    unresolved.resources[1].sharps[0].dwords[7] = unresolved.Emit(0, IR::Opcode::Phi, {}, u32(IR::Type::U32));
    unresolved.Analyze(); assert(!unresolved.resources[0].uniform_guard.enabled);
    Graph r128;
    r128.Guard(r128.Count()); r128.Image(); r128.Image(1, 8, IR::Opcode::ImageSampleRaw, false, true);
    r128.Analyze(); assert(!r128.resources[0].uniform_guard.enabled);
    Graph sampler;
    sampler.Guard(sampler.Count()); sampler.Image(); sampler.Image(3, 4, IR::Opcode::ImageSampleRaw, false, false, true);
    sampler.Analyze(); assert(!sampler.resources[0].uniform_guard.enabled);
    Graph phi;
    auto unknown_count = phi.Emit(0, IR::Opcode::Phi, {}, u32(IR::Type::U32));
    phi.Guard(unknown_count); phi.Image(); phi.Analyze();
    assert(!phi.resources[0].uniform_guard.enabled);
    Graph dynamic;
    dynamic.Guard(dynamic.Count(0)); dynamic.Image(); dynamic.Analyze();
    assert(!dynamic.resources[0].uniform_guard.enabled);
    Graph gpu;
    auto gpu_count = gpu.Emit(0, IR::Opcode::LoadBufferU32, {IR::Value{u32{0}}, IR::Value{u32{0}}});
    gpu.Guard(gpu_count); gpu.Image(); gpu.Analyze();
    assert(!gpu.resources[0].uniform_guard.enabled);
    Graph dag;
    dag.Guard(dag.Count()); dag.Image();
    auto a = dag.Emit(0, IR::Opcode::Ballot, {IR::Value{true}});
    auto b = a;
    for (u32 i = 0; i < 80; ++i) {
        auto next = dag.Emit(0, IR::Opcode::BitwiseAnd64, {a, b}); a = b; b = next;
    }
    auto logical_not = dag.blocks[0]->branch_cond.Inst()->Arg(0).Inst();
    auto mask = logical_not->Arg(0).Inst()->Arg(0).Inst();
    mask->SetArg(0, b);
    dag.Analyze();
    assert(dag.resources[0].uniform_guard.enabled);

    ImageResource image{};
    image.uniform_guard = g.resources[0].uniform_guard;
    image.declared_binding_count = 1;
    image.sharp_fetch.load_mask = 0xff;
    image.sharp_fetch.offsets.fill(UNKNOWN_LOCATION); // inactive path must not fetch this
    snapshot.data[37] = 1;
    const auto placeholder = image.GetSharp(snapshot);
    assert(!placeholder && placeholder.GetType() == AmdGpu::ImageType::Color2D);
    assert(placeholder.GetNumberFmt() == AmdGpu::NumberFormat::Unorm);
    assert(image.NumBindings(snapshot) == 1);
    image.is_atomic = true;
    assert(!image.IsUniformlyInactive(snapshot));
    image.is_atomic = false;
    auto actual = AmdGpu::Image::Null(false);
    actual.type = u64(AmdGpu::ImageType::Cube);
    actual.base_address = 0x1234;
    actual.width = actual.height = actual.pitch = 255;
    image.sharp_fetch.load_mask = 0;
    std::memcpy(image.sharp_fetch.immediates.data(), &actual, sizeof(actual));
    snapshot.data[37] = 10;
    assert(image.GetSharp(snapshot).IsCube());
    assert(image.NumBindings(snapshot) == 1);
    snapshot.size = 0;
    assert(!image.IsUniformlyInactive(snapshot));

    StageSpecialization inactive, active;
    inactive.info = active.info = reinterpret_cast<const Info*>(1);
    inactive.images.emplace_back(); active.images.emplace_back();
    inactive.images[0].is_inactive = true;
    assert(!(inactive == active) && !(active == inactive)); // all-unbound shortcut
    active.bitset.set(0);
    assert(!(inactive == active) && !(active == inactive)); // wildcard shortcut
    static_assert(std::is_trivially_copyable_v<UniformResourceGuard>);
    std::array<std::byte, sizeof(image)> bytes{};
    std::memcpy(bytes.data(), &image, sizeof(image));
    ImageResource restored{};
    std::memcpy(&restored, bytes.data(), sizeof(restored));
    assert(restored.uniform_guard == image.uniform_guard && restored.declared_binding_count == 1);
}
