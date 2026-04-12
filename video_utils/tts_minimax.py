"""MiniMax TTS with sentence-level generation and cue estimation.

High quality cloud TTS. Generates per-sentence audio, estimates cue positions
by character ratio within sentences (same approach as tts_edge.py).

Usage:
    from video_utils.tts_minimax import generate_and_save
    timing = generate_and_save(SCENES, AUDIO_DIR, voice="English_expressive_narrator")
"""
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv()  # loads .env from project root or working directory

API_KEY = os.environ.get("MINIMAX_API_KEY", "")
GROUP_ID = os.environ.get("MINIMAX_GROUP_ID", "")
MODEL = "speech-2.8-turbo"
VOICE = "English_expressive_narrator"
GAP_MS = 350
SEG_GAP_MS = 500


def _generate_sentence(text: str, outpath: Path, voice: str = VOICE) -> float:
    """Generate one sentence with MiniMax sync API. Returns duration in seconds."""
    outpath = Path(outpath)
    outpath.parent.mkdir(parents=True, exist_ok=True)

    resp = requests.post(
        f"https://api.minimax.io/v1/t2a_v2?GroupId={GROUP_ID}",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "text": text,
            "voice_setting": {"voice_id": voice, "speed": 1.0, "vol": 1.0, "pitch": 0},
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
        },
    )
    data = resp.json()
    if "data" not in data or "audio" not in data.get("data", {}):
        raise RuntimeError(f"MiniMax API error: {data}")

    audio_bytes = bytes.fromhex(data["data"]["audio"])
    with open(outpath, "wb") as f:
        f.write(audio_bytes)

    audio = AudioSegment.from_mp3(str(outpath))
    return len(audio) / 1000.0


def _split_sentences(text: str) -> list[str]:
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


def _estimate_cue_time(cue_char_pos, sentence_text, sentence_start_in_text,
                       sentence_audio_start, sentence_duration):
    sentence_end_in_text = sentence_start_in_text + len(sentence_text)
    if not (sentence_start_in_text <= cue_char_pos <= sentence_end_in_text):
        return None
    offset = cue_char_pos - sentence_start_in_text
    ratio = max(0.0, min(offset / max(len(sentence_text), 1), 0.95))
    return sentence_audio_start + ratio * sentence_duration


def generate_segment(seg_key: str, narration: str, audio_dir: Path,
                     voice: str = VOICE) -> dict:
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    clean_text, cues = _extract_cues(narration)
    sentences = _split_sentences(clean_text)

    sentence_data = []
    seg_audio = AudioSegment.empty()
    gap = AudioSegment.silent(duration=GAP_MS)
    cumulative = 0.0
    char_cursor = 0

    for i, sent in enumerate(sentences):
        sent_file = audio_dir / f"{seg_key}_s{i}.mp3"
        if sent_file.exists():
            dur = len(AudioSegment.from_mp3(str(sent_file))) / 1000.0
        else:
            dur = _generate_sentence(sent, sent_file, voice)

        if i > 0:
            seg_audio += gap
            cumulative += GAP_MS / 1000.0

        start = cumulative
        seg_audio += AudioSegment.from_mp3(str(sent_file))

        sent_start = clean_text.find(sent, char_cursor)
        if sent_start == -1:
            sent_start = char_cursor

        cumulative += dur
        sentence_data.append({
            "text": sent, "start": round(start, 3), "end": round(cumulative, 3),
            "duration": round(dur, 3), "_char_start": sent_start,
        })
        char_cursor = sent_start + len(sent)
        print(f"    [{start:5.1f}s-{cumulative:5.1f}s] {sent[:65]}")

    # Estimate cue times
    cue_times = {}
    for cue in cues:
        for sd in sentence_data:
            t = _estimate_cue_time(cue["char_pos"], sd["text"], sd["_char_start"],
                                   sd["start"], sd["duration"])
            if t is not None:
                cue_times[cue["name"]] = round(t, 3)
                break
        else:
            for sd in sentence_data:
                if sd["_char_start"] >= cue["char_pos"]:
                    cue_times[cue["name"]] = sd["start"]
                    break

    if cue_times:
        print(f"    Cues: {cue_times}")

    seg_file = audio_dir / f"{seg_key}.mp3"
    seg_audio.export(str(seg_file), format="mp3")

    clean_sentences = [{k: v for k, v in sd.items() if not k.startswith("_")}
                       for sd in sentence_data]

    return {
        "duration": round(len(seg_audio) / 1000.0, 3),
        "sentences": clean_sentences, "cues": cue_times, "file": str(seg_file),
    }


def generate_scene(scene_name: str, segments: dict[str, str],
                   audio_dir: Path, voice: str = VOICE) -> dict:
    audio_dir = Path(audio_dir)
    scene_audio = AudioSegment.empty()
    scene_gap = AudioSegment.silent(duration=SEG_GAP_MS)

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
        "scene_file": str(scene_file), "segments": seg_results,
    }


def generate_and_save(scenes: dict, audio_dir: Path, voice: str = VOICE) -> dict:
    audio_dir = Path(audio_dir)
    all_timing = {}
    flat_seg = {}

    for scene_name, scene_data in scenes.items():
        print(f"\n=== {scene_name} ===")
        result = generate_scene(scene_name, scene_data["segments"], audio_dir, voice)
        all_timing[scene_name] = result
        for sk, sd in result["segments"].items():
            flat_seg[sk] = sd["duration"]

    all_timing["segments"] = flat_seg
    with open(audio_dir / "durations.json", "w") as f:
        json.dump(all_timing, f, indent=2)
    return all_timing
