#!/usr/bin/env python3
"""Motion-only camera recorder.

Per camera, one ffmpeg process:
  * copies the stream into 10 s MPEG-TS segments in a rolling buffer (crash-safe), and
  * decodes keyframes only (every ~2 s on Wyze cams), downscaled to grey, piped to us
    for a cheap frame-difference motion score.
Segments within PRE_ROLL before / POST_ROLL after any motion are kept and remuxed into
one MP4 per event:  /mnt/data/cameras/<cam>/<YYYY-MM-DD>/<HH-MM-SS>.mp4  (local time, MST).
Everything else is deleted. A pruner keeps the archive under MAX_ARCHIVE_GB and keeps a
free-space floor on the drive. It only ever deletes inside ROOT.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "cameras.json").read_text())

ROOT = Path(CONFIG.get("root", "/mnt/data/cameras"))
BUFFER = ROOT / ".buffer"
LOGFILE = ROOT / "events.jsonl"
SCORES = ROOT / ".scores"

SEG_SECONDS = 10
PRE_ROLL = 15            # seconds kept before first motion
POST_ROLL = 30           # seconds kept after last motion
MAX_EVENT_SECONDS = 600  # split very long events
STALL_SECONDS = 45       # no frames / no new segment for this long → restart ffmpeg
W, H = 192, 108          # motion analysis size
PIX_DIFF = 25            # per-pixel grey change that counts
MOTION_FRAC = float(CONFIG.get("motion_frac", 0.004))  # fraction of changed pixels = motion
MAX_ARCHIVE_GB = float(CONFIG.get("max_archive_gb", 50))
MIN_FREE_GB = float(CONFIG.get("min_free_gb", 100))

_stop = threading.Event()


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def seg_start(p: Path) -> float:
    return datetime.strptime(p.stem, "%Y%m%d-%H%M%S").timestamp()


def make_mask(ignore=()):
    m = np.ones((H, W), dtype=bool)
    # Wyze on-screen clock sits bottom-right; ignore that strip.
    m[int(H * 0.86):, int(W * 0.55):] = False
    # per-camera ignore boxes from cameras.json: [x0, y0, x1, y1] as fractions of the frame
    for x0, y0, x1, y1 in ignore:
        m[int(H * y0):int(H * y1) + 1, int(W * x0):int(W * x1) + 1] = False
    return m


class Camera(threading.Thread):
    def __init__(self, name, url, audio, ignore=()):
        super().__init__(name=f"cam-{name}", daemon=True)
        self.cam, self.url, self.audio = name, url, audio
        self.buf = BUFFER / name
        self.buf.mkdir(parents=True, exist_ok=True)
        self.motion_times = []           # epoch seconds of motion keyframes
        self.lock = threading.Lock()
        self.last_frame = 0.0
        self.proc = None
        self.event = None                # {"segs": [...], "start": t, "peak": score}
        self.mask = make_mask(ignore)
        self.peak_minute = (0, 0.0)

    # ── ffmpeg ──────────────────────────────────────────────────────────────
    def cmd(self):
        c = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
             "-rtsp_transport", "tcp", "-timeout", "15000000",
             "-skip_frame", "nokey", "-i", self.url,
             "-map", "0:v:0", "-c:v", "copy"]
        if self.audio:
            c += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "64k"]
        else:
            c += ["-an"]
        c += ["-f", "segment", "-segment_time", str(SEG_SECONDS), "-segment_format", "mpegts",
              "-reset_timestamps", "1", "-strftime", "1", str(self.buf / "%Y%m%d-%H%M%S.ts"),
              "-map", "0:v:0", "-vf", f"scale={W}:{H},format=gray", "-fps_mode", "passthrough",
              "-f", "rawvideo", "pipe:1"]
        return c

    def run(self):
        leftovers = sorted(self.buf.glob("*.kept"))   # event in progress when we last died
        if leftovers:
            self.event = {"segs": leftovers, "start": seg_start(leftovers[0]), "peak": 0.0}
            self.finish()
        while not _stop.is_set():
            log(f"[{self.cam}] starting ffmpeg")
            self.last_frame = time.time()
            self.proc = subprocess.Popen(self.cmd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            threading.Thread(target=self._drain_stderr, args=(self.proc,), daemon=True).start()
            reader = threading.Thread(target=self._frames, args=(self.proc,), daemon=True)
            reader.start()
            while not _stop.is_set() and self.proc.poll() is None:
                time.sleep(2)
                self.manage()
                newest = max((p.stat().st_mtime for p in self.buf.glob("*.ts")), default=0)
                stale = time.time() - max(self.last_frame, newest)
                if stale > STALL_SECONDS:
                    log(f"[{self.cam}] stalled {stale:.0f}s, restarting ffmpeg")
                    self.proc.kill()
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc.wait()
            self.manage()
            if not _stop.is_set():
                time.sleep(5)
        self.manage(final=True)

    def _drain_stderr(self, proc):
        last = {}
        for line in proc.stderr:
            s = line.decode(errors="replace").strip()
            if (not s or "non-existing PPS" in s or "decode_slice_header" in s
                    or "no frame!" in s or "Last message repeated" in s
                    or "error while decoding MB" in s or "top block unavailable" in s
                    or "cabac decode" in s):
                continue
            if time.time() - last.get(s, 0) > 300:   # rate-limit repeats
                last[s] = time.time()
                log(f"[{self.cam}] ffmpeg: {s[:200]}")

    def _frames(self, proc):
        size = W * H
        prev = None
        while True:
            data = proc.stdout.read(size)
            if not data or len(data) < size:
                return
            now = time.time()
            self.last_frame = now
            cur = np.frombuffer(data, dtype=np.uint8).reshape(H, W).astype(np.int16)
            if prev is not None:
                changed = (np.abs(cur - prev) > PIX_DIFF) & self.mask
                score = float(changed.sum()) / self.mask.sum()
                self._score(now, score)
                if score >= MOTION_FRAC:
                    with self.lock:
                        self.motion_times.append(now)
                        if self.event is not None:
                            self.event["peak"] = max(self.event["peak"], score)
                        else:
                            self.pending_peak = max(getattr(self, "pending_peak", 0.0), score)
            prev = cur

    def _score(self, now, score):
        minute = int(now // 60)
        m, peak = self.peak_minute
        if minute != m:
            if m:
                SCORES.mkdir(parents=True, exist_ok=True)
                with open(SCORES / f"{self.cam}.log", "a") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(m * 60))} {peak:.4f}\n")
            self.peak_minute = (minute, score)
        elif score > peak:
            self.peak_minute = (m, score)

    # ── segment bookkeeping ─────────────────────────────────────────────────
    def manage(self, final=False):
        segs = sorted(self.buf.glob("*.ts"))
        if not final:
            segs = segs[:-1]              # newest segment is still being written
        now = time.time()
        with self.lock:
            motions = [m for m in self.motion_times if m > now - 3600]
            self.motion_times = motions
        for i, p in enumerate(segs):
            try:
                s = seg_start(p)
            except ValueError:
                p.unlink(missing_ok=True)
                continue
            e = seg_start(segs[i + 1]) if i + 1 < len(segs) else s + SEG_SECONDS
            if not final and now < e + PRE_ROLL:
                break                     # can't decide yet: motion may still arrive
            keep = any(s - POST_ROLL <= m <= e + PRE_ROLL for m in motions)
            if keep:
                if self.event is None:
                    self.event = {"segs": [], "start": s,
                                  "peak": getattr(self, "pending_peak", 0.0)}
                    self.pending_peak = 0.0
                kept = p.with_suffix(".kept")   # out of the *.ts glob → decided once
                p.rename(kept)
                self.event["segs"].append(kept)
                if e - self.event["start"] >= MAX_EVENT_SECONDS:
                    self.finish()
            else:
                if self.event is not None:
                    self.finish()
                p.unlink(missing_ok=True)
        if final and self.event is not None:
            self.finish()

    def finish(self):
        ev, self.event = self.event, None
        segs = [p for p in ev["segs"] if p.exists() and p.stat().st_size > 0]
        if not segs:
            return
        start = datetime.fromtimestamp(ev["start"])
        outdir = ROOT / self.cam / start.strftime("%Y-%m-%d")
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / (start.strftime("%H-%M-%S") + ".mp4")
        lst = self.buf / ".concat.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in segs))
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                            "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c", "copy", "-movflags", "+faststart", str(out)],
                           capture_output=True, timeout=300)
        lst.unlink(missing_ok=True)
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            # keep the raw segments rather than lose footage
            raw = outdir / (start.strftime("%H-%M-%S") + "_raw")
            raw.mkdir(exist_ok=True)
            for p in segs:
                shutil.move(str(p), raw / p.name)
            log(f"[{self.cam}] remux failed ({r.stderr.decode(errors='replace')[:200]}); kept raw in {raw}")
            return
        for p in segs:
            p.unlink(missing_ok=True)
        dur = len(segs) * SEG_SECONDS
        rec = {"cam": self.cam, "start": start.isoformat(timespec="seconds"),
               "approx_seconds": dur, "peak_score": round(ev["peak"], 4), "file": str(out)}
        with open(LOGFILE, "a") as f:
            f.write(json.dumps(rec) + "\n")
        log(f"[{self.cam}] event saved {out} (~{dur}s, peak {ev['peak']:.3f})")


def prune():
    """Delete oldest event files until archive < MAX_ARCHIVE_GB and drive free > MIN_FREE_GB.
    Only touches files under ROOT/<camera>/ ."""
    files = [p for p in ROOT.glob("*/*/*") if p.is_file() and not p.parts[-3].startswith(".")
             and not (ROOT / ".saved" / p.relative_to(ROOT)).exists()]   # ⭐ saved clips are kept forever
    files += [p for p in ROOT.glob("*/*/*_raw/*.ts") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    removed = 0
    while files and (total > MAX_ARCHIVE_GB * 1e9 or shutil.disk_usage(ROOT).free < MIN_FREE_GB * 1e9):
        p = files.pop(0)
        assert ROOT in p.resolve().parents
        total -= p.stat().st_size
        p.unlink()
        removed += 1
    for d in sorted(ROOT.glob("*/*"), reverse=True):
        if any(part.startswith(".") for part in d.relative_to(ROOT).parts):
            continue                      # never touch .buffer / .scores
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    if removed:
        log(f"pruner removed {removed} old files; archive now {total / 1e9:.1f} GB")


def main():
    BUFFER.mkdir(parents=True, exist_ok=True)
    cams = [Camera(c["name"], c["url"], c.get("audio", False), c.get("ignore", ()))
            for c in CONFIG["cameras"]]

    def stop(*_):
        _stop.set()
        for c in cams:
            if c.proc and c.proc.poll() is None:
                c.proc.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    for c in cams:
        c.start()
    log(f"recording {len(cams)} cameras to {ROOT} (motion-only, cap {MAX_ARCHIVE_GB:.0f} GB)")
    last_prune = 0
    while not _stop.is_set():
        if time.time() - last_prune > 600:
            try:
                prune()
            except Exception as exc:
                log(f"pruner error: {exc}")
            last_prune = time.time()
        _stop.wait(5)
    for c in cams:
        c.join(timeout=60)
    log("stopped")


if __name__ == "__main__":
    sys.exit(main())
