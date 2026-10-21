#!/usr/bin/env python3
"""Build multipart prayer clips and verify their encoded playback timestamps."""
import argparse
import csv
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_streams', '-show_packets', '-of', 'json', str(path)
    ]))


def build(prayer, source):
    groups = {}
    with (ROOT / f'{prayer}-timings.csv').open() as handle:
        for row in csv.DictReader(handle):
            a, b = float(row['start']), float(row['end'])
            if not 0 <= a < b:
                raise ValueError(f'Invalid range: {row}')
            groups.setdefault(int(row['line']), []).append((a, b))
    with tempfile.TemporaryDirectory() as temp:
        for line, parts in groups.items():
            duration = sum(b - a for a, b in parts)
            filters = [
                f'[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]'
                for i, (a, b) in enumerate(parts)
            ]
            inputs = ''.join(f'[a{i}]' for i in range(len(parts)))
            # concat uses a microsecond time base. Reset it explicitly before
            # encoding, and derive timestamps from sample counts, not old PTS.
            filters.append(inputs + f'concat=n={len(parts)}:v=0:a=1,'
                           f'afade=t=in:d=0.005,afade=t=out:st={duration-0.005}:d=0.005,'
                           'asettb=1/sr,asetpts=N/SR/TB[out]')
            target = ROOT / 'audio' / f'{prayer}-{line:02d}.m4a'
            staged = Path(temp) / target.name
            subprocess.run([
                'ffmpeg', '-y', '-v', 'error', '-i', str(source),
                '-filter_complex', ';'.join(filters), '-map', '[out]',
                '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(staged)
            ], check=True)
            result = probe(staged)
            stream = result['streams'][0]
            actual = float(stream['duration'])
            if abs(actual - duration) > 0.05:
                raise ValueError(f'{target.name}: expected {duration}, got {actual}')
            rate = int(stream['sample_rate'])
            packets = result['packets']
            for before, after in zip(packets, packets[1:]):
                delta = float(after['pts_time']) - float(before['pts_time'])
                if abs(delta - 1024 / rate) > 0.0001:
                    raise ValueError(f'{target.name}: irregular AAC packet timestamps')
            target.write_bytes(staged.read_bytes())
            print(f'{target.name}: {actual:.3f}s verified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prayer', choices=['aleinu', 'kaddish-drabbanan'])
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    build(args.prayer, args.source)
