# Manual DLSS GPU smoke

The GPU fixture is excluded from default builds and CTest. It reuses the existing
FSR static-image upload/readback harness while dynamically loading the production
DLSS DLL; it does not link the NVIDIA static library into the test executable.

```powershell
rtk proxy pwsh -NoProfile -File gpu/dlss_bridge/build.ps1
rtk proxy cmake --build out/dlss-bridge --config Release --target order_dlss_gpu_smoke
$env:VK_LAYER_PATH = 'C:/msys64/clang64/bin'
$env:VK_LAYER_VALIDATE_SYNC = '1'
rtk proxy out/dlss-bridge/Release/order_dlss_gpu_smoke.exe --run-gpu D:/Emulator/The-Order-1886_pc/out/dlss-bridge/Release/order1886_dlss.dll out/dlss-bridge/gpu-smoke
```

Set the environment only in the child test process. Run while other game/capture
GPU workloads are stopped. Khronos validation and the debug messenger are
required. The fixture selects the RTX 3070, queries and enables NGX-required
extensions before instance/device creation, initializes NGX and checks SR
capability through the production provider, and dispatches two frames from the
shared ABI. The static gradient/checkerboard has constant depth and zero motion;
frame zero resets history, frame one retains it. The reused fixture currently
renders 128x72 to 256x144, deliberately keeping this a small correctness test.

The caller submits work and waits on fences; the provider never submits/waits.
DLSS output images also include TRANSFER_DST because NGX clears them internally;
the fixture provisions and reports that usage through the shared ABI.
Readbacks must be finite, nonblack and varying. Logs include actual GPU/driver,
enabled extensions/features, provider status and requested preset K, and the
actual loaded NGX runtime path/version/SHA256. Requested preset is not evidence
that a driver override did not change the effective model.

No real Order inputs, gameplay, image-quality comparison or performance acceptance
is established by this fixture. Retain full validation logs and both `.rgba16f`
readbacks; a successful provider call alone is insufficient.

Verified on 16 October 2026 with RTX 3070 / NVIDIA 617.14: real NGX initialization
and SR capability check, both reset/history dispatches, and finite/nonblack
readbacks passed with zero Khronos/synchronization validation errors or warnings.
Evidence remains in ignored `out/dlss-bridge/gpu-smoke-validated/`. The initial
failed run is retained separately in `gpu-smoke/`: it exposed missing output
TRANSFER_DST usage and transfer synchronization, now covered by CPU regressions.
