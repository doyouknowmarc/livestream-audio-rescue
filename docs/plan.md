# Meetup audio rescue: plan

**Source:** "MartinAtrin Live Stream" (Polygonfaces AI Society), 1:10:47, YouTube `Dng83kIb-BY`

## What we have (`source/`)
| File | Content |
|---|---|
| `meetup.mkv` | 1080p60 H.264 video plus Opus audio, merged (263 MB) |
| `meetup.f299.mp4` | video only (1080p60) |
| `meetup.f251.webm` | audio only, Opus ~99 kbps, 48 kHz (the best audio YouTube has) |

## First look
- **Audio:** over the 10:00–15:00 window the RMS is −17.7 dB and the noise floor is −19.6 dB. That is only about 2 dB of dynamic range, so the voice and the noise are nearly the same level. Room noise and/or heavy compression is likely.
- **Video:** static slides, plus a **live caption bar** at the bottom: one line, white box, an "EN" badge, roughly y=665–715 at 720p.
  - The captions are **live ASR**, not a clean transcript. They have errors ("bad, bad. And how was it thated").
  - Words show up gradually: grey means not yet final, black means final. The line scrolls and starts with "…".
  - So OCR will give us *a* transcript, not *the* transcript. Some cleanup is needed either way.

## Pipeline: test on a 5-minute sample first (e.g. 10:00–15:00)

### Step 0: Cut the sample
`ffmpeg -ss 00:10:00 -t 300` produces the sample video and a 48 kHz WAV.

### Step 1, Path A: rescue the real voice (preferred, keeps Martin's own voice)
1. **Voice isolation.** Try a few tools on the WAV and compare by ear:
   - Demucs v4 / `htdemucs` vocals stem (local, `pip install demucs`)
   - DeepFilterNet 3 (local, very good on speech in noise)
   - Resemble Enhance (denoise plus bandwidth restore, local)
   - ElevenLabs Voice Isolator (cloud, often the best on hard cases)
2. Light finishing: high-pass ~80 Hz, de-ess, loudness normalize to −16 LUFS.
3. **Decision gate:** if it is intelligible, stop here and remux. No sync problems at all.

### Step 2: Get a clean transcript (needed for Path B, and useful for subtitles anyway)
Use two sources and merge them:
- **OCR of the caption bar.** Crop the strip, sample at about 3 fps, and drop duplicate frames. Then reconstruct the text with timestamps: keep only the black (final) words and stitch the scrolling lines together by overlap.
  - OCR engine: **Apple Vision** (built into macOS, fast, free, very accurate on clean UI text). It is a better fit than a large model for one line of crisp text. We can still try `baidu/Unlimited-OCR` as a comparison.
- **Whisper on the isolated audio** (`whisper-cli` is already installed). It gives word-level timestamps, which we need for sync.
- **Merge:** use the OCR text and Whisper's text and timings, then correct the result with an LLM. The slide text helps with names and terms (MAI Code 2, Copilot, Foundry…).

### Step 3, Path B: re-voice, only if Path A fails
1. TTS per sentence or segment:
   - **Qwen3-TTS** (Pinokio, local). It supports voice cloning from a short clip of Martin.
   - Kokoro (local, fast, stock voices only)
   - ElevenLabs (cloud, best quality, can clone)
   - ⚠️ Cloning Martin's voice needs **his OK**.
2. **Resync.** Anchor each TTS segment at its Whisper or caption start time, then time-stretch it to fit its slot (`atempo` / rubberband, within ±15%). Where it doesn't fit, close up silence.
   - Because the video is static slides, small drifts are invisible. There is no lip-sync problem unless a webcam view shows up somewhere.
3. Optional: mix in a little room tone or the isolated original underneath so it doesn't sound sterile.

### Step 4: Remux
Replace the audio with ffmpeg (`-c:v copy`), then add soft subtitles from the cleaned transcript.

## Success check for the 5-minute sample
- Path A: listen at 3 or 4 spots and judge whether the voice is understandable without reading the captions.
- Path B: no audible drift by the end of the 5 minutes, and the voice sounds acceptable.

## Results on the 10:00–15:00 sample (2026-11-19)
- **Path A failed.** DeepFilterNet, Demucs and Demucs followed by DFN all left the speech unintelligible. Whisper large-v3-turbo produced only hallucinations ("Thank you.", French fragments). Path A is dropped.
- **Path B, caption OCR, works well.**
  - `scripts/ocr_captions.py` crops the caption bar and runs Apple Vision OCR at 4 fps. It took 43 s for the 5 minutes and produced 309 caption states.
  - `scripts/stitch_captions.py` aligns the scrolling, self-correcting states into 44 timed sentences (`work/ocr/sample_stitched.json/.srt`).
- **Remaining text issues come from the live ASR, not the OCR.** Examples: "vote in Nep poll", "GPT terror", "willll", "........". There are also a few audience interjections. These go to the polish step.
- **Next:** polish the text, generate TTS per sentence (Kokoro or Qwen3-TTS), fit each line to its time slot, and remux.

## Locally available
yt-dlp, ffmpeg, whisper / whisper-cli, and Pinokio with Qwen3-TTS. Not installed yet: demucs, DeepFilterNet, kokoro.
