#include <cassert>
#include <cstdio>
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
    assert(defaults.output_res == Ps4Settings::OutputAutomatic);
    // Any launcher cap from 30 to 240 is honoured as written; 0 stays uncapped.
    assert(Ps4Graphics::ParseFpsLimit(45) == 45 && Ps4Graphics::ParseFpsLimit(0) == 0);
    assert(Ps4Graphics::ParseFpsLimit(10) == 30 && Ps4Graphics::ParseFpsLimit(500) == 240);
    // Launcher settings survive Load(): sharpening, async shaders and output size are no
    // longer forced off after the file is read.
    {
        const char* ini = "order1886_render_baseline_test.ini";
        FILE* file = std::fopen(ini, "w");
        std::fputs("rcas=1\nrcas_strength=40\nasync_shaders=1\noutput_res=3840x2160\nfps_limit=45\nupscaler=fsr3\n", file);
        std::fclose(file);
#ifdef _WIN32
        _putenv_s("ORDER1886_CONFIG", ini);
#else
        setenv("ORDER1886_CONFIG", ini, 1);
#endif
        Ps4Settings::Load();
        const auto& loaded = Ps4Settings::Get();
        assert(loaded.rcas && loaded.rcas_strength == 40 && loaded.async_shaders);
        assert(loaded.startup_output_res == 3 && loaded.fps_limit == 45);
        assert(loaded.upscaler == Ps4Settings::UpscalerOff);
        // The request survives for the fallback report even though no provider runs yet.
        assert(loaded.requested_upscaler == Ps4Settings::UpscalerFsr3);
        std::remove(ini);
    }
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
