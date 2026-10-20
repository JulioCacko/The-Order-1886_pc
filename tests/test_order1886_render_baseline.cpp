#include <cassert>
#include <cstdlib>
#include <cstring>
#include <type_traits>
#include "ps4_settings.h"
#include "ps4_graphics.h"
#include "video_core/renderer_vulkan/order1886_render_baseline.h"
#include "video_core/renderer_vulkan/vk_blend_rewrite.h"
#include "video_core/amdgpu/ps4_msaa.h"

using namespace Vulkan;
static_assert(!CameraMotion::Enabled() && !CameraMotion::Ready());
static_assert(!ObjectMotion::Enabled());
static_assert(!TemporalUpscaler::Enabled() && !TemporalUpscaler::RasterScaling());
static_assert(TemporalUpscaler::SceneMipBias() == 0);
static_assert(TemporalUpscaler::RedirectState() == 0);
static_assert(TemporalUpscaler::Jitter() == std::array<float, 2>{});
static_assert(!SceneTargets::Reduced() && !SceneTargets::Tracks(42));
static_assert(SceneTargets::Size().width == 0 && SceneTargets::Size().height == 0);
// No engine camera/history/FFX resource state can be allocated by these types.
static_assert(std::is_empty_v<CameraMotion> && std::is_empty_v<ObjectMotion> &&
              std::is_empty_v<TemporalUpscaler>);
// Sizes used by the retired palette/camera classifier remain ordinary data.
static_assert(Motion::ClassifyBuffer(864) == Motion::BufferRole::Other);
static_assert(Motion::ClassifyBuffer(416) == Motion::BufferRole::Other);
static_assert(Motion::ClassifyBuffer(656) == Motion::BufferRole::Other);
static_assert(Motion::ClassifyBuffer(96) == Motion::BufferRole::Other);

int main() {
    // Defaults must be safe before Load(), independently of config/environment.
    Ps4Settings::Values defaults;
    assert(defaults.upscaler == Ps4Settings::UpscalerOff);
    assert(!defaults.object_motion && !defaults.jitter && !defaults.sharpen);
    assert(!defaults.async_shaders && !defaults.rcas);
    assert(!defaults.deferred_readback && !defaults.stale_readback);
    assert(defaults.fps_limit == 30);
    assert(Ps4Graphics::FsrPassRuns(true, false, 1920, 1080, 3840, 2160));
    assert(!Ps4Graphics::FsrPassRuns(false, false, 1920, 1080, 3840, 2160));
    assert(!Ps4Graphics::FsrPassRuns(true, false, 1920, 1080, 1920, 1080));
    // The capability gates have to leave a reason behind: a reader asking "can this GPU run DLSS or
    // FSR 4?" got a silently false flag before these were called at init.
    Ps4Settings::ConfigureUpscalerSupport(false, false, "test: fsr4 unavailable");
    Ps4Settings::ConfigureDlssSupport(false, "test: dlss unavailable");
    const char* fsr4_problem = Ps4Settings::Get().fsr4_problem.load();
    const char* dlss_problem = Ps4Settings::Get().dlss_problem.load();
    assert(fsr4_problem && std::strstr(fsr4_problem, "fsr4 unavailable"));
    assert(dlss_problem && std::strstr(dlss_problem, "dlss unavailable"));
    // Asking for a provider that is unavailable falls back rather than leaving the session pointed
    // at a pass that cannot run.
    Ps4Settings::Get().upscaler = Ps4Settings::UpscalerFsr4;
    Ps4Settings::ConfigureUpscalerSupport(false, false, "test: fsr4 unavailable");
    assert(Ps4Settings::Get().upscaler == Ps4Settings::UpscalerFsr3);
    Ps4Settings::Get().upscaler = Ps4Settings::UpscalerDlss;
    Ps4Settings::ConfigureDlssSupport(false, "test: dlss unavailable");
    assert(Ps4Settings::Get().upscaler == Ps4Settings::UpscalerFsr3);
    // And a supported provider clears the reason instead of keeping a stale one.
    Ps4Settings::ConfigureUpscalerSupport(true, true, "test: fsr4 unavailable");
    assert(Ps4Settings::Get().fsr4_problem.load() == nullptr);
    assert(defaults.startup_upscaler == Ps4Settings::UpscalerOff);
    assert(!defaults.startup_object_motion && !defaults.startup_deferred_readback &&
           !defaults.startup_stale_readback);
    AmdGpu::no_msaa.store(true);
    assert(!AmdGpu::NoMsaa());
    using Factor = AmdGpu::BlendControl::BlendFactor;
    using Function = AmdGpu::BlendControl::BlendFunc;
    BlendEquation scaled{Factor::SrcColor, Function::Min, Factor::DstColor};
    assert(RewriteScaledMinMaxBlend(scaled, AmdGpu::NumberFormat::Unorm,
                                    BlendChannel::Color) == BlendRewriteResult::Unsupported);
    assert(scaled.function == Function::Min && scaled.src_factor == Factor::SrcColor &&
           scaled.dst_factor == Factor::DstColor);
    BlendEquation native{Factor::One, Function::Add, Factor::Zero};
    assert(RewriteScaledMinMaxBlend(native, AmdGpu::NumberFormat::Unorm,
                                    BlendChannel::Color) == BlendRewriteResult::Native);
}
