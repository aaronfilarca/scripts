#!/usr/bin/env python3

from pathlib import Path
import subprocess
import sys
import time

EXTENSIONS = {".mp4", ".mov", ".mkv", ".m4v"}

CRF = "35"
PRESET = "4"
PIX_FMT = "yuv420p10le"
SVT_PARAMS = "tune=0"
AUDIO_BITRATE = "96k"

MIN_DURATION_TOLERANCE = 2.0
MIN_DURATION_RATIO = 0.98


def fmt_time(seconds):
    seconds = int(seconds)
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    return f"{h:02}:{m:02}:{s:02}"


def fmt_size(size):
    if size >= 1024**3:
        return f"{size / 1024 ** 3:.2f} GB"
    return f"{size / 1024 ** 2:.1f} MB"


def get_duration(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )

    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def main():
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()

    if not root.is_dir():
        print(f"ERROR: Directory not found: {root}")
        return 1

    for program in ("ffmpeg", "ffprobe"):
        result = subprocess.run(
            [program, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        if result.returncode != 0:
            print(f"ERROR: {program} is not installed or not in PATH.")
            return 1

    files = sorted(
        f
        for f in root.rglob("*")
        if (
            f.is_file()
            and f.suffix.lower() in EXTENSIONS
            and not f.stem.startswith(("compressed_", "partial_"))
            and not f.with_name(f"compressed_{f.stem}.mkv").exists()
        )
    )

    if not files:
        print("Nothing to encode.")
        return 0

    print("\nScanning videos...")

    info = [(f, get_duration(f), f.stat().st_size) for f in files]

    total_duration = sum(x[1] for x in info)
    total_source_size = sum(x[2] for x in info)

    print("\n" + "=" * 60)
    print("SVT-AV1 ENCODER")
    print("=" * 60)
    print(f"Videos:          {len(files)}")
    print(f"Duration:        {fmt_time(total_duration)}")
    print(f"Source size:     {fmt_size(total_source_size)}")
    print("=" * 60)

    start = time.time()

    completed_duration = 0
    completed = 0
    failed = 0
    output_size = 0

    try:
        for number, (src, duration, source_size) in enumerate(info, 1):

            partial = src.with_name(f"partial_{src.stem}.mkv")

            output = src.with_name(f"compressed_{src.stem}.mkv")

            if partial.exists():
                print(f"Removing old partial: {partial.name}")
                partial.unlink()

            print("\n" + "=" * 60)
            print(f"[{number}/{len(files)}] {src.name}")
            print("=" * 60)

            print(f"Duration: {fmt_time(duration)} | " f"Size: {fmt_size(source_size)}")

            command = [
                "ffmpeg",
                "-hide_banner",
                "-fflags",
                "+genpts",
                "-i",
                str(src),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-map_metadata",
                "0",
                "-c:v",
                "libsvtav1",
                "-preset",
                PRESET,
                "-crf",
                CRF,
                "-pix_fmt",
                PIX_FMT,
                "-svtav1-params",
                SVT_PARAMS,
                "-c:a",
                "libopus",
                "-b:a",
                AUDIO_BITRATE,
                "-c:s",
                "copy",
                "-y",
                str(partial),
            ]

            result = subprocess.run(command)

            if result.returncode != 0:
                failed += 1
                print(f"\nFAILED — FFmpeg error." f"\nPartial kept: {partial.name}")
                continue

            output_duration = get_duration(partial)

            minimum_duration = max(
                duration - MIN_DURATION_TOLERANCE, duration * MIN_DURATION_RATIO
            )

            print(f"\nSource duration:  {duration:.2f} sec")
            print(f"Output duration:  {output_duration:.2f} sec")
            print(f"Minimum accepted: {minimum_duration:.2f} sec")

            if duration > 0 and (
                output_duration <= 0 or output_duration < minimum_duration
            ):
                failed += 1

                print("\nFAILED — output appears truncated.")
                print(f"Partial kept: {partial.name}")

                continue

            partial.rename(output)

            new_size = output.stat().st_size

            saved = source_size - new_size
            reduction = saved / source_size * 100 if source_size else 0

            completed += 1
            completed_duration += duration
            output_size += new_size

            elapsed = time.time() - start

            eta = (
                elapsed * total_duration / completed_duration - elapsed
                if completed_duration
                else 0
            )

            print(
                f"\nDone: {fmt_size(new_size)} | "
                f"Saved: {fmt_size(max(saved, 0))} "
                f"({max(reduction, 0):.1f}%)"
            )

            print(f"Progress: {completed}/{len(files)} | " f"ETA: {fmt_time(eta)}")

    except KeyboardInterrupt:
        print("\n\nInterrupted." "\nCurrent partial file was kept.")
        return 130

    elapsed = time.time() - start

    total_saved = total_source_size - output_size

    total_reduction = total_saved / total_source_size * 100 if total_source_size else 0

    print("\n" + "=" * 60)
    print("COMPLETE")
    print("=" * 60)
    print(f"Completed:       {completed}/{len(files)}")
    print(f"Failed:          {failed}")
    print(f"Duration:        {fmt_time(completed_duration)}")
    print(f"Encode time:     {fmt_time(elapsed)}")
    print(f"Output size:     {fmt_size(output_size)}")
    print(f"Total saved:     {fmt_size(max(total_saved, 0))}")
    print(f"Reduction:       {max(total_reduction, 0):.1f}%")
    print("=" * 60)

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
