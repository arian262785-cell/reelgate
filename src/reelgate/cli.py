"""Command-line interface for reelgate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .inspector import inspect_media_file, resolve_ffmpeg_binary
from .ledger import AssetLedger, DuplicateAssetError
from .normalizer import normalize_media_file
from .spec import GatePolicy, load_policy, save_policy


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the reelgate CLI."""
    parser = argparse.ArgumentParser(
        prog="reelgate",
        description="Broadcast and vertical video quality gate (H.264, yuv420p, faststart, ITU-R BS.1770-4 LUFS, SHA-256 ledger).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-policy", help="Write a starter GatePolicy JSON file.")
    p_init.add_argument("output", help="Destination path for the JSON policy file.")
    p_init.add_argument("--target-lufs", type=float, default=-15.0, help="Target integrated loudness in LUFS.")
    p_init.add_argument("--max-true-peak", type=float, default=-0.5, help="Maximum true peak in dBTP.")

    p_check = sub.add_parser("check", help="Inspect an MP4 file against a GatePolicy.")
    p_check.add_argument("input", help="Path to the MP4 file to inspect.")
    p_check.add_argument("--policy", help="Optional path to a GatePolicy JSON file.")
    p_check.add_argument("--report", help="Optional path to write the JSON inspection report.")

    p_fix = sub.add_parser("fix", help="Remaster an MP4 file to comply with a GatePolicy.")
    p_fix.add_argument("input", help="Path to the source MP4 file.")
    p_fix.add_argument("-o", "--output", required=True, help="Destination path for the remastered MP4 file.")
    p_fix.add_argument("--policy", help="Optional path to a GatePolicy JSON file.")
    p_fix.add_argument("--width", type=int, help="Optional target width override.")
    p_fix.add_argument("--height", type=int, help="Optional target height override.")
    p_fix.add_argument("--fps", type=int, default=30, help="Target frame rate (default: 30).")

    p_ledger = sub.add_parser("ledger", help="Register or check media files in a SQLite SHA-256 ledger.")
    p_ledger.add_argument("--db", required=True, help="Path to the SQLite ledger database.")
    p_ledger.add_argument("--register", help="Path to a media file to register in the ledger.")
    p_ledger.add_argument("--role", default="master", help="Asset role label (master or source_clip).")
    p_ledger.add_argument("--channel", default="default", help="Channel or project identifier.")
    p_ledger.add_argument("--list", action="store_true", help="List registered assets in the ledger.")

    sub.add_parser("probe", help="Verify FFmpeg binary resolution.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute the reelgate CLI command and return an exit status code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "probe":
        exe = resolve_ffmpeg_binary()
        print(json.dumps({"ffmpeg_binary": exe, "status": "ok"}, indent=2))
        return 0

    if args.command == "init-policy":
        policy = GatePolicy(
            target_lufs=args.target_lufs,
            max_true_peak_dbtp=args.max_true_peak,
        )
        out = save_policy(policy, args.output)
        print(json.dumps({"written": str(out), "policy": policy.to_dict()}, indent=2))
        return 0

    if args.command == "check":
        policy = load_policy(args.policy) if args.policy else GatePolicy()
        report = inspect_media_file(args.input, policy=policy)
        payload = report.to_dict()
        if args.report:
            rp = Path(args.report)
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 0 if report.passed else 2

    if args.command == "fix":
        policy = load_policy(args.policy) if args.policy else GatePolicy()
        report = normalize_media_file(
            args.input,
            args.output,
            policy=policy,
            target_width=args.width,
            target_height=args.height,
            target_fps=args.fps,
        )
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.passed else 2

    if args.command == "ledger":
        ledger = AssetLedger(args.db)
        if args.register:
            try:
                rec = ledger.register_file(args.register, asset_role=args.role, channel_tag=args.channel)
            except DuplicateAssetError as exc:
                print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
                return 3
            print(json.dumps(rec, indent=2))
            return 0
        if args.list:
            entries = ledger.list_entries(channel_tag=args.channel if args.channel != "default" else None)
            print(json.dumps({"entries": entries}, indent=2))
            return 0
        parser.error("ledger requires --register <path> or --list")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
