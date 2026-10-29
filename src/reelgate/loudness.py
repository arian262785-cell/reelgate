"""ITU-R BS.1770-4 / EBU R128 loudness, 4x oversampled true peak, and silence gap analyzer."""

from __future__ import annotations

import math
import numpy as np

from .spec import LoudnessMetrics


def _biquad_filter(signal: np.ndarray, b: tuple[float, float, float], a: tuple[float, float]) -> np.ndarray:
    """Apply a second-order IIR biquad filter across frames using direct form II transposed."""
    b0, b1, b2 = b
    a1, a2 = a
    out = np.empty_like(signal, dtype=np.float64)
    n_samples, n_channels = signal.shape

    for ch in range(n_channels):
        x = signal[:, ch]
        y = out[:, ch]
        z1 = 0.0
        z2 = 0.0
        for i in range(n_samples):
            xi = float(x[i])
            yi = b0 * xi + z1
            z1 = b1 * xi - a1 * yi + z2
            z2 = b2 * xi - a2 * yi
            y[i] = yi
    return out


def _k_weight_48k(samples: np.ndarray) -> np.ndarray:
    """Apply ITU-R BS.1770-4 pre-filter and RLB high-pass filter for 48 kHz audio."""
    pre_b = (1.53512485958697, -2.69169618940638, 1.19839281085285)
    pre_a = (-1.69065929318241, 0.73248077421585)
    rlb_b = (1.0, -2.0, 1.0)
    rlb_a = (-1.99004745483398, 0.99007225036621)

    chunk_len = 8192
    n_samples = samples.shape[0]
    if n_samples <= chunk_len:
        stage1 = _biquad_filter(samples, pre_b, pre_a)
        return _biquad_filter(stage1, rlb_b, rlb_a)

    fft_len = 1 << (n_samples * 2 - 1).bit_length()
    freqs = np.fft.rfftfreq(fft_len, d=1.0)
    z1 = np.exp(-2j * np.pi * freqs)
    z2 = z1 * z1

    h_pre = (pre_b[0] + pre_b[1] * z1 + pre_b[2] * z2) / (1.0 + pre_a[0] * z1 + pre_a[1] * z2)
    h_rlb = (rlb_b[0] + rlb_b[1] * z1 + rlb_b[2] * z2) / (1.0 + rlb_a[0] * z1 + rlb_a[1] * z2)
    h_total = (h_pre * h_rlb)[:, np.newaxis]

    spec = np.fft.rfft(samples, n=fft_len, axis=0)
    filtered = np.fft.irfft(spec * h_total, n=fft_len, axis=0)
    return filtered[:n_samples, :]


def measure_pcm_loudness(
    pcm_float: np.ndarray,
    sample_rate_hz: int = 48000,
    silence_threshold_dbfs: float = -55.0,
) -> LoudnessMetrics:
    """Compute integrated LUFS, 4x oversampled true peak (dBTP), and longest silence gap."""
    if pcm_float.ndim == 1:
        samples = pcm_float[:, np.newaxis].astype(np.float64, copy=False)
    else:
        samples = pcm_float.astype(np.float64, copy=False)

    n_samples, n_channels = samples.shape
    if n_samples == 0:
        return LoudnessMetrics(
            integrated_lufs=-70.0,
            true_peak_dbtp=-70.0,
            longest_silence_sec=0.0,
            sample_rate_hz=sample_rate_hz,
            channels=n_channels,
        )

    s0 = samples[:-1, :]
    s1 = samples[1:, :]
    interp_25 = 0.75 * s0 + 0.25 * s1
    interp_50 = 0.50 * s0 + 0.50 * s1
    interp_75 = 0.25 * s0 + 0.75 * s1
    peak_lin = max(
        float(np.max(np.abs(samples))),
        float(np.max(np.abs(interp_25))) if n_samples > 1 else 0.0,
        float(np.max(np.abs(interp_50))) if n_samples > 1 else 0.0,
        float(np.max(np.abs(interp_75))) if n_samples > 1 else 0.0,
    )
    true_peak_dbtp = 20.0 * math.log10(max(peak_lin, 1e-9))

    weighted = _k_weight_48k(samples)
    block_size = max(1, int(round(0.400 * sample_rate_hz)))
    step_size = max(1, int(round(0.100 * sample_rate_hz)))

    block_powers: list[float] = []
    if n_samples >= block_size:
        for start in range(0, n_samples - block_size + 1, step_size):
            block = weighted[start : start + block_size, :]
            power = float(np.sum(np.mean(block * block, axis=0)))
            block_powers.append(power)
    else:
        block_powers.append(float(np.sum(np.mean(weighted * weighted, axis=0))))

    abs_gate_power = 10.0 ** ((-70.0 + 0.691) / 10.0)
    gated_abs = [p for p in block_powers if p > abs_gate_power]
    if not gated_abs:
        integrated_lufs = -70.0
    else:
        rel_gate_power = (sum(gated_abs) / len(gated_abs)) * 0.1
        gated_rel = [p for p in gated_abs if p > rel_gate_power]
        mean_power = sum(gated_rel) / len(gated_rel) if gated_rel else sum(gated_abs) / len(gated_abs)
        integrated_lufs = -0.691 + 10.0 * math.log10(max(mean_power, 1e-12))

    win_samples = max(1, int(round(0.050 * sample_rate_hz)))
    n_wins = n_samples // win_samples
    silence_thresh_lin = 10.0 ** (silence_threshold_dbfs / 20.0)
    longest_run = 0
    current_run = 0
    for idx in range(n_wins):
        seg = samples[idx * win_samples : (idx + 1) * win_samples, :]
        rms = float(np.sqrt(np.mean(seg * seg)))
        if rms < silence_thresh_lin:
            current_run += 1
            if current_run > longest_run:
                longest_run = current_run
        else:
            current_run = 0
    longest_silence_sec = round(longest_run * (win_samples / sample_rate_hz), 3)

    return LoudnessMetrics(
        integrated_lufs=round(integrated_lufs, 2),
        true_peak_dbtp=round(true_peak_dbtp, 2),
        longest_silence_sec=longest_silence_sec,
        sample_rate_hz=sample_rate_hz,
        channels=n_channels,
    )
