"""Voice a polished transcript with Kokoro (MLX) and lay it on the video timeline.

Usage: python narrate.py POLISHED.json VIDEO OUT_PREFIX [--video-start 600]
           [--voice am_michael] [--audience-voice am_eric | --drop-audience]
           [--max-speed 1.25] [--bed-db -inf]

For every sentence: synthesize at speed 1.0; if it is longer than its slot
(time until the next sentence), re-synthesize faster (up to --max-speed).
If it still doesn't fit it may run over, and the following lines are pushed
back until the timeline catches up at a pause. No lip-sync: it's slides.

Writes OUT_PREFIX.wav (narration), OUT_PREFIX.srt (polished subtitles),
OUT_PREFIX.mp4 (video + narration + soft subtitles) and OUT_PREFIX.report.json.
--bed-db mixes the original audio underneath (e.g. -28) for room ambience.
Needs ESPEAK_DATA_PATH=/opt/homebrew/share/espeak-ng-data (set by run script).
"""
import argparse, json, subprocess
import numpy as np, soundfile as sf
from mlx_audio.tts.utils import load_model

MODEL = "mlx-community/Kokoro-82M-bf16"
GAP = 0.15  # min silence between pushed-back lines (s)


def tts(model, text, voice, speed):
    lang = "b" if voice.startswith("b") else "a"
    chunks = [np.array(r.audio).ravel() for r in model.generate(text=text, voice=voice, speed=speed, lang_code=lang)]
    return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)


def srt_time(s):
    ms = int(round(s * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("polished"); ap.add_argument("video"); ap.add_argument("out")
    ap.add_argument("--video-start", type=float, default=0, help="transcript time at video t=0")
    ap.add_argument("--voice", default="am_michael")
    ap.add_argument("--audience-voice", default="am_eric")
    ap.add_argument("--drop-audience", action="store_true")
    ap.add_argument("--max-speed", type=float, default=1.25)
    ap.add_argument("--bed-db", type=float, default=float("-inf"))
    a = ap.parse_args()

    sents = [dict(s, idx=k) for k, s in enumerate(json.load(open(a.polished)))
             if s["text"].strip() and not (a.drop_audience and s.get("speaker") == "audience")]
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                         "-of", "csv=p=0", a.video]).decode())
    model = load_model(MODEL)
    sr = model.sample_rate
    track = np.zeros(int((dur + 30) * sr), np.float32)
    cursor, report, subs = 0.0, [], []

    for i, s in enumerate(sents):
        start = s["start"] - a.video_start
        nxt = sents[i + 1]["start"] - a.video_start if i + 1 < len(sents) else dur
        if start < -1 or start > dur:
            continue
        voice = a.audience_voice if s.get("speaker") == "audience" else a.voice
        at = max(start, cursor + GAP if cursor > 0 else start, 0)
        slot = max(0.3, nxt - at)
        audio, speed = tts(model, s["text"], voice, 1.0), 1.0
        if len(audio) / sr > slot:
            speed = min(a.max_speed, (len(audio) / sr) / slot * 1.03)
            audio = tts(model, s["text"], voice, speed)
        n0 = int(at * sr)
        track[n0:n0 + len(audio)] += audio[:max(0, len(track) - n0)]
        cursor = at + len(audio) / sr
        subs.append((at, cursor, s["text"]))
        report.append({"i": s["idx"], "start": round(start, 2), "placed": round(at, 2),
                       "delay": round(at - start, 2), "slot": round(nxt - start, 2),
                       "speech": round(len(audio) / sr, 2), "speed": round(speed, 2), "text": s["text"]})
        print(f"{i + 1}/{len(sents)} speed={speed:.2f} delay={at - start:+.2f}s", flush=True)

    track = track[:int(dur * sr)]
    peak = np.abs(track).max() or 1
    sf.write(a.out + ".wav", track / peak * 0.89, sr)
    with open(a.out + ".srt", "w") as fh:
        for k, (t0, t1, txt) in enumerate(subs, 1):
            fh.write(f"{k}\n{srt_time(t0)} --> {srt_time(t1)}\n{txt}\n\n")

    if a.bed_db == float("-inf"):
        audio_args = ["-map", "1:a", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    else:
        audio_args = ["-filter_complex",
                      f"[0:a]volume={a.bed_db}dB[bed];[1:a]aresample=48000[nar];"
                      f"[nar][bed]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]",
                      "-map", "[out]"]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", a.video, "-i", a.out + ".wav", "-i", a.out + ".srt",
                    "-map", "0:v", *audio_args, "-map", "2:s", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-ar", "48000", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
                    "-shortest", a.out + ".mp4"], check=True)

    delays = [r["delay"] for r in report]
    summary = {"lines": len(report), "max_delay_s": max(delays, default=0),
               "lines_sped_up": sum(r["speed"] > 1 for r in report),
               "lines_delayed_over_1s": sum(d > 1 for d in delays), "voice": a.voice, "lines_detail": report}
    json.dump(summary, open(a.out + ".report.json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in summary.items() if k != "lines_detail"}))


if __name__ == "__main__":
    main()
