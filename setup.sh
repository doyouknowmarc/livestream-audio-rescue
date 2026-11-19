#!/usr/bin/env bash
# One-time setup: system tools via Homebrew, Python env via uv.
set -euo pipefail
cd "$(dirname "$0")"
for tool in ffmpeg yt-dlp espeak-ng uv; do
  command -v "$tool" >/dev/null || { echo "missing: $tool  ->  brew install $tool"; exit 1; }
done
command -v claude >/dev/null || echo "note: 'claude' CLI not found; the polish step will fall back to rule-based cleanup"
uv venv --python 3.12 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
echo "ok. run: ./rescue.py --help"
