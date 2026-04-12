"""Fully local TTS pipeline: Chatterbox + faster-whisper word timestamps.

No API keys, no cloud. Generates high-quality speech with exact word-level
timestamps for Manim animation sync.

Usage:
    from video_utils.tts_local import generate_and_save
    timing = generate_and_save(SCENES, AUDIO_DIR)
"""
import json
import re
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from pydub import AudioSegment

GAP_MS = 350   # silence between sentences
SEG_GAP_MS = 500  # silence between segments within a scene


def _get_tts_model():
    """Load Chatterbox TTS model (cached after first call)."""
    if not hasattr(_get_tts_model, "_model"):
        from chatterbox.tts import ChatterboxTTS
        print("  Loading Chatterbox TTS model...")
        t0 = time.time()
        _get_tts_model._model = ChatterboxTTS.from_pretrained(device="cuda")
        print(f"  Model loaded in {time.time()-t0:.1f}s")
    return _get_tts_model._model


def _get_whisper_model():
    """Load faster-whisper model (cached after first call)."""
    if not hasattr(_get_whisper_model, "_model"):
        from faster_whisper import WhisperModel
        print("  Loading faster-whisper model...")
        _get_whisper_model._model = WhisperModel("base", device="cuda",
                                                  compute_type="float16")
    return _get_whisper_model._model


def _generate_sentence(text: str, outpath: Path,
                       voice_ref: str | None = None) -> float:
    """Generate one sentence with Chatterbox. Returns duration in seconds.
    voice_ref: optional path to a .wav/.mp3 file to clone voice from.
    """
    model = _get_tts_model()
    kwargs = {}
    if voice_ref:
        kwargs["audio_prompt_path"] = voice_ref
    wav = model.generate(text, **kwargs)
    audio_np = wav.squeeze().cpu().numpy()
    sf.write(str(outpath), audio_np, model.sr)
    return len(audio_np) / model.sr


def _get_word_timestamps(audio_path: str) -> list[dict]:
    """Get word-level timestamps from audio using faster-whisper."""
    model = _get_whisper_model()
    segments, _ = model.transcribe(str(audio_path), word_timestamps=True)
    words = []
    for seg in segments:
        for w in seg.words:
            words.append({
                "word": w.word.strip(),
                "start": round(w.start, 3),
                "end": round(w.end, 3),
            })
    return words


def _split_sentences(text: str) -> list[str]:
    """Split into sentences, merge short ones."""
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
    """Extract {CUE_NAME} markers. Returns (clean_text, cues_with_char_positions)."""
    cues = []
    clean = ""
    i = 0
    while i < len(text):
        if text[i] == '{':
            end = text.index('}', i)
            cues.append({"name": text[i+1:end], "char_pos": len(clean)})
            i = end + 1
            while i < len(text) and text[i] == ' ':
                i += 1
        else:
            clean += text[i]
            i += 1
    return clean.strip(), cues


def _match_cue_to_word(cue_char_pos: int, clean_text: str,
                       sentence_text: str, sentence_char_start: int,
                       sentence_words: list[dict]) -> float | None:
    """Find the exact word timestamp for a cue position using whisper data."""
    sent_end = sentence_char_start + len(sentence_text)
    if not (sentence_char_start <= cue_char_pos <= sent_end):
        return None

    # Character offset within this sentence
    offset = cue_char_pos - sentence_char_start
    # Find the word at this offset
    char_cursor = 0
    for w in sentence_words:
        word_len = len(w["word"]) + 1  # +1 for space
        if char_cursor + word_len >= offset:
            return w["start"]
        char_cursor += word_len

    # Fallback: return start of sentence
    return sentence_words[0]["start"] if sentence_words else None


def generate_segment(seg_key: str, narration: str, audio_dir: Path,
                     voice_ref: str | None = None) -> dict:
    """Generate TTS for one segment with word-level cue timestamps.

    Returns: {"duration", "sentences": [...], "cues": {"CUE": time}, "file"}
    """
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    clean_text, cues = _extract_cues(narration)
    sentences = _split_sentences(clean_text)

    sentence_data = []
    all_sentence_words = []  # whisper words per sentence, with global offsets
    seg_audio = AudioSegment.empty()
    gap = AudioSegment.silent(duration=GAP_MS)
    cumulative = 0.0
    char_cursor = 0

    for i, sent in enumerate(sentences):
        sent_file = audio_dir / f"{seg_key}_s{i}.wav"

        if sent_file.exists():
            dur = len(AudioSegment.from_file(str(sent_file))) / 1000.0
        else:
            dur = _generate_sentence(sent, sent_file, voice_ref=voice_ref)

        if i > 0:
            seg_audio += gap
            cumulative += GAP_MS / 1000.0

        start = cumulative
        seg_audio += AudioSegment.from_file(str(sent_file))

        # Get word timestamps for this sentence
        words = _get_word_timestamps(str(sent_file))
        # Offset word timestamps to global segment time
        global_words = []
        for w in words:
            gw = {**w, "start": round(w["start"] + start, 3),
                       "end": round(w["end"] + start, 3)}
            global_words.append(gw)

        sent_char_start = clean_text.find(sent, char_cursor)
        if sent_char_start == -1:
            sent_char_start = char_cursor

        cumulative += dur
        sentence_data.append({
            "text": sent,
            "start": round(start, 3),
            "end": round(cumulative, 3),
            "duration": round(dur, 3),
            "_char_start": sent_char_start,
            "_words": global_words,
        })
        char_cursor = sent_char_start + len(sent)

        print(f"    [{start:5.1f}s-{cumulative:5.1f}s] {sent[:60]}")

    # Match cues to exact word timestamps
    cue_times = {}
    for cue in cues:
        for sd in sentence_data:
            # Try word-level match first
            t = _match_cue_to_word(
                cue["char_pos"], clean_text,
                sd["text"], sd["_char_start"], sd["_words"]
            )
            if t is not None:
                cue_times[cue["name"]] = round(t, 3)
                break
        else:
            # Fallback: start of next sentence after cue position
            for sd in sentence_data:
                if sd["_char_start"] >= cue["char_pos"]:
                    cue_times[cue["name"]] = sd["start"]
                    break

    if cue_times:
        print(f"    Cues: {cue_times}")

    # Export concatenated segment audio as mp3
    seg_file = audio_dir / f"{seg_key}.mp3"
    seg_audio.export(str(seg_file), format="mp3")

    # Clean internal keys from output
    clean_sentences = []
    for sd in sentence_data:
        clean_sentences.append({
            k: v for k, v in sd.items() if not k.startswith("_")
        })

    return {
        "duration": round(len(seg_audio) / 1000.0, 3),
        "sentences": clean_sentences,
        "cues": cue_times,
        "file": str(seg_file),
    }


def generate_scene(scene_name: str, segments: dict[str, str],
                   audio_dir: Path, voice_ref: str | None = None) -> dict:
    """Generate TTS for all segments of a scene."""
    audio_dir = Path(audio_dir)
    scene_audio = AudioSegment.empty()
    scene_gap = AudioSegment.silent(duration=SEG_GAP_MS)

    seg_results = {}
    for i, (seg_key, narration) in enumerate(segments.items()):
        print(f"  {seg_key}:")
        result = generate_segment(seg_key, narration, audio_dir, voice_ref=voice_ref)
        if i > 0:
            scene_audio += scene_gap
        scene_audio += AudioSegment.from_mp3(result["file"])
        seg_results[seg_key] = result

    scene_file = audio_dir / f"{scene_name}.mp3"
    scene_audio.export(str(scene_file), format="mp3")

    return {
        "scene_duration": round(len(scene_audio) / 1000.0, 3),
        "scene_file": str(scene_file),
        "segments": seg_results,
    }


def generate_and_save(scenes: dict, audio_dir: Path,
                      voice_ref: str | None = None) -> dict:
    """Generate TTS for all scenes. Save durations.json."""
    audio_dir = Path(audio_dir)
    all_timing = {}
    flat_seg = {}

    for scene_name, scene_data in scenes.items():
        print(f"\n=== {scene_name} ===")
        result = generate_scene(scene_name, scene_data["segments"], audio_dir,
                               voice_ref=voice_ref)
        all_timing[scene_name] = result
        for sk, sd in result["segments"].items():
            flat_seg[sk] = sd["duration"]

    all_timing["segments"] = flat_seg
    with open(audio_dir / "durations.json", "w") as f:
        json.dump(all_timing, f, indent=2)

    # Free GPU memory
    if hasattr(_get_tts_model, "_model"):
        del _get_tts_model._model
        torch.cuda.empty_cache()

    return all_timing
