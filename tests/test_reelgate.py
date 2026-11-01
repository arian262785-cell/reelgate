"""Unit and integration tests for reelgate."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np

from reelgate import (
    AssetLedger,
    CompliancePolicy,
    DuplicateAssetError,
    GatePolicy,
    SubmissionMetadata,
    evaluate_compliance,
    has_faststart_moov,
    inspect_media_file,
    load_policy,
    measure_pcm_loudness,
    normalize_media_file,
    resolve_ffmpeg_binary,
    save_policy,
    scan_mp4_boxes,
)
from reelgate.cli import main as cli_main


class TestReelGate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.ffmpeg = resolve_ffmpeg_binary()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _generate_mp4(
        self,
        out_path: Path,
        width: int = 720,
        height: int = 1280,
        pix_fmt: str = "yuv420p",
        faststart: bool = True,
        sine_amp: float = 0.25,
    ) -> Path:
        cmd = [
            self.ffmpeg,
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=navy:s={width}x{height}:r=30:d=1.5",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=1000:sample_rate=48000:duration=1.5,volume={sine_amp}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            pix_fmt,
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
        ]
        if faststart:
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(out_path))
        subprocess.run(cmd, check=True)
        return out_path

    def test_loudness_1khz_sine_calibration(self) -> None:
        sr = 48000
        t = np.arange(sr * 2, dtype=np.float64) / sr
        amp = 10.0 ** (-15.0 / 20.0)
        tone = (amp * np.sin(2.0 * math.pi * 1000.0 * t)).astype(np.float32)
        stereo = np.column_stack([tone, tone])
        metrics = measure_pcm_loudness(stereo, sample_rate_hz=sr)
        self.assertAlmostEqual(metrics.integrated_lufs, -15.0, delta=0.4)
        self.assertAlmostEqual(metrics.true_peak_dbtp, -15.0, delta=0.2)
        self.assertEqual(metrics.longest_silence_sec, 0.0)

    def test_mp4_box_scanner_and_faststart(self) -> None:
        fast_mp4 = self._generate_mp4(self.tmp_dir / "fast.mp4", faststart=True)
        boxes = scan_mp4_boxes(fast_mp4)
        box_names = [b[0] for b in boxes]
        self.assertIn("ftyp", box_names)
        self.assertIn("moov", box_names)
        self.assertIn("mdat", box_names)
        self.assertTrue(has_faststart_moov(fast_mp4))

    def test_inspect_and_fix_non_compliant_video(self) -> None:
        bad_mp4 = self._generate_mp4(
            self.tmp_dir / "bad.mp4",
            width=640,
            height=640,
            pix_fmt="yuv444p",
            faststart=False,
            sine_amp=0.95,
        )
        policy = GatePolicy()
        bad_report = inspect_media_file(bad_mp4, policy=policy)
        self.assertFalse(bad_report.passed)
        self.assertGreaterEqual(len(bad_report.violations), 2)

        fixed_mp4 = self.tmp_dir / "fixed.mp4"
        fixed_report = normalize_media_file(
            bad_mp4,
            fixed_mp4,
            policy=policy,
            target_width=720,
            target_height=1280,
            target_fps=30,
        )
        self.assertTrue(fixed_report.passed, msg=f"Violations: {fixed_report.violations}")
        self.assertEqual((fixed_report.width, fixed_report.height), (720, 1280))
        self.assertEqual(fixed_report.pixel_format, "yuv420p")
        self.assertTrue(fixed_report.faststart_ok)

    def test_sqlite_ledger_deduplication(self) -> None:
        sample = self._generate_mp4(self.tmp_dir / "clip.mp4")
        db_path = self.tmp_dir / "ledger.sqlite3"
        ledger = AssetLedger(db_path)
        rec = ledger.register_file(sample, asset_role="master", channel_tag="ch1")
        self.assertEqual(len(rec["sha256"]), 64)
        self.assertTrue(ledger.has_hash(rec["sha256"]))
        with self.assertRaises(DuplicateAssetError):
            ledger.register_file(sample, asset_role="master", channel_tag="ch1")
        self.assertEqual(len(ledger.list_entries("ch1")), 1)

    def test_compliance_kids_safety_and_deduplication(self) -> None:
        policy = CompliancePolicy(made_for_kids=True)
        clean_kids = SubmissionMetadata(
            title="Die Tierfreunde im Wald",
            caption="Wir lernen die Tiere im Wald kennen! #shorts #kidsvideo",
            script_text="Heute besuchen wir das kleine Eichhoernchen und die Eule.",
            duration_sec=32.0,
            made_for_kids=True,
            recent_titles=["Zaehl mit: Die Seifenblasen-Reime"],
        )
        rep_ok = evaluate_compliance(clean_kids, policy=policy)
        self.assertTrue(rep_ok.passed, msg=f"Reasons: {rep_ok.reasons}")

        bad_kids = SubmissionMetadata(
            title="Zaehl mit: Die Seifenblasen-Reime",
            caption="Kauf jetzt im Shop https://example.com mit Rabattcode! #shorts",
            script_text="He picked up a gun in the forest.",
            duration_sec=8.5,
            made_for_kids=True,
            recent_titles=["Zaehl mit: Die Seifenblasen-Reime"],
        )
        rep_bad = evaluate_compliance(bad_kids, policy=policy)
        self.assertFalse(rep_bad.passed)
        joined = " | ".join(rep_bad.reasons)
        self.assertIn("duration_out_of_bounds", joined)
        self.assertIn("duplicate_title", joined)
        self.assertIn("blocked_terms_found", joined)
        self.assertIn("kids_external_links_forbidden", joined)

    def test_compliance_commercial_synthetic_and_remix_rules(self) -> None:
        policy = CompliancePolicy(
            require_synthetic_disclosure=True,
            blocked_domains=["forbidden-example.de"],
            require_imprint_reference=True,
        )
        bad_sub = SubmissionMetadata(
            title="Top 3 Werkzeuge im Test",
            caption="Hier bestellen: https://forbidden-example.de/shop?utm_source=reel",
            script_text="Kurzer Satz ohne ausreichende eigene Kommentierung.",
            duration_sec=25.0,
            is_commercial=True,
            paid_promotion_flag=False,
            is_synthetic_media=True,
            synthetic_disclosure_flag=False,
            is_remix=True,
            original_audio_replaced=False,
            source_clip_count=1,
        )
        rep_bad = evaluate_compliance(bad_sub, policy=policy)
        self.assertFalse(rep_bad.passed)
        joined = " | ".join(rep_bad.reasons)
        self.assertIn("missing_commercial_disclosure", joined)
        self.assertIn("missing_synthetic_disclosure", joined)
        self.assertIn("remix_unmodified_audio", joined)
        self.assertIn("remix_insufficient_commentary", joined)
        self.assertIn("remix_insufficient_clips", joined)
        self.assertIn("blocked_domain_found", joined)
        self.assertIn("missing_imprint_reference", joined)

        good_sub = SubmissionMetadata(
            title="Anzeige: Taktik-Analyse zum Spieltag",
            caption="Anzeige | Analyse der drei Spielszenen. Impressum: Inhaber Arian Abdi",
            script_text=(
                "In dieser Szene sieht man deutlich wie die Viererkette bei Ballverlust "
                "zu hoch steht und der Raum hinter den Aussenverteidigern komplett offen bleibt."
            ),
            duration_sec=45.0,
            is_commercial=True,
            paid_promotion_flag=True,
            is_synthetic_media=True,
            synthetic_disclosure_flag=True,
            is_remix=True,
            original_audio_replaced=True,
            source_clip_count=5,
        )
        rep_good = evaluate_compliance(good_sub, policy=policy)
        self.assertTrue(rep_good.passed, msg=f"Reasons: {rep_good.reasons}")

    def test_cli_end_to_end(self) -> None:
        policy_path = self.tmp_dir / "policy.json"
        rc_init = cli_main(["init-policy", str(policy_path), "--target-lufs", "-15.0"])
        self.assertEqual(rc_init, 0)
        loaded = load_policy(policy_path)
        self.assertEqual(loaded.target_lufs, -15.0)
        save_policy(loaded, policy_path)

        raw_mp4 = self._generate_mp4(self.tmp_dir / "raw.mp4", width=640, height=640, sine_amp=0.8)
        rc_check_bad = cli_main(["check", str(raw_mp4), "--policy", str(policy_path)])
        self.assertEqual(rc_check_bad, 2)

        fixed_mp4 = self.tmp_dir / "out.mp4"
        rc_fix = cli_main([
            "fix",
            str(raw_mp4),
            "-o",
            str(fixed_mp4),
            "--policy",
            str(policy_path),
            "--width",
            "720",
            "--height",
            "1280",
        ])
        self.assertEqual(rc_fix, 0)

        report_json = self.tmp_dir / "report.json"
        rc_check_ok = cli_main([
            "check",
            str(fixed_mp4),
            "--policy",
            str(policy_path),
            "--report",
            str(report_json),
        ])
        self.assertEqual(rc_check_ok, 0)
        rep_data = json.loads(report_json.read_text(encoding="utf-8"))
        self.assertTrue(rep_data["passed"])

        meta_json = self.tmp_dir / "sub.json"
        meta_json.write_text(
            json.dumps({
                "title": "Barnaby und die Apfelernte",
                "caption": "Kinderlied vom Bauernhof #shorts",
                "script_text": "Heute helfen alle Freunde bei der grossen Apfelernte auf dem Sonnenhof.",
                "duration_sec": 31.0,
                "made_for_kids": True,
            }),
            encoding="utf-8",
        )
        comp_rep_json = self.tmp_dir / "comp_report.json"
        rc_comp = cli_main([
            "compliance",
            str(meta_json),
            "--report",
            str(comp_rep_json),
        ])
        self.assertEqual(rc_comp, 0)

        db_path = self.tmp_dir / "cli_ledger.sqlite3"
        self.assertEqual(
            cli_main(["ledger", "--db", str(db_path), "--register", str(fixed_mp4)]),
            0,
        )
        self.assertEqual(
            cli_main(["ledger", "--db", str(db_path), "--register", str(fixed_mp4)]),
            3,
        )
        self.assertEqual(cli_main(["probe"]), 0)


if __name__ == "__main__":
    unittest.main()
