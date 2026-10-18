param(
    [Parameter(Mandatory=$true)][string]$LegacyPackage,
    [string]$Python = 'python',
    [switch]$SkipFrontendBuild
)
$ErrorActionPreference = 'Stop'
function Get-SHA256([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$legacyRoot = (Resolve-Path -LiteralPath $LegacyPackage).Path
$legacyManifest = Get-Content -LiteralPath (Join-Path $legacyRoot 'package-manifest.json') -Raw | ConvertFrom-Json
$runtime = Join-Path $legacyRoot 'bin/order1886-runtime.exe'
$hash = Get-SHA256 $runtime
if ($hash -ne $legacyManifest.runtime_sha256) { throw 'Legacy runtime does not match its package manifest.' }
if (-not (Test-Path -LiteralPath (Join-Path $legacyRoot 'The Order 1886.exe'))) { throw 'Missing legacy launcher.' }
if ($legacyManifest.runtime_build.game_profile -ne 'order1886' -or $legacyManifest.runtime_build.runtime_abi -ne 'order1886-native-1') {
    throw 'Legacy package is not a dedicated Order build.'
}
foreach ($entry in $legacyManifest.files) {
    $source = [System.IO.Path]::GetFullPath((Join-Path $legacyRoot $entry.path))
    if (-not $source.StartsWith($legacyRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Legacy manifest path escapes its package.'
    }
    if ((Get-SHA256 $source) -ne $entry.sha256) { throw "Legacy package file hash mismatch: $($entry.path)" }
}
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stage = Join-Path $projectRoot "out/order1886-go-package/$stamp"
$destination = Join-Path $stage 'The Order 1886'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($entry in Get-ChildItem -LiteralPath $legacyRoot) {
    if ($entry.Name -ne 'user') { Copy-Item -LiteralPath $entry.FullName -Destination $destination -Recurse }
}
$incomplete = Join-Path $destination 'GO-BUILD-INCOMPLETE.txt'
'This Go preview is incomplete until packaging and smoke checks finish.' | Set-Content -LiteralPath $incomplete -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $destination 'The Order 1886.exe') -Destination (Join-Path $destination 'The Order 1886 Legacy.exe')
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
    $scriptData = Join-Path $stage 'scripts'
    New-Item -ItemType Directory -Force -Path $scriptData | Out-Null
    foreach ($name in @('prepare.py','link_modules.py','link_libc.py','save_backup.py',
            'order1886_frame_rate.py','order1886_display.py','order1886_cache.py',
            'order1886_steam.py','order1886_mods.py','order1886_trophy_history.py')) {
        Copy-Item -LiteralPath (Join-Path "$projectRoot/scripts" $name) -Destination $scriptData
    }
    & $Python -m PyInstaller --noconfirm --clean --console --onedir --log-level WARN --name order1886-worker --paths $projectRoot --add-data "$scriptData;scripts" --distpath "$stage/worker-dist" --workpath "$stage/worker-build" --specpath $stage "$projectRoot/launcher/order1886_worker.py"
    if ($LASTEXITCODE) { throw 'Worker build failed.' }
    foreach ($entry in Get-ChildItem -LiteralPath "$stage/worker-dist/order1886-worker") {
        Copy-Item -LiteralPath $entry.FullName -Destination (Join-Path $destination 'bin') -Recurse -Force
    }
    $manifest = [ordered]@{
        product='The Order: 1886'; launcher='Go / Wails v2.17.0'; status='development preview'
        built_utc=(Get-Date).ToUniversalTime().ToString('o'); runtime_sha256=$hash
        runtime_build=$legacyManifest.runtime_build
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
    & $Python "$projectRoot/packaging/windows/order1886-go-smoke.py" $destination
    if ($LASTEXITCODE) { throw 'Go portable smoke failed; the incomplete marker remains.' }
    Remove-Item -LiteralPath $incomplete
    Write-Output $destination
} finally { Pop-Location }

