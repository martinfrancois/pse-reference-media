"""Shared helpers: the manifest, SHA3-256 digests and the ffprobe facts recorded per clip.

Run it on a file to print the size, digest and facts for a new manifest entry:
    python scripts/clipfacts.py clips/new-clip.mp4 [--stream N]
"""

import argparse
import hashlib
import json
import os
import subprocess
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "manifest.json"
SCHEMA_PATH = REPO_ROOT / "manifest.schema.json"

# Override with the FFPROBE / FFMPEG environment variables to use a specific build.
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# The order here is the order of the "facts" object in the manifest.
FACT_NAMES = (
    "container",
    "codec",
    "profile",
    "width",
    "height",
    "sample_aspect_ratio",
    "frame_rate",
    "average_frame_rate",
    "scan",
    "pixel_format",
    "bit_depth",
    "color_primaries",
    "color_transfer",
    "color_matrix",
    "color_range",
    "frame_count",
    "duration",
)


def load_manifest():
    with MANIFEST_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def sha3_256_file(path):
    digest = hashlib.sha3_256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run_json(args):
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


@cache
def pixel_format_bit_depths():
    """Bit depth per pixel format name, taken from ffprobe's own pixel format table."""
    table = run_json([FFPROBE, "-v", "error", "-show_pixel_formats", "-of", "json"])
    return {
        fmt["name"]: max(c["bit_depth"] for c in fmt.get("components", [])) if fmt.get("components") else None
        for fmt in table["pixel_formats"]
    }


def probe(path):
    """Run ffprobe once, decoding every frame so the frame count is exact."""
    return run_json(
        [FFPROBE, "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)]
    )


def facts_from_probe(probed, video_stream):
    stream = probed["streams"][video_stream]
    pix_fmt = stream.get("pix_fmt")
    frames = stream.get("nb_read_frames")
    return {
        "container": probed["format"].get("format_name"),
        "codec": stream.get("codec_name"),
        "profile": stream.get("profile"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "sample_aspect_ratio": stream.get("sample_aspect_ratio"),
        "frame_rate": stream.get("r_frame_rate"),
        "average_frame_rate": stream.get("avg_frame_rate"),
        "scan": stream.get("field_order"),
        "pixel_format": pix_fmt,
        "bit_depth": pixel_format_bit_depths().get(pix_fmt),
        "color_primaries": stream.get("color_primaries"),
        "color_transfer": stream.get("color_transfer"),
        "color_matrix": stream.get("color_space"),
        "color_range": stream.get("color_range"),
        "frame_count": int(frames) if frames is not None else None,
        "duration": probed["format"].get("duration"),
    }


def stream_types(probed):
    return [s.get("codec_type") for s in probed["streams"]]


def ffmpeg_version(binary=FFMPEG):
    first_line = subprocess.run([binary, "-version"], check=True, capture_output=True, text=True).stdout.splitlines()[0]
    # "ffmpeg version 8.1.3 Copyright ..." -> "8.1.3"
    return first_line.split()[2]


def main():
    parser = argparse.ArgumentParser(description="Print the manifest fields that come from the file itself.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--stream", type=int, default=0, help="index of the video stream to describe (default 0)")
    args = parser.parse_args()
    entry = {
        "sha3_256": sha3_256_file(args.file),
        "size": args.file.stat().st_size,
        "video_stream": args.stream,
        "facts": facts_from_probe(probe(args.file), args.stream),
    }
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
