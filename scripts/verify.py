"""Check manifest.json against the files in clips/.

Checks, for every clip: the manifest validates against manifest.schema.json, the file exists,
its size and SHA3-256 match, it holds only video streams (no audio, subtitles or data), it is
within the size limit, and the ffprobe facts match. Also checks that clips/ holds no file the
manifest does not list and that the clips together stay within the repository size limit.

Usage:
    python scripts/verify.py
"""

import json
import sys

from jsonschema import Draft202012Validator

from clipfacts import (
    FACT_NAMES,
    FFPROBE,
    REPO_ROOT,
    SCHEMA_PATH,
    facts_from_probe,
    ffmpeg_version,
    load_manifest,
    probe,
    sha3_256_file,
    stream_types,
)

# Limits agreed for this repository: no clip over 8 MB, all clips together under 120 MB, so the
# repository stays clonable without Git LFS.
MAX_CLIP_BYTES = 8_000_000
MAX_TOTAL_BYTES = 120_000_000


def schema_errors(manifest):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [f"manifest.json {'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(manifest)]


def clip_errors(clip):
    path = REPO_ROOT / clip["file"]
    if not path.is_file():
        return [f"{clip['file']}: listed in manifest.json but missing"]
    errors = []
    size = path.stat().st_size
    if size != clip["size"]:
        errors.append(f"{clip['file']}: size {size}, manifest says {clip['size']}")
    if size > MAX_CLIP_BYTES:
        errors.append(f"{clip['file']}: {size} bytes is over the {MAX_CLIP_BYTES} byte limit per clip")
    digest = sha3_256_file(path)
    if digest != clip["sha3_256"]:
        errors.append(f"{clip['file']}: SHA3-256 {digest}, manifest says {clip['sha3_256']}")
    probed = probe(path)
    non_video = [t for t in stream_types(probed) if t != "video"]
    if non_video:
        errors.append(f"{clip['file']}: has non-video streams {non_video}; clips must be silent")
    actual = facts_from_probe(probed, clip["video_stream"])
    for name in FACT_NAMES:
        if actual[name] != clip["facts"][name]:
            errors.append(f"{clip['file']}: {name} is {actual[name]!r}, manifest says {clip['facts'][name]!r}")
    return errors


def main():
    manifest = load_manifest()
    errors = schema_errors(manifest)
    if errors:
        print("\n".join(errors))
        sys.exit(1)

    local = ffmpeg_version(FFPROBE)
    if local != manifest["ffmpeg"]["version"]:
        print(
            f"note: ffprobe {local} differs from the recorded {manifest['ffmpeg']['version']}; "
            "fact mismatches may come from the version difference"
        )

    listed = {c["file"] for c in manifest["clips"]}
    if len(listed) != len(manifest["clips"]):
        errors.append("manifest.json lists a file more than once")
    on_disk = {f"clips/{p.name}" for p in (REPO_ROOT / "clips").iterdir() if p.is_file()}
    errors += [f"{f}: in clips/ but not in manifest.json" for f in sorted(on_disk - listed)]

    total = 0
    for clip in manifest["clips"]:
        errors += clip_errors(clip)
        total += clip["size"]
    if total > MAX_TOTAL_BYTES:
        errors.append(f"clips total {total} bytes, over the {MAX_TOTAL_BYTES} byte limit")

    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"{len(manifest['clips'])} clips, {total} bytes: all match manifest.json")


if __name__ == "__main__":
    main()
