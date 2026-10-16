// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

// The Order baseline uses the original PS4 targets and shaders. These interfaces
// disable optional host reconstruction passes for this build; they do
// not implement or replace any guest API, shader, draw, or synchronization work.

#include <algorithm>
#include <array>
#include <functional>
#include <optional>
#include "video_core/renderer_vulkan/motion_history.h"
#include "video_core/renderer_vulkan/scene_resolution.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image.h"

namespace VideoCore { class TextureCache; }
namespace Vulkan {
class Instance;
class Scheduler;
class Runtime;
struct RenderState;

class SceneTargets {
public:
    using Lookup = std::function<VideoCore::Image*(VideoCore::ImageId, u64)>;
    SceneTargets(const Instance&, Scheduler&, Runtime&, VideoCore::TextureCache&) {}
    SceneTargets(const Instance&, Scheduler&, Runtime&, Lookup) {}
    static constexpr bool SetSize(SceneResolution::Size) { return false; }
    static constexpr SceneResolution::Size Size() { return {0, 0}; }
    static constexpr bool Reduced() { return false; }
    static constexpr bool Eligible(const VideoCore::Image&) { return false; }
    static constexpr bool EligibleScene(const VideoCore::Image&) { return false; }
    static SceneResolution::Size ProxySize(const VideoCore::Image& image, u32 level = 0) {
        return {std::max(1u, image.info.size.width >> level),
                std::max(1u, image.info.size.height >> level)};
    }
    struct Target {
        vk::Image image;
        vk::ImageView view;
        vk::ImageLayout layout;
        vk::ImageUsageFlags usage;
    };
    static Target Attachment(VideoCore::ImageId, const VideoCore::ImageViewInfo&) { return {}; }
    static Target Read(VideoCore::ImageId, const VideoCore::ImageViewInfo&,
                       vk::PipelineStageFlags2 = vk::PipelineStageFlagBits2::eComputeShader,
                       vk::AccessFlags2 = vk::AccessFlagBits2::eShaderRead) { return {}; }
    static void NativeAccess(VideoCore::Image&, vk::AccessFlags2) {}
    static std::optional<Target> SampleProxy(const VideoCore::Image&, const VideoCore::ImageViewInfo&) {
        return std::nullopt;
    }
    static constexpr bool ProxyCurrent(const VideoCore::Image&, u32 = 0, u32 = 1) { return false; }
    static constexpr vk::ImageLayout PrepareSample(const VideoCore::Image&, u32 = 0) {
        return vk::ImageLayout::eUndefined;
    }
    static constexpr u64 Generation() { return 0; }
    static constexpr bool Tracks(u64) { return false; }
    static void ResolveAll() {}
    bool debug = false;
};

class ObjectMotion {
public:
    ObjectMotion(const Instance&, Scheduler&) {}
    using DrawInfo = Motion::Draw;
    static constexpr bool Enabled() { return false; }
    static constexpr u32 PrepareDraw(const DrawInfo&) { return 0; }
    static constexpr bool Moving(const Motion::History::GateKey&, u64) { return false; }
    template <class Scan>
    static Motion::IndexRangeCache::Result IndexRange(const Motion::IndexRangeCache::Key&, Scan&&) {
        return {};
    }
    static void Attach(RenderState&, u32, u32) {}
    static void OnFrameStart() {}
    static void InvalidateHistory() {}
    static vk::ImageView PrepareRead(vk::CommandBuffer, u32, u32, bool& valid) {
        valid = false;
        return {};
    }
    static vk::ImageView View() { return {}; }
    static vk::Image Image(u32, u32) { return {}; }
};

class CameraMotion {
public:
    CameraMotion(const Instance&, Scheduler&, VideoCore::TextureCache&, Runtime&) {}
    static constexpr bool Enabled() { return false; }
    static constexpr bool Ready() { return false; }
    static void InvalidateHistory() {}
    static void SetObjectMotion(ObjectMotion*) {}
    static void SetJitter(std::array<float, 2>) {}
    static VideoCore::ImageId Depth() { return {}; }
    static vk::ImageView ObjectMotionView() { return {}; }
    static vk::Image ObjectMotionImage(u32, u32) { return {}; }
    static constexpr std::array<u32, 2> RenderSize() { return {}; }
    static constexpr float VerticalFov() { return 0; }
    static constexpr float Near() { return 0; }
    static constexpr std::array<std::array<float, 4>, 3> TaaDepthParameters() { return {}; }
    static void RecordMotion(vk::CommandBuffer, vk::ImageView, vk::ImageView, u32, u32) {}
    static void OnConstants(const float*) {}
    static void OnGBufferPass(VideoCore::ImageId) {}
    static void OnDisplayPass(VideoCore::ImageId) {}
};

class TemporalUpscaler {
public:
    TemporalUpscaler(const Instance&, Scheduler&, VideoCore::TextureCache&, Runtime&,
                     CameraMotion&, SceneTargets&) {}
    static constexpr bool Enabled() { return false; }
    static void OnSceneColor(VideoCore::ImageId) {}
    static void OnBlendedSceneDraw() {}
    static void OnSceneComposite() {}
    static void OnDispatch(u64) {}
    static constexpr bool OnFrameStart() { return false; }
    static constexpr bool RasterScaling() { return false; }
    static constexpr float SceneMipBias() { return 0; }
    static constexpr u64 RedirectState() { return 0; }
    static constexpr std::array<float, 2> Jitter() { return {}; }
    static void OnDraw(u64, VideoCore::ImageId, VideoCore::ImageId, bool) {}
    static void OnColorTarget(VideoCore::ImageId) {}
    struct Target {
        vk::ImageView view;
        vk::ImageLayout layout;
        u32 width, height;
        bool native_ui = false;
    };
    static constexpr bool RedirectColor(VideoCore::ImageId, const VideoCore::ImageViewInfo&, Target&) { return false; }
    static constexpr bool RedirectDepth(VideoCore::ImageId, Target&) { return false; }
    static constexpr bool RedirectSampled(VideoCore::ImageId, const VideoCore::ImageViewInfo&,
                                          vk::ImageView&, vk::ImageLayout&) { return false; }
    static constexpr bool RedirectsSampled(VideoCore::ImageId) { return false; }
    struct Display {
        vk::Image image;
        vk::Format format;
        u32 width, height;
    };
    static constexpr bool DisplayOverride(VAddr, Display&) { return false; }
};
} // namespace Vulkan
