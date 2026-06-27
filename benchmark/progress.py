"""A tiny stdlib progress tracker the benchmark harnesses share.

The suite builds ~100 real sessions and runs three tracks — minutes, not seconds — so it
needs to be watchable. A ``Tracker`` draws a live bar to stderr AND persists a snapshot to
``results/progress.json`` after every step, so a second terminal can check progress anytime:

    uv run python benchmark/progress.py        # prints the current snapshot, then exits

No tqdm, no deps: a progress bar is a carriage return and a percent.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
PROGRESS_FILE = RESULTS_DIR / "progress.json"


def _fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def _bar(done: int, total: int, width: int = 24) -> str:
    frac = 0.0 if total <= 0 else min(1.0, done / total)
    filled = int(frac * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _eta_seconds(done: int, total: int, elapsed: float) -> float | None:
    if done <= 0 or done >= total:
        return None
    return elapsed / done * (total - done)


def render_line(phase: str, done: int, total: int, elapsed: float, current: str) -> str:
    """The one-line bar (pure, so it can be asserted on)."""
    pct = 0 if total <= 0 else int(100 * min(1.0, done / total))
    eta = _eta_seconds(done, total, elapsed)
    tail = f" · {current}" if current else ""
    return (
        f"{_bar(done, total)} {done}/{total} {pct:3d}% | {phase} | "
        f"{_fmt_dur(elapsed)} elapsed, ~{_fmt_dur(eta)} left{tail}"
    )


class Tracker:
    """Drive one or more phases; redraw + persist on every step."""

    def __init__(self, *, n_phases: int = 1, stream=sys.stderr) -> None:
        self.stream = stream
        self.n_phases = n_phases
        self.phase_index = 0
        self.phase_name = ""
        self.total = 0
        self.done = 0
        self.current = ""
        self._t0 = time.monotonic()
        self._lock = threading.Lock()  # step() is called from worker threads during parallel recall
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    def phase(self, name: str, total: int) -> "Tracker":
        self.phase_index += 1
        self.phase_name, self.total, self.done, self.current = name, total, 0, ""
        self._draw()
        return self

    def step(self, current: str = "", *, n: int = 1) -> None:
        with self._lock:
            self.done += n
            self.current = current
            self._draw()

    def done_phase(self) -> None:
        if self.stream:
            self.stream.write("\n")
            self.stream.flush()
        self._persist(finished=self.phase_index >= self.n_phases)

    def _label(self) -> str:
        return f"[{self.phase_index}/{self.n_phases}] {self.phase_name}" if self.n_phases > 1 else self.phase_name

    def _draw(self) -> None:
        if self.stream:
            self.stream.write("\r" + render_line(self._label(), self.done, self.total, self.elapsed, self.current)[:160])
            self.stream.flush()
        self._persist()

    def _persist(self, *, finished: bool = False) -> None:
        snapshot = {
            "phase": self.phase_name,
            "phase_index": self.phase_index,
            "n_phases": self.n_phases,
            "done": self.done,
            "total": self.total,
            "percent": 0 if self.total <= 0 else round(100 * min(1.0, self.done / self.total), 1),
            "current": self.current,
            "elapsed_s": round(self.elapsed, 1),
            "eta_s": _eta_seconds(self.done, self.total, self.elapsed),
            "finished": finished,
            "updated_at": time.time(),
        }
        tmp = PROGRESS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, indent=2))
        tmp.replace(PROGRESS_FILE)  # atomic so a concurrent reader never sees a half-write


def read_snapshot() -> dict | None:
    try:
        return json.loads(PROGRESS_FILE.read_text())
    except (OSError, ValueError):
        return None


def print_snapshot() -> int:
    snap = read_snapshot()
    if not snap:
        print("no benchmark in progress (results/progress.json not found)")
        return 1
    state = "done" if snap.get("finished") else "running"
    phase = snap["phase"]
    if snap.get("n_phases", 1) > 1:
        phase = f"[{snap['phase_index']}/{snap['n_phases']}] {phase}"
    print(f"{state}: {phase}")
    print(render_line(phase, snap["done"], snap["total"], snap["elapsed_s"], snap.get("current", "")))
    return 0


def _selftest() -> None:
    assert _bar(0, 10) == "[" + "-" * 24 + "]"
    assert _bar(10, 10) == "[" + "#" * 24 + "]"
    assert _bar(5, 10).count("#") == 12
    assert _bar(1, 0) == "[" + "-" * 24 + "]"  # zero total never divides
    assert _eta_seconds(0, 10, 5) is None and _eta_seconds(10, 10, 5) is None
    assert _eta_seconds(5, 10, 10.0) == 10.0  # half done in 10s -> ~10s left
    assert _fmt_dur(None) == "?" and _fmt_dur(45) == "45s" and _fmt_dur(80) == "1m20s"
    line = render_line("Track A", 5, 10, 10.0, "flip-flop")
    assert "5/10" in line and " 50%" in line and "flip-flop" in line
    print("progress.py selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit(print_snapshot())
