import logging
from pathlib import Path
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

class TranscriptionService:
    def __init__(self, model_size: str, device: str, compute_type: str):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: Path) -> str:
        txt_path = audio_path.with_suffix(".txt")
        if txt_path.exists():
            log.info("  transcript cached: %s", txt_path.name)
            return txt_path.read_text(encoding="utf-8")

        log.info("  transcribing %s …", audio_path.name)
        segments, _ = self.model.transcribe(str(audio_path), beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments)

        txt_path.write_text(text, encoding="utf-8")
        log.info("  saved transcript: %s", txt_path.name)
        return text
