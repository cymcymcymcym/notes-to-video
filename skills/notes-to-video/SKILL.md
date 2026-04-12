---
name: make-video
description: Turn notes (LaTeX, PDF, or plain text) into 3Blue1Brown-style animated videos using Manim + TTS + ffmpeg. Use when the user wants to create an explainer video.
user-invocable: true
argument-hint: <source-file-or-topic>
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# 3b1b-Style Video Producer

Turn notes into 3Blue1Brown-style animated explainer videos.

**Input**: `$ARGUMENTS` — a source file path (`.tex`, `.pdf`, notes) or topic description.

## Environment Setup

### Prerequisites

| Dependency | Required | Install |
|-----------|----------|---------|
| Python 3.10+ | Yes | System package manager |
| FFmpeg | Yes | See platform instructions below |
| LaTeX | For equations only | `texlive` / MiKTeX / MacTeX |

### Platform Install

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y ffmpeg
pip install manim edge-tts pydub
```

**macOS:**
```bash
brew install ffmpeg
pip install manim edge-tts pydub
```

**Windows:**
```powershell
# Install ffmpeg via chocolatey or winget
choco install ffmpeg   # or: winget install Gyan.FFmpeg
pip install manim edge-tts pydub
```

**Optional extras** (install only if you choose these TTS backends):
```bash
# MiniMax TTS (cloud, best quality, requires API key)
pip install httpx python-dotenv

# Chatterbox TTS (local, voice cloning, requires NVIDIA GPU)
pip install chatterbox-tts faster-whisper torch
```

### Project Structure

Each project is self-contained. The `video_utils/` library ships with the skill:

```
video_utils/                # shared video production utilities (bundled)
  manim_helpers.py          # CText, colors, sync helpers
  tts_edge.py              # Edge-TTS with cue estimation (free, default)
  tts_minimax.py           # MiniMax TTS with cue estimation (cloud)
  tts_local.py             # Chatterbox + faster-whisper (local GPU)
  tts_openai.py            # OpenAI TTS (cloud)
  validate_scenes.py       # overlap, OOB, text-overflow, line-cross, screenshot checker

videos/                    # per-project output
  src/
    part{N}_narration.py   # narration with {CUE} markers
    video{N}.py            # Manim scenes
    build_all.py           # unified build script
  audio/video{N}/          # TTS output + durations.json
  output/                  # final MP4s
  review/                  # validation screenshots
  plan_<topic>.md          # series plan
```

### First-Time Project Setup

```bash
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install manim edge-tts pydub
```

### TTS Selection

**Ask the user which TTS backend they prefer before generating audio.** Default to Edge-TTS if they have no preference.

| Backend | Quality | Cost | Requirements | Best for |
|---------|---------|------|-------------|----------|
| **Edge-TTS** (default) | Good | Free | None | Getting started, no API key needed |
| **MiniMax** | Best | ~$0.04/min | `MINIMAX_API_KEY` in `.env` | Production quality |
| **Chatterbox** | Good + voice cloning | Free | NVIDIA GPU | Privacy, custom voices |
| **OpenAI TTS** | Good | ~$0.06/min | `OPENAI_API_KEY` in `.env` | OpenAI ecosystem users |

### Font Configuration

CMU Serif (3Blue1Brown's font) is **strongly recommended** for the best visual results:

- **Linux:** `sudo apt install fonts-cmu`
- **macOS:** `brew install --cask font-cmu-serif` (via homebrew-cask-fonts)
- **Windows:** Download from [CTAN](https://www.ctan.org/pkg/cm-unicode) and install the .otf files

If CMU Serif is not installed, `CText()` falls back to the system default automatically.

## Pipeline

### Step 1: Extract Content
Read the source material. Identify key concepts, flow, and dependencies.

### Step 2: Plan the Video Series
Write a plan to `videos/plan_<topic>.md`.

### Step 3: Write Narration with Cue Markers
Write narration as a Python dict in `videos/src/part{N}_narration.py`:
```python
VIDEO1 = {
    "Scene1_Name": {"segments": {
        "s1_seg1": (
            "Here's the key idea. "
            "{CONCEPT} The model predicts representations, not pixels. "
            "{EQUATION} The loss is simply L2 distance in embedding space."
        ),
    }},
}
```
Rules:
- Conversational 3b1b tone: contractions, short sentences, rhetorical questions
- `{CUE_NAME}` markers BEFORE the keyword they reference
- Each segment ~60-100 words (~25-40 seconds of speech)
- 3-5 segments per scene

**Derivation scenes (CRITICAL):** When a scene shows a step-by-step equation derivation or proof:

1. **Narration describes each transformation as it happens.** Write narration and animation together — each sentence corresponds to one visual step. Do NOT write general narration separately and try to fit equations afterwards.

2. **Use per-submobject `ReplacementTransform` — NOT `TransformMatchingTex`.** `TransformMatchingTex` does global interpolation that makes everything float. The 3b1b technique is individual `ReplacementTransform` per term, so unchanged parts stay perfectly frozen:

   ```python
   # Morphing "=" into "≥" while everything else stays perfectly still:
   eq1 = MathTex(r"\log p(x)", r"=", r"\mathbb{E}[\log p]")
   eq2 = MathTex(r"\log p(x)", r"\geq", r"\mathbb{E}[\log p]")
   eq2.shift(eq1[0].get_center() - eq2[0].get_center())  # align anchor
   self.play(
       ReplacementTransform(eq1[0], eq2[0]),  # frozen
       ReplacementTransform(eq1[1], eq2[1]),  # "=" morphs to "≥"
       ReplacementTransform(eq1[2], eq2[2]),  # frozen
   )
   ```

   **Adding new terms** — existing parts transform, new parts FadeIn:
   ```python
   self.play(
       ReplacementTransform(eq1[0], eq2[0]),  # stays
       FadeOut(eq1[1]),                        # old "+" disappears
       FadeIn(eq2[1]),                         # new "-" appears
       ReplacementTransform(eq1[2], eq2[3]),  # term moves to new position
   )
   ```

   **Cancellation** — shrink/fade the term, then close the gap:
   ```python
   self.play(eq[2].animate.scale(0).set_opacity(0), run_time=0.8)
   remaining = VGroup(eq[0], eq[1], eq[3])
   self.play(remaining.animate.move_to(ORIGIN), run_time=0.5)
   ```

3. **Structure equations for per-term control.** Each meaningful part must be its own submobject:
   ```python
   # BAD — one blob, can't address terms individually
   eq = MathTex(r"\log p(x) = \log \int Q(z) \frac{p(x,z)}{Q(z)} dz")
   
   # GOOD — each term addressable by index
   eq = MathTex(r"\log p(x)", r"=", r"\log \int", r"Q(z)", r"\frac{p(x,z)}{Q(z)}", r"\,dz")
   # eq[0] is "\log p(x)", eq[1] is "=", etc.
   ```

4. **Align before transforming.** Position eq2 relative to eq1 so frozen parts don't drift:
   ```python
   eq2.shift(eq1[0].get_center() - eq2[0].get_center())  # anchor on first term
   ```

5. **Keep the equation on screen throughout.** It lives in one place and transforms. The viewer watches one object evolve, not a slideshow.

**3b1b scene design rules (follow these for authentic style):**

- **Pacing**: `self.wait()` (1s) after every `self.play()`. Let the viewer absorb. Longer pauses (`wait(2)`) for complex ideas. Don't rush.
- **Layout**: titles `to_edge(UP)`, main equations centered, diagrams center or lower region, working math `to_corner(UL)`. Use `set_max_width(config.frame_width - 1)` to prevent overflow.
- **Font sizes**: hero equations 48-72, body math 42-48 (default), labels/notes 24-36. Much larger than typical.
- **Minimal text**: almost never full sentences on screen. Key terms and equations only. The narration carries the explanation, not the screen text.
- **Focus/defocus**: dim non-focus items with `.animate.set_fill(opacity=0.35)`, restore with `set_fill(opacity=1)`. This is how 3b1b directs attention.
- **Color**: use semantic color mapping — each variable gets a consistent color via `tex_to_color_map`. Key palette: BLUE `#58C4DD`, YELLOW `#FFFF00`, TEAL `#5CD0B3`, RED `#FC6255`, PINK `#D147BD`, GREEN `#83C167`.
- **Sequential reveals**: `LaggedStart(*anims, lag_ratio=0.1)` for dramatic builds, not simultaneous FadeIn.
- **Curved arrows**: `Arrow(..., path_arc=-60*DEGREES)` for conceptual links between objects.

Example for a derivation:
```python
"s3_seg1": (
    "We start with log p of x. "
    "{EXPAND} Now we introduce Q of z — "
    "multiplying and dividing inside the integral. "
    "{JENSEN} Applying Jensen's inequality, "
    "the log moves inside as a lower bound. "
    "{LABEL_ELBO} And this? That's the ELBO."
),
```

### Step 4: Build Source Files

#### 4a. Manim Scenes — `videos/src/video{N}.py`

**Required boilerplate:**
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))  # project root
from pathlib import Path
from video_utils.manim_helpers import *
from video_utils.manim_helpers import make_sync_helpers

DURATIONS_FILE = Path(__file__).resolve().parents[1] / "audio" / "video{N}" / "durations.json"
seg_dur, cue_t, until, sync, fill = make_sync_helpers(DURATIONS_FILE)
```

This gives you:
- `CText()` — kerning-fixed Text (renders at 8x size, scales down). **Always use instead of `Text()`.**
- `MathTex` — for equations (uses LaTeX, no kerning issues)
- `BG`, `ACCENT`, `GOLD`, `TEAL`, `SOFT_WHITE`, `DIMMED` — standard colors
- `seg_dur()`, `cue_t()`, `until()`, `sync()`, `fill()` — audio sync helpers
- CMU Serif font (strongly recommended — falls back to system default if not installed)

**Why `CText()` not `Text()`:** Manim's Pango renderer has broken kerning at small font sizes — uneven letter spacing. `CText` renders at 8x size then scales down, fixing it. Known issue: [manim #2844](https://github.com/ManimCommunity/manim/issues/2844).

**Audio-video sync — the cue system:**

The narration has `{CUE_NAME}` markers. TTS generates per-sentence audio and estimates cue positions by character ratio. In Manim:

```python
class Scene1_Example(Scene):
    def construct(self):
        seg = seg_dur("s1_seg1")
        sk = "s1_seg1"
        e = 0.0

        title = CText("Key Idea", font_size=44, color=ACCENT).to_edge(UP, buff=0.5)
        self.play(Write(title), run_time=2.0); e += 2.0

        # Fill gap until next cue with slow animation (NOT static wait)
        rt = until(sk, "CONCEPT", e)
        self.play(title.animate.scale(0.9), run_time=rt); e += rt

        # CUE: visual event fires when narrator says the keyword
        e = sync(self, sk, "EQUATION", e)
        eq = MathTex(r"E = mc^2")
        self.play(Write(eq), run_time=1.5); e += 1.5

        fill(self, seg, e)
        self.play(FadeOut(Group(*self.mobjects)), run_time=0.5)
```

**Key sync rules:**
- **Never `self.wait()` > 1s** — fill with slow animations using `until()` as `run_time`
- **Place `{CUE}` before the keyword**: `"...for a {BAG} plastic bag..."`
- **Dynamic run_time**: `rt = until(sk, "NEXT_CUE", e)` expands animation to fill available time
- **`fill()` at segment end < 3s** — if longer, add more animation or cues

**Anti-overlap rules (CRITICAL):**

Overlapping text is the #1 quality problem. **Every scene must pass the validator with 0 issues. Do NOT render until the validator reports 0 issues.** Intentional visual effects (like crossing out an equation) do not justify skipping validation — restructure the scene to avoid triggering the validator, or use visual approaches that don't generate false positives (e.g. fade the equation to low opacity, then show the replacement, rather than overlaying a Cross on top).

- **`FadeOut(Group(*self.mobjects))` between EVERY concept change** — within AND between segments. Never accumulate unrelated elements.
- **For derivation scenes**: use `TransformMatchingTex` to morph equations in place. Do NOT stack equations vertically hoping they fit.
- **FadeOut before FadeIn** when reusing the same screen position (except for `TransformMatchingTex` which handles this automatically)
- **Text inside containers**: `CText()` width can be surprising. Circle radius ≥ 1.1 for single words. RoundedRectangle needs 0.4+ padding.
- **Never route arrows through text** — use `.get_top()`, `.get_bottom()`, `.get_left()`, `.get_right()` for arrow endpoints
- **Safe bounds**: x in [-6.5, 6.5], y in [-3.5, 3.5]. Reserve y > 3.0 for titles only.
- **Min font_size=24** for CText

#### 4b. Validation (MANDATORY — never skip)

The validator lives at `video_utils/validate_scenes.py`. Three modes:

**Fast mode** (default, seconds):
- Text-vs-text overlaps (>10% area)
- Text-overflow (text exceeding container boundary)
- Line-cross (arrows/curves through text, >15% coverage)
- OOB (outside safe bounds)

**Screenshot mode** (`--screenshots`, <1s/scene):
- Captures PNG at end of each segment (right before `FadeOut(Group(*))`)
- **Claude MUST read every screenshot** to catch visual issues automated checks miss
- Most reliable way to catch layout problems

**Usage:**
```bash
# 1. Fast automated check
python video_utils/validate_scenes.py videos/src/video{N}.py

# 2. Screenshot visual review — read every PNG
python video_utils/validate_scenes.py videos/src/video{N}.py --screenshots
# Then: Read videos/review/<stem>/*.png
```

**Workflow:**
1. Fast check → fix until `✓ No issues found`
2. Screenshot check → read every PNG, fix visual issues
3. Only build after both pass

#### 4c. TTS Generation

**Ask the user which TTS backend they want before generating audio.** If they have no preference, use Edge-TTS (free, zero config).

Four backends, all in `video_utils/`:

| Backend | Quality | Cost | Extra install | File |
|---------|---------|------|--------------|------|
| **Edge-TTS** (default) | Good | Free | None | `tts_edge.py` |
| **MiniMax** | Best | ~$0.04/min | `pip install httpx python-dotenv` + API key | `tts_minimax.py` |
| **Chatterbox** | Good + voice cloning | Free | NVIDIA GPU + `pip install chatterbox-tts faster-whisper` | `tts_local.py` |
| **OpenAI TTS** | Good | ~$0.06/min | `pip install openai` + API key | `tts_openai.py` |

```python
# Edge-TTS (default — free, no API key):
from video_utils.tts_edge import generate_and_save
timing = generate_and_save(SCENES, AUDIO_DIR, voice="en-US-GuyNeural")

# MiniMax (best quality, requires MINIMAX_API_KEY in .env):
from video_utils.tts_minimax import generate_and_save
timing = generate_and_save(SCENES, AUDIO_DIR, voice="English_expressive_narrator")

# Chatterbox (local, voice cloning, requires NVIDIA GPU):
from video_utils.tts_local import generate_and_save
timing = generate_and_save(SCENES, AUDIO_DIR, voice_ref="path/to/reference.wav")
```

All produce `durations.json` with sentence timing + cue timestamps.

#### 4d. Rendering

**Ask the user what resolution they want before rendering.** Default to 1080p 24fps if they have no preference.

| Flag | Resolution | Use case |
|------|-----------|----------|
| `-ql` | 480p | Fast preview / iteration |
| `-qm` | 720p | Draft review |
| `-qh` | 1080p (default) | Final output |
| `-qp` | 1440p | High-quality upload |

**Default (CPU)** — works on all platforms:
```bash
python -m manim render -qh --fps 24 --disable_caching videos/src/video{N}.py SceneName
```

**Optional speedup — parallel rendering** (create `fast_render.py` in project):
```python
from fast_render import parallel_render
parallel_render(MANIM_FILE, SCENE_ORDER, quality="-qh", fps=24)
```
Parallel rendering splits scenes across CPU cores. GPU (NVENC) encoding is optional but provides minimal speedup — the bottleneck is frame generation, not encoding.

#### 4e. Composition
```bash
# Mux video + audio per scene
ffmpeg -y -i video.mp4 -i audio.mp3 -c:v copy -c:a aac -b:a 192k -shortest out.mp4

# Concatenate scenes
ffmpeg -y -f concat -safe 0 -i list.txt -c copy final.mp4
```

#### 4f. Captions (SRT)

Our TTS pipeline already has exact sentence timing in `durations.json`. Generate SRT captions from it — no extra alignment needed:

```python
def srt_time(seconds):
    h, m = int(seconds // 3600), int((seconds % 3600) // 60)
    s, ms = int(seconds % 60), int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def generate_srt(durations_json, output_srt):
    timing = json.load(open(durations_json))
    idx, cumulative = 1, 0.0
    with open(output_srt, "w") as f:
        for key, scene_data in timing.items():
            if not isinstance(scene_data, dict) or "segments" not in scene_data:
                continue
            seg_offset = 0.0
            for seg in scene_data["segments"].values():
                for sent in seg.get("sentences", []):
                    t0 = cumulative + seg_offset + sent["start"]
                    t1 = cumulative + seg_offset + sent["end"]
                    f.write(f"{idx}\n{srt_time(t0)} --> {srt_time(t1)}\n{sent['text']}\n\n")
                    idx += 1
                seg_offset += seg["duration"] + 0.5
            cumulative += scene_data.get("scene_duration", seg_offset)
```

**Two ways to use captions:**

1. **Soft subtitles (recommended)** — generate `.srt` file alongside each video. Players (VLC, YouTube) load it automatically. Toggleable.

2. **Burned-in** — for platforms without soft sub support (Google Drive):
```bash
ffmpeg -y -i video.mp4 \
  -vf "subtitles=captions.srt:force_style='FontName=Arial,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,Outline=1,BorderStyle=4,BackColour=&H80000000,MarginV=8,MarginL=60,MarginR=60'" \
  -c:a copy output_with_captions.mp4
```

Key settings: FontSize=11 (small, non-intrusive), MarginV=8 (hugs bottom edge), semi-transparent background box.

### Step 5: Hand Off to User

Give the user the build command:
```bash
python -u videos/src/build_all.py
```

## Conventions

| Setting | Value |
|---------|-------|
| TTS (default) | Edge-TTS `en-US-GuyNeural` (free) |
| TTS (best quality) | MiniMax `speech-2.8-turbo` (requires API key) |
| TTS (local) | Chatterbox + faster-whisper (requires GPU) |
| Font | CMU Serif (strongly recommended; system default fallback) |
| Text wrapper | Always `CText()` not `Text()` |
| Cue markers | `{CUE_NAME}` inline in narration |
| Sentence gap | 350ms |
| Segment gap | 500ms |
| Render quality | `-qh --fps 24` (1080p 24fps) CPU |
| Background | `#1a1a2e` |
| Safe bounds | x: [-6.5, 6.5], y: [-3.5, 3.5] |
| Min font size | 24 for CText |

## Sync Workflow Summary

```
1. WRITE narration with {CUE} markers at visual event points
2. GENERATE TTS per-sentence → cue times estimated by character ratio → durations.json
3. MANIM reads cue times:
   - sync(scene, sk, "CUE", e)   → wait until cue (last resort)
   - until(sk, "CUE", e)         → available time → use as run_time
   - fill(scene, seg_dur, e)     → pad segment end (keep < 3s)
4. VALIDATE: fast check (0 issues) + screenshot check (read every PNG)
5. BUILD: TTS → render (CPU) → mux → compose
```
