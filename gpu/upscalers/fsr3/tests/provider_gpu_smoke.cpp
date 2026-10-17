#include "order1886_upscale.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" OrderUpscaleStatus order1886_fsr_get_api(uint32_t, OrderUpscaleProviderApi*);

// Manual synthetic fixture only: static scene, constant depth, and zero motion.
// All submissions/waits belong to this harness, never to the provider.
namespace {
constexpr uint32_t width = 128, height = 72, out_width = 256, out_height = 144;
static uint32_t validation_errors = 0, validation_warnings = 0;
void require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
void vk_check(VkResult result, const char* operation) {
    if (result != VK_SUCCESS) throw std::runtime_error(std::string(operation) + ": VkResult=" + std::to_string(result));
}
VKAPI_ATTR VkBool32 VKAPI_CALL debug_callback(VkDebugUtilsMessageSeverityFlagBitsEXT severity,
    VkDebugUtilsMessageTypeFlagsEXT, const VkDebugUtilsMessengerCallbackDataEXT* data, void*) {
    if (severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT) ++validation_errors;
    if (severity & VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT) ++validation_warnings;
    std::fprintf(stderr, "VALIDATION [%s] %s\n", data->pMessageIdName ? data->pMessageIdName : "unknown", data->pMessage);
    return VK_FALSE;
}
struct Image {
    VkImage image = VK_NULL_HANDLE;
    VkImageView view = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkFormat format{};
    uint32_t width{}, height{};
    VkImageUsageFlags usage{};
};
struct State {
    OrderUpscaleProviderApi api{};
    void* context = nullptr;
    VkInstance instance = VK_NULL_HANDLE;
    VkDebugUtilsMessengerEXT messenger = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkCommandBuffer command = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    VkBuffer staging = VK_NULL_HANDLE, readback = VK_NULL_HANDLE;
    VkDeviceMemory staging_memory = VK_NULL_HANDLE, readback_memory = VK_NULL_HANDLE;
    Image images[4];
    ~State() {
        if (device) {
            vkDeviceWaitIdle(device);
            if (context) api.destroy(context);
            for (auto& image : images) {
                if (image.view) vkDestroyImageView(device, image.view, nullptr);
                if (image.image) vkDestroyImage(device, image.image, nullptr);
                if (image.memory) vkFreeMemory(device, image.memory, nullptr);
            }
            if (staging) vkDestroyBuffer(device, staging, nullptr);
            if (readback) vkDestroyBuffer(device, readback, nullptr);
            if (staging_memory) vkFreeMemory(device, staging_memory, nullptr);
            if (readback_memory) vkFreeMemory(device, readback_memory, nullptr);
            if (fence) vkDestroyFence(device, fence, nullptr);
            if (pool) vkDestroyCommandPool(device, pool, nullptr);
            vkDestroyDevice(device, nullptr);
        }
        if (messenger) {
            auto destroy = reinterpret_cast<PFN_vkDestroyDebugUtilsMessengerEXT>(vkGetInstanceProcAddr(instance, "vkDestroyDebugUtilsMessengerEXT"));
            if (destroy) destroy(instance, messenger, nullptr);
        }
        if (instance) vkDestroyInstance(instance, nullptr);
    }
};
uint32_t memory_type(State& s, uint32_t bits, VkMemoryPropertyFlags flags) {
    VkPhysicalDeviceMemoryProperties p{}; vkGetPhysicalDeviceMemoryProperties(s.physical, &p);
    for (uint32_t i = 0; i < p.memoryTypeCount; ++i)
        if ((bits & (1u << i)) && (p.memoryTypes[i].propertyFlags & flags) == flags) return i;
    throw std::runtime_error("Required memory type unavailable");
}
void buffer(State& s, VkDeviceSize size, VkBufferUsageFlags usage, VkBuffer& out, VkDeviceMemory& memory) {
    VkBufferCreateInfo create{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    create.size = size; create.usage = usage; create.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    vk_check(vkCreateBuffer(s.device, &create, nullptr, &out), "vkCreateBuffer");
    VkMemoryRequirements requirements{}; vkGetBufferMemoryRequirements(s.device, out, &requirements);
    VkMemoryAllocateInfo allocate{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    allocate.allocationSize = requirements.size;
    allocate.memoryTypeIndex = memory_type(s, requirements.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    vk_check(vkAllocateMemory(s.device, &allocate, nullptr, &memory), "vkAllocateMemory(buffer)");
    vk_check(vkBindBufferMemory(s.device, out, memory, 0), "vkBindBufferMemory");
}
void image(State& s, Image& out, VkFormat format, uint32_t w, uint32_t h, VkImageUsageFlags usage) {
    out.format = format; out.width = w; out.height = h; out.usage = usage;
    VkImageCreateInfo create{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
    create.imageType = VK_IMAGE_TYPE_2D; create.format = format; create.extent = {w, h, 1};
    create.mipLevels = create.arrayLayers = 1; create.samples = VK_SAMPLE_COUNT_1_BIT;
    create.tiling = VK_IMAGE_TILING_OPTIMAL; create.usage = usage; create.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    vk_check(vkCreateImage(s.device, &create, nullptr, &out.image), "vkCreateImage");
    VkMemoryRequirements requirements{}; vkGetImageMemoryRequirements(s.device, out.image, &requirements);
    VkMemoryAllocateInfo allocate{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    allocate.allocationSize = requirements.size;
    allocate.memoryTypeIndex = memory_type(s, requirements.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    vk_check(vkAllocateMemory(s.device, &allocate, nullptr, &out.memory), "vkAllocateMemory(image)");
    vk_check(vkBindImageMemory(s.device, out.image, out.memory, 0), "vkBindImageMemory");
    VkImageViewCreateInfo view{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    view.image = out.image; view.viewType = VK_IMAGE_VIEW_TYPE_2D; view.format = format;
    view.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vk_check(vkCreateImageView(s.device, &view, nullptr, &out.view), "vkCreateImageView");
}
void barrier(State& s, const Image& image, VkImageLayout old_layout, VkImageLayout new_layout,
    VkAccessFlags src_access, VkAccessFlags dst_access, VkPipelineStageFlags src_stage, VkPipelineStageFlags dst_stage) {
    VkImageMemoryBarrier b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
    b.srcAccessMask = src_access; b.dstAccessMask = dst_access; b.oldLayout = old_layout; b.newLayout = new_layout;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED; b.image = image.image;
    b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdPipelineBarrier(s.command, src_stage, dst_stage, 0, 0, nullptr, 0, nullptr, 1, &b);
}
OrderUpscaleImage abi_image(const Image& image, bool output = false) {
    return {image.image, image.view, image.format, image.width, image.height, image.usage,
        output ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
}
float half_float(uint16_t bits) {
    const int exponent = (bits >> 10) & 31, mantissa = bits & 1023;
    float result = exponent == 31 ? (mantissa ? std::numeric_limits<float>::quiet_NaN() : std::numeric_limits<float>::infinity())
        : exponent ? std::ldexp(float(mantissa + 1024), exponent - 25) : std::ldexp(float(mantissa), -24);
    return bits & 0x8000 ? -result : result;
}
void run(const std::filesystem::path& directory) {
    State s;
    require(order1886_fsr_get_api(ORDER1886_UPSCALE_ABI, &s.api) == ORDER_UPSCALE_OK, "Provider ABI unavailable");
    require(half_float(0x3c00) == 1 && half_float(0x3400) == 0.25f && half_float(0) == 0, "Half decode self-check");
    std::printf("Provider: %s %s\n", s.api.name, s.api.version);
    uint32_t count = 0;
    vk_check(vkEnumerateInstanceLayerProperties(&count, nullptr), "vkEnumerateInstanceLayerProperties");
    std::vector<VkLayerProperties> layers(count); vk_check(vkEnumerateInstanceLayerProperties(&count, layers.data()), "vkEnumerateInstanceLayerProperties");
    const char* validation = "VK_LAYER_KHRONOS_validation";
    bool has_validation = std::any_of(layers.begin(), layers.end(), [&](auto& l) { return !std::strcmp(l.layerName, validation); });
    vk_check(vkEnumerateInstanceExtensionProperties(nullptr, &count, nullptr), "vkEnumerateInstanceExtensionProperties");
    std::vector<VkExtensionProperties> instance_properties(count);
    vk_check(vkEnumerateInstanceExtensionProperties(nullptr, &count, instance_properties.data()), "vkEnumerateInstanceExtensionProperties");
    bool debug = std::any_of(instance_properties.begin(), instance_properties.end(), [](auto& e) { return !std::strcmp(e.extensionName, VK_EXT_DEBUG_UTILS_EXTENSION_NAME); });
    uint32_t required_count = 0; const char* const* required_names = nullptr; char error[512]{};
    require(s.api.required_instance_extensions(&required_count, &required_names, error, sizeof(error)) == ORDER_UPSCALE_OK, error);
    std::vector<const char*> instance_extensions;
    for (uint32_t i = 0; i < required_count; ++i) instance_extensions.push_back(required_names[i]);
    if (debug) instance_extensions.push_back(VK_EXT_DEBUG_UTILS_EXTENSION_NAME);
    VkApplicationInfo application{VK_STRUCTURE_TYPE_APPLICATION_INFO}; application.pApplicationName = "Order FSR synthetic smoke"; application.apiVersion = VK_API_VERSION_1_2;
    VkDebugUtilsMessengerCreateInfoEXT debug_info{VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT};
    debug_info.messageSeverity = VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT;
    debug_info.messageType = VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT;
    debug_info.pfnUserCallback = debug_callback;
    VkInstanceCreateInfo instance_info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    instance_info.pApplicationInfo = &application; instance_info.enabledExtensionCount = uint32_t(instance_extensions.size());
    instance_info.ppEnabledExtensionNames = instance_extensions.data();
    instance_info.enabledLayerCount = has_validation ? 1 : 0; instance_info.ppEnabledLayerNames = &validation;
    instance_info.pNext = debug ? &debug_info : nullptr;
    vk_check(vkCreateInstance(&instance_info, nullptr, &s.instance), "vkCreateInstance");
    if (debug) {
        auto create = reinterpret_cast<PFN_vkCreateDebugUtilsMessengerEXT>(vkGetInstanceProcAddr(s.instance, "vkCreateDebugUtilsMessengerEXT"));
        require(create, "Debug messenger function unavailable"); vk_check(create(s.instance, &debug_info, nullptr, &s.messenger), "vkCreateDebugUtilsMessengerEXT");
    }
    std::printf("Validation layer: %s; debug messenger: %s\n", has_validation ? "enabled" : "UNAVAILABLE", debug ? "enabled" : "UNAVAILABLE");
    vk_check(vkEnumeratePhysicalDevices(s.instance, &count, nullptr), "vkEnumeratePhysicalDevices");
    std::vector<VkPhysicalDevice> devices(count); vk_check(vkEnumeratePhysicalDevices(s.instance, &count, devices.data()), "vkEnumeratePhysicalDevices");
    for (auto physical : devices) {
        VkPhysicalDeviceProperties p{}; vkGetPhysicalDeviceProperties(physical, &p);
        if (std::strstr(p.deviceName, "RTX 3070")) { s.physical = physical; break; }
    }
    require(s.physical, "Requested RTX 3070 not found");
    VkPhysicalDeviceDriverProperties driver{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
    VkPhysicalDeviceProperties2 properties{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2}; properties.pNext = &driver;
    vkGetPhysicalDeviceProperties2(s.physical, &properties);
    auto& p = properties.properties;
    std::printf("GPU: %s; vendor=0x%04x device=0x%04x Vulkan=%u.%u.%u raw_driver=%u driver_name=%s driver_info=%s\n",
        p.deviceName, p.vendorID, p.deviceID, VK_VERSION_MAJOR(p.apiVersion), VK_VERSION_MINOR(p.apiVersion), VK_VERSION_PATCH(p.apiVersion), p.driverVersion, driver.driverName, driver.driverInfo);
    VkPhysicalDeviceFeatures features{}; vkGetPhysicalDeviceFeatures(s.physical, &features);
    require(features.shaderStorageImageWriteWithoutFormat, "Required storage image feature unsupported");
    VkPhysicalDeviceFeatures enabled{}; enabled.shaderStorageImageWriteWithoutFormat = VK_TRUE;
    uint32_t queue_count = 0; vkGetPhysicalDeviceQueueFamilyProperties(s.physical, &queue_count, nullptr);
    std::vector<VkQueueFamilyProperties> queue_properties(queue_count); vkGetPhysicalDeviceQueueFamilyProperties(s.physical, &queue_count, queue_properties.data());
    uint32_t family = UINT32_MAX;
    for (uint32_t i = 0; i < queue_count; ++i) if (queue_properties[i].queueCount && (queue_properties[i].queueFlags & VK_QUEUE_COMPUTE_BIT)) { family = i; break; }
    require(family != UINT32_MAX, "Compute queue unavailable");
    float priority = 1;
    VkDeviceQueueCreateInfo queue_info{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO}; queue_info.queueFamilyIndex = family; queue_info.queueCount = 1; queue_info.pQueuePriorities = &priority;
    require(s.api.required_device_extensions(s.instance, s.physical, &required_count, &required_names, error, sizeof(error)) == ORDER_UPSCALE_OK, error);
    VkDeviceCreateInfo device_info{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; device_info.queueCreateInfoCount = 1; device_info.pQueueCreateInfos = &queue_info;
    device_info.pEnabledFeatures = &enabled; device_info.enabledExtensionCount = required_count; device_info.ppEnabledExtensionNames = required_names;
    vk_check(vkCreateDevice(s.physical, &device_info, nullptr, &s.device), "vkCreateDevice");
    vkGetDeviceQueue(s.device, family, 0, &s.queue);
    OrderUpscaleDevice device{s.instance, s.physical, s.device, vkGetInstanceProcAddr, vkGetDeviceProcAddr, s.queue, family, VK_TRUE};
    OrderUpscaleConfig config{width, height, out_width, out_height, ORDER_UPSCALE_HDR};
    require(s.api.create(&device, &config, &s.context, error, sizeof(error)) == ORDER_UPSCALE_OK, error);
    std::puts("Real provider context created");
    const VkImageUsageFlags input_usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    image(s, s.images[0], VK_FORMAT_R16G16B16A16_SFLOAT, width, height, input_usage);
    image(s, s.images[1], VK_FORMAT_R32_SFLOAT, width, height, input_usage);
    image(s, s.images[2], VK_FORMAT_R16G16_SFLOAT, width, height, input_usage);
    image(s, s.images[3], VK_FORMAT_R16G16B16A16_SFLOAT, out_width, out_height, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
    constexpr VkDeviceSize color_bytes = width * height * 8, depth_bytes = width * height * 4, motion_bytes = width * height * 4;
    constexpr VkDeviceSize output_bytes = out_width * out_height * 8;
    buffer(s, color_bytes + depth_bytes + motion_bytes, VK_BUFFER_USAGE_TRANSFER_SRC_BIT, s.staging, s.staging_memory);
    buffer(s, output_bytes, VK_BUFFER_USAGE_TRANSFER_DST_BIT, s.readback, s.readback_memory);
    void* mapped = nullptr; vk_check(vkMapMemory(s.device, s.staging_memory, 0, VK_WHOLE_SIZE, 0, &mapped), "vkMapMemory(staging)");
    auto* color = static_cast<uint16_t*>(mapped);
    const uint16_t levels[] = {0x3000, 0x3400, 0x3600, 0x3800, 0x3900, 0x3a00, 0x3b00, 0x3c00};
    for (uint32_t y = 0; y < height; ++y) for (uint32_t x = 0; x < width; ++x) {
        const size_t i = (y * width + x) * 4;
        color[i] = levels[x * 8 / width]; color[i + 1] = levels[y * 8 / height];
        color[i + 2] = ((x / 8 + y / 8) & 1) ? 0x3400 : 0x3a00; color[i + 3] = 0x3c00;
    }
    auto* depth = reinterpret_cast<float*>(static_cast<uint8_t*>(mapped) + color_bytes);
    std::fill(depth, depth + width * height, 0.5f);
    std::memset(static_cast<uint8_t*>(mapped) + color_bytes + depth_bytes, 0, size_t(motion_bytes));
    vkUnmapMemory(s.device, s.staging_memory);
    VkCommandPoolCreateInfo pool_info{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; pool_info.queueFamilyIndex = family; pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    vk_check(vkCreateCommandPool(s.device, &pool_info, nullptr, &s.pool), "vkCreateCommandPool");
    VkCommandBufferAllocateInfo allocate{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO}; allocate.commandPool = s.pool; allocate.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY; allocate.commandBufferCount = 1;
    vk_check(vkAllocateCommandBuffers(s.device, &allocate, &s.command), "vkAllocateCommandBuffers");
    VkFenceCreateInfo fence_info{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO}; vk_check(vkCreateFence(s.device, &fence_info, nullptr, &s.fence), "vkCreateFence");
    std::filesystem::create_directories(directory);
    for (uint32_t frame_id = 0; frame_id < 2; ++frame_id) {
        auto start = std::chrono::steady_clock::now();
        vk_check(vkResetCommandBuffer(s.command, 0), "vkResetCommandBuffer");
        VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        vk_check(vkBeginCommandBuffer(s.command, &begin), "vkBeginCommandBuffer");
        if (frame_id == 0) {
            VkDeviceSize offset = 0;
            const VkDeviceSize sizes[] = {color_bytes, depth_bytes, motion_bytes};
            for (uint32_t i = 0; i < 3; ++i) {
                auto& img = s.images[i];
                barrier(s, img, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0, VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
                VkBufferImageCopy copy{}; copy.bufferOffset = offset; copy.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}; copy.imageExtent = {width, height, 1};
                vkCmdCopyBufferToImage(s.command, s.staging, img.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &copy);
                barrier(s, img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
                offset += sizes[i];
            }
            barrier(s, s.images[3], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, 0, VK_ACCESS_SHADER_WRITE_BIT, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
        } else {
            barrier(s, s.images[3], VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_GENERAL, VK_ACCESS_TRANSFER_READ_BIT, VK_ACCESS_SHADER_WRITE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT);
        }
        OrderUpscaleFrame frame{}; frame.command_buffer = s.command;
        frame.color = abi_image(s.images[0]); frame.depth = abi_image(s.images[1]); frame.motion = abi_image(s.images[2]); frame.output = abi_image(s.images[3], true);
        frame.render_width = width; frame.render_height = height; frame.motion_scale_x = width; frame.motion_scale_y = height;
        frame.frame_time_ms = 1000.0f / 60; frame.pre_exposure = 1; frame.camera_near = 0.1f; frame.camera_far = 1000; frame.vertical_fov = 1.0f; frame.reset_history = frame_id == 0;
        require(s.api.dispatch(s.context, &frame, error, sizeof(error)) == ORDER_UPSCALE_OK, error);
        barrier(s, s.images[3], VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT);
        VkBufferImageCopy copy{}; copy.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}; copy.imageExtent = {out_width, out_height, 1};
        vkCmdCopyImageToBuffer(s.command, s.images[3].image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, s.readback, 1, &copy);
        VkBufferMemoryBarrier host{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER}; host.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT; host.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
        host.srcQueueFamilyIndex = host.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED; host.buffer = s.readback; host.size = VK_WHOLE_SIZE;
        vkCmdPipelineBarrier(s.command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 0, nullptr, 1, &host, 0, nullptr);
        vk_check(vkEndCommandBuffer(s.command), "vkEndCommandBuffer");
        VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO}; submit.commandBufferCount = 1; submit.pCommandBuffers = &s.command;
        vk_check(vkQueueSubmit(s.queue, 1, &submit, s.fence), "harness vkQueueSubmit");
        vk_check(vkWaitForFences(s.device, 1, &s.fence, VK_TRUE, UINT64_C(30000000000)), "harness vkWaitForFences");
        vk_check(vkResetFences(s.device, 1, &s.fence), "vkResetFences");
        vk_check(vkMapMemory(s.device, s.readback_memory, 0, VK_WHOLE_SIZE, 0, &mapped), "vkMapMemory(readback)");
        const auto* values = static_cast<const uint16_t*>(mapped);
        float low = std::numeric_limits<float>::infinity(), high = -low; double sum = 0; bool finite = true;
        for (uint32_t i = 0; i < out_width * out_height * 4; ++i) {
            float value = half_float(values[i]); finite &= std::isfinite(value);
            if (i % 4 != 3) { low = std::min(low, value); high = std::max(high, value); sum += value; }
        }
        auto output_path = directory / ("frame-" + std::to_string(frame_id) + ".rgba16f");
        std::ofstream output(output_path, std::ios::binary); output.write(static_cast<const char*>(mapped), output_bytes); output.close();
        vkUnmapMemory(s.device, s.readback_memory);
        require(bool(output), "Readback file write failed");
        std::printf("frame=%u reset=%u finite=%d rgb_min=%.9g rgb_max=%.9g rgb_mean=%.9g wall_ms=%.3f output=%s\n",
            frame_id, frame.reset_history, finite, low, high, sum / (out_width * out_height * 3),
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count(), output_path.string().c_str());
        require(finite && high > 0.01f && high - low > 0.001f, "Output must be finite, nonblack and spatially varying");
    }
    s.api.destroy(s.context); s.context = nullptr;
    std::printf("Context destroyed after caller fence completion; validation_errors=%u validation_warnings=%u\n", validation_errors, validation_warnings);
    require(validation_errors == 0, "Vulkan validation errors were reported");
}
} // namespace
int main(int argc, char** argv) {
    if (argc != 3 || std::strcmp(argv[1], "--run-gpu")) {
        std::fprintf(stderr, "Explicit opt-in required: order1886_fsr3_gpu_smoke --run-gpu OUTPUT_DIRECTORY\n"); return 2;
    }
    try { run(argv[2]); return validation_errors ? 1 : 0; }
    catch (const std::exception& e) { std::fprintf(stderr, "FSR GPU smoke FAILED: %s\n", e.what()); return 1; }
}
