// SPDX-License-Identifier: GPL-2.0-or-later
//
// A guest sampler descriptor (S#) is narrower than the fields that hold it: three bits for
// max_aniso and two each for the filter modes. This tree used to answer "is it valid?" with an
// unconditional yes, so a reserved value reached the conversion switch (which aborts) or a
// custom border colour read guest address zero. Upstream shadPS4 validates it; this pins the rule.

#include <cstdio>
#include <cstdlib>
#include <string_view>

#include "video_core/amdgpu/resource.h"

namespace {

int fail(std::string_view message) {
    std::printf("%.*s\n", static_cast<int>(message.size()), message.data());
    return EXIT_FAILURE;
}

using AmdGpu::AnisoRatio;
using AmdGpu::BorderColor;
using AmdGpu::FilterMode;
using AmdGpu::MipFilter;
using AmdGpu::Sampler;

Sampler crafted(unsigned aniso, unsigned filter, unsigned mip, BorderColor border) {
    Sampler sampler{};
    sampler.max_aniso.Assign(static_cast<AnisoRatio>(aniso));
    sampler.filter_mode.Assign(static_cast<FilterMode>(filter));
    sampler.mip_filter.Assign(static_cast<MipFilter>(mip));
    sampler.border_color_type.Assign(border);
    return sampler;
}

} // Anonymous namespace

int main() {
    // A default descriptor is usable and needs no border-colour table.
    if (!Sampler{}.Usable(0)) {
        return fail("a zeroed sampler must be usable");
    }

    // Every representable enum value is accepted.
    for (unsigned aniso = 0; aniso <= 4; ++aniso) {
        if (!crafted(aniso, 0, 0, BorderColor::OpaqueBlack).Valid()) {
            return fail("every representable anisotropy ratio must be valid");
        }
    }
    for (unsigned filter = 0; filter <= 2; ++filter) {
        if (!crafted(0, filter, 0, BorderColor::OpaqueBlack).Valid()) {
            return fail("every representable filter mode must be valid");
        }
    }
    for (unsigned mip = 0; mip <= 2; ++mip) {
        if (!crafted(0, 0, mip, BorderColor::OpaqueBlack).Valid()) {
            return fail("every representable mip filter must be valid");
        }
    }

    // The reserved values the three-bit and two-bit fields can hold are refused, which is what
    // keeps them out of the conversion switch.
    for (unsigned aniso = 5; aniso <= 7; ++aniso) {
        if (crafted(aniso, 0, 0, BorderColor::OpaqueBlack).Valid()) {
            return fail("a reserved anisotropy ratio must be refused");
        }
    }
    if (crafted(0, 3, 0, BorderColor::OpaqueBlack).Valid()) {
        return fail("a reserved filter mode must be refused");
    }
    if (crafted(0, 0, 3, BorderColor::OpaqueBlack).Valid()) {
        return fail("a reserved mip filter must be refused");
    }

    // A custom border colour reads a table; without a base address the sampler cannot be decoded.
    if (crafted(0, 0, 0, BorderColor::Custom).Usable(0)) {
        return fail("a custom border colour without a base address must be refused");
    }
    if (!crafted(0, 0, 0, BorderColor::Custom).Usable(0x1000)) {
        return fail("a custom border colour with a base address must be usable");
    }
    // The other border colours never read the table, so a zero base is fine for them.
    for (const auto border : {BorderColor::TransparentBlack, BorderColor::OpaqueBlack,
                              BorderColor::White}) {
        if (!crafted(0, 0, 0, border).Usable(0)) {
            return fail("only a custom border colour needs the table");
        }
    }

    std::puts("Sampler descriptor: reserved field values and a missing border table are refused");
    return EXIT_SUCCESS;
}
