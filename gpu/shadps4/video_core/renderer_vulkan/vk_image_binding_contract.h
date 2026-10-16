#pragma once

#include <vulkan/vulkan.hpp>
#include "shader_recompiler/resource.h"

namespace Vulkan {

// The pipeline's resource declaration determines descriptor metadata, including when its
// current guest descriptor is null or rejected and no image view can be bound.
struct ImageBindingContract {
    bool storage;
    u32 count;

    void Apply(vk::WriteDescriptorSet& write, u32& next_binding) const {
        write.dstBinding = next_binding;
        write.descriptorCount = count;
        write.descriptorType = storage ? vk::DescriptorType::eStorageImage
                                       : vk::DescriptorType::eSampledImage;
        next_binding += count;
    }
};

inline ImageBindingContract MakeImageBindingContract(const Shader::ImageResource& resource,
                                                    const AmdGpu::Image& sharp) {
    return {resource.is_written, resource.NumBindings(sharp)};
}

} // namespace Vulkan
