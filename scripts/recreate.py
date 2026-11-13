"""Re-create clips from their published sources and compare them with the files in clips/.

For each clip the script downloads the source named in manifest.json, checks its size and
SHA3-256, runs the recorded ffmpeg command and compares the SHA3-256 of the result with the
manifest. Byte-identical output needs the ffmpeg build named in the manifest (see README.md).

Usage:
    python scripts/recreate.py --work-dir /tmp/pse-work [--clip NAME ...] [--out-dir DIR]
"""

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from clipfacts import FFMPEG, ffmpeg_version, load_manifest, sha3_256_file

# Wikimedia asks automated clients for a descriptive User-Agent.
USER_AGENT = "pse-reference-media-recreate/1 (+https://github.com/martinfrancois/pse-reference-media)"
MAX_SOURCE_BYTES = 2 * 1024**3


def download(url, target, expected_size):
    if target.exists() and target.stat().st_size == expected_size:
        return
    if expected_size > MAX_SOURCE_BYTES:
        raise SystemExit(f"{url}: {expected_size} bytes is over the {MAX_SOURCE_BYTES} byte download limit")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    partial = target.with_name(target.name + ".part")
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    partial.replace(target)


def check_file(path, size, sha3):
    actual_size = path.stat().st_size
    if actual_size != size:
        raise SystemExit(f"{path}: size {actual_size}, manifest says {size}")
    actual = sha3_256_file(path)
    if actual != sha3:
        raise SystemExit(f"{path}: SHA3-256 {actual}, manifest says {sha3}")


def plain_name(name):
    """Refuse file names from the manifest that would leave the work folder."""
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise SystemExit(f"refusing file name {name!r}")
    return name


def extract_member(archive, member, target):
    """Extract one named file from a zip archive."""
    if target.exists() and target.stat().st_size == member["size"]:
        return
    with zipfile.ZipFile(archive) as z, z.open(member["name"]) as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)


def prepare_input(clip, work_dir):
    """Return the path or URL that the clip's command reads, after checking the source."""
    source = clip["source"]
    if source.get("remote_cut"):
        return source["url"]
    # Clips that share a source share one download.
    folder = work_dir / "sources"
    folder.mkdir(parents=True, exist_ok=True)
    downloaded = folder / plain_name(source["file_name"])
    download(source["url"], downloaded, source["size"])
    check_file(downloaded, source["size"], source["sha3_256"])
    member = source.get("archive_member")
    if member is None:
        return str(downloaded)
    extracted = folder / plain_name(member["name"])
    extract_member(downloaded, member, extracted)
    check_file(extracted, member["size"], member["sha3_256"])
    return str(extracted)


def build(clip, input_path, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    cut = clip["cut"]
    if cut["method"] == "whole-file":
        shutil.copyfile(input_path, output)
        return
    args = [part.replace("{input}", input_path).replace("{output}", str(output)) for part in cut["command"]]
    args[0] = FFMPEG
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", required=True, type=Path, help="folder for downloads and results")
    parser.add_argument("--clip", action="append", help="clip file name, for example clips/x.mp4; repeatable")
    parser.add_argument("--out-dir", type=Path, help="write results here instead of WORK_DIR/out")
    args = parser.parse_args()

    clips = load_manifest()["clips"]
    if args.clip:
        wanted = set(args.clip)
        clips = [c for c in clips if c["file"] in wanted or Path(c["file"]).name in wanted]
        missing = wanted - {c["file"] for c in clips} - {Path(c["file"]).name for c in clips}
        if missing:
            raise SystemExit(f"not in manifest.json: {', '.join(sorted(missing))}")

    out_dir = args.out_dir or args.work_dir / "out"
    local_version = ffmpeg_version()
    mismatches = 0
    for clip in clips:
        name = Path(clip["file"]).name
        input_path = prepare_input(clip, args.work_dir)
        output = out_dir / name
        build(clip, input_path, output)
        digest = sha3_256_file(output)
        recorded = clip["cut"].get("ffmpeg_version")
        if digest == clip["sha3_256"]:
            print(f"same bytes      {name}")
        else:
            mismatches += 1
            hint = ""
            if recorded and recorded != local_version:
                hint = f" (cut with ffmpeg {recorded}, this run used {local_version})"
            print(f"different bytes {name}: {digest}{hint}")
    sys.exit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
