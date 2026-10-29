"""Data structures and JSON serialization for video and audio gate policies and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GatePolicy:
    """Validation policy thresholds for MP4 container, video stream, and audio loudness."""

    allowed_resolutions: list[tuple[int, int]] = field(
        default_factory=lambda: [(1080, 1920), (720, 1280)]
    )
    allowed_video_codecs: list[str] = field(default_factory=lambda: ["h264", "avc1"])
    required_pixel_format: str = "yuv420p"
    require_faststart: bool = True
    min_fps: float = 23.9
    max_fps: float = 60.1
    min_duration_sec: float = 1.0
    max_duration_sec: float = 180.0
    target_lufs: float = -15.0
    lufs_tolerance_db: float = 2.5
    max_true_peak_dbtp: float = -0.5
    max_silence_gap_sec: float = 2.0
    silence_threshold_dbfs: float = -55.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_resolutions"] = [list(pair) for pair in self.allowed_resolutions]
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> GatePolicy:
        res_raw = raw.get("allowed_resolutions", [[1080, 1920], [720, 1280]])
        resolutions = [(int(pair[0]), int(pair[1])) for pair in res_raw]
        return cls(
            allowed_resolutions=resolutions,
            allowed_video_codecs=list(raw.get("allowed_video_codecs", ["h264", "avc1"])),
            required_pixel_format=str(raw.get("required_pixel_format", "yuv420p")),
            require_faststart=bool(raw.get("require_faststart", True)),
            min_fps=float(raw.get("min_fps", 23.9)),
            max_fps=float(raw.get("max_fps", 60.1)),
            min_duration_sec=float(raw.get("min_duration_sec", 1.0)),
            max_duration_sec=float(raw.get("max_duration_sec", 180.0)),
            target_lufs=float(raw.get("target_lufs", -15.0)),
            lufs_tolerance_db=float(raw.get("lufs_tolerance_db", 2.5)),
            max_true_peak_dbtp=float(raw.get("max_true_peak_dbtp", -0.5)),
            max_silence_gap_sec=float(raw.get("max_silence_gap_sec", 2.0)),
            silence_threshold_dbfs=float(raw.get("silence_threshold_dbfs", -55.0)),
        )


@dataclass(frozen=True)
class LoudnessMetrics:
    """Measured ITU-R BS.1770-4 audio loudness, true peak, and longest silence gap."""

    integrated_lufs: float
    true_peak_dbtp: float
    longest_silence_sec: float
    sample_rate_hz: int
    channels: int


@dataclass(frozen=True)
class ProbeReport:
    """Complete inspection result for an MP4 file evaluated against a GatePolicy."""

    path: str
    sha256: str
    passed: bool
    width: int
    height: int
    fps: float
    duration_sec: float
    video_codec: str
    pixel_format: str
    faststart_ok: bool
    loudness: LoudnessMetrics
    violations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_policy(path: str | Path) -> GatePolicy:
    """Read a GatePolicy from a JSON file on disk."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return GatePolicy.from_dict(raw)


def save_policy(policy: GatePolicy, path: str | Path) -> Path:
    """Write a GatePolicy to a formatted JSON file on disk."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(policy.to_dict(), indent=2) + "\n", encoding="utf-8")
    return target
