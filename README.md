# make-video

Turn notes (LaTeX, PDF, or plain text) into animated explainer videos in the style popularized by 3Blue1Brown — using Manim, TTS, and ffmpeg.

A [Claude Code](https://claude.com/claude-code) skill that handles the full pipeline: content extraction, narration writing with cue markers, Manim scene generation with audio-video sync, validation, rendering, and composition.

## Features

- **Notes to video pipeline** — feed in LaTeX, PDF, or plain text notes, get animated explainer videos
- **Audio-video sync** — cue-based system that synchronizes Manim animations to narration timestamps
- **CText kerning fix** — workaround for Manim's broken Pango kerning ([manim #2844](https://github.com/ManimCommunity/manim/issues/2844))
- **4 TTS backends** — Edge-TTS (free, default), MiniMax (best quality), Chatterbox (local + voice cloning), OpenAI
- **Scene validator** — catches text overlaps, out-of-bounds elements, text overflow, and line-through-text issues before rendering
- **Cross-platform** — Linux, macOS, Windows

## Install

```bash
/plugin marketplace add cymcymcymcym/make-video
/plugin install make-video@make-video-marketplace
```

Or manually: clone this repo and copy `skills/make-video/` to `~/.claude/skills/` and `video_utils/` to your project root.

## Quick Start

1. Install dependencies:
   ```bash
   pip install manim edge-tts pydub
   ```

2. In Claude Code, run:
   ```
   /make-video my_notes.tex
   ```

3. Claude will:
   - Extract key concepts from your notes
   - Write a narration script with cue markers
   - Generate Manim scenes synced to the narration
   - Validate all scenes for visual issues
   - Hand you the build command

## TTS Options

| Backend | Quality | Cost | Requirements |
|---------|---------|------|-------------|
| **Edge-TTS** (default) | Good | Free | None |
| **MiniMax** | Best | ~$0.04/min | API key |
| **Chatterbox** | Good + voice cloning | Free | NVIDIA GPU |
| **OpenAI TTS** | Good | ~$0.06/min | API key |

## How It Works

The core innovation is the **cue-based audio-video sync system**:

1. Narration is written with `{CUE_NAME}` markers at visual event points
2. TTS generates per-sentence audio and estimates cue positions by character ratio
3. Manim scenes read cue timestamps and sync animations accordingly
4. `until()` fills gaps with slow animations, `sync()` waits for exact cue times

This produces smooth, naturally-paced videos where animations fire exactly when the narrator says the relevant keyword.

## Project Structure

```
video_utils/              # Bundled library
  manim_helpers.py        # CText, colors, sync helpers
  tts_edge.py            # Edge-TTS (free, default)
  tts_minimax.py         # MiniMax TTS (cloud)
  tts_local.py           # Chatterbox + Whisper (local)
  tts_openai.py          # OpenAI TTS (cloud)
  validate_scenes.py     # Scene validator

skills/make-video/
  SKILL.md               # Claude Code skill definition
```

## License

MIT
