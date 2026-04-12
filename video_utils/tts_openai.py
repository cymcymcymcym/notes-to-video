"""TTS utility: generate narration audio via OpenAI TTS API."""
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment

def get_client() -> OpenAI:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def generate_narration(
    text: str, output_path: str | Path,
    voice: str = "onyx", model: str = "tts-1-hd",
) -> float:
    client = get_client()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    response = client.audio.speech.create(model=model, voice=voice, input=text)
    response.write_to_file(str(output_path))
    audio = AudioSegment.from_mp3(str(output_path))
    duration = len(audio) / 1000.0
    print(f"  {output_path.name}: {duration:.1f}s ({len(text)} chars)")
    return duration

def concat_audio(files: list[str | Path], output_path: str | Path, gap_ms: int = 600):
    output_path = Path(output_path)
    combined = AudioSegment.empty()
    gap = AudioSegment.silent(duration=gap_ms)
    for i, f in enumerate(files):
        if i > 0:
            combined += gap
        combined += AudioSegment.from_mp3(str(f))
    combined.export(str(output_path), format="mp3")
    return len(combined) / 1000.0
