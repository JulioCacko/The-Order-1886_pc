// SPDX-License-Identifier: GPL-2.0-or-later
#include "ps4_overlay.h"

#include <algorithm>
#include <atomic>
#include <cfloat>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

#include <SDL3/SDL.h>
#include "ps4_settings.h"
#include "ps4_graphics.h"
#include "ps4_perf_stats.h"
#include "ps4_guest_image.h"

extern "C" void runtime_restart(void); // src/probe.c: starts run.py again, ends this process
#include "common/elf_info.h"
#include "imgui.h"
#include "imgui_internal.h" // RegisterUserTexture (save pictures)
#include "imgui_impl_vulkan.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_frame_capture.h"
#include "video_core/renderdoc.h"

// DejaVu Sans (Cyrillic), embedded (third_party/fonts, Bitstream Vera license).
#ifdef _WIN32
asm(".section .rdata,\"dr\"\n"
    ".balign 16\n"
    ".global ps4_font_ttf\n"
    "ps4_font_ttf:\n"
    ".incbin \"" PS4_FONT_PATH "\"\n"
    ".global ps4_font_ttf_end\n"
    "ps4_font_ttf_end:\n"
    ".text\n");
#else
asm(".section .rodata\n"
    ".balign 16\n"
    ".hidden ps4_font_ttf\n"
    ".global ps4_font_ttf\n"
    "ps4_font_ttf:\n"
    ".incbin \"" PS4_FONT_PATH "\"\n"
    ".hidden ps4_font_ttf_end\n"
    ".global ps4_font_ttf_end\n"
    "ps4_font_ttf_end:\n"
    ".previous\n");
#endif
extern "C" const unsigned char ps4_font_ttf[];
extern "C" const unsigned char ps4_font_ttf_end[];

namespace Ps4Overlay {

namespace {

std::mutex imgui_mutex; // the ImGui context: window thread (input) and present thread
bool initialized = false;
std::atomic<bool> menu_open{false};
bool r3_down = false, l2_down = false;
std::atomic<bool> loading{false};
std::atomic<u32> loading_done{0}, loading_total{0};
std::atomic<u32> background_done{0}, background_total{0};
// A short message in a corner (saved screenshot), shown until notice_until.
std::mutex notice_mutex;
std::string notice_text;
std::atomic<s64> notice_until{0}; // steady_clock milliseconds
bool dirty = false; // settings changed while open: saved on close
int requested_tab = -1; // switch on the next frame (L1/R1, Q/E, menu opened)
// The game's text dialog (SetTextEntry), guarded by imgui_mutex.
bool text_entry_active = false;
std::string text_entry_prompt, text_entry_text;
// The game's save list (sceSaveDataDialog): a choice made with the arrows/D-pad.
std::atomic<bool> choice_active{false};
std::string choice_title;
std::vector<std::string> choice_items;
int choice_index = 0;
std::atomic<int> choice_result{-1}; // -1 open, -2 cancelled, else the chosen index
// Save pictures: decoded by BeginChoice, made textures on the present thread (null = none).
// Closed lists' textures wait in choice_retired until the backend has destroyed them.
std::vector<Ps4Png::Image> choice_pictures;
std::vector<ImTextureData*> choice_textures, choice_retired;
std::atomic<bool> choice_retiring{false};
float base_scale = 1.0f;

std::mutex presentation_mutex;
Ps4PerfStats::PresentationCounter presentation_counter;
std::chrono::steady_clock::time_point last_ui_frame{};

bool SettingsMenuEnabled() {
    // Per launch through ORDER1886_SETTINGS_MENU=1, which the backend sets when the launcher passes
    // --in-game-menu (its "game menu" option, on by default); a direct runtime launch stays closed.
    return Ps4Settings::MenuEnabled();
}

void SetOpen(bool value) {
    if (value && !SettingsMenuEnabled()) {
        return;
    }
    if (menu_open.exchange(value) == value) {
        return;
    }
    ImGui::GetIO().MouseDrawCursor = value;
    if (value) {
        requested_tab = Ps4Settings::Get().menu_tab;
    }
    if (!value && dirty) {
        dirty = false;
        Ps4Settings::Save();
    }
}

ImGuiKey KeyFromSdl(SDL_Keycode key) {
    switch (key) {
    case SDLK_TAB: return ImGuiKey_Tab;
    case SDLK_LEFT: return ImGuiKey_LeftArrow;
    case SDLK_RIGHT: return ImGuiKey_RightArrow;
    case SDLK_UP: return ImGuiKey_UpArrow;
    case SDLK_DOWN: return ImGuiKey_DownArrow;
    case SDLK_PAGEUP: return ImGuiKey_PageUp;
    case SDLK_PAGEDOWN: return ImGuiKey_PageDown;
    case SDLK_HOME: return ImGuiKey_Home;
    case SDLK_END: return ImGuiKey_End;
    case SDLK_DELETE: return ImGuiKey_Delete;
    case SDLK_BACKSPACE: return ImGuiKey_Backspace;
    case SDLK_SPACE: return ImGuiKey_Space;
    case SDLK_RETURN: return ImGuiKey_Enter;
    case SDLK_KP_ENTER: return ImGuiKey_KeypadEnter;
    case SDLK_ESCAPE: return ImGuiKey_Escape;
    case SDLK_Q: return ImGuiKey_Q;
    case SDLK_E: return ImGuiKey_E;
    case SDLK_LCTRL: return ImGuiKey_LeftCtrl;
    case SDLK_RCTRL: return ImGuiKey_RightCtrl;
    case SDLK_LSHIFT: return ImGuiKey_LeftShift;
    case SDLK_RSHIFT: return ImGuiKey_RightShift;
    case SDLK_LALT: return ImGuiKey_LeftAlt;
    case SDLK_RALT: return ImGuiKey_RightAlt;
    default: return ImGuiKey_None;
    }
}

ImGuiKey KeyFromGamepad(u8 button) {
    switch (button) {
    case SDL_GAMEPAD_BUTTON_SOUTH: return ImGuiKey_GamepadFaceDown;
    case SDL_GAMEPAD_BUTTON_EAST: return ImGuiKey_GamepadFaceRight;
    case SDL_GAMEPAD_BUTTON_WEST: return ImGuiKey_GamepadFaceLeft;
    case SDL_GAMEPAD_BUTTON_NORTH: return ImGuiKey_GamepadFaceUp;
    case SDL_GAMEPAD_BUTTON_DPAD_UP: return ImGuiKey_GamepadDpadUp;
    case SDL_GAMEPAD_BUTTON_DPAD_DOWN: return ImGuiKey_GamepadDpadDown;
    case SDL_GAMEPAD_BUTTON_DPAD_LEFT: return ImGuiKey_GamepadDpadLeft;
    case SDL_GAMEPAD_BUTTON_DPAD_RIGHT: return ImGuiKey_GamepadDpadRight;
    case SDL_GAMEPAD_BUTTON_LEFT_SHOULDER: return ImGuiKey_GamepadL1;
    case SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER: return ImGuiKey_GamepadR1;
    case SDL_GAMEPAD_BUTTON_START: return ImGuiKey_GamepadStart;
    case SDL_GAMEPAD_BUTTON_BACK: return ImGuiKey_GamepadBack;
    default: return ImGuiKey_None;
    }
}

float PixelDensity(SDL_WindowID id) {
    SDL_Window* window = SDL_GetWindowFromID(id);
    const float density = window ? SDL_GetWindowPixelDensity(window) : 1.0f;
    return density > 0.0f ? density : 1.0f;
}

// Marks the settings dirty when a widget changed them.
template <typename T>
void Store(std::atomic<T>& target, T value, bool changed) {
    if (changed) {
        target = value;
        dirty = true;
    }
}

void Checkbox(const char* label, std::atomic<bool>& value) {
    bool v = value;
    const bool changed = ImGui::Checkbox(label, &v);
    Store(value, v, changed);
}

// A combo over `count` labels storing an index or a value from `values`.
void Choice(const char* label, std::atomic<int>& target, const char* const* labels, const int* values,
            int count) {
    int current = 0;
    for (int i = 0; i < count; ++i) {
        if ((values ? values[i] : i) == target.load()) current = i;
    }
    if (ImGui::Combo(label, &current, labels, count)) {
        Store(target, values ? values[current] : current, true);
    }
}

// Controller button names in the help text follow ORDER1886_GLYPHS (run.py sets xbox or nintendo when
// the glyph feature is on); unset is PlayStation. Read once: the environment is fixed for a run.
static const char* PadText(const char* playstation, const char* xbox, const char* nintendo) {
    static const char* style = std::getenv("ORDER1886_GLYPHS");
    if (!style) return playstation;
    return !std::strcmp(style, "xbox") ? xbox : !std::strcmp(style, "nintendo") ? nintendo : playstation;
}

// The note for the item under the mouse or the gamepad/keyboard focus, shown in the footer.
const char* footer_help = nullptr;

void Help(const char* text) {
    if (text && (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled) || ImGui::IsItemFocused())) {
        footer_help = text;
    }
}

// Two-column rows: the name on the left, the control on the right.
bool BeginRows(const char* id) {
    if (!ImGui::BeginTable(id, 2, ImGuiTableFlags_SizingStretchProp)) {
        return false;
    }
    ImGui::TableSetupColumn("name", ImGuiTableColumnFlags_WidthStretch, 0.52f);
    ImGui::TableSetupColumn("value", ImGuiTableColumnFlags_WidthStretch, 0.48f);
    return true;
}

void Row(const char* label) {
    ImGui::TableNextRow();
    ImGui::TableNextColumn();
    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted(label);
    ImGui::TableNextColumn();
    ImGui::SetNextItemWidth(-FLT_MIN);
    ImGui::PushID(label);
}

void CheckRow(const char* label, std::atomic<bool>& value, const char* help = nullptr) {
    Row(label);
    Checkbox("##value", value);
    Help(help);
    ImGui::PopID();
}

void ChoiceRow(const char* label, std::atomic<int>& target, const char* const* labels, const int* values,
               int count, const char* help = nullptr) {
    Row(label);
    Choice("##value", target, labels, values, count);
    Help(help);
    ImGui::PopID();
}

// A 0.1x to 100x multiplier with a 1x button.



void InfoRow(const char* label, const char* text) {
    Row(label);
    ImGui::TextDisabled("%s", text);
    ImGui::PopID();
}

void SliderRow(const char* label, std::atomic<int>& value, int lo, int hi, const char* format, const char* help) {
    Row(label);
    int v = value;
    if (ImGui::SliderInt("##value", &v, lo, hi, format, ImGuiSliderFlags_AlwaysClamp)) {
        Store(value, std::clamp(v, lo, hi), true);
    }
    Help(help);
    ImGui::PopID();
}

const char* UpscalerLabel(int upscaler) {
    switch (upscaler) {
    case Ps4Settings::UpscalerFsr3: return "FSR 3.1";
    case Ps4Settings::UpscalerFsr4: return "FSR 4";
    case Ps4Settings::UpscalerFsr411: return "FSR 4.1.1";
    case Ps4Settings::UpscalerTaa: return "TAA";
    case Ps4Settings::UpscalerDlss: return "DLSS";
    default: return "";
    }
}

const Vulkan::Instance* overlay_instance = nullptr; // for the overlay's measurements

// The performance overlay's text with the current settings (also the menu's preview).
std::string OverlayText() {
    namespace P = Ps4PerfStats;
    const auto& s = Ps4Settings::Get();
    const unsigned items = s.overlay_items;
    if ((items & (P::Gpu | P::Cpu | P::Ram | P::Vram)) && overlay_instance) {
        P::Start(*overlay_instance, items);
    }
    P::Sample sample = P::Latest();
    {
        std::scoped_lock lock{presentation_mutex};
        const auto timing = presentation_counter.Latest();
        sample.fps = timing.fps;
        sample.frame_ms = timing.interval_ms;
    }
    sample.upscaler = UpscalerLabel(s.upscaler);
    return P::Format(sample, items, s.overlay_layout == 0);
}

constexpr const char* Unsupported = "Unavailable: game version or code signature mismatch.";


void TextEntryBox() {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
                                   viewport->WorkPos.y + viewport->WorkSize.y * 0.42f),
                            ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSizeConstraints(ImVec2(viewport->WorkSize.x * 0.32f, 0.0f),
                                        ImVec2(viewport->WorkSize.x * 0.8f, FLT_MAX));
    ImGui::SetNextWindowBgAlpha(0.92f);
    ImGui::Begin("##text_entry", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::TextColored(ImVec4(0.85f, 0.72f, 0.45f, 1.0f), "%s", text_entry_prompt.c_str());
    ImGui::Separator();
    ImGui::SetWindowFontScale(1.4f);
    ImGui::Text("%s_", text_entry_text.c_str());
    ImGui::SetWindowFontScale(1.0f);
    ImGui::Separator();
    ImGui::TextDisabled("Keyboard: type, Backspace to erase, Enter = OK, Esc = cancel");
    ImGui::TextDisabled("%s", PadText("Controller: Cross (A) = OK, Circle (B) = cancel", "Controller: A = OK, B = cancel", "Controller: B = OK, A = cancel"));
    ImGui::End();
}

void ChoiceBox() {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
                                   viewport->WorkPos.y + viewport->WorkSize.y * 0.5f),
                            ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSizeConstraints(ImVec2(viewport->WorkSize.x * 0.36f, 0.0f),
                                        ImVec2(viewport->WorkSize.x * 0.8f, viewport->WorkSize.y * 0.8f));
    ImGui::SetNextWindowBgAlpha(0.94f);
    ImGui::Begin("##choice", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::TextColored(ImVec4(0.85f, 0.72f, 0.45f, 1.0f), "%s", choice_title.c_str());
    ImGui::Separator();
    // Save pictures are 228x128; rows without one keep the text aligned when others have one.
    const bool pictures = std::any_of(choice_textures.begin(), choice_textures.end(),
                                      [](ImTextureData* tex) { return tex != nullptr; });
    const ImVec2 picture_size(228.0f * base_scale, 128.0f * base_scale);
    for (int i = 0; i < int(choice_items.size()); ++i) {
        const bool selected = i == choice_index;
        ImGui::BeginGroup();
        ImTextureData* tex = i < int(choice_textures.size()) ? choice_textures[i] : nullptr;
        if (tex) {
            ImGui::Image(tex->GetTexRef(), picture_size);
        } else if (pictures) {
            ImGui::Dummy(picture_size);
        }
        if (pictures) {
            ImGui::SameLine();
        }
        if (selected) {
            ImGui::TextColored(ImVec4(1.0f, 0.9f, 0.55f, 1.0f), "> %s", choice_items[i].c_str());
        } else {
            ImGui::Text("  %s", choice_items[i].c_str());
        }
        ImGui::EndGroup();
        if (selected) {
            if (pictures) {
                const ImVec2 min = ImGui::GetItemRectMin(), max = ImGui::GetItemRectMax();
                const float pad = 3.0f * base_scale;
                ImGui::GetWindowDrawList()->AddRect(ImVec2(min.x - pad, min.y - pad),
                                                    ImVec2(max.x + pad, max.y + pad),
                                                    IM_COL32(255, 230, 140, 255), 0.0f, 0,
                                                    2.0f * base_scale);
            }
            ImGui::SetScrollHereY();
        }
    }
    ImGui::Separator();
    ImGui::TextDisabled("%s", PadText("Up/Down or D-pad: choose   Enter or Cross (A): OK   Esc or Circle (B): cancel", "Up/Down or D-pad: choose   Enter or A: OK   Esc or B: cancel", "Up/Down or D-pad: choose   Enter or B: OK   Esc or A: cancel"));
    ImGui::End();
}

void LoadingScreen() {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
                                   viewport->WorkPos.y + viewport->WorkSize.y * 0.5f),
                            ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(viewport->WorkSize.x * 0.4f, 0.0f), ImGuiCond_Always);
    ImGui::SetNextWindowBgAlpha(0.0f);
    ImGui::Begin("##loading", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoInputs |
                     ImGuiWindowFlags_NoNav | ImGuiWindowFlags_NoFocusOnAppearing);
    const u32 done = loading_done, total = loading_total;
    ImGui::SetWindowFontScale(1.6f);
    ImGui::TextUnformatted(total ? "Loading shader cache..." : "Preparing graphics...");
    ImGui::SetWindowFontScale(1.0f);
    if (total) {
        char count[64];
        std::snprintf(count, sizeof(count), "%u / %u (%u%%)", done, total,
                      u32(u64(done) * 100 / total));
        ImGui::ProgressBar(float(done) / float(total), ImVec2(-1.0f, 0.0f), count);
    }
    ImGui::TextDisabled("The first start after an update takes longer.");
    ImGui::End();
}

void FpsCounter() {
    const auto& s = Ps4Settings::Get();
    const std::string text = OverlayText();
    if (text.empty()) {
        return;
    }
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    const float pad = 12.0f * base_scale;
    const int corner = s.overlay_corner;
    const bool right = corner == 1 || corner == 3, bottom = corner >= 2;
    ImGui::SetNextWindowPos(ImVec2(right ? viewport->WorkPos.x + viewport->WorkSize.x - pad : viewport->WorkPos.x + pad,
                                   bottom ? viewport->WorkPos.y + viewport->WorkSize.y - pad : viewport->WorkPos.y + pad),
                            ImGuiCond_Always, ImVec2(right ? 1.0f : 0.0f, bottom ? 1.0f : 0.0f));
    ImGui::SetNextWindowBgAlpha(s.overlay_opacity / 100.0f);
    ImGui::Begin("##fps", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::SetWindowFontScale(s.overlay_scale / 100.0f);
    ImGui::TextUnformatted("The Order: 1886");
    ImGui::TextDisabled("Guest flips / host presents | F9 to hide");
    ImGui::Separator();
    ImGui::TextUnformatted(text.c_str());
    ImGui::End();
}

void BackgroundLoading() {
    const u32 done = background_done, total = std::max(background_total.load(), 1u);
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    const float pad = 12.0f * base_scale;
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + pad,
                                   viewport->WorkPos.y + viewport->WorkSize.y - pad),
                            ImGuiCond_Always, ImVec2(0.0f, 1.0f));
    ImGui::SetNextWindowBgAlpha(0.35f);
    ImGui::Begin("##background_loading", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::TextDisabled("Loading shader cache %u%%", u32(u64(done) * 100 / total));
    ImGui::End();
}

s64 NowMs() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

bool NoticeActive() {
    return notice_until.load(std::memory_order_relaxed) > NowMs();
}

void Notice() {
    std::string text;
    {
        std::scoped_lock lock{notice_mutex};
        text = notice_text;
    }
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    const float pad = 12.0f * base_scale;
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x - pad,
                                   viewport->WorkPos.y + viewport->WorkSize.y - pad),
                            ImGuiCond_Always, ImVec2(1.0f, 1.0f));
    ImGui::SetNextWindowBgAlpha(0.6f);
    ImGui::Begin("##notice", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::TextUnformatted(text.c_str());
    ImGui::End();
}


// ---- In-game settings menu (F1) -------------------------------------------------------------
// Laid out like Longshot's (rows of label | value, a description panel, key hints), coloured
// with the launcher's palette, which follows the game's: charcoal, parchment and gold.
namespace Menu {

constexpr ImU32 Rgba(u32 rgb, float alpha = 1.0f) {
    return IM_COL32((rgb >> 16) & 0xff, (rgb >> 8) & 0xff, rgb & 0xff, int(alpha * 255.0f));
}
constexpr ImU32 Backdrop = IM_COL32(0, 0, 0, 150);
constexpr ImU32 Panel = Rgba(0x0c0e0f, 0.97f);
constexpr ImU32 Surface = Rgba(0x141718);
constexpr ImU32 Surface2 = Rgba(0x1b1e1f);
constexpr ImU32 Line = IM_COL32(255, 255, 255, 20);
constexpr ImU32 LineStrong = IM_COL32(255, 255, 255, 38);
constexpr ImU32 Ink = Rgba(0xf1ede4);
constexpr ImU32 Muted = Rgba(0x9c9d96);
constexpr ImU32 Accent = Rgba(0xd8bd77);
constexpr ImU32 AccentInk = Rgba(0x17150f);
constexpr ImU32 Focus = Rgba(0xf2d894);
constexpr ImU32 RowFocus = Rgba(0x2a2418);
constexpr ImU32 Segment = Rgba(0x3a3122);

enum class Kind { Choice, Toggle };
struct Row {
    const char* section; // non-null: a heading drawn above this row
    const char* label;
    Kind kind;
    std::vector<std::string> values; // Toggle: {"Off", "On"}
    int current;
    bool available;
    const char* title;
    const char* body;
    std::string note;          // shown under the body with a gold bar (current effect)
    void (*apply)(int index);  // stores the new value
};

int focused = 0;
// 0: the game decides its own interval; otherwise the interval the menu set, plus one (the
// interval itself can be 0), kept every frame.
std::atomic<u32> chosen_interval{0};

const int OutputChoices[] = {Ps4Settings::OutputAutomatic, 0, 1, 2, 3};
// One frame-rate row. 30 and 60 are the engine's own intervals (2 and 1); every higher rate runs
// the engine uncapped (interval 0) and lets the presentation cap pace it, so no executable code
// is changed live. Unlocked removes the cap: V-Sync or the GPU sets the limit.
constexpr int Rates[] = {30, 60, 90, 120, 144, 165, 240, 0};
constexpr int RateCount = int(sizeof(Rates) / sizeof(Rates[0]));

void SetGameFrameRate(int index) {
    const int rate = Rates[index];
    const u32 interval = rate == 30 ? 2u : rate == 60 ? 1u : 0u;
    chosen_interval = interval + 1;
    if (volatile uint32_t* global = Ps4GuestImage::IntervalGlobal()) {
        *global = interval;
    }
    Ps4Settings::Get().fps_limit = rate;
}

std::vector<Row> BuildRows() {
    auto& s = Ps4Settings::Get();
    std::vector<Row> rows;
    volatile uint32_t* global = Ps4GuestImage::IntervalGlobal();
    const u32 interval = global ? *global : 2u;
    const int limit = s.fps_limit.load();
    int rate = interval >= 2 ? 0 : interval == 1 ? 1 : RateCount - 1;
    if (interval == 0) {
        for (int i = 2; i < RateCount - 1; ++i) {
            if (Rates[i] == limit) {
                rate = i;
            }
        }
    }
    std::vector<std::string> labels;
    for (int i = 0; i < RateCount; ++i) {
        labels.push_back(Rates[i] == 0    ? "Unlocked \xe2\x80\x94 experimental"
                         : Rates[i] == 30 ? "30 FPS \xe2\x80\x94 native"
                                          : std::to_string(Rates[i]) + " FPS \xe2\x80\x94 experimental");
    }
    std::string note = "Not available: this executable is not the verified 01.02 build.";
    if (global) {
        note = rate == 0 ? "Running at 30 FPS, as on the console."
               : rate == RateCount - 1
                   ? "Running uncapped: V-Sync or the GPU sets the limit."
                   : "Running at " + std::to_string(Rates[rate]) + " FPS.";
    }
    rows.push_back({"Frame rate", "Game frame rate", Kind::Choice, labels, rate, global != nullptr,
                    "Game frame rate",
                    "How many frames the game runs per second. Changes right away. 30 FPS is native; "
                    "the rest are experimental: the game clock follows measured time, but some "
                    "quick-time events in Chapters 6 and 9 can get stuck, so go back to 30 there if one "
                    "does. With V-Sync on, the display's refresh rate is the most you will see.",
                    note, SetGameFrameRate});
    const int mode = std::clamp(s.display_mode.load(), 0, int(Ps4Graphics::DisplayModeCount) - 1);
    rows.push_back({"Screen", "Window mode", Kind::Choice, {"Window", "Borderless", "Fullscreen"}, mode,
                    true, "Window mode",
                    "Window keeps the desktop around the game. Borderless fills the screen without a "
                    "border and switches instantly. Fullscreen takes the display for itself.",
                    "", [](int index) { Ps4Settings::Get().display_mode = index; }});
    rows.push_back({nullptr, "V-Sync", Kind::Toggle, {"Off", "On"}, s.vsync ? 1 : 0, true, "V-Sync",
                    "Waits for the monitor before showing each frame: no tearing, a little more "
                    "input delay. Off shows frames as soon as they are ready.",
                    "", [](int index) { Ps4Settings::Get().vsync = index == 1; }});
    int output = 0;
    for (int i = 0; i < 5; ++i) {
        if (OutputChoices[i] == s.output_res) {
            output = i;
        }
    }
    std::string size_note;
    if (const int w = s.image_width, h = s.image_height; w > 0 && h > 0) {
        size_note = "The game's picture is " + std::to_string(w) + "x" + std::to_string(h) + ".";
    }
    rows.push_back({nullptr, "Output resolution", Kind::Choice,
                    {"Automatic (window)", "1280x720", "1920x1080", "2560x1440", "3840x2160"}, output, true,
                    "Output resolution",
                    "The size the finished picture is scaled to before it is fitted to the window. "
                    "Automatic follows the window. The game still renders its scene at its own size.",
                    size_note, [](int index) { Ps4Settings::Get().output_res = OutputChoices[index]; }});
    rows.push_back({"Overlay", "FPS counter", Kind::Toggle, {"Off", "On"}, s.show_fps ? 1 : 0, true,
                    "FPS counter", "The frame rate and frame time in a corner of the screen. F9 also "
                    "shows or hides it.",
                    "", [](int index) { Ps4Settings::Get().show_fps = index == 1; }});
    return rows;
}

ImVec2 TextSize(float size, const char* text) {
    return ImGui::GetFont()->CalcTextSizeA(size, FLT_MAX, 0.0f, text);
}
void Text(ImDrawList* dl, float size, ImVec2 pos, ImU32 color, const char* text, float wrap = 0.0f) {
    dl->AddText(ImGui::GetFont(), size, pos, color, text, nullptr, wrap);
}
void TextCentered(ImDrawList* dl, float size, ImVec2 a, ImVec2 b, ImU32 color, const char* text) {
    const ImVec2 t = TextSize(size, text);
    Text(dl, size, ImVec2((a.x + b.x - t.x) * 0.5f, (a.y + b.y - t.y) * 0.5f), color, text);
}
void Arrow(ImDrawList* dl, ImVec2 center, float r, bool right, ImU32 color) {
    if (right) {
        dl->AddTriangleFilled(ImVec2(center.x - r * 0.6f, center.y - r), ImVec2(center.x - r * 0.6f, center.y + r),
                              ImVec2(center.x + r * 0.8f, center.y), color);
    } else {
        dl->AddTriangleFilled(ImVec2(center.x + r * 0.6f, center.y - r), ImVec2(center.x + r * 0.6f, center.y + r),
                              ImVec2(center.x - r * 0.8f, center.y), color);
    }
}
void KeyCap(ImDrawList* dl, float s, ImVec2& pos, const char* key) {
    const float size = 22.0f * s;
    const ImVec2 t = TextSize(size, key);
    const ImVec2 a = pos, b = ImVec2(pos.x + std::max(t.x + 16.0f * s, 34.0f * s), pos.y + 34.0f * s);
    dl->AddRectFilled(a, b, Ink, 4.0f * s);
    TextCentered(dl, size, a, b, AccentInk, key);
    pos.x = b.x + 6.0f * s;
}

void Change(std::vector<Row>& rows, int row, int step) {
    Row& r = rows[row];
    if (!r.available || r.values.empty()) {
        return;
    }
    const int count = int(r.values.size());
    const int next = r.kind == Kind::Toggle ? (step == 0 ? 1 - r.current : std::clamp(r.current + step, 0, 1))
                                            : (r.current + step + count) % count;
    if (next != r.current) {
        r.apply(next);
        r.current = next;
        dirty = true;
    }
}

void Draw() {
    std::vector<Row> rows = BuildRows();
    const int count = int(rows.size());
    focused = std::clamp(focused, 0, count - 1);

    // Keyboard and controller (forwarded to ImGui while the menu is open).
    const auto pressed = [](ImGuiKey key) { return ImGui::IsKeyPressed(key, true); };
    if (pressed(ImGuiKey_UpArrow) || pressed(ImGuiKey_GamepadDpadUp)) {
        focused = (focused + count - 1) % count;
    }
    if (pressed(ImGuiKey_DownArrow) || pressed(ImGuiKey_GamepadDpadDown)) {
        focused = (focused + 1) % count;
    }
    if (pressed(ImGuiKey_LeftArrow) || pressed(ImGuiKey_GamepadDpadLeft)) {
        Change(rows, focused, -1);
    }
    if (pressed(ImGuiKey_RightArrow) || pressed(ImGuiKey_GamepadDpadRight)) {
        Change(rows, focused, 1);
    }
    if (ImGui::IsKeyPressed(ImGuiKey_Enter, false) || ImGui::IsKeyPressed(ImGuiKey_Space, false) ||
        ImGui::IsKeyPressed(ImGuiKey_GamepadFaceDown, false)) {
        Change(rows, focused, rows[focused].kind == Kind::Toggle ? 0 : 1);
    }
    bool close = ImGui::IsKeyPressed(ImGuiKey_GamepadFaceRight, false);

    const ImGuiIO& io = ImGui::GetIO();
    const float W = io.DisplaySize.x, H = io.DisplaySize.y;
    const float s = std::max(H / 1080.0f, 0.6f);
    ImGui::SetNextWindowPos(ImVec2(0, 0));
    ImGui::SetNextWindowSize(io.DisplaySize);
    ImGui::Begin("##settings_menu", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoBackground | ImGuiWindowFlags_NoMove |
                     ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoBringToFrontOnFocus);
    ImDrawList* dl = ImGui::GetWindowDrawList();
    dl->AddRectFilled(ImVec2(0, 0), io.DisplaySize, Backdrop);

    const float margin = std::min(60.0f * s, W * 0.03f);
    const ImVec2 p0(margin, margin), p1(W - margin, H - margin);
    dl->AddRectFilled(p0, p1, Panel, 6.0f * s);
    dl->AddRect(p0, p1, LineStrong, 6.0f * s);

    // Top bar: title and the tab row.
    const float bar = 74.0f * s;
    dl->AddRectFilled(p0, ImVec2(p1.x, p0.y + bar), Surface, 6.0f * s, ImDrawFlags_RoundCornersTop);
    dl->AddLine(ImVec2(p0.x, p0.y + bar), ImVec2(p1.x, p0.y + bar), Line);
    Text(dl, 24.0f * s, ImVec2(p0.x + 28.0f * s, p0.y + 14.0f * s), Accent, "THE ORDER: 1886");
    Text(dl, 18.0f * s, ImVec2(p0.x + 28.0f * s, p0.y + 44.0f * s), Muted, "In-game settings");
    const float tab_x = p0.x + 330.0f * s, tab_w = 210.0f * s;
    dl->AddRectFilled(ImVec2(tab_x, p0.y), ImVec2(tab_x + tab_w, p0.y + bar), RowFocus);
    dl->AddRectFilled(ImVec2(tab_x, p0.y + bar - 4.0f * s), ImVec2(tab_x + tab_w, p0.y + bar), Accent);
    TextCentered(dl, 32.0f * s, ImVec2(tab_x, p0.y), ImVec2(tab_x + tab_w, p0.y + bar), Ink, "Graphics");

    // Rows on the left, description on the right.
    const float top = p0.y + bar + 36.0f * s, bottom = p1.y - 78.0f * s;
    const float left = p0.x + 40.0f * s, inner = p1.x - p0.x - 80.0f * s;
    const float list_w = inner * 0.56f, label_w = list_w * 0.5f;
    const float row_h = 58.0f * s, gap = 12.0f * s;
    const float text = 27.0f * s;
    float y = top;
    const ImVec2 mouse = io.MousePos;
    for (int i = 0; i < count; ++i) {
        Row& r = rows[i];
        if (r.section) {
            if (i > 0) {
                y += 14.0f * s;
            }
            const ImVec2 t = TextSize(26.0f * s, r.section);
            Text(dl, 26.0f * s, ImVec2(left, y), Accent, r.section);
            dl->AddLine(ImVec2(left + t.x + 18.0f * s, y + t.y * 0.55f), ImVec2(left + list_w, y + t.y * 0.55f),
                        LineStrong);
            y += t.y + 16.0f * s;
        }
        const bool focus = i == focused;
        const ImVec2 a(left, y), m(left + label_w, y + row_h), b(left + list_w, y + row_h);
        // Mouse: hovering focuses a row, a click on the value changes it (left half back).
        if (mouse.x >= a.x && mouse.x < b.x && mouse.y >= a.y && mouse.y < b.y) {
            if (ImGui::IsMouseClicked(0)) {
                focused = i;
                if (mouse.x >= m.x) {
                    const bool back = r.kind == Kind::Choice && mouse.x < (m.x + b.x) * 0.5f;
                    if (r.kind == Kind::Toggle) {
                        const int target = mouse.x < (m.x + b.x) * 0.5f ? 0 : 1;
                        if (target != r.current) {
                            Change(rows, i, 0);
                        }
                    } else {
                        Change(rows, i, back ? -1 : 1);
                    }
                }
            }
        }
        dl->AddRectFilled(a, ImVec2(m.x, b.y), focus ? RowFocus : Surface2);
        dl->AddRect(a, b, Line);
        if (focus) {
            dl->AddRectFilled(a, ImVec2(a.x + 5.0f * s, b.y), Accent);
        }
        Text(dl, text, ImVec2(a.x + 26.0f * s, a.y + (row_h - text) * 0.5f - 1.0f * s),
             r.available ? Ink : Muted, r.label);
        const ImVec2 va(m.x, a.y), vb(b.x, b.y);
        if (r.kind == Kind::Toggle) {
            const float half = (vb.x - va.x) * 0.5f, inset = 5.0f * s;
            for (int k = 0; k < 2; ++k) {
                const ImVec2 sa(va.x + half * k + inset, va.y + inset), sb(va.x + half * (k + 1) - inset, vb.y - inset);
                const bool on = k == r.current;
                if (on) {
                    dl->AddRectFilled(sa, sb, focus ? Accent : Segment, 2.0f * s);
                }
                TextCentered(dl, text, sa, sb, on ? (focus ? AccentInk : Ink) : Muted, r.values[k].c_str());
            }
            if (focus) {
                dl->AddRect(ImVec2(va.x - 1, va.y - 1), ImVec2(vb.x + 1, vb.y + 1), Ink, 3.0f * s, 0, 3.0f * s);
            }
        } else {
            if (focus) {
                dl->AddRectFilled(ImVec2(va.x + 5.0f * s, va.y + 5.0f * s), ImVec2(vb.x - 5.0f * s, vb.y - 5.0f * s),
                                  r.available ? Accent : Segment, 2.0f * s);
                dl->AddRect(ImVec2(va.x - 1, va.y - 1), ImVec2(vb.x + 1, vb.y + 1), Ink, 3.0f * s, 0, 3.0f * s);
            } else {
                dl->AddRectFilled(va, vb, Surface);
            }
            const ImU32 ink = focus && r.available ? AccentInk : (r.available ? Ink : Muted);
            TextCentered(dl, text, va, vb, ink, r.values[r.current].c_str());
            if (r.available) {
                const float cy = (va.y + vb.y) * 0.5f;
                Arrow(dl, ImVec2(va.x + 26.0f * s, cy), 7.0f * s, false, focus ? AccentInk : Muted);
                Arrow(dl, ImVec2(vb.x - 26.0f * s, cy), 7.0f * s, true, focus ? AccentInk : Muted);
            }
        }
        y += row_h + gap;
    }

    // Description panel for the focused row.
    const Row& r = rows[focused];
    const ImVec2 da(left + list_w + 48.0f * s, top), db(p1.x - 40.0f * s, bottom - 10.0f * s);
    dl->AddRectFilled(da, db, Surface);
    dl->AddRect(da, db, LineStrong);
    const float pad = 30.0f * s, wrap = db.x - da.x - pad * 2;
    float dy = da.y + pad;
    Text(dl, 32.0f * s, ImVec2(da.x + pad, dy), Focus, r.title);
    dy += 50.0f * s;
    Text(dl, 26.0f * s, ImVec2(da.x + pad, dy), Ink, r.body, wrap);  // wrap is a width
    dy += ImGui::GetFont()->CalcTextSizeA(26.0f * s, FLT_MAX, wrap, r.body).y + 22.0f * s;
    if (!r.note.empty()) {
        const ImVec2 t = ImGui::GetFont()->CalcTextSizeA(24.0f * s, FLT_MAX, wrap - 20.0f * s, r.note.c_str());
        dl->AddRectFilled(ImVec2(da.x + pad, dy), ImVec2(da.x + pad + 4.0f * s, dy + t.y), Accent);
        Text(dl, 24.0f * s, ImVec2(da.x + pad + 20.0f * s, dy), Muted, r.note.c_str(), wrap - 20.0f * s);
    }

    // Key hints, right-aligned like Longshot's.
    const float hy = p1.y - 58.0f * s;
    dl->AddLine(ImVec2(p0.x, hy - 14.0f * s), ImVec2(p1.x, hy - 14.0f * s), Line);
    struct Hint { const char* label; const char* keys[2]; };
    const Hint hints[] = {{"Choose", {"\xe2\x96\xb2", "\xe2\x96\xbc"}}, {"Change", {"\xe2\x97\x80", "\xe2\x96\xb6"}},
                          {"Close", {"F1", "Esc"}}};
    float width = 0.0f;
    for (const Hint& h : hints) {
        width += TextSize(24.0f * s, h.label).x + 12.0f * s + 2 * 40.0f * s + 36.0f * s;
    }
    ImVec2 hp(p1.x - 40.0f * s - width, hy);
    for (const Hint& h : hints) {
        Text(dl, 24.0f * s, ImVec2(hp.x, hp.y + 4.0f * s), Ink, h.label);
        hp.x += TextSize(24.0f * s, h.label).x + 12.0f * s;
        KeyCap(dl, s, hp, h.keys[0]);
        KeyCap(dl, s, hp, h.keys[1]);
        hp.x += 30.0f * s;
    }
    ImGui::End();
    if (close) {
        SetOpen(false);
    }
}

// Keep the interval the menu chose: the game writes its own at a few scripted moments.
void EnforceFrameRate() {
    const u32 chosen = chosen_interval.load(std::memory_order_relaxed);
    if (!chosen) {
        return;
    }
    const u32 interval = chosen - 1;
    if (volatile uint32_t* global = Ps4GuestImage::IntervalGlobal(); global && *global != interval) {
        *global = interval;
    }
}

} // namespace Menu

} // namespace

void OnPresented(bool loading_frame) {
    const auto now_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now().time_since_epoch()).count();
    std::scoped_lock lock{presentation_mutex};
    presentation_counter.Present(u64(now_ns), loading_frame);
    Ps4PerfStats::OnHostPresented(u64(now_ns), loading_frame);
}

void ShowNotice(const std::string& text, int milliseconds) {
    {
        std::scoped_lock lock{notice_mutex};
        notice_text = text;
    }
    notice_until.store(NowMs() + milliseconds, std::memory_order_relaxed);
}

void Init(const Vulkan::Instance& instance, vk::Format format, u32 image_count) {
    std::scoped_lock lock{imgui_mutex};
    if (initialized) {
        return;
    }
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr; // window positions are not kept
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_NavEnableGamepad;
    io.BackendFlags |= ImGuiBackendFlags_HasGamepad;
    io.BackendPlatformName = "ps4";

    ImGui::StyleColorsDark();
    ImGuiStyle& style = ImGui::GetStyle();
    style.WindowRounding = 6.0f;
    style.FrameRounding = 4.0f;
    style.GrabRounding = 4.0f;
    style.Colors[ImGuiCol_WindowBg].w = 0.92f;

    ImFontConfig font_config;
    font_config.FontDataOwnedByAtlas = false;
    io.Fonts->AddFontFromMemoryTTF(const_cast<unsigned char*>(ps4_font_ttf),
                                   int(ps4_font_ttf_end - ps4_font_ttf), 18.0f, &font_config);

    const vk::Instance vk_instance = instance.GetInstance();
    ImGui_ImplVulkan_LoadFunctions(
        instance.ApiVersion(),
        [](const char* name, void* user) {
            return VULKAN_HPP_DEFAULT_DISPATCHER.vkGetInstanceProcAddr(
                *static_cast<const vk::Instance*>(user), name);
        },
        const_cast<vk::Instance*>(&vk_instance));

    const VkFormat color_format = static_cast<VkFormat>(format);
    ImGui_ImplVulkan_InitInfo info{};
    info.ApiVersion = instance.ApiVersion();
    info.Instance = vk_instance;
    info.PhysicalDevice = instance.GetPhysicalDevice();
    info.Device = instance.GetDevice();
    info.QueueFamily = instance.GetGraphicsQueueFamilyIndex();
    info.Queue = instance.GetGraphicsQueue();
    // Font atlas plus the save list pictures (up to 33, and a closed list's until freed).
    info.DescriptorPoolSize = 128;
    info.MinImageCount = std::max(image_count, 2u);
    info.ImageCount = std::max(image_count, 2u);
    info.UseDynamicRendering = true;
    info.PipelineInfoMain.PipelineRenderingCreateInfo = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO_KHR,
        .colorAttachmentCount = 1,
        .pColorAttachmentFormats = &color_format,
    };
    if (!ImGui_ImplVulkan_Init(&info)) {
        std::printf("Overlay: ImGui Vulkan backend init failed\n");
        ImGui::DestroyContext();
        return;
    }
    overlay_instance = &instance;
    initialized = true;
    std::printf("Overlay: %s\n", SettingsMenuEnabled()
                    ? "menu ready (F1 or Insert; R3+L2 on a controller)"
                    : "settings menu disabled; system dialogs and screenshots available");
}

void UpdateTextInput(SDL_Window* window) {
    bool want = false;
    {
        std::scoped_lock lock{imgui_mutex};
        want = initialized && menu_open && ImGui::GetIO().WantTextInput;
    }
    if (want != SDL_TextInputActive(window)) {
        if (want) {
            SDL_StartTextInput(window);
        } else {
            SDL_StopTextInput(window);
        }
    }
}

// imgui_mutex held. The backend frees a texture some frames after its last use.
void RetireChoiceTextures() {
    for (ImTextureData* tex : choice_textures) {
        if (tex) {
            tex->WantDestroyNextFrame = true;
            choice_retired.push_back(tex);
        }
    }
    choice_textures.clear();
    choice_pictures.clear();
    choice_retiring = !choice_retired.empty();
}

// imgui_mutex held, before NewFrame: new pictures become textures, destroyed ones are freed.
void UpdateChoiceTextures() {
    if (!choice_pictures.empty()) {
        choice_textures.assign(choice_pictures.size(), nullptr);
        for (size_t i = 0; i < choice_pictures.size(); ++i) {
            const Ps4Png::Image& picture = choice_pictures[i];
            if (picture.rgba.empty()) {
                continue;
            }
            ImTextureData* tex = IM_NEW(ImTextureData)();
            tex->Create(ImTextureFormat_RGBA32, picture.width, picture.height);
            std::memcpy(tex->GetPixels(), picture.rgba.data(), picture.rgba.size());
            ImGui::RegisterUserTexture(tex);
            choice_textures[i] = tex;
        }
        choice_pictures.clear();
    }
    std::erase_if(choice_retired, [](ImTextureData* tex) {
        if (tex->Status != ImTextureStatus_Destroyed) {
            return false;
        }
        ImGui::UnregisterUserTexture(tex);
        IM_DELETE(tex);
        return true;
    });
    choice_retiring = !choice_retired.empty();
}

// The save list takes the keys and buttons that move and confirm; the rest stays with the game
// (held neutral by CapturesInput).
bool HandleChoiceEvent(const SDL_Event& event) {
    int move = 0, finish = 0; // finish: 1 accept, 2 cancel
    if (event.type == SDL_EVENT_KEY_DOWN) {
        const SDL_Keycode key = event.key.key;
        move = key == SDLK_UP || key == SDLK_W ? -1 : key == SDLK_DOWN || key == SDLK_S ? 1 : 0;
        finish = key == SDLK_RETURN || key == SDLK_KP_ENTER || key == SDLK_SPACE ? 1
                 : key == SDLK_ESCAPE || key == SDLK_BACKSPACE                   ? 2
                                                                                 : 0;
    } else if (event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) {
        const u8 button = event.gbutton.button;
        move = button == SDL_GAMEPAD_BUTTON_DPAD_UP ? -1 : button == SDL_GAMEPAD_BUTTON_DPAD_DOWN ? 1 : 0;
        finish = button == SDL_GAMEPAD_BUTTON_SOUTH ? 1 : button == SDL_GAMEPAD_BUTTON_EAST ? 2 : 0;
    } else {
        return event.type == SDL_EVENT_KEY_UP || event.type == SDL_EVENT_GAMEPAD_BUTTON_UP;
    }
    const int count = int(choice_items.size());
    if (move && count) {
        choice_index = (choice_index + move + count) % count;
    }
    if (finish) {
        choice_result = finish == 1 && count ? choice_index : -2;
        choice_active = false;
        RetireChoiceTextures();
    }
    return true;
}

bool HandleEvent(const SDL_Event& event) {
    std::scoped_lock lock{imgui_mutex};
    if (!initialized) {
        return false;
    }
    if (choice_active && !menu_open) {
        return HandleChoiceEvent(event);
    }
    ImGuiIO& io = ImGui::GetIO();
    const bool is_open = menu_open;
    const bool settings_menu_enabled = SettingsMenuEnabled();
    switch (event.type) {
    case SDL_EVENT_KEY_DOWN:
    case SDL_EVENT_KEY_UP: {
        const bool down = event.type == SDL_EVENT_KEY_DOWN;
        if (event.key.key == SDLK_F9) {
            if (down && !event.key.repeat) {
                auto& settings = Ps4Settings::Get();
                settings.show_fps = !settings.show_fps.load();
            }
            return true;
        }
        static const bool capture_key = [] {
            const char* env = std::getenv("ORDER1886_FRAME_CAPTURE_KEY");
            return env && *env == '1';
        }();
        if (event.key.key == SDLK_F12) {
            if (down && !event.key.repeat) {
                VideoCore::RequestScreenshot(VideoCore::ScreenshotRequest::GameOnly);
            }
            return true;
        }
        if (down && !event.key.repeat && capture_key && event.key.key == SDLK_F11) {
            Vulkan::FrameCapture::Request();
            return true;
        }
        // F1 (and Insert) open and close the menu; Esc closes it.
        const bool toggle_key = event.key.key == SDLK_F1 || event.key.key == SDLK_INSERT;
        if (settings_menu_enabled && down && !event.key.repeat &&
            (toggle_key || (is_open && event.key.key == SDLK_ESCAPE))) {
            SetOpen(toggle_key ? !is_open : false);
            return true;
        }
        if (!is_open) {
            return false;
        }
        io.AddKeyEvent(ImGuiMod_Ctrl, (event.key.mod & SDL_KMOD_CTRL) != 0);
        io.AddKeyEvent(ImGuiMod_Shift, (event.key.mod & SDL_KMOD_SHIFT) != 0);
        io.AddKeyEvent(ImGuiMod_Alt, (event.key.mod & SDL_KMOD_ALT) != 0);
        if (const ImGuiKey key = KeyFromSdl(event.key.key); key != ImGuiKey_None) {
            io.AddKeyEvent(key, down);
        }
        return true;
    }
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
    case SDL_EVENT_GAMEPAD_BUTTON_UP: {
        const bool down = event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN;
        const u8 button = event.gbutton.button;
        // R3+L2 opens the optional host settings menu.
        if (button == SDL_GAMEPAD_BUTTON_RIGHT_STICK) {
            r3_down = down;
            if (settings_menu_enabled && down && l2_down) {
                SetOpen(!is_open);
                return true;
            }
        }
        if (!is_open) {
            return false;
        }
        if (const ImGuiKey key = KeyFromGamepad(button); key != ImGuiKey_None) {
            io.AddKeyEvent(key, down);
        }
        return true;
    }
    case SDL_EVENT_GAMEPAD_AXIS_MOTION: {
        if (event.gaxis.axis == SDL_GAMEPAD_AXIS_LEFT_TRIGGER) {
            const bool down = event.gaxis.value > 16000;
            if (settings_menu_enabled && down && !l2_down && r3_down) {
                l2_down = true;
                SetOpen(!is_open);
                return true;
            }
            l2_down = down;
        }
        return false;
    }
    case SDL_EVENT_TEXT_INPUT: {
        // Typed characters (Ctrl+click on a slider, a text field): key events alone erase but
        // do not type. SDL sends them while text input is on (UpdateTextInput).
        if (!is_open) {
            return false;
        }
        io.AddInputCharactersUTF8(event.text.text);
        return true;
    }
    case SDL_EVENT_MOUSE_MOTION: {
        if (!is_open) {
            return false;
        }
        const float density = PixelDensity(event.motion.windowID);
        io.AddMousePosEvent(event.motion.x * density, event.motion.y * density);
        return true;
    }
    case SDL_EVENT_MOUSE_BUTTON_DOWN:
    case SDL_EVENT_MOUSE_BUTTON_UP: {
        if (!is_open) {
            return false;
        }
        const int button = event.button.button == SDL_BUTTON_LEFT    ? 0
                           : event.button.button == SDL_BUTTON_RIGHT  ? 1
                           : event.button.button == SDL_BUTTON_MIDDLE ? 2
                                                                      : -1;
        if (button >= 0) {
            io.AddMouseButtonEvent(button, event.type == SDL_EVENT_MOUSE_BUTTON_DOWN);
        }
        return true;
    }
    case SDL_EVENT_MOUSE_WHEEL:
        if (!is_open) {
            return false;
        }
        io.AddMouseWheelEvent(event.wheel.x, event.wheel.y);
        return true;
    default:
        return false;
    }
}

// After "Apply and restart", the new options are kept once the game has shown about ten
// seconds of frames after loading (run.py restores the previous ones otherwise).
void ConfirmRestart() {
    static u32 frames = 0;
    auto& s = Ps4Settings::Get();
    if (!s.restart_unconfirmed || loading || ++frames < 600) {
        return;
    }
    s.restart_unconfirmed = false;
    Ps4Settings::Save();
    std::puts("Settings: graphics options confirmed after restart");
}

void SetBackgroundLoading(u32 done, u32 total) {
    background_done = done;
    background_total = total;
}

void SetLoading(bool active, u32 done, u32 total) {
    loading_done = done;
    loading_total = total;
    loading = active;
}

bool Visible() {
    const auto& s = Ps4Settings::Get();
    return initialized && (loading || background_total || menu_open || text_entry_active || choice_active ||
                           choice_retiring || s.show_fps || NoticeActive());
}

bool CapturesInput() {
    return menu_open || text_entry_active || choice_active;
}

void BeginChoice(const std::string& title, const std::vector<std::string>& items,
                 std::vector<Ps4Png::Image> pictures, int focus) {
    std::scoped_lock lock{imgui_mutex};
    RetireChoiceTextures();
    choice_pictures = std::move(pictures);
    choice_pictures.resize(items.size());
    choice_title = title;
    choice_items = items;
    choice_index = focus >= 0 && focus < int(items.size()) ? focus : 0;
    choice_result = -1;
    choice_active = true;
}

int PollChoice() {
    return choice_result;
}

void SetTextEntry(bool active, const std::string& prompt, const std::string& text) {
    std::scoped_lock lock{imgui_mutex};
    text_entry_active = active;
    text_entry_prompt = prompt;
    text_entry_text = text;
}

void Render(vk::CommandBuffer cmdbuf, vk::ImageView view, vk::Extent2D extent) {
    // ImGui needs a UI delta even when no presentation sample exists yet.
    const auto now = std::chrono::steady_clock::now();
    const float ms = std::chrono::duration<float, std::milli>(now - last_ui_frame).count();
    last_ui_frame = now;
    ConfirmRestart();
    Menu::EnforceFrameRate();
    if (!Visible()) {
        return;
    }
    std::scoped_lock lock{imgui_mutex};
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(float(extent.width), float(extent.height));
    io.DeltaTime = ms > 0.0f && ms < 1000.0f ? ms / 1000.0f : 1.0f / 60.0f;
    // UI scale follows the display height (1080p = 1).
    const float scale = std::max(float(extent.height) / 1080.0f, 0.75f);
    if (std::abs(scale - base_scale) > 0.01f) {
        ImGuiStyle& style = ImGui::GetStyle();
        style.ScaleAllSizes(scale / base_scale);
        style.FontScaleMain = scale;
        base_scale = scale;
    }

    UpdateChoiceTextures();
    ImGui_ImplVulkan_NewFrame();
    ImGui::NewFrame();
    if (loading) {
        LoadingScreen();
    }

    if (Ps4Settings::Get().show_fps && !menu_open) {
        FpsCounter();
    }
    if (NoticeActive()) {
        Notice();
    }

    if (background_total && !loading && !menu_open) {
        BackgroundLoading();
    }
    if (text_entry_active) {
        TextEntryBox();
    }
    if (choice_active && !menu_open) {
        ChoiceBox();
    }
    if (menu_open) {
        Menu::Draw();
    }
    ImGui::Render();

    const vk::RenderingAttachmentInfo attachment{
        .imageView = view,
        .imageLayout = vk::ImageLayout::eColorAttachmentOptimal,
        .loadOp = vk::AttachmentLoadOp::eLoad,
        .storeOp = vk::AttachmentStoreOp::eStore,
    };
    cmdbuf.beginRendering(vk::RenderingInfo{
        .renderArea = {{0, 0}, extent},
        .layerCount = 1,
        .colorAttachmentCount = 1,
        .pColorAttachments = &attachment,
    });
    {
        // Font atlas uploads submit to the graphics queue themselves.
        std::scoped_lock submit_lock{Vulkan::Scheduler::submit_mutex};
        ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), cmdbuf);
    }
    cmdbuf.endRendering();
}

} // namespace Ps4Overlay
