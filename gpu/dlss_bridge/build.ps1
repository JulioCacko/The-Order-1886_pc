param([string]$SdkPath, [string]$VulkanInclude)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$deps = Join-Path $repo 'out/deps'
$build = Join-Path $repo 'out/dlss-bridge'
$archive = Join-Path $deps 'DLSS-v310.9.16.zip'
$source = 'https://github.com/NVIDIA/DLSS/archive/refs/tags/v310.9.16.zip'
$archiveHash = '418d6c685b062855f970d55d1e172eff834658a17b3483aaffddf44d5b0cb026'
$runtimeHash = 'd00b5b0ab29c3ca101b70c3a5ecb3a01b7ef33766a3383a28a18623083e6123e'
if (!$SdkPath) { $SdkPath = Join-Path $deps 'DLSS-310.9.16' }
if (!(Test-Path -LiteralPath $SdkPath)) {
    New-Item -ItemType Directory -Path $deps -Force | Out-Null
    if (!(Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest -Uri $source -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $archiveHash) {
        throw 'Official SDK archive hash differs from the verified 310.9.16 source; inspect before proceeding'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $deps -Force
}
$SdkPath = (Resolve-Path -LiteralPath $SdkPath).Path
$runtime = Join-Path $SdkPath 'lib/Windows_x86_64/rel/nvngx_dlss.dll'
if ((Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash.ToLowerInvariant() -ne $runtimeHash) {
    throw 'Expected the verified official release nvngx_dlss.dll 310.9.16.0'
}
if (!$VulkanInclude) {
    $cache = Join-Path $repo 'out/gpu/CMakeCache.txt'
    if (Test-Path -LiteralPath $cache) {
        $match = Select-String -LiteralPath $cache -Pattern '^Vulkan_INCLUDE_DIR:PATH=(.+)$'
        if ($match) { $VulkanInclude = $match.Matches[0].Groups[1].Value }
    }
}
if (!$VulkanInclude -or !(Test-Path -LiteralPath (Join-Path $VulkanInclude 'vulkan/vulkan.h'))) {
    throw 'Pass -VulkanInclude pointing to installed Vulkan headers (no SDK installation is performed)'
}
# MSYS include roots also contain an incompatible C runtime; isolate only Vulkan headers for MSVC.
$isolated = Join-Path $deps 'vulkan-headers/include'
New-Item -ItemType Directory -Path $isolated -Force | Out-Null
foreach ($dir in @('vulkan', 'vk_video')) {
    $from = Join-Path $VulkanInclude $dir
    $to = Join-Path $isolated $dir
    if ((Test-Path -LiteralPath $from) -and ([IO.Path]::GetFullPath($from) -ne [IO.Path]::GetFullPath($to))) {
        Copy-Item -LiteralPath $from -Destination $isolated -Recurse -Force
    }
}
& cmake -S $PSScriptRoot -B $build -G 'Visual Studio 17 2022' -A x64 "-DORDER_DLSS_SDK:PATH=$SdkPath" "-DORDER_VULKAN_INCLUDE:PATH=$isolated"
if ($LASTEXITCODE) { throw 'DLSS configure failed' }
& cmake --build $build --config Release
if ($LASTEXITCODE) { throw 'DLSS build failed' }
& ctest --test-dir $build -C Release --output-on-failure
if ($LASTEXITCODE) { throw 'DLSS CPU contracts failed' }
$release = Join-Path $build 'Release'
Copy-Item -LiteralPath $runtime -Destination $release -Force
Copy-Item -LiteralPath (Join-Path $SdkPath 'LICENSE.txt') -Destination (Join-Path $release 'NVIDIA-DLSS-LICENSE.txt') -Force
$files = @('include/nvsdk_ngx_vk.h', 'lib/Windows_x86_64/x64/nvsdk_ngx_s.lib', 'lib/Windows_x86_64/rel/nvngx_dlss.dll', 'LICENSE.txt')
$hashes = foreach ($file in $files) {
    [ordered]@{ path=$file; sha256=(Get-FileHash -LiteralPath (Join-Path $SdkPath $file)).Hash.ToLowerInvariant() }
}
$receipt = [ordered]@{
    source=$source; sdk='310.9.16'; archive_sha256=$archiveHash
    runtime_version=(Get-Item -LiteralPath $runtime).VersionInfo.FileVersion
    plugin_sha256=(Get-FileHash -LiteralPath (Join-Path $release 'order1886_dlss.dll')).Hash.ToLowerInvariant()
    proprietary_files_tracked=$false; gpu_initialization_tested=$false; files=$hashes
}
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $build 'provenance.json') -Encoding utf8
Write-Output "Optional DLL and NVIDIA runtime staged only in $release; GPU integration remains unverified."
