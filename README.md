# reelgate

`reelgate` is a command-line broadcast and vertical video quality gate (`1080x1920` / `720x1280`, H.264 `avc1`, `yuv420p` BT.709). It inspects ISO/IEC 14496-12 MP4 box headers (`moov` before `mdat` faststart placement), measures integrated loudness (`LUFS`), 4x oversampled true peak (`dBTP`), and silence gaps according to ITU-R BS.1770-4 / EBU R128, remasters non-compliant streams over FFmpeg pipes, and tracks SHA-256 asset digests in SQLite.

## Package Layout

```text
src/reelgate/
  __init__.py
  spec.py        # GatePolicy, LoudnessMetrics, and ProbeReport dataclasses
  mp4box.py      # ISO BMFF binary atom parser for faststart verification
  loudness.py    # ITU-R BS.1770-4 K-weighting cascade, gated LUFS, 4x true peak
  inspector.py   # FFmpeg stream probing, PCM decoding, and policy evaluation
  normalizer.py  # H.264 yuv420p BT.709 faststart remastering and loudness trim
  ledger.py      # SQLite SHA-256 asset and source clip deduplication ledger
  cli.py         # CLI entry point (init-policy, check, fix, ledger, probe)
examples/
  broadcast_9x16_policy.json
tests/
  test_reelgate.py
```

## Installation

```bash
pip install -e .
```

Dependencies: `numpy`, `imageio-ffmpeg`.

## Usage

Generate a starter JSON policy file:

```bash
reelgate init-policy policy.json --target-lufs -15.0 --max-true-peak -0.5
```

Inspect an MP4 file against a policy (exits `0` on pass, `2` on policy violation):

```bash
reelgate check input.mp4 --policy examples/broadcast_9x16_policy.json --report report.json
```

Remaster a non-compliant MP4 file to `yuv420p` BT.709 (`-g 60 -bf 2 -aq-mode 3 +faststart`) and target loudness:

```bash
reelgate fix raw_clip.mp4 -o output/master.mp4 --policy examples/broadcast_9x16_policy.json --fps 30
```

Register an asset in the SQLite SHA-256 deduplication ledger (exits `3` if the hash was already published):

```bash
reelgate ledger --db published_assets.sqlite3 --register output/master.mp4 --role master --channel main
```

Check FFmpeg binary resolution:

```bash
reelgate probe
```

## Running Tests

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
