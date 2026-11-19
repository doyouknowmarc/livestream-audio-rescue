"""Polish a stitched live-caption transcript with an LLM (headless Claude Code).

Usage: python polish_transcript.py STITCHED.json OUT.json [--context "talk topic / names"]
                                   [--chunk 40] [--model sonnet] [--no-llm]

Keeps the sentence count and timings intact; only the text changes, plus a
"speaker" tag ("presenter" or "audience") so audience interjections can be
voiced differently or dropped. Uses `claude -p`; if that fails for a chunk
(or --no-llm), the original text is kept with simple rule-based cleanup.
"""
import argparse, json, re, subprocess, sys

PROMPT = """You are cleaning up an automatic live-caption transcript of a talk so it can be
re-voiced by a text-to-speech engine. Context about the talk: {context}

The captions came from live speech recognition, so expect misheard words
(e.g. "Nep poll" -> "the poll", "agenticommerce" -> "agentic commerce"),
stutters, doubled words, stray dots and broken punctuation.

Rules:
- Return ONLY a JSON array, one object per input item, same order, same "i":
  {{"i": <int>, "text": <cleaned sentence>, "speaker": "presenter" | "audience"}}
- Fix obvious mis-hearings, punctuation, casing, doubled words and filler
  ("uh", "like" used as filler) so it reads naturally aloud. Keep the
  speaker's wording, tone and meaning; do NOT summarise, add facts or merge items.
- Write numbers the way they should be spoken where it helps TTS
  ("100s of 1000000s" -> "hundreds of millions").
- If a line is clearly a short interjection from someone else in the room,
  set speaker to "audience".
- If a fragment is unrecoverable, keep your best plausible reading.

Input:
{items}
"""

RULES = [(r"\.{3,}", "…"), (r"\b(\w+) \1\b", r"\1"), (r"\s+([,.?!])", r"\1"),
         (r"\buh,?\s*", ""), (r"\s+", " ")]


def rule_clean(t):
    for a, b in RULES:
        t = re.sub(a, b, t, flags=re.I)
    t = t.strip(" ,")
    return t[:1].upper() + t[1:] if t else t


def llm_chunk(items, context, model):
    prompt = PROMPT.format(context=context, items=json.dumps(items, ensure_ascii=False, indent=0))
    r = subprocess.run(["claude", "-p", "--model", model, "--output-format", "text"],
                       input=prompt, capture_output=True, text=True, timeout=600)
    m = re.search(r"\[.*\]", r.stdout, re.S)
    out = json.loads(m.group(0))
    if [o["i"] for o in out] != [it["i"] for it in items]:
        raise ValueError("LLM changed item ids/count")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp"); ap.add_argument("out")
    ap.add_argument("--context", default="a tech meetup talk about AI")
    ap.add_argument("--chunk", type=int, default=40)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()

    sents = json.load(open(a.inp))
    for i in range(0, len(sents), a.chunk):
        part = sents[i:i + a.chunk]
        items = [{"i": i + k, "text": s["text"]} for k, s in enumerate(part)]
        res = None
        if not a.no_llm:
            try:
                res = llm_chunk(items, a.context, a.model)
            except Exception as e:  # keep going with rule-based cleanup
                print(f"chunk {i}: LLM polish failed ({e}); using rules", file=sys.stderr)
        for k, s in enumerate(part):
            s["raw"] = s["text"]
            if res:
                s["text"], s["speaker"] = res[k]["text"].strip(), res[k].get("speaker", "presenter")
            else:
                s["text"], s["speaker"] = rule_clean(s["text"]), "presenter"
        print(f"polished {min(i + a.chunk, len(sents))}/{len(sents)}", file=sys.stderr)
    json.dump(sents, open(a.out, "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
