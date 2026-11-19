"""OCR the live-caption bar of the meetup video.

Usage: python ocr_captions.py VIDEO OUT.jsonl [--fps 4] [--offset SECONDS]

Crops the caption strip (1080p coords), samples frames with ffmpeg,
skips frames whose strip didn't change, and OCRs the rest with Apple
Vision (via ocrmac). Writes one JSON line per change: {"t": sec, "text": str}.
--offset is added to timestamps (e.g. 600 for a clip cut at 10:00).
"""
import argparse, json, subprocess, sys
import numpy as np
from PIL import Image
from ocrmac import ocrmac

# caption bar at 1920x1080, including the "EN" badge on the left (used to detect the bar)
CROP_W, CROP_H, CROP_X, CROP_Y = 1724, 72, 96, 999
TEXT_X = 144  # text area starts here inside the crop (skips the badge)


def has_caption_bar(img):
    """True if the white caption box with the dark 'EN' badge is on screen.
    During screen shares the bar is gone and OCR would read random page text."""
    margin, badge, text = img[22:48, 10:50], img[22:48, 56:108], img[:, TEXT_X:]
    return margin.mean() > 200 and badge.mean() < 120 and (text > 200).mean() > 0.5


def frames(video, fps):
    # crop is defined at 1080p; scale the frame to 1080p first so any input size works
    cmd = ["ffmpeg", "-loglevel", "error", "-i", video, "-vf",
           f"fps={fps},scale=-2:1080:flags=lanczos,crop={CROP_W}:{CROP_H}:{CROP_X}:{CROP_Y},format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = CROP_W * CROP_H
    i = 0
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield i / fps, np.frombuffer(buf, np.uint8).reshape(CROP_H, CROP_W)
        i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=4)
    ap.add_argument("--offset", type=float, default=0)
    a = ap.parse_args()

    prev, last_text, n, hidden = None, None, 0, 0
    with open(a.out, "w") as fh:
        for t, img in frames(a.video, a.fps):
            if t % 60 == 0 and t:
                print(f"ocr {int((t + a.offset) // 60)} min, {n} caption states", file=sys.stderr, flush=True)
            if not has_caption_bar(img):
                hidden += 1
                prev = None
                continue
            img = np.ascontiguousarray(img[:, TEXT_X:])
            small = img[::4, ::4].astype(np.int16)
            if prev is not None and np.abs(small - prev).mean() < 1.0:
                continue  # strip unchanged
            prev = small
            # upscale + plain dark-on-light image helps Vision on thin text
            pil = Image.fromarray(img).resize((img.shape[1] * 2, CROP_H * 2), Image.LANCZOS)
            res = ocrmac.OCR(pil, recognition_level="accurate",
                             language_preference=["en-US"]).recognize()
            text = " ".join(r[0] for r in res).strip()
            if text and text != last_text:
                fh.write(json.dumps({"t": round(t + a.offset, 2), "text": text}) + "\n")
                last_text = text
                n += 1
    print(f"{n} caption states written to {a.out}; caption bar not visible for "
          f"{hidden / a.fps / 60:.1f} min (skipped)", file=sys.stderr)


if __name__ == "__main__":
    main()
