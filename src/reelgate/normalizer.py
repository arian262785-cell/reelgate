"""Broadcast MP4 remastering and loudness normalization pipeline."""

from __future__ import annotations

from pathlib import Path
import subprocess

from .inspector import inspect_media_file, resolve_ffmpeg_binary
from .spec import GatePolicy, ProbeReport


def normalize_media_file(
    input_path: str | Path,
    output_path: str | Path,
    policy: GatePolicy | None = None,
    target_width: int | None = None,
    target_height: int | None = None,
    target_fps: int = 30,
) -> ProbeReport:
    """Remaster an MP4 file to compliant H.264 yuv420p BT.709 faststart and target LUFS."""
    active_policy = policy or GatePolicy()
    src = Path(input_path)
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    initial = inspect_media_file(src, policy=active_policy)
    out_w = target_width or (
        initial.width
        if (initial.width, initial.height) in active_policy.allowed_resolutions
        else active_policy.allowed_resolutions[0][0]
    )
    out_h = target_height or (
        initial.height
        if (initial.width, initial.height) in active_policy.allowed_resolutions
        else active_policy.allowed_resolutions[0][1]
    )

    gain_db = 0.0
    if initial.loudness.channels > 0 and initial.loudness.integrated_lufs > -65.0:
        desired_gain = active_policy.target_lufs - initial.loudness.integrated_lufs
        max_headroom = (active_policy.max_true_peak_dbtp - 0.2) - initial.loudness.true_peak_dbtp
        gain_db = min(desired_gain, max_headroom)

    vf_chain = (
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
        f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={target_fps},format={active_policy.required_pixel_format}"
    )
    af_chain = (
        f"volume={gain_db:.3f}dB,"
        f"alimiter=limit={10.0 ** (active_policy.max_true_peak_dbtp / 20.0):.5f}:level=disabled"
    )

    exe = resolve_ffmpeg_binary()
    cmd = [
        exe,
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-i",
        str(src),
        "-vf",
        vf_chain,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-profile:v",
        "high",
        "-pix_fmt",
        active_policy.required_pixel_format,
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-g",
        "60",
        "-bf",
        "2",
        "-x264-params",
        "aq-mode=3",
        "-tag:v",
        "avc1",
        "-af",
        af_chain,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg normalization failed: {proc.stderr.strip()}")

    return inspect_media_file(dst, policy=active_policy)
