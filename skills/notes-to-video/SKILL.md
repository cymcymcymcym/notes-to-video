---
name: notes-to-video
description: Turn notes (LaTeX, PDF, or plain text) into 3Blue1Brown-style animated videos using Manim + TTS + ffmpeg. Use when the user wants to create an explainer video.
user-invocable: true
argument-hint: <source-file-or-topic>
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# 3b1b-Style Video Producer

Turn notes into 3Blue1Brown-style animated explainer videos.

**Input**: `$ARGUMENTS` — a source file path (`.tex`, `.pdf`, notes) or topic description.

## Environment Setup

**Required:** Python 3.10+, FFmpeg, `pip install manim edge-tts pydub`. LaTeX only if equations are used.

**FFmpeg per OS:** `apt install ffmpeg` (Linux) · `brew install ffmpeg` (macOS) · `choco install ffmpeg` or `winget install Gyan.FFmpeg` (Windows).

**Optional TTS extras** (install only the backend you'll use): MiniMax → `pip install httpx python-dotenv` + `MINIMAX_API_KEY` · Chatterbox (NVIDIA GPU) → `pip install chatterbox-tts faster-whisper torch` · OpenAI → `pip install openai` + `OPENAI_API_KEY`.

**Font (optional but recommended):** CMU Serif for authentic 3b1b look — `apt install fonts-cmu` (Linux) / `brew install --cask font-cmu-serif` (macOS) / [CTAN .otf](https://www.ctan.org/pkg/cm-unicode) (Windows). `CText()` falls back to system default if missing.

### Project Structure

Every video is a self-contained `<project>/` subfolder. Use this layout from day one so a repo with many explainers stays navigable:

```
final/                                 # THE DELIVERABLE — what users watch/share
  <project>/
    <project>.pdf                      # source paper, if applicable
    <project>.mp4                      # final video
    <project>.srt                      # soft captions (sidecar)
    <project>_captioned.mp4            # optional: burned-in captions variant

intermediate/                          # everything else (heavy; .gitignore by default)
  <project>/
    src/
      video_<project>.py               # Manim scenes
      part_<project>_narration.py      # narration with {CUE} markers
      generate_tts_<project>.py        # TTS runner
      build_<project>.py               # render + mux + caption
      assets/<project>/*.png           # extracted source figures (Step 1a)
    audio/video_<project>/             # TTS output + durations.json
    media/videos/video_<project>/      # manim render cache
    review/video_<project>/            # validator screenshots
    output/                            # per-scene muxed MP4s, concat.txt
    plan_<project>.md                  # scene-by-scene plan

video_utils/                           # shared helpers (bundled with the skill)
  manim_helpers.py                     # CText, colors, sync helpers
  tts_{edge,minimax,local,openai}.py   # 4 TTS backends with cue estimation
  validate_scenes.py                   # overlap / OOB / overflow / line-cross / screenshot checker
  captions.py                          # generate_srt(durations_json, output_srt)
```

**Why per-project subfolders from day one:**

- **`final/<project>/` is self-contained.** Paper PDF, video, and captions share the same slug — `vlc final/grpo/grpo.mp4` auto-loads `grpo.srt`. When the user asks "where's the video?", they open one folder.
- **Adding a second video is zero migration.** Just create another `final/<other>/` + `intermediate/<other>/`. No renaming, no moving. The moment the user builds video #2, the repo scales cleanly.
- **The slug ties everything together.** Pick a short name (`grpo`, `drifting`, `vae_intro`) and use it consistently: subfolder name, filename stem, and interpolated wherever the scripts hardcode a project name (`video_<project>.py`, `audio/video_<project>/`). Shared tooling discovers projects by scanning these slugs.

**For multi-topic repos** (e.g., many papers organized by subject), add a topic layer:
```
final/<topic>/<project>/
intermediate/<topic>/<project>/
```
Scripts keep working — each project subtree is self-contained, and relative paths (`Path(__file__).resolve().parents[1]`) still resolve to the project root regardless of how deeply nested.

**Don't flatten everything into one `videos/` folder.** When the user has three projects, a flat `videos/src/video1.py`, `video2.py`, `video3.py` with shared `audio/`, `media/`, `output/` directories interleaves projects and makes per-project cleanup impossible. Per-project subfolders prevent this from day one.

## Pipeline

### Step 1: Extract Content
Read the source material. Identify key concepts, flow, and dependencies.

### Checkpoint: Confirm Scope with User (MANDATORY)

**Before any expensive work — figure extraction, narration drafting, TTS, or rendering — confirm the video's shape with the user in one exchange.** These questions cost seconds to ask and prevent hours of rework if the defaults don't match intent. Do not proceed past this checkpoint until the user has answered all four.

Ask together:

1. **Resolution / frame rate.** Default is **1080p at 24 fps** (matches this skill's render config). Confirm or offer to override, e.g.:
   > "I'll render at 1080p, 24 fps. Good, or do you want something different (1440p, 4K, 30/60 fps)?"

2. **Target length + time allocation.** You've just read the source in Step 1, so propose a concrete total and a one-sentence breakdown across scenes, e.g.:
   > "Targeting ~12 minutes, roughly: 2 min motivation → 4 min the central mechanism → 3 min training setup → 2 min results → 1 min wrap. Does that work?"

3. **Caption format.** Default is soft subtitles (a separate `.srt` file next to the MP4 — toggleable in VLC/YouTube). Burned-in captions are permanently rendered into the video (needed for platforms like Google Drive that don't load sidecar `.srt`). Ask:
   > "Captions as a soft `.srt` next to the video (toggleable), or burned into the video (always visible, needed for Google Drive)? Or both?"

4. **TTS backend.** Default is **Edge-TTS** (free, no API key — recommended when quality is "good enough"). Alternatives: **MiniMax** (best quality, ~$0.04/min, needs `MINIMAX_API_KEY`), **Chatterbox** (voice cloning, free, needs NVIDIA GPU), **OpenAI** (~$0.06/min, needs `OPENAI_API_KEY`). Ask:
   > "I'll use Edge-TTS (free, no API key). Prefer MiniMax (best quality, cloud), Chatterbox (voice cloning, local GPU), or OpenAI (cloud)?"

The length and backend answers feed Step 2a (TTS WPM calibration — Chatterbox runs ~70% faster than the others, so the word-count target differs). The caption answer determines which branch of Step 4f runs. If the user revises length after audio has been generated, apply Step 2a's recovery procedure.

### Step 1a: Extract Source Figures (MANDATORY when source is a paper/document)

**When the source has figures, extract them and use them in the video.** The author's own Fig 2 is almost always a clearer vector diagram than anything you can animate, ablation tables are more persuasive than "FID 1.54" on a title card, and qualitative sample grids beat narration. Plan figure placement into `plan_<topic>.md` before writing narration — scenes fall into place around figure reveals, not around animated bars.

**Good candidates:** headline concept diagrams (Fig 1), architecture / vector illustrations, ablation tables, qualitative sample grids, 2D toy panels.

**Storage:** `intermediate/<project>/src/assets/<project>/` (co-located with scene code).

**Extraction — render-and-clip with PyMuPDF.** More reliable than `page.get_images()` (which misses vector overlays). Zoom ≥ 3.0 (~216 DPI) so figures stay crisp when scaled in Manim:

```python
import fitz
from pathlib import Path

PDF = "path/to/paper.pdf"
OUT = Path("intermediate/<project>/src/assets/<project>/"); OUT.mkdir(parents=True, exist_ok=True)
doc = fitz.open(PDF)

def render(page_num, out_name, clip, zoom=4.0):
    """page_num is 1-indexed. clip is fitz.Rect in PDF points.
    Letter page ≈ 612 × 792 pt; two-column ≈ 300 pt per column."""
    pix = doc[page_num - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    pix.save(str(OUT / out_name))

render(4, "fig2_illustration.png", fitz.Rect(55, 50, 305, 320))  # Fig 2, left column, top half
```

Iterate the clip box visually: render wide first, `Read` the PNG, tighten. Drop Algorithm boxes, adjacent tables, and body text — keep only the figure plus its caption line.

For purely-embedded images (sample grids saved as single PNGs), inspect first:
```python
for p, page in enumerate(doc):
    for i, img in enumerate(page.get_images()):
        b = doc.extract_image(img[0]); print(f"p{p+1}.img{i}: {b['width']}x{b['height']} ({b['ext']})")
```

**Using figures in Manim** — prefer `set_width` for safety (wide aspect ratios overflow if you set height). Always include a brief attribution caption:

```python
fig = ImageMobject("src/assets/<project>/fig2.png").set_width(config.frame_width - 1.4)
cap = CText("Figure 2 — Author et al. YEAR", font_size=18, color=DIMMED).next_to(fig, DOWN, buff=0.2)
self.play(FadeIn(fig, shift=UP * 0.15), run_time=1.4)
self.play(FadeIn(cap), run_time=0.6)
```

Treat figures as first-class scene elements: assign a `{FIG_N}` cue marker per figure reveal in narration.

### Step 2: Plan the Video Series
Write a plan to `intermediate/<project>/plan_<project>.md`.

### Step 2a: Calibrate narration length against TTS pace (MANDATORY)

**Before writing a single segment of narration, estimate how long the TTS will actually run.** Different backends speak at very different paces. Getting this wrong means generating 20+ minutes of audio, discovering the video is half the target length, rewriting narration, and regenerating — a one-hour round trip.

**Approximate speaking paces (words per minute) for each backend:**

| Backend | Typical WPM | Notes |
|---------|------|-------|
| Edge-TTS | **155-165** | Neutral, newscaster pace |
| OpenAI TTS | **160-175** | Similar to Edge, slightly faster on some voices |
| MiniMax | **150-170** | Varies by voice; expressive narrators run slower |
| Chatterbox | **255-280** | Notably faster than other backends — plan for it |

**Calibration:** backend was chosen in the Checkpoint. **Compute target word count = minutes × backend WPM.** For a 25-minute Chatterbox video, that's 25 × 270 = **~6750 words** of narration. For the same length on Edge-TTS, it's 25 × 160 = **~4000 words**. The gap is almost 2×.

If the user specifies "5+ minutes per problem" and you're using Chatterbox, each problem needs ~1350 words of narration, not ~750. Plan accordingly.

**When the estimate is off and you discover it only after generating TTS**, fix in this order before touching anything else:
1. Regenerate the WPM estimate from the actual `durations.json` (total words ÷ total seconds × 60).
2. Revise the narration to the correct target length.
3. Delete the old audio directory and rerun TTS — *don't* just append to the existing audio, durations and cue tables need to be recomputed from scratch.

A 20-second quick sanity check of an early segment is worth doing once you've committed to a backend — if your first segment clocks in at 15 seconds when you budgeted 30, stop and recalibrate before writing the rest.

### Step 3: Write Narration with Cue Markers
Write narration as a Python dict in `intermediate/<project>/src/part_<project>_narration.py`:
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

**3b1b scene design rules:**

- **Pacing:** `self.wait(1)` after every `self.play()`; `wait(2)` for complex ideas. Don't rush.
- **Layout:** titles `to_edge(UP)`, equations centered, diagrams center/lower. **Corner-park** derived results with `to_corner(UL)` to keep them visible while building the next idea. Guard wide equations with `.set_max_width(config.frame_width - 1)`. Split-screen compare with `Line(UP, DOWN).set_height(config.frame_height)`.
- **Font sizes:** hero 48–72, body math 42–48, labels 24–36 — much larger than typical.
- **Minimal on-screen text:** narration carries the explanation; the screen shows key terms and equations only.
- **Focus = dim everything else** (3b1b's #1 technique): `self.play(*[m.animate.set_fill(opacity=0.35) for m in others])`, restore with `set_fill(opacity=1)`. `Circumscribe(m)` for quick emphasis bursts.
- **Color:** `tex_to_color_map` works for **unique multi-char strings only** — `"x"` matches inside `\max`, `\text{}` and corrupts LaTeX. Use manual `eq[i].set_color()` for single letters. Palette: BLUE `#58C4DD`, YELLOW `#FFFF00`, TEAL `#5CD0B3`, RED `#FC6255`, PINK `#D147BD`, GREEN `#83C167`. Use `color_gradient([TEAL, RED], 5)` for sequences like x, x', x''.
- **Animation patterns:** sequential reveals via `LaggedStartMap(FadeIn, group, shift=0.5*UP, lag_ratio=0.3)` (never all-at-once); curved conceptual arrows (`Arrow(..., path_arc=-60*DEGREES)`); `FadeTransform(A, B)` for cross-type morphs (diagram → equation); `.space_out_submobjects(1.5)` to emphasize equation structure; semi-transparent rect backgrounds to group related items; `pointwise_become_partial` for progressive curve drawing.

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

#### 4a. Manim Scenes — `intermediate/<project>/src/video_<project>.py`

**Required boilerplate:**
```python
import sys, os
sys.path.insert(0, os.path.expanduser("~/tools"))  # where `npx notes-to-video` installs video_utils
from pathlib import Path
from video_utils.manim_helpers import *
from video_utils.manim_helpers import make_sync_helpers

# parents[1] resolves to intermediate/<project>/ regardless of topic nesting
DURATIONS_FILE = Path(__file__).resolve().parents[1] / "audio" / "video_<project>" / "durations.json"
seg_dur, cue_t, until, sync, fill = make_sync_helpers(DURATIONS_FILE)
```

This gives you `CText()` (kerning-fixed Text — **always use instead of `Text()`**), `MathTex` for equations, colors (`BG ACCENT GOLD TEAL SOFT_WHITE DIMMED`), and sync helpers (`seg_dur cue_t until sync fill`). CMU Serif is auto-used if installed.

`CText()` exists because Manim's Pango renderer has broken kerning at small font sizes ([#2844](https://github.com/ManimCommunity/manim/issues/2844)); it renders at 8× then scales down.

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
- **Derivation scenes**: morph in place with per-submobject `ReplacementTransform` (see Step 3). Don't stack equations vertically.
- **FadeOut before FadeIn** when reusing the same screen position.
- **Containers:** circle radius ≥ 1.1 for single words; RoundedRectangle ≥ 0.4 padding. `CText()` width can be surprising.
- **Arrow endpoints:** `.get_top()/.get_bottom()/.get_left()/.get_right()` — never route through text.
- **Safe bounds:** x ∈ [-6.5, 6.5], y ∈ [-3.5, 3.5]. Reserve y > 3.0 for titles.
- **Min font_size = 24** for CText.

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
python ~/tools/video_utils/validate_scenes.py intermediate/<project>/src/video_<project>.py

# 2. Screenshot visual review — read every PNG
python ~/tools/video_utils/validate_scenes.py intermediate/<project>/src/video_<project>.py --screenshots
# Then: Read intermediate/<project>/review/video_<project>/*.png
```

**Workflow:**
1. Fast check → fix until `✓ No issues found`
2. Screenshot check → read every PNG, fix visual issues
3. Only build after both pass

#### 4c. TTS Generation

Backend was chosen in Step 2a. All four live in `video_utils/` and write `intermediate/<project>/audio/video_<project>/durations.json` with sentence timing + cue timestamps.

| Backend | Quality | Cost | Extra install | Module |
|---------|---------|------|--------------|--------|
| **Edge-TTS** (default) | Good | Free | None | `tts_edge` |
| **MiniMax** | Best | ~$0.04/min | `httpx python-dotenv` + `MINIMAX_API_KEY` | `tts_minimax` |
| **Chatterbox** | Good + voice clone | Free | NVIDIA GPU + `chatterbox-tts faster-whisper` | `tts_local` |
| **OpenAI** | Good | ~$0.06/min | `openai` + `OPENAI_API_KEY` | `tts_openai` |

```python
from video_utils.tts_edge     import generate_and_save  # voice="en-US-GuyNeural"
from video_utils.tts_minimax  import generate_and_save  # voice="English_expressive_narrator"
from video_utils.tts_local    import generate_and_save  # voice_ref="reference.wav"
timing = generate_and_save(SCENES, AUDIO_DIR, voice=...)
```

#### 4d. Rendering

Resolution/fps were confirmed in the Checkpoint. Manim quality flags: `-ql` 480p (preview) · `-qm` 720p · `-qh` 1080p (default) · `-qp` 1440p.

```bash
# Run from intermediate/<project>/ so manim's media/ cache is per-project
cd intermediate/<project>
python -m manim render -qh --fps 24 --disable_caching src/video_<project>.py SceneName
```

**Speedup:** parallel rendering across CPU cores via a project-local `fast_render.py` (`parallel_render(MANIM_FILE, SCENE_ORDER, quality="-qh", fps=24)`). GPU (NVENC) encoding barely helps — the bottleneck is frame generation, not encoding.

#### 4e. Composition
```bash
# Mux video + audio per scene
ffmpeg -y -i video.mp4 -i audio.mp3 -c:v copy -c:a aac -b:a 192k -shortest out.mp4

# Concatenate scenes
ffmpeg -y -f concat -safe 0 -i list.txt -c copy final.mp4
```

#### 4f. Captions (SRT)

`durations.json` already has exact per-sentence timing — no forced alignment needed:

```python
from video_utils.captions import generate_srt
generate_srt("intermediate/<project>/audio/video_<project>/durations.json",
             "final/<project>/<project>.srt")
```

**Soft subs (recommended):** ship the `.srt` next to the MP4. Players (VLC, YouTube) load it automatically and it's toggleable.

**Burned-in** (for platforms without soft-sub support, e.g. Google Drive):
```bash
ffmpeg -y -i video.mp4 -vf "subtitles=captions.srt:force_style='FontName=Arial,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,Outline=1,BorderStyle=4,BackColour=&H80000000,MarginV=8,MarginL=60,MarginR=60'" -c:a copy output_with_captions.mp4
```
Key choices: small non-intrusive font, bottom-hugging margin, semi-transparent box.

### Step 5: Hand Off to User

Give the user the build command:
```bash
python -u intermediate/<project>/src/build_<project>.py
```

After the build completes, point the user to `final/<project>/` — everything they want to watch or share lives there:

```
final/<project>/
  <project>.pdf            # source paper (if any)
  <project>.mp4            # final video
  <project>.srt            # soft subtitles
  <project>_captioned.mp4  # burned-in variant, if they asked for one
```

They should never need to look inside `intermediate/<project>/`. The build script writes both directories; that's by design.

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

