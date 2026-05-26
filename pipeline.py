import logging
from config import Config
from utils.parser import parse_filename
from utils.services.drive_service import DriveService
from utils.services.sheets_service import SheetsService
from utils.services.transcription import TranscriptionService
from utils.services.analysis_service import AnalysisService

log = logging.getLogger(__name__)


class CallAnalyticsPipeline:
    def __init__(
            self,
            drive: DriveService,
            sheets: SheetsService,
            transcriber: TranscriptionService,
            analyzer: AnalysisService
    ):
        self.drive = drive
        self.sheets = sheets
        self.transcriber = transcriber
        self.analyzer = analyzer

    def process_file(self, file_meta: dict, sheet_id: str):
        name = file_meta["name"]
        file_id = file_meta["id"]
        log.info("Processing: %s", name)

        meta = parse_filename(name)

        dest = Config.DOWNLOAD_DIR / name
        self.drive.download_file(file_id, dest)

        transcript = self.transcriber.transcribe(dest)
        if not transcript.strip():
            log.warning("  empty transcript, skipping")
            return

        analysis = self.analyzer.analyze(transcript)
        log.info("  analysis: %s", analysis)

        row_num = self.sheets.append_row(sheet_id, meta, analysis)

        if not analysis.get("professionalism_ok", True):
            self.sheets.highlight_row_red(sheet_id, row_num)
            comment = analysis.get("comment", "Manager flagged as unprofessional")
            self.sheets.add_note(sheet_id, row_num, col_index=11, note=comment)

        log.info("  → row %d written ✓", row_num)

    def run(self, folder_id: str, sheet_id: str, tab: str = "Sheet1"):
        self.sheets.ensure_header(sheet_id, tab)

        files = self.drive.list_audio_files(folder_id)
        log.info("Found %d audio file(s) in Drive folder", len(files))

        for f in files:
            try:
                self.process_file(f, sheet_id)
            except Exception as exc:
                log.error("  FAILED %s: %s", f["name"], exc)
