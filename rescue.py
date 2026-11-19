#!/usr/bin/env python3
"""Rescue a talk video with unusable audio by re-voicing its burned-in live captions.

  ./rescue.py URL_OR_FILE --name meetup-2026-11 [--start 10:00 --duration 5:00]
              [--voice am_michael] [--context "talk topic, speaker, product names"]

Steps (each skipped if its output already exists; use --force STEP to redo):
  download -> cut -> ocr -> stitch -> polish -> narrate
All files land in jobs/<name>/. Final video: jobs/<name>/narrated.mp4
Edit jobs/<name>/polished.json by hand and re-run with --force narrate to fix lines.
"""
import argparse, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = str(ROOT / ".venv/bin/python")
STEPS = ["download", "cut", "ocr", "stitch", "polish", "narrate"]
# Kokoro's phonemizer needs espeak-ng data; default to Homebrew's copy (Apple Silicon prefix)
ENV = {**os.environ, "ESPEAK_DATA_PATH": os.environ.get("ESPEAK_DATA_PATH", "/opt/homebrew/share/espeak-ng-data")}


def secs(t):
    if t is None:
        return None
    parts = [float(p) for p in str(t).split(":")]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def run(cmd):
    short = [str(c).replace(str(ROOT) + "/", "") for c in cmd]
    print("  $", " ".join(f'"{c}"' if " " in c else c for c in short), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, env=ENV)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="YouTube URL or local video file")
    ap.add_argument("--name", required=True, help="job folder name under jobs/")
    ap.add_argument("--start", help="clip start, e.g. 10:00 (omit for whole video)")
    ap.add_argument("--duration", help="clip length, e.g. 5:00")
    ap.add_argument("--voice", default="am_michael", help="Kokoro voice (am_michael, am_adam, am_eric, bm_george, af_heart, ...)")
    ap.add_argument("--audience-voice", default="am_eric")
    ap.add_argument("--drop-audience", action="store_true")
    ap.add_argument("--context", default="a tech meetup talk about AI", help="hints for the polish step")
    ap.add_argument("--bed-db", default="-inf", help="mix original audio underneath at this dB, e.g. -28")
    ap.add_argument("--height", type=int, help="output height, e.g. 720 (also drops to 30 fps); default keeps source")
    ap.add_argument("--fps", default="4", help="caption OCR sample rate")
    ap.add_argument("--lag", default="1.0", help="live-caption latency to subtract (s)")
    ap.add_argument("--no-llm", action="store_true", help="skip LLM polish, rules only")
    ap.add_argument("--force", action="append", default=[], choices=STEPS + ["all"],
                    help="redo this step and everything after it")
    a = ap.parse_args()

    job = ROOT / "jobs" / a.name
    job.mkdir(parents=True, exist_ok=True)
    # remember the clip range per job, so a later "--force narrate" without --start still lines up
    meta_f = job / "job.json"
    meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
    a.start = a.start or meta.get("start")
    a.duration = a.duration or meta.get("duration")
    meta.update({k: v for k, v in {"name": a.name, "source": a.source, "start": a.start,
                                   "duration": a.duration}.items() if v})
    meta_f.write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    start, dur = secs(a.start), secs(a.duration)
    first_forced = min([STEPS.index(f) for f in a.force if f != "all"] + ([0] if "all" in a.force else [99]))

    def todo(step, out):
        need = STEPS.index(step) >= first_forced or not Path(out).exists()
        print(f"[{step}] {'running' if need else 'skip (exists)'} -> {Path(out).relative_to(ROOT)}", flush=True)
        return need

    src = job / "source.mkv"
    existing = sorted(job.glob("source.*"))
    if todo("download", existing[0] if existing else src):
        if Path(a.source).exists():
            src.unlink(missing_ok=True)
            src = job / ("source" + Path(a.source).suffix)
            src.unlink(missing_ok=True)
            src.symlink_to(Path(a.source).resolve())
        else:
            run(["yt-dlp", "--no-warnings", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mkv",
                 "-o", str(src), a.source])

    src = next(iter(sorted(job.glob("source.*"))), src)  # local sources are symlinked with their own extension

    clip = job / "clip.mp4"
    if todo("cut", clip):
        cut = (["-ss", str(start)] if start else []) + (["-t", str(dur)] if dur else [])
        vf = ["-vf", f"scale=-2:{a.height},fps=30"] if a.height else []
        run(["ffmpeg", "-loglevel", "error", "-y", *cut, "-i", src, *vf, "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-c:a", "aac", "-b:a", "160k", clip])

    offset = str(start or 0)
    raw = job / "captions_raw.jsonl"
    if todo("ocr", raw):
        run([PY, "-I", ROOT / "scripts/ocr_captions.py", clip, raw, "--fps", a.fps, "--offset", offset])

    stitched = job / "stitched"
    if todo("stitch", f"{stitched}.json"):
        run([PY, "-I", ROOT / "scripts/stitch_captions.py", raw, stitched, "--lag", a.lag])

    polished = job / "polished.json"
    if todo("polish", polished):
        run([PY, "-I", ROOT / "scripts/polish_transcript.py", f"{stitched}.json", polished,
             "--context", a.context] + (["--no-llm"] if a.no_llm else []))

    out = job / "narrated"
    if todo("narrate", f"{out}.mp4"):
        run([PY, "-I", ROOT / "scripts/narrate.py", polished, clip, out, "--video-start", offset,
             "--voice", a.voice, "--audience-voice", a.audience_voice, f"--bed-db={a.bed_db}"]
            + (["--drop-audience"] if a.drop_audience else []))

    print(f"\ndone: {out.relative_to(ROOT)}.mp4  (report: narrated.report.json, subtitles: narrated.srt)")


if __name__ == "__main__":
    sys.exit(main())
