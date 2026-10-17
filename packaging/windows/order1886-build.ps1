param(
    [string]$Python = 'python',
    [string]$Runtime = '',
    [string]$DependencyRoot = 'C:/msys64/clang64/bin',
    [switch]$SkipDependencyInstall
)
$ErrorActionPreference = 'Stop'
function Get-SHA256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $Runtime) { $Runtime = Join-Path $projectRoot 'out/order1886-runtime.exe' }
$runtimePath = (Resolve-Path -LiteralPath $Runtime).Path
$runtimeOriginDirectory = Split-Path $runtimePath
$runtimeIdentityPath = Join-Path (Split-Path $runtimePath) 'runtime-build.json'
if (-not (Test-Path -LiteralPath $runtimeIdentityPath)) {
    throw 'Build identity is missing. Build the Order runtime and write out/runtime-build.json first.'
}
$runtimeIdentity = Get-Content -LiteralPath $runtimeIdentityPath -Raw | ConvertFrom-Json
$runtimeHash = Get-SHA256 $runtimePath
if ($runtimeIdentity.game_profile -ne 'order1886' -or $runtimeIdentity.runtime_abi -ne 'order1886-native-1' -or
    $runtimeIdentity.runtime_sha256 -ne $runtimeHash) {
    throw 'Runtime identity does not match this Order build; refusing to package a reference runtime.'
}
$dependencyPath = (Resolve-Path -LiteralPath $DependencyRoot).Path
$inspector = Join-Path $dependencyPath 'llvm-readobj.exe'
if (-not (Test-Path -LiteralPath $inspector)) { throw "Missing dependency inspector: $inspector" }
$buildId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + $runtimeHash.Substring(0, 12)
$stage = Join-Path $projectRoot "out/order1886-package/$buildId"
$destination = Join-Path $projectRoot "dist/order1886/$buildId"
New-Item -ItemType Directory -Force -Path $stage, $destination | Out-Null
$incomplete = Join-Path $destination 'BUILD-INCOMPLETE.txt'
'This build has not finished. Do not distribute or use it as a validated package.' |
    Set-Content -LiteralPath $incomplete -Encoding UTF8
$snapshot = Join-Path $stage 'runtime-snapshot'
New-Item -ItemType Directory -Path $snapshot | Out-Null
Copy-Item -LiteralPath $runtimePath -Destination (Join-Path $snapshot 'order1886-runtime.exe')
Copy-Item -LiteralPath $runtimeIdentityPath -Destination $snapshot
$runtimePath = Join-Path $snapshot 'order1886-runtime.exe'
$runtimeIdentityPath = Join-Path $snapshot 'runtime-build.json'
$runtimeIdentity = Get-Content -LiteralPath $runtimeIdentityPath -Raw | ConvertFrom-Json
if ((Get-SHA256 $runtimePath) -ne $runtimeHash -or
    $runtimeIdentity.runtime_sha256 -ne $runtimeHash -or $runtimeIdentity.runtime_abi -ne 'order1886-native-1') {
    throw 'Runtime changed while creating the package snapshot. Retry after the source build has finished.'
}

# Follow every non-system PE dependency from this build's runtime or CLANG64.
function Copy-RuntimeDependencies([string]$Executable, [string]$Target) {
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item -LiteralPath $Executable -Destination (Join-Path $Target 'order1886-runtime.exe')
    $pending = [System.Collections.Generic.Queue[string]]::new()
    $seen = @{}
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
            $candidates = @((Join-Path $runtimeOriginDirectory $name), (Join-Path $dependencyPath $name))
            $source = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
            if ($source) {
                Copy-Item -LiteralPath $source -Destination (Join-Path $Target $name)
                $pending.Enqueue($source)
            } elseif ($name -notmatch '^(api-ms-|ext-ms-)' -and
                      -not (Test-Path -LiteralPath (Join-Path "$env:SystemRoot/System32" $name))) {
                throw "Unresolved host dependency $name imported by $binary"
            }
        }
    }
}

Push-Location $projectRoot
try {
    $venv = Join-Path $projectRoot 'out/order1886-pyenv'
    if (-not (Test-Path "$venv/Scripts/python.exe")) {
        & $Python -m venv $venv
        if ($LASTEXITCODE) { throw 'Virtual environment creation failed.' }
    }
    $buildPython = Join-Path $venv 'Scripts/python.exe'
    if (-not $SkipDependencyInstall) {
        & $buildPython -m pip install --disable-pip-version-check 'pyinstaller==6.20.0' 'pillow==12.3.0'
        if ($LASTEXITCODE) { throw 'Build dependencies installation failed.' }
    }
    $artwork = Join-Path $stage 'artwork'
    & $buildPython (Join-Path $PSScriptRoot 'order1886_icon.py') $artwork
    if ($LASTEXITCODE) { throw 'Original launcher icon generation failed.' }
    Copy-Item -LiteralPath "$projectRoot/launcher/order1886/launcher-art.png" -Destination $artwork
    Copy-Item -LiteralPath "$projectRoot/launcher/order1886/launcher-art.txt" -Destination $artwork
    Copy-Item -LiteralPath "$projectRoot/launcher/order1886/play-brass.png" -Destination $artwork
    $scriptData = Join-Path $stage 'scripts'
    New-Item -ItemType Directory -Force -Path $scriptData | Out-Null
    # This is the complete source/data closure of the Order preparation path.
    # Do not ship unrelated patch, overlay, mod, resource or title helpers.
    foreach ($name in @('prepare.py', 'link_modules.py', 'link_libc.py', 'save_backup.py', 'order1886_frame_rate.py', 'order1886_display.py')) {
        Copy-Item -LiteralPath (Join-Path "$projectRoot/scripts" $name) -Destination (Join-Path $scriptData $name)
    }
    $pythonSource = Join-Path $stage 'python-source'
    New-Item -ItemType Directory -Force -Path "$pythonSource/launcher" | Out-Null
    Copy-Item -LiteralPath "$projectRoot/order1886.py" -Destination "$pythonSource/order1886.py"
    Copy-Item -LiteralPath "$projectRoot/launcher/order1886_launcher.py" -Destination "$pythonSource/launcher/order1886_launcher.py"
    $pythonSources = [ordered]@{
        'order1886.py'=(Get-SHA256 "$pythonSource/order1886.py")
        'launcher/order1886_launcher.py'=(Get-SHA256 "$pythonSource/launcher/order1886_launcher.py")
    }
    foreach ($name in @('prepare.py', 'link_modules.py', 'link_libc.py', 'save_backup.py', 'order1886_frame_rate.py', 'order1886_display.py')) {
        $pythonSources["scripts/$name"] = Get-SHA256 (Join-Path $scriptData $name)
    }
    $versionFile = Join-Path $stage 'version-info.txt'
    @'
VSVersionInfo(ffi=FixedFileInfo(filevers=(0,1,0,0), prodvers=(0,1,0,0), mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=[StringFileInfo([StringTable('040904B0', [StringStruct('CompanyName','The Order 1886 PC compatibility project'), StringStruct('FileDescription','The Order: 1886 Launcher'), StringStruct('FileVersion','0.1.0'), StringStruct('InternalName','Order1886Launcher'), StringStruct('OriginalFilename','The Order 1886.exe'), StringStruct('ProductName','The Order: 1886'), StringStruct('ProductVersion','0.1.0 - experimental'), StringStruct('LegalCopyright','Community compatibility software. See LICENSE and notices.')])]), VarFileInfo([VarStruct('Translation',[1033,1200])])])
'@ | Set-Content -LiteralPath $versionFile -Encoding UTF8
    & $buildPython -m PyInstaller --noconfirm --clean --windowed --log-level WARN `
        --name 'The Order 1886' --icon "$artwork/order1886.ico" `
        --version-file $versionFile --distpath $destination --workpath "$stage/pyi" --specpath $stage `
        --paths $pythonSource --paths $scriptData `
        --add-data "$artwork;launcher/order1886" --add-data "$scriptData;scripts" `
        --hidden-import order1886 --hidden-import prepare --hidden-import link_modules `
        --hidden-import link_libc --hidden-import save_backup --hidden-import order1886_frame_rate --hidden-import order1886_display `
        "$pythonSource/launcher/order1886_launcher.py"
    if ($LASTEXITCODE) { throw 'Launcher packaging failed.' }
    $packageRoot = Join-Path $destination 'The Order 1886'
    $runtimeBin = Join-Path $packageRoot 'bin'
    Copy-RuntimeDependencies $runtimePath $runtimeBin
    if ((Get-SHA256 (Join-Path $runtimeBin 'order1886-runtime.exe')) -ne $runtimeHash) {
        throw 'Runtime changed during packaging. Re-run after the source build has finished.'
    }
    Copy-Item -LiteralPath $runtimeIdentityPath -Destination (Join-Path $runtimeBin 'runtime-build.json')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination $packageRoot
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README-Order1886.txt') -Destination $packageRoot
    $noticeRoot = Join-Path $packageRoot 'notices'
    New-Item -ItemType Directory -Force -Path $noticeRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ATTRIBUTION-Order1886.txt') -Destination (Join-Path $noticeRoot 'ATTRIBUTION.txt')
    & $buildPython (Join-Path $PSScriptRoot 'order1886_notices.py') (Join-Path $noticeRoot 'python')
    if ($LASTEXITCODE) { throw 'Python, UI and bootloader license collection failed.' }
    foreach ($scope in @('third_party', 'gpu/third_party', 'gpu/shadps4')) {
        foreach ($file in Get-ChildItem -LiteralPath (Join-Path $projectRoot $scope) -File -Recurse) {
            if ($file.Name -notmatch '^(LICENSE|COPYING|NOTICE|UNLICENSE)') { continue }
            $relative = $file.FullName.Substring($projectRoot.Length + 1)
            $target = Join-Path $noticeRoot $relative
            New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $target
        }
    }
    $msysNotices = Join-Path (Split-Path $dependencyPath) 'share/licenses'
    if (-not (Test-Path -LiteralPath $msysNotices)) { throw 'MSYS2 dependency license collection is missing.' }
    Copy-Item -LiteralPath $msysNotices -Destination (Join-Path $noticeRoot 'msys2-clang64') -Recurse
    $forbidden = Get-ChildItem -LiteralPath $packageRoot -Recurse | Where-Object {
        $_.Name -match '^(eboot\.bin|sce_module|sce_sys|savedata|user|cache|settings\.json|runtime\.ini)$' -or
        $_.Name -match '\.(log|spv|pkg|sprx|prx)$' -or $_.Name -like 'nvngx_dlss*.dll'
    }
    if ($forbidden) { throw ('Package contains excluded content: ' + ($forbidden.FullName -join ', ')) }
    $files = @(Get-ChildItem -LiteralPath $packageRoot -File -Recurse | ForEach-Object {
        [ordered]@{ path=$_.FullName.Substring($packageRoot.Length + 1).Replace('\','/'); bytes=$_.Length;
                    sha256=(Get-SHA256 $_.FullName) }
    })
    [ordered]@{ product='The Order: 1886'; package_version='0.1.0'; built_utc=(Get-Date).ToUniversalTime().ToString('o');
                runtime_sha256=$runtimeHash; runtime_build=$runtimeIdentity; python_sources=$pythonSources; files=$files } |
        ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $packageRoot 'package-manifest.json') -Encoding UTF8
    $archive = Join-Path $destination 'order1886-windows.zip'
    & $buildPython -m zipfile -c $archive $packageRoot
    if ($LASTEXITCODE) { throw 'Portable ZIP creation failed.' }
    Remove-Item -LiteralPath $incomplete
    Write-Output "Built launcher: $packageRoot/The Order 1886.exe"
    Write-Output "Runtime: $runtimeBin/order1886-runtime.exe | SHA256 $runtimeHash"
    Write-Output "Portable archive: $archive"
} finally {
    Pop-Location
}
