"""SRT caption generation from durations.json.

Usage:
    from video_utils.captions import generate_srt
    generate_srt("audio/video1/durations.json", "output/video1.srt")
"""
import json


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_srt(durations_json: str, output_srt: str, segment_gap: float = 0.5) -> None:
    """Write an SRT file using the exact sentence timing already in durations.json.

    No extra forced-alignment needed — the TTS pipeline records per-sentence
    start/end offsets within each segment, and each segment has a duration.
    """
    with open(durations_json) as f:
        timing = json.load(f)

    idx = 1
    cumulative = 0.0
    with open(output_srt, "w") as out:
        for scene_data in timing.values():
            if not isinstance(scene_data, dict) or "segments" not in scene_data:
                continue
            seg_offset = 0.0
            for seg in scene_data["segments"].values():
                for sent in seg.get("sentences", []):
                    t0 = cumulative + seg_offset + sent["start"]
                    t1 = cumulative + seg_offset + sent["end"]
                    out.write(f"{idx}\n{_srt_time(t0)} --> {_srt_time(t1)}\n{sent['text']}\n\n")
                    idx += 1
                seg_offset += seg["duration"] + segment_gap
            cumulative += scene_data.get("scene_duration", seg_offset)
