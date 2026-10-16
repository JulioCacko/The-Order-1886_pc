#pragma once

namespace Vulkan {

// Refresh the selected translation, never the program's canonical lookup layout.
// Its walker and flattened offsets belong to the same module as its resource lists.
template <typename Module, typename Params>
auto& RefreshPermutationInfo(Module& module, const Params& params) {
    auto& info = *module.info;
    info.pgm_base = params.Base();
    info.user_data = params.user_data;
    info.RefreshFlatBuf();
    return info;
}

} // namespace Vulkan
