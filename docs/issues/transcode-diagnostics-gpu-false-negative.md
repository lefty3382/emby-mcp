# `transcode_diagnostics` reports `gpu_available: false` when `nvidia-smi` is absent from the Emby container (false negative)

**Status:** Open
**Reported:** 2026-04-19
**Component:** `transcode_diagnostics` tool
**Severity:** Medium — misleads operators troubleshooting hardware transcoding

## Summary

`transcode_diagnostics` probes GPU availability by shelling out to `nvidia-smi` inside the Emby container. The official `emby/embyserver` image does not ship `nvidia-smi`, so the probe always fails — even when the NVIDIA driver, CDI-injected devices, and NVENC are fully functional. This produces a misleading top-level `gpu_available: false` regardless of actual hardware transcoding state.

## Actual Output (GPU Fully Working)

```json
{
  "active_transcodes": [],
  "transcode_count": 0,
  "gpu_available": false,
  "gpu_info": "nvidia-smi not found in container"
}
```

## Ground Truth on the Same Host at the Same Moment

```
# nvidia-smi on the VM (host of the container)
NVIDIA-SMI 570.211.01   Driver Version: 570.211.01   CUDA Version: 12.8
Quadro RTX 5000   0 MiB / 16384 MiB   P0   35 °C

# /dev nodes inside the Emby container
/dev/nvidia0
/dev/nvidiactl
/dev/nvidia-uvm
/dev/nvidia-uvm-tools

# FFmpeg inside the Emby container
$ /bin/ffmpeg -encoders | grep nvenc
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder

$ /bin/ffmpeg -hwaccels
cuda  vaapi  qsv  drm  opencl
```

The container has full NVENC/CUDA capability; only the `nvidia-smi` CLI binary is missing from the image.

## Impact

- Users troubleshooting hardware transcoding see `gpu_available: false` and chase a non-issue
- Masks the *real* signal: the per-transcode `hardware_acceleration_type` field in `active_transcodes[]`, which is the authoritative indicator
- Forced a drop to `ssh → nvidia-smi` on the VM host to get correct state during a recent GPU driver hang incident on a production homelab Emby instance
- The same false negative appears both when the GPU is broken AND when the GPU is healthy — making the field useless for diagnosis

## Suggested Fix

Replace the `nvidia-smi` probe with one or more of these signals, none of which require extra binaries in the image:

### Option A — `/dev/nvidia*` device presence (preferred)

Most reliable — reflects whether the NVIDIA Container Toolkit actually wired up devices to the container.

```python
import os
nvidia_devs = {p for p in os.listdir("/dev") if p.startswith("nvidia")}
gpu_available = {"nvidia0", "nvidiactl"}.issubset(nvidia_devs)
gpu_info = f"nvidia devices: {sorted(nvidia_devs)}" if gpu_available else "no nvidia devices in /dev"
```

### Option B — FFmpeg encoder probe

Confirms FFmpeg was linked against CUDA/NVENC. Works for both NVIDIA and alternative HW stacks (QSV/VAAPI).

```python
import subprocess
out = subprocess.run(["/bin/ffmpeg", "-hide_banner", "-encoders"],
                     capture_output=True, text=True).stdout
has_nvenc = "nvenc" in out
has_qsv   = "qsv"   in out
has_vaapi = "vaapi" in out
```

### Option C — Parse Emby's own hardware-acceleration state

Query `/System/Info` or the server configuration for `HardwareAccelerationType` and report what Emby *thinks* it's using. This is the most user-meaningful signal.

### Recommended

Combine A + B: check `/dev/nvidia*` for NVIDIA devices, then probe `ffmpeg -encoders` to confirm the codec paths are actually linked. Report both in `gpu_info` so users can diagnose mismatches (e.g., devices present but FFmpeg not built with NVENC).

## Related: Reconsider the Top-Level Field

The per-transcode `hardware_acceleration_type` field on each entry in `active_transcodes[]` is already the definitive signal of whether hardware transcoding is actually happening. Consider:

- Removing `gpu_available` entirely (it's redundant with per-transcode signal), or
- Renaming it to something honest like `nvidia_smi_available` so it doesn't imply GPU health, or
- Replacing it with a `hardware_transcoding_capability` object that separates "devices present" from "encoders linked" from "Emby configured to use"

## Environment

| Item | Value |
|------|-------|
| Emby image | `emby/embyserver:latest` (Emby Server 4.9.3.0) |
| Host OS | Ubuntu 24.04 LTS (VM guest) |
| NVIDIA driver | 570.211.01 (server branch) |
| GPU | Quadro RTX 5000 (Turing TU104GL) via Proxmox vfio passthrough |
| Container runtime | Docker with NVIDIA Container Toolkit 1.19.0, CDI-based device injection |
| MCP image | `ghcr.io/lefty3382/emby-mcp:latest` |

## Discovery Context

This false negative was uncovered during an incident investigation on 2026-04-18 where the NVIDIA driver inside the VM entered a `RmInitAdapter failed (0x62:0x40:2522)` state mid-uptime, causing Emby to silently fall back to software transcoding. The MCP's `gpu_available: false` output looked identical *before and after* the VM was rebooted and the GPU recovered — which led to the realization that the signal is not tied to GPU state at all.

The authoritative indicator in both cases was the per-transcode `hardware_acceleration_type` field (null during the failure, `cuda`/`nvenc` after recovery).
