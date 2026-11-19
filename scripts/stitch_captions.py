"""Stitch scrolling live-caption OCR states into timed sentences.

Usage: python stitch_captions.py RAW.jsonl OUT_PREFIX [--lag 1.0]

Each OCR state is a window onto the running transcript; later states may
revise words that were still pending. We align each new state against the
tail of the transcript, replace everything from the anchor on with the new
state, and keep the first-seen time of words that survive.
Writes OUT_PREFIX.json (sentences with start/end) and OUT_PREFIX.srt.
--lag shifts times earlier to compensate for live-ASR latency.
"""
import argparse, json, re
from difflib import SequenceMatcher

FIXES = [(r"\bAl\b", "AI"), (r"I'II", "I'll"), (r"\bIl\b", "I'll"), (r",,+", ","), (r"\s+", " ")]
TAIL = 40  # words of transcript to align against


def clean(text):
    text = re.sub(r"^\.{2,}|^…", "", text.strip())
    for a, b in FIXES:
        text = re.sub(a, b, text)
    return text.strip()


def norm(w):
    return re.sub(r"[^\w']", "", w.lower())


def stitch(states):
    W = []  # list of [word, t]
    for st in states:
        new = clean(st["text"]).split()
        if not new:
            continue
        ts = max(0, len(W) - TAIL)
        tail = [norm(w) for w, _ in W[ts:]]
        nn = [norm(w) for w in new]
        sm = SequenceMatcher(a=tail, b=nn, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
        if not blocks:
            W += [[w, st["t"]] for w in new]
            continue
        a0, b0 = blocks[0].a, blocks[0].b
        old_times = {}
        for b in sm.get_matching_blocks():
            for k in range(b.size):
                old_times[b.b + k] = W[ts + b.a + k][1]
        W = W[:ts + a0] + [[new[i], old_times.get(i, st["t"])] for i in range(b0, len(new))]
    return W


def sentences(W, lag, end_time):
    out, cur = [], []
    for w, t in W:
        cur.append((w, t))
        if re.search(r"[.?!]$", w) and len(cur) >= 3:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    res = []
    for i, s in enumerate(out):
        start = max(0, s[0][1] - lag)
        end = (out[i + 1][0][1] - lag) if i + 1 < len(out) else end_time
        res.append({"start": round(start, 2), "end": round(end, 2),
                    "text": " ".join(w for w, _ in s)})
    return res


def srt_time(s):
    h, r = divmod(s, 3600); m, r = divmod(r, 60)
    return f"{int(h):02}:{int(m):02}:{int(r):02},{int((r % 1) * 1000):03}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw"); ap.add_argument("out")
    ap.add_argument("--lag", type=float, default=1.0)
    a = ap.parse_args()
    states = [json.loads(l) for l in open(a.raw)]
    W = stitch(states)
    sents = sentences(W, a.lag, states[-1]["t"] + 2)
    json.dump(sents, open(a.out + ".json", "w"), indent=1, ensure_ascii=False)
    with open(a.out + ".srt", "w") as fh:
        for i, s in enumerate(sents, 1):
            fh.write(f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}\n\n")
    print(f"{len(W)} words, {len(sents)} sentences -> {a.out}.json/.srt")


if __name__ == "__main__":
    main()
