"""Sentence-level TTS with word-ratio cue estimation (v2).

Key improvements over v1:
- TTS generates FULL SENTENCES (no splitting at cues → no micro-pauses)
- Cue positions estimated by word ratio within the sentence
- Returns both sentence timing AND precise cue timestamps
"""
import asyncio
import json
import re
from pathlib import Path

import edge_tts
from pydub import AudioSegment

VOICE = "en-US-GuyNeural"
GAP_MS = 350  # silence between sentences (smaller = more natural)
SCENE_GAP_MS = 500  # silence between segments


async def _gen_one(text: str, outpath: str, voice: str = VOICE) -> float:
    communicate = edge_tts.Communicate(text, voice)
    with open(outpath, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
    audio = AudioSegment.from_mp3(outpath)
    return len(audio) / 1000.0


def _split_sentences(text: str) -> list[str]:
    """Split clean text (no cue markers) into sentences."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    merged = []
    buf = ""
    for s in raw:
        buf = (buf + " " + s).strip() if buf else s
        if len(buf) >= 25 or s == raw[-1]:
            merged.append(buf)
            buf = ""
    if buf:
        merged.append(buf)
    return merged


def _extract_cues(text: str) -> tuple[str, list[dict]]:
    """Extract {CUE_NAME} markers from text.
    Returns (clean_text, [{"name": "CUE", "char_pos": 42}, ...])
    """
    cues = []
    clean = ""
    i = 0
    while i < len(text):
        if text[i] == '{':
            end = text.index('}', i)
            cue_name = text[i+1:end]
            cues.append({"name": cue_name, "char_pos": len(clean)})
            i = end + 1
            # Skip whitespace after cue
            while i < len(text) and text[i] == ' ':
                i += 1
        else:
            clean += text[i]
            i += 1
    return clean.strip(), cues


def _estimate_cue_time(cue_char_pos: int, sentence_text: str,
                       sentence_start_in_text: int, sentence_audio_start: float,
                       sentence_duration: float) -> float | None:
    """Estimate when a cue fires within a sentence using character ratio."""
    sentence_end_in_text = sentence_start_in_text + len(sentence_text)

    if not (sentence_start_in_text <= cue_char_pos <= sentence_end_in_text):
        return None  # cue not in this sentence

    # Position within sentence (0.0 to 1.0)
    offset_in_sentence = cue_char_pos - sentence_start_in_text
    ratio = offset_in_sentence / max(len(sentence_text), 1)

    # Clamp ratio slightly -- speech doesn't start at t=0 exactly
    ratio = max(0.0, min(ratio, 0.95))

    return sentence_audio_start + ratio * sentence_duration


def generate_segment(seg_key: str, narration: str, audio_dir: Path,
                     voice: str = VOICE) -> dict:
    """Generate TTS for one segment with cue estimation.

    Args:
        seg_key: e.g. "s2_seg1"
        narration: text with optional {CUE_NAME} markers
        audio_dir: output directory
        voice: edge-tts voice

    Returns:
        {
            "duration": float,
            "sentences": [{"text", "start", "end", "duration"}, ...],
            "cues": {"CUE_NAME": float_seconds, ...},
            "file": str
        }
    """
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Extract cues and get clean text
    clean_text, cues = _extract_cues(narration)
    sentences = _split_sentences(clean_text)

    # Generate TTS per sentence
    sentence_data = []
    seg_audio = AudioSegment.empty()
    gap = AudioSegment.silent(duration=GAP_MS)
    cumulative = 0.0

    # Track character position in clean text for cue mapping
    char_cursor = 0

    for i, sent in enumerate(sentences):
        sent_file = audio_dir / f"{seg_key}_s{i}.mp3"
        if sent_file.exists():
            dur = len(AudioSegment.from_mp3(str(sent_file))) / 1000.0
        else:
            dur = asyncio.run(_gen_one(sent, str(sent_file), voice))

        if i > 0:
            seg_audio += gap
            cumulative += GAP_MS / 1000.0

        start = cumulative
        seg_audio += AudioSegment.from_mp3(str(sent_file))
        cumulative += dur

        # Find where this sentence starts in clean_text
        sent_start = clean_text.find(sent, char_cursor)
        if sent_start == -1:
            sent_start = char_cursor  # fallback

        sentence_data.append({
            "text": sent,
            "start": round(start, 3),
            "end": round(cumulative, 3),
            "duration": round(dur, 3),
            "_char_start": sent_start,
        })
        char_cursor = sent_start + len(sent)

        print(f"    [{start:5.1f}s-{cumulative:5.1f}s] {sent[:65]}")

    # Estimate cue times using character ratios
    cue_times = {}
    for cue in cues:
        for sd in sentence_data:
            t = _estimate_cue_time(
                cue["char_pos"], sd["text"],
                sd["_char_start"], sd["start"], sd["duration"]
            )
            if t is not None:
                cue_times[cue["name"]] = round(t, 3)
                break
        else:
            # Cue between sentences -- use the start of the next sentence
            for sd in sentence_data:
                if sd["_char_start"] >= cue["char_pos"]:
                    cue_times[cue["name"]] = sd["start"]
                    break

    if cue_times:
        print(f"    Cues: {cue_times}")

    # Export segment audio
    seg_file = audio_dir / f"{seg_key}.mp3"
    seg_audio.export(str(seg_file), format="mp3")

    # Clean up internal keys
    for sd in sentence_data:
        del sd["_char_start"]

    return {
        "duration": round(len(seg_audio) / 1000.0, 3),
        "sentences": sentence_data,
        "cues": cue_times,
        "file": str(seg_file),
    }


def generate_scene(scene_name: str, segments: dict[str, str],
                   audio_dir: Path, voice: str = VOICE) -> dict:
    """Generate TTS for all segments of a scene."""
    audio_dir = Path(audio_dir)
    scene_audio = AudioSegment.empty()
    scene_gap = AudioSegment.silent(duration=SCENE_GAP_MS)

    seg_results = {}
    for i, (seg_key, narration) in enumerate(segments.items()):
        print(f"  {seg_key}:")
        result = generate_segment(seg_key, narration, audio_dir, voice)

        if i > 0:
            scene_audio += scene_gap

        seg_audio = AudioSegment.from_mp3(result["file"])
        scene_audio += seg_audio
        seg_results[seg_key] = result

    scene_file = audio_dir / f"{scene_name}.mp3"
    scene_audio.export(str(scene_file), format="mp3")

    return {
        "scene_duration": round(len(scene_audio) / 1000.0, 3),
        "scene_file": str(scene_file),
        "segments": seg_results,
    }


def generate_and_save(scenes: dict, audio_dir: Path,
                      voice: str = VOICE) -> dict:
    """Generate TTS for all scenes and save durations.json."""
    audio_dir = Path(audio_dir)
    all_timing = {}
    flat_seg = {}

    for scene_name, scene_data in scenes.items():
        print(f"\n=== {scene_name} ===")
        result = generate_scene(scene_name, scene_data["segments"],
                                audio_dir, voice)
        all_timing[scene_name] = result
        for sk, sd in result["segments"].items():
            flat_seg[sk] = sd["duration"]

    all_timing["segments"] = flat_seg
    with open(audio_dir / "durations.json", "w") as f:
        json.dump(all_timing, f, indent=2)
    return all_timing
