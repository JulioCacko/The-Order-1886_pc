// Provider ABI for Order-specific temporal reconstruction. Images contain only the
// active scene; HUD and letterboxing are composed by the caller after reconstruction.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <vulkan/vulkan.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ORDER1886_UPSCALE_ABI 1u
typedef enum OrderUpscaleStatus {
    ORDER_UPSCALE_OK = 0,
    ORDER_UPSCALE_INVALID_ARGUMENT = 1,
    ORDER_UPSCALE_UNSUPPORTED = 2,
    ORDER_UPSCALE_BACKEND_ERROR = 3
} OrderUpscaleStatus;

enum {
    ORDER_UPSCALE_HDR = 1u << 0,
    ORDER_UPSCALE_DEPTH_INVERTED = 1u << 1,
    ORDER_UPSCALE_DEPTH_INFINITE = 1u << 2,
    ORDER_UPSCALE_MOTION_JITTERED = 1u << 3
};

typedef struct OrderUpscaleDevice {
    VkInstance instance;
    VkPhysicalDevice physical_device;
    VkDevice device;
    PFN_vkGetInstanceProcAddr get_instance_proc_addr;
    PFN_vkGetDeviceProcAddr get_device_proc_addr;
    VkQueue graphics_queue;
    uint32_t graphics_queue_family;
    // Enabled logical-device feature, not merely advertised physical support.
    VkBool32 shader_storage_image_write_without_format_enabled;
} OrderUpscaleDevice;

typedef struct OrderUpscaleConfig {
    uint32_t max_render_width, max_render_height;
    uint32_t output_width, output_height;
    uint32_t flags;
} OrderUpscaleConfig;

typedef struct OrderUpscaleImage {
    VkImage image;
    VkImageView view;
    VkFormat format;
    uint32_t width, height;
    VkImageUsageFlags usage;
    VkImageLayout layout;
} OrderUpscaleImage;

typedef struct OrderUpscaleFrame {
    VkCommandBuffer command_buffer;
    // Baseline adapter formats: RGBA16F color/output, R32F depth, RG16F motion.
    // Motion direction/convention must be verified from Order's captured frame.
    OrderUpscaleImage color, depth, motion, output;
    uint32_t render_width, render_height;
    float jitter_x, jitter_y;
    float motion_scale_x, motion_scale_y;
    float frame_time_ms, pre_exposure;
    float camera_near, camera_far, vertical_fov;
    uint32_t reset_history;
} OrderUpscaleFrame;

typedef struct OrderUpscaleProviderApi {
    uint32_t abi_version;
    const char* name;
    const char* version;
    // Query before Vulkan instance/device creation. Returned strings remain owned
    // by the loaded provider. Providers requiring no extensions return count=0.
    OrderUpscaleStatus (*required_instance_extensions)(uint32_t* count, const char* const** names,
                                                       char* error, size_t error_size);
    OrderUpscaleStatus (*required_device_extensions)(VkInstance, VkPhysicalDevice,
                                                     uint32_t* count, const char* const** names,
                                                     char* error, size_t error_size);
    // create/dispatch return errors without exceptions across the ABI. Failed create
    // leaves *context null. Caller keeps resources alive until GPU work completes.
    OrderUpscaleStatus (*create)(const OrderUpscaleDevice*, const OrderUpscaleConfig*,
                                 void** context, char* error, size_t error_size);
    OrderUpscaleStatus (*dispatch)(void* context, const OrderUpscaleFrame*,
                                   char* error, size_t error_size);
    void (*destroy)(void* context);
} OrderUpscaleProviderApi;

typedef OrderUpscaleStatus (*OrderUpscaleGetApi)(uint32_t abi, OrderUpscaleProviderApi* api);

#ifdef __cplusplus
}
#endif
