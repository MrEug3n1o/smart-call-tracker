import os
from pathlib import Path


class Config:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GOOGLE_CREDS_FILE = "credentials.json"

    # Whisper settings
    WHISPER_MODEL = "base"
    WHISPER_DEVICE = "cpu"
    WHISPER_COMPUTE = "int8"

    # File system
    DOWNLOAD_DIR = Path("./audio_cache")

    @classmethod
    def ensure_directories(cls):
        cls.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
