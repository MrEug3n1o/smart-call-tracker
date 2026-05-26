import logging
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

log = logging.getLogger(__name__)

class DriveService:
    def __init__(self, creds_file: str):
        scopes = ["https://www.googleapis.com/auth/drive.readonly"]
        creds = service_account.Credentials.from_service_account_file(creds_file, scopes=scopes)
        self.service = build("drive", "v3", credentials=creds)

    def list_audio_files(self, folder_id: str) -> list[dict]:
        query = (
            f"'{folder_id}' in parents "
            "and mimeType contains 'audio/' "
            "and trashed = false"
        )
        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        return results.get("files", [])

    def download_file(self, file_id: str, dest: Path) -> Path:
        if dest.exists():
            log.info("  already cached: %s", dest.name)
            return dest

        import io
        request = self.service.files().get_media(fileId=file_id)
        with open(dest, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        log.info("  downloaded: %s", dest.name)
        return dest
