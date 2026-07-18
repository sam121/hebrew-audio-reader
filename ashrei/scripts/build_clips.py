#!/usr/bin/env python3
import argparse
import csv
import subprocess
import tempfile
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path("/Users/samueltaylor/Downloads/Ashrei - Learner's Speed [Qy-gdPGuUmo].mp3")


def parse_time(value):
    value = value.strip()
    if ":" not in value:
        return float(value)

    parts = [float(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError(f"Unsupported time value: {value}")


def read_timings(path):
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    timings = []
    for row in rows:
        line = int(row["line"])
        start = parse_time(row["start"])
        end = parse_time(row["end"])
        if end <= start:
            raise ValueError(f"Line {line} has end <= start")
        timings.append((line, start, end))

    expected = list(range(1, 25))
    found = [line for line, _, _ in timings]
    if found != expected:
        raise ValueError(f"Expected lines 1-24 in order, found {found}")
    return timings


def decode_to_wav(source, wav_path):
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16", str(source), str(wav_path)],
        check=True,
    )


def encode_clip(wav_path, m4a_path):
    subprocess.run(
        ["afconvert", "-f", "m4af", "-d", "aac", "-b", "64000", str(wav_path), str(m4a_path)],
        check=True,
    )


def build_clips(source, timings_path, output_dir, only_line=None):
    timings = read_timings(timings_path)
    if only_line is not None:
        timings = [timing for timing in timings if timing[0] == only_line]
        if not timings:
            raise ValueError(f"Line {only_line} was not found in {timings_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ashrei-clips-") as tmp:
        tmp_dir = Path(tmp)
        decoded = tmp_dir / "source.wav"
        decode_to_wav(source, decoded)

        with wave.open(str(decoded), "rb") as source_wav:
            params = source_wav.getparams()
            rate = source_wav.getframerate()

            for line, start, end in timings:
                source_wav.setpos(max(0, int(start * rate)))
                frames = source_wav.readframes(max(1, int((end - start) * rate)))
                clip_wav = tmp_dir / f"ashrei-{line:02d}.wav"
                clip_m4a = output_dir / f"ashrei-{line:02d}.m4a"

                with wave.open(str(clip_wav), "wb") as out_wav:
                    out_wav.setparams(params)
                    out_wav.writeframes(frames)

                encode_clip(clip_wav, clip_m4a)
                print(f"Wrote {clip_m4a.relative_to(ROOT)} ({end - start:.2f}s)")


def main():
    parser = argparse.ArgumentParser(description="Cut the Ashrei source MP3 into 24 line clips.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Path to the source MP3.")
    parser.add_argument("--timings", type=Path, default=ROOT / "timings.csv", help="CSV with line,start,end.")
    parser.add_argument("--output", type=Path, default=ROOT / "audio", help="Output directory for .m4a clips.")
    parser.add_argument("--line", type=int, help="Only regenerate one line number.")
    args = parser.parse_args()

    if not args.source.exists():
        raise SystemExit(f"Source audio not found: {args.source}")
    build_clips(args.source, args.timings, args.output, args.line)


if __name__ == "__main__":
    main()
