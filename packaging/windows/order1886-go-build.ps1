param(
    [Parameter(Mandatory=$true)][string]$Runtime,
    [string]$DependencyRoot = 'C:/msys64/clang64/bin',
    [string]$Python = 'python',
    [switch]$SkipFrontendBuild,
    [switch]$SkipDependencyInstall
)
$ErrorActionPreference = 'Stop'
function Get-SHA256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}

# Copy the runtime plus every non-system DLL it imports, so the package runs on a machine without the
# build toolchain that produced it. This used to live in the retired Python-launcher builder.
function Copy-RuntimeDependencies([string]$Executable, [string]$Target, [string]$DependencyPath) {
    $inspector = Join-Path $DependencyPath 'llvm-readobj.exe'
    if (-not (Test-Path -LiteralPath $inspector)) { throw "Missing dependency inspector: $inspector" }
    $origin = Split-Path -Parent $Executable
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item -LiteralPath $Executable -Destination (Join-Path $Target 'order1886-runtime.exe')
    $seen = @{}
    $pending = [System.Collections.Generic.Queue[string]]::new()
    $pending.Enqueue($Executable)
    while ($pending.Count -gt 0) {
        $binary = $pending.Dequeue()
        $imports = & $inspector --coff-imports $binary
        if ($LASTEXITCODE) { throw "Could not inspect PE imports: $binary" }
        foreach ($line in $imports) {
            if ($line -notmatch '^\s*Name:\s*(\S+\.dll)\s*$') { continue }
            $name = $Matches[1]
            $key = $name.ToLowerInvariant()
            if ($seen.ContainsKey($key)) { continue }
            $seen[$key] = $true
            $candidates = @((Join-Path $origin $name), (Join-Path $DependencyPath $name))
            $found = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
            if ($found) {
                Copy-Item -LiteralPath $found -Destination (Join-Path $Target $name)
                $pending.Enqueue($found)
            } elseif ($name -notmatch '^(api-ms-|ext-ms-)' -and
                      -not (Test-Path -LiteralPath (Join-Path "$env:SystemRoot/System32" $name))) {
                throw "Unresolved host dependency $name imported by $binary"
            }
        }
    }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtimePath = (Resolve-Path -LiteralPath $Runtime).Path
$runtimeIdentityPath = Join-Path (Split-Path -Parent $runtimePath) 'runtime-build.json'
if (-not (Test-Path -LiteralPath $runtimeIdentityPath)) {
    throw 'The runtime build receipt is missing next to the runtime; build it with build.sh first.'
}
$runtimeBuild = Get-Content -LiteralPath $runtimeIdentityPath -Raw | ConvertFrom-Json
if ($runtimeBuild.game_profile -ne 'order1886' -or $runtimeBuild.runtime_abi -ne 'order1886-native-1') {
    throw 'This runtime is not a dedicated Order build.'
}
$dependencyPath = (Resolve-Path -LiteralPath $DependencyRoot).Path
$hash = Get-SHA256 $runtimePath

$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stage = Join-Path $projectRoot "out/order1886-go-package/$stamp"
$destination = Join-Path $stage 'The Order 1886'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$incomplete = Join-Path $destination 'GO-BUILD-INCOMPLETE.txt'
'This Go preview is incomplete until packaging and smoke checks finish.' | Set-Content -LiteralPath $incomplete -Encoding UTF8
Push-Location (Join-Path $projectRoot 'launcher-go')
try {
    if (-not $SkipFrontendBuild) {
        & go run github.com/wailsapp/wails/v2/cmd/wails@v2.17.0 build -clean -skipbindings
        if ($LASTEXITCODE) { throw 'Go launcher build failed.' }
    }
    $goLauncher = Join-Path $projectRoot 'launcher-go/build/bin/The Order 1886.exe'
    if (-not (Test-Path -LiteralPath $goLauncher)) { throw 'Go launcher executable is missing.' }
    foreach ($name in @('The Order 1886.exe','Play The Order 1886.exe')) {
        Copy-Item -LiteralPath $goLauncher -Destination (Join-Path $destination $name) -Force
    }

    # Runtime payload: the exe, the DLLs it imports, and its build receipt.
    $runtimeBin = Join-Path $destination 'bin'
    Copy-RuntimeDependencies $runtimePath $runtimeBin $dependencyPath
    if ((Get-SHA256 (Join-Path $runtimeBin 'order1886-runtime.exe')) -ne $hash) {
        throw 'Runtime changed during packaging. Re-run after the source build has finished.'
    }
    Copy-Item -LiteralPath $runtimeIdentityPath -Destination (Join-Path $runtimeBin 'runtime-build.json')
    # The FSR 3.1 provider the runtime loads from its own folder for the Upscaling choice (#10).
    # It imports only libc++ and the Vulkan loader, which the runtime already brought along.
    $provider = Join-Path (Split-Path -Parent $runtimePath) 'order1886_fsr3.dll'
    if (-not (Test-Path -LiteralPath $provider)) {
        throw 'order1886_fsr3.dll is missing next to the runtime; build it with build.sh first.'
    }
    Copy-Item -LiteralPath $provider -Destination (Join-Path $runtimeBin 'order1886_fsr3.dll')
    # NVIDIA DLAA (#11): the MSVC-built bridge and NVIDIA's runtime, when gpu/dlss_bridge/build.ps1
    # staged them beside the runtime. Both or neither: the bridge cannot work without the runtime.
    $runtimeDir = Split-Path -Parent $runtimePath
    $dlss = @('order1886_dlss.dll', 'nvngx_dlss.dll') | ForEach-Object { Join-Path $runtimeDir $_ }
    $present = @($dlss | Where-Object { Test-Path -LiteralPath $_ })
    if ($present.Count -eq 1) { throw 'Only one of order1886_dlss.dll and nvngx_dlss.dll is next to the runtime.' }
    if ($present.Count -eq 2) {
        $nvidiaLicense = Join-Path $runtimeDir 'NVIDIA-DLSS-LICENSE.txt'
        if (-not (Test-Path -LiteralPath $nvidiaLicense)) { throw 'NVIDIA-DLSS-LICENSE.txt must accompany nvngx_dlss.dll.' }
        $dlss | ForEach-Object { Copy-Item -LiteralPath $_ -Destination $runtimeBin }
        New-Item -ItemType Directory -Force -Path (Join-Path $destination 'notices') | Out-Null
        Copy-Item -LiteralPath $nvidiaLicense -Destination (Join-Path $destination 'notices/NVIDIA-DLSS-LICENSE.txt')
    }

    $modules = @(& go list -deps -tags desktop,production -f '{{with .Module}}{{if not .Main}}{{.Path}}|{{.Version}}|{{.Dir}}{{end}}{{end}}' .)
    if ($LASTEXITCODE) { throw 'Go dependency listing failed.' }
    $copiedModules = @{}
    foreach ($module in $modules) {
        if (-not $module.Trim()) { continue }
        $parts = $module.Split('|')
        if ($copiedModules.ContainsKey($parts[0])) { continue }
        $copiedModules[$parts[0]] = $true
        $licenses = @(Get-ChildItem -LiteralPath $parts[2] -File | Where-Object { $_.Name -match '^(LICENSE|LICENCE|COPYING|NOTICE|PATENTS|UNLICENSE)' })
        if (-not $licenses.Count) { throw "Missing license metadata for $($parts[0])" }
        $notice = Join-Path $destination ("notices/go/" + $parts[0].Replace('/','_') + '@' + $parts[1])
        New-Item -ItemType Directory -Force -Path $notice | Out-Null
        foreach ($license in $licenses) { Copy-Item -LiteralPath $license.FullName -Destination $notice }
    }
    $goRoot = (& go env GOROOT | Out-String).Trim()
    Copy-Item -LiteralPath (Join-Path $goRoot 'LICENSE') -Destination (Join-Path $destination 'notices/go/GO-STDLIB-LICENSE')
    Write-Output $destination
} finally { Pop-Location }

$venv = Join-Path $projectRoot 'out/order1886-pyenv'
if (-not (Test-Path "$venv/Scripts/python.exe")) {
    & $Python -m venv $venv
    if ($LASTEXITCODE) { throw 'Virtual environment creation failed.' }
}
$buildPython = Join-Path $venv 'Scripts/python.exe'
if (-not $SkipDependencyInstall) {
    & $buildPython -m pip install --disable-pip-version-check 'pyinstaller==6.20.0' 'pillow==12.3.0' 'cryptography==50.0.1'
    if ($LASTEXITCODE) { throw 'Build dependencies installation failed.' }
}

# Launcher artwork and the documents a player reads first.
$artwork = Join-Path $stage 'artwork'
& $buildPython (Join-Path $PSScriptRoot 'order1886_icon.py') $artwork
if ($LASTEXITCODE) { throw 'Launcher icon conversion failed.' }
foreach ($name in @('logo-horizontal.png', 'logo-stacked.png', 'app-icon.png', 'BRANDING.txt',
        'launcher-art.jpg', 'launcher-art.txt')) {
    Copy-Item -LiteralPath (Join-Path "$projectRoot/launcher/order1886" $name) -Destination $artwork
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination $destination
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README-Order1886.txt') -Destination $destination
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'QUICKSTART-Order1886.txt') -Destination (Join-Path $destination 'QUICKSTART.txt')
$noticeRoot = Join-Path $destination 'notices'
New-Item -ItemType Directory -Force -Path $noticeRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ATTRIBUTION-Order1886.txt') -Destination (Join-Path $noticeRoot 'ATTRIBUTION.txt')
& $buildPython (Join-Path $PSScriptRoot 'order1886_notices.py') (Join-Path $noticeRoot 'python')
if ($LASTEXITCODE) { throw 'Python notices generation failed.' }

# The worker that the Go launcher drives over stdio.
$scriptData = Join-Path $stage 'scripts'
New-Item -ItemType Directory -Force -Path $scriptData | Out-Null
foreach ($name in @('prepare.py','link_modules.py','link_libc.py','save_backup.py',
        'order1886_frame_rate.py','order1886_display.py','order1886_resolution.py','order1886_post_effects.py','order1886_cache.py',
        'order1886_steam.py','order1886_mods.py','order1886_trophy_history.py','order1886_trophy_text.py','order1886_input.py',
        # performance.report reads the recorded CSV through the shared frame-trace parser.
        'order1886_frame_trace.py','order1886_perf_report.py',
        # order1886.py imports this by name from the shipped scripts/ directory; without it
        # every packaged Play fails on the import, before any game file is read.
        'order1886_patches.py','order1886_editions.py')) {
    Copy-Item -LiteralPath (Join-Path "$projectRoot/scripts" $name) -Destination $scriptData
}
& $buildPython -m PyInstaller --noconfirm --clean --console --onedir --log-level WARN --name order1886-worker --paths $projectRoot --add-data "$scriptData;scripts" --distpath "$stage/worker-dist" --workpath "$stage/worker-build" --specpath $stage "$projectRoot/launcher/order1886_worker.py"
if ($LASTEXITCODE) { throw 'Worker build failed.' }
foreach ($entry in Get-ChildItem -LiteralPath "$stage/worker-dist/order1886-worker") {
    Copy-Item -LiteralPath $entry.FullName -Destination (Join-Path $destination 'bin') -Recurse -Force
}

$manifest = [ordered]@{
    product='The Order: 1886'; launcher='Go / Wails v2.17.0'; status='release'
    built_utc=(Get-Date).ToUniversalTime().ToString('o'); runtime_sha256=$hash
    runtime_build=$runtimeBuild
    # Advertised only now that the copied helper and startup recovery exist.
    update_abi='order1886-update-2'
    source_revision=(& git -C $projectRoot rev-parse HEAD | Out-String).Trim()
    source_dirty=([bool](& git -C $projectRoot status --porcelain | Out-String).Trim())
    files=@()
}
$manifest.files = @(Get-ChildItem -LiteralPath $destination -File -Recurse | Where-Object {
    $_.Name -notin @('package-manifest.json','GO-BUILD-INCOMPLETE.txt')
} | ForEach-Object {
    [ordered]@{path=$_.FullName.Substring($destination.Length+1).Replace('\','/'); sha256=(Get-SHA256 $_.FullName)}
})
$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $destination 'package-manifest.json') -Encoding UTF8
& $buildPython "$projectRoot/packaging/windows/order1886-go-smoke.py" $destination
if ($LASTEXITCODE) { throw 'Go portable smoke failed; the incomplete marker remains.' }
Remove-Item -LiteralPath $incomplete
Write-Output $destination
