#!/usr/bin/env python3
"""Tiny local UI for rescue.py.  Run: .venv/bin/python ui.py  ->  http://127.0.0.1:8765

Start jobs, watch logs, compare original vs re-voiced, edit lines and re-voice.
Standard library only; listens on localhost only.
"""
import json, os, re, subprocess, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "jobs"
PORT = int(os.environ.get("PORT", 8765))
NAME_RE = re.compile(r"^[\w.-]{1,80}$")
RUNNING = {}  # name -> Popen


def job_dir(name):
    if not name or not NAME_RE.match(name):
        raise ValueError("bad job name")
    return JOBS / name


def status(name):
    p = RUNNING.get(name)
    if p and p.poll() is None:
        return "running"
    if p and p.returncode:
        return "failed"
    return "done" if (JOBS / name / "narrated.mp4").exists() else "idle"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def send_file(self, path, ctype):
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else end
            else:
                start = size - int(m.group(2))
            self.send_response(206); self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype); self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1)); self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start); left = end - start + 1
            try:
                while left > 0:
                    chunk = fh.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self.send_file(ROOT / "ui.html", "text/html; charset=utf-8")
            if u.path == "/api/jobs":
                names = sorted(p.name for p in JOBS.iterdir() if p.is_dir()) if JOBS.exists() else []
                return self.send_json([{"name": n, "status": status(n)} for n in names])
            if u.path == "/api/log":
                log = job_dir(q.get("name")) / "run.log"
                return self.send_json({"status": status(q["name"]),
                                       "log": log.read_text()[-20000:] if log.exists() else ""})
            if u.path == "/api/job":
                d = job_dir(q.get("name"))
                pol = json.loads((d / "polished.json").read_text()) if (d / "polished.json").exists() else []
                rep = json.loads((d / "narrated.report.json").read_text()) if (d / "narrated.report.json").exists() else {}
                meta = json.loads((d / "job.json").read_text()) if (d / "job.json").exists() else {}
                return self.send_json({"polished": pol, "report": rep, "meta": meta, "status": status(q["name"])})
            if m := re.match(r"^/media/([\w.-]+)/(clip|narrated)\.mp4$", u.path):
                f = job_dir(m.group(1)) / f"{m.group(2)}.mp4"
                if f.exists():
                    return self.send_file(f, "video/mp4")
            self.send_error(404)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/api/run":
                name = body.get("name") or (json.loads((job_dir(body["rerun"]) / "job.json").read_text())["name"])
                d = job_dir(name); d.mkdir(parents=True, exist_ok=True)
                if status(name) == "running":
                    return self.send_json({"error": "already running"}, 409)
                meta_f = d / "job.json"
                meta = json.loads(meta_f.read_text()) if body.get("rerun") and meta_f.exists() else {
                    k: body.get(k) for k in ("name", "source", "start", "duration", "height", "voice", "context", "drop_audience")}
                if body.get("rerun") and body.get("voice"):
                    meta["voice"] = body["voice"]
                meta_f.write_text(json.dumps(meta, indent=1))
                cmd = [sys.executable, str(ROOT / "rescue.py"), meta["source"], "--name", name]
                for k in ("start", "duration", "height", "voice", "context"):
                    if meta.get(k):
                        cmd += [f"--{k}", str(meta[k])]
                if meta.get("drop_audience"):
                    cmd.append("--drop-audience")
                if body.get("force"):
                    cmd += ["--force", body["force"]]
                log = open(d / "run.log", "w")
                RUNNING[name] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
                return self.send_json({"ok": True, "name": name})
            if self.path == "/api/lines":
                d = job_dir(body.get("name")); f = d / "polished.json"
                pol = json.loads(f.read_text())
                for i, txt in body.get("edits", {}).items():
                    pol[int(i)]["text"] = txt.strip()
                f.write_text(json.dumps(pol, indent=1, ensure_ascii=False))
                return self.send_json({"ok": True, "saved": len(body.get("edits", {}))})
            self.send_error(404)
        except (ValueError, KeyError) as e:
            self.send_json({"error": str(e)}, 400)


if __name__ == "__main__":
    JOBS.mkdir(exist_ok=True)
    print(f"Talk audio rescue UI → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
