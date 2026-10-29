"""FFmpeg stream metadata inspector, audio PCM decoder, and policy evaluator."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import numpy as np

from .loudness import measure_pcm_loudness
from .mp4box import has_faststart_moov
from .spec import GatePolicy, LoudnessMetrics, ProbeReport


def resolve_ffmpeg_binary() -> str:
    """Return path to the FFmpeg executable via imageio-ffmpeg or system PATH."""
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return str(exe)
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError("FFmpeg executable not found via imageio-ffmpeg or PATH.")


def compute_file_sha256(path: str | Path) -> str:
    """Compute the hexadecimal SHA-256 digest of a file in 1 MB chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1048576)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def decode_audio_pcm48k(path: str | Path, ffmpeg_bin: str | None = None) -> np.ndarray:
    """Decode the audio track of a media file to 48 kHz stereo float32 PCM over a pipe."""
    exe = ffmpeg_bin or resolve_ffmpeg_binary()
    cmd = [
        exe,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-f",
        "f32le",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        return np.zeros((0, 2), dtype=np.float32)
    raw = np.frombuffer(proc.stdout, dtype=np.float32)
    n_frames = raw.size // 2
    if n_frames == 0:
        return np.zeros((0, 2), dtype=np.float32)
    return raw[: n_frames * 2].reshape((n_frames, 2))


def inspect_media_file(path: str | Path, policy: GatePolicy | None = None) -> ProbeReport:
    """Inspect an MP4 file and evaluate all container, video, and audio policy constraints."""
    active_policy = policy or GatePolicy()
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Media file does not exist: {file_path}")

    exe = resolve_ffmpeg_binary()
    proc = subprocess.run(
        [exe, "-nostdin", "-hide_banner", "-i", str(file_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    info = proc.stderr or ""

    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    if dur_match:
        hours = int(dur_match.group(1))
        minutes = int(dur_match.group(2))
        seconds = float(dur_match.group(3))
        duration_sec = round(hours * 3600.0 + minutes * 60.0 + seconds, 3)
    else:
        duration_sec = 0.0

    video_line = ""
    for line in info.splitlines():
        if "Video:" in line:
            video_line = line
            break

    codec_match = re.search(r"Video:\s*([a-zA-Z0-9_]+)", video_line)
    video_codec = codec_match.group(1).lower() if codec_match else "unknown"

    pix_match = re.search(r"\b(yuv420p|yuvj420p|yuv422p|yuv444p|nv12|rgb24|bgra)\b", video_line)
    pixel_format = pix_match.group(1).lower() if pix_match else "unknown"

    res_match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", video_line)
    width = int(res_match.group(1)) if res_match else 0
    height = int(res_match.group(2)) if res_match else 0

    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", video_line)
    fps = float(fps_match.group(1)) if fps_match else 0.0

    faststart_ok = has_faststart_moov(file_path)
    pcm = decode_audio_pcm48k(file_path, ffmpeg_bin=exe)
    if pcm.shape[0] > 0:
        loudness = measure_pcm_loudness(
            pcm,
            sample_rate_hz=48000,
            silence_threshold_dbfs=active_policy.silence_threshold_dbfs,
        )
    else:
        loudness = LoudnessMetrics(
            integrated_lufs=-70.0,
            true_peak_dbtp=-70.0,
            longest_silence_sec=duration_sec,
            sample_rate_hz=48000,
            channels=0,
        )

    violations: list[str] = []
    if (width, height) not in active_policy.allowed_resolutions:
        allowed_str = ", ".join(f"{w}x{h}" for w, h in active_policy.allowed_resolutions)
        violations.append(f"resolution {width}x{height} not in [{allowed_str}]")

    if video_codec not in [c.lower() for c in active_policy.allowed_video_codecs]:
        violations.append(
            f"video_codec '{video_codec}' not in {active_policy.allowed_video_codecs}"
        )

    if pixel_format != active_policy.required_pixel_format.lower():
        violations.append(
            f"pixel_format '{pixel_format}' != '{active_policy.required_pixel_format}'"
        )

    if active_policy.require_faststart and not faststart_ok:
        violations.append("moov atom is not placed before mdat (faststart missing)")

    if not (active_policy.min_fps <= fps <= active_policy.max_fps):
        violations.append(
            f"fps {fps:.2f} outside [{active_policy.min_fps}, {active_policy.max_fps}]"
        )

    if not (active_policy.min_duration_sec <= duration_sec <= active_policy.max_duration_sec):
        violations.append(
            f"duration {duration_sec:.2f}s outside "
            f"[{active_policy.min_duration_sec}, {active_policy.max_duration_sec}]"
        )

    if loudness.channels == 0:
        violations.append("missing or empty audio stream")
    else:
        lufs_diff = abs(loudness.integrated_lufs - active_policy.target_lufs)
        if lufs_diff > active_policy.lufs_tolerance_db:
            violations.append(
                f"integrated_lufs {loudness.integrated_lufs:.2f} LUFS deviates from "
                f"target {active_policy.target_lufs:.2f} LUFS by {lufs_diff:.2f} dB "
                f"(tolerance {active_policy.lufs_tolerance_db:.2f} dB)"
            )
        if loudness.true_peak_dbtp > active_policy.max_true_peak_dbtp:
            violations.append(
                f"true_peak {loudness.true_peak_dbtp:.2f} dBTP exceeds "
                f"max {active_policy.max_true_peak_dbtp:.2f} dBTP"
            )
        if loudness.longest_silence_sec > active_policy.max_silence_gap_sec:
            violations.append(
                f"longest_silence {loudness.longest_silence_sec:.2f}s exceeds "
                f"max {active_policy.max_silence_gap_sec:.2f}s"
            )

    return ProbeReport(
        path=str(file_path),
        sha256=compute_file_sha256(file_path),
        passed=len(violations) == 0,
        width=width,
        height=height,
        fps=fps,
        duration_sec=duration_sec,
        video_codec=video_codec,
        pixel_format=pixel_format,
        faststart_ok=faststart_ok,
        loudness=loudness,
        violations=violations,
    )
