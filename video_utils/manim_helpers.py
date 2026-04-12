"""Shared Manim helpers: CText (kerning fix), sync helpers, standard boilerplate.

Usage in any video{N}.py:
    from video_utils.manim_helpers import *
"""
import json
from pathlib import Path
from manim import *

# ── Standard config ──────────────────────────────────────
BG = "#1a1a2e"
config.background_color = BG

# 3b1b font — CMU Serif if installed, system default otherwise
# Install CMU Serif for authentic 3b1b look:
#   Linux:   sudo apt install fonts-cmu
#   macOS:   brew install --cask font-cmu-serif
#   Windows: download from https://www.ctan.org/pkg/cm-unicode
import subprocess, shutil
def _font_available(name):
    """Check if a font is available on the system."""
    if shutil.which("fc-list"):  # Linux/macOS with fontconfig
        try:
            result = subprocess.run(["fc-list", f":family={name}"], capture_output=True, text=True, timeout=5)
            return bool(result.stdout.strip())
        except Exception:
            return False
    return False  # Windows or no fontconfig — use system default

if _font_available("CMU Serif"):
    Text.set_default(font="CMU Serif")

# ── Standard colors ──────────────────────────────────────
ACCENT  = "#e94560"
ACCENT2 = "#0f3460"
GOLD    = "#f5c518"
TEAL    = "#16c79a"
SOFT_WHITE = "#eaeaea"
DIMMED  = "#555555"

# ── CText: fix Pango kerning ────────────────────────────
_SF = 8  # scale factor

def CText(*args, font_size=36, **kwargs):
    """Crisp Text with proper kerning.
    Renders at 8x font size then scales down to fix Pango's bad kerning
    at small sizes (known manim issue #2844).
    """
    t = Text(*args, font_size=font_size * _SF, **kwargs)
    t.scale(1.0 / _SF)
    return t

# ── Timing / sync helpers ───────────────────────────────

def load_timing(durations_file: str | Path) -> dict:
    """Load full timing data from durations.json."""
    try:
        with open(durations_file) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def make_sync_helpers(durations_file: str | Path):
    """Create sync helper functions bound to a specific durations.json.

    Usage:
        seg_dur, cue_t, until, sync, fill = make_sync_helpers(DURATIONS_FILE)
    """
    timing = load_timing(durations_file)

    def seg_dur(key, default=30.0):
        return timing.get("segments", {}).get(key, default)

    def cue_t(seg_key, cue_name):
        for v in timing.values():
            if isinstance(v, dict) and "segments" in v:
                seg = v["segments"].get(seg_key)
                if seg:
                    return seg.get("cues", {}).get(cue_name)
        return None

    def until(seg_key, cue_name, elapsed, min_rt=0.5):
        """Seconds until next cue. Use as run_time to fill gap with animation."""
        t = cue_t(seg_key, cue_name)
        if t is not None:
            return max(t - elapsed, min_rt)
        return 2.0

    def sync_fn(scene, seg_key, cue_name, elapsed):
        """Wait until cue time. Use sparingly — prefer filling with animation."""
        t = cue_t(seg_key, cue_name)
        if t is not None:
            gap = t - elapsed
            if gap > 0.05:
                scene.wait(gap)
                return elapsed + gap
        return elapsed

    def fill(scene, target, elapsed):
        """Pad remaining time at segment end. Keep < 3s."""
        r = target - elapsed
        if r > 0.05:
            scene.wait(r)

    return seg_dur, cue_t, until, sync_fn, fill
