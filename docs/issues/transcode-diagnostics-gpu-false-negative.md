# `transcode_diagnostics` reports `gpu_available: false` even when hardware transcoding is working (false negative)

**Status:** Resolved (2026-04-20, v1.2.0)
**Reported:** 2026-04-19
**Component:** `transcode_diagnostics` tool
**Severity:** Medium — misleads operators troubleshooting hardware transcoding

## Summary

`transcode_diagnostics` probed GPU availability by shelling out to `nvidia-smi`. The MCP container does not ship `nvidia-smi`, and — more importantly — the MCP runs in its own container separate from Emby. A binary-presence check on the MCP side was never a valid signal for Emby's GPU state. The result was `gpu_available: false` regardless of what was actually happening on the Emby server side.

## Original Misdiagnosis (preserved for the record)

This issue was originally filed during an incident investigation with a wrong hypothesis. The reporter observed that `transcode_diagnostics` returned the same `gpu_available: false` output both during an active GPU hang **and** after the hang was recovered by VM reboot, and framed the bug as "the `nvidia-smi` probe can't see into Emby's container."

That framing had two errors:

1. **Container-layer confusion.** The probe was not reaching "into" any Emby container — it was reaching into the MCP's *own* container (where `nvidia-smi` doesn't exist either). The error message `"nvidia-smi not found in container"` referred to the MCP container, not Emby's.
2. **Misidentified driver symptom.** The recurring kernel error cited in the original report (`RmInitAdapter failed (0x62:0x40:2522)`) was treated as the trigger of the hang. Later investigation showed it was a *symptom* — every new transcode attempt retrying against an already-dead GPU. The actual trigger was **NVIDIA Xid 140** ("uncorrectable ECC error / possible firmware handling failure"), which fired once, 7 days before the reporter noticed, and put the NVIDIA kernel driver into a stuck state that only a VM reboot could clear. Root cause was GSP (GPU System Processor) firmware instability on Turing under driver 570.x. See [homelab issue 009](https://github.com/lefty3382/homelab/blob/main/docs/issues/vm-106-emby-gpu-xid-hang.md) for the full RCA and the `NVreg_EnableGpuFirmware=0` mitigation.

The tool bug and the driver hang were real and independent. Fixing the tool does not prevent driver hangs; fixing the driver does not fix the tool's probe logic.

## Fix Applied (v1.2.0)

Replaced the `nvidia-smi` probe with a query to Emby's own `/System/Configuration/encoding` endpoint, which returns the authoritative configuration record. The new output:

```json
{
  "active_transcodes": [...],
  "transcode_count": 0,
  "hardware_acceleration_config": {
    "enabled": true,
    "backends_configured": ["nvenc", "cuda_decode", "qsv"],
    "nvenc_encoders": ["V-E-h264_nvenc-nv-cudaId0", "V-E-hevc_nvenc-nv-cudaId0"],
    "cuda_decoders": ["V-D-h264-nv-cudaId0", "V-D-hevc-nv-cudaId0", ...],
    "qsv_codecs": [...],
    "vaapi_codecs": []
  }
}
```

`connectivity_check` received the same treatment — its GPU check now reports `hardware_encoding: { enabled, has_hw_encoder }` instead of probing `nvidia-smi`.

## What the new fields *can* and *cannot* tell you

**Can** tell you:
- Whether Emby is configured to use hardware encoding (`enabled`)
- Which HW backends have at least one enabled codec (`backends_configured`)
- Which specific codec IDs Emby will try (`nvenc_encoders`, `cuda_decoders`, etc.)

**Cannot** tell you:
- Whether the GPU driver is currently healthy
- Whether the GPU firmware has crashed
- Whether a specific transcode succeeded on hardware or silently fell back to software

For that last point — the live signal — `active_transcodes[*].hardware_acceleration_type` is and remains the definitive indicator: `null` means software, a non-null string (`cuda`, `nvenc`, `qsv`) means hardware succeeded.

## Related

- v1.2.0 CHANGELOG entry
- homelab repo: `docs/issues/vm-106-emby-gpu-xid-hang.md` (the actual driver-hang RCA that triggered this investigation)
- homelab repo: `Logs/changelog.md` 2026-04-20 entry (GSP firmware disable, Xid monitoring deployment)
