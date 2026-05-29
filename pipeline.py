import logging
from config import Config
from utils.parser import parse_filename
from utils.services.drive_service import DriveService
from utils.services.sheets_service import SheetsService
from utils.services.transcription import TranscriptionService
from utils.services.analysis_service import AnalysisService, SCORE_KEYS

log = logging.getLogger(__name__)


class CallAnalyticsPipeline:
    def __init__(
        self,
        drive: DriveService,
        sheets: SheetsService,
        transcriber: TranscriptionService,
        analyzer: AnalysisService,
    ):
        self.drive = drive
        self.sheets = sheets
        self.transcriber = transcriber
        self.analyzer = analyzer

    # ------------------------------------------------------------------
    def process_file(self, file_meta: dict, sheet_id: str, tab: str = "Sheet1"):
        name    = file_meta["name"]
        file_id = file_meta["id"]
        log.info("Processing: %s", name)

        # 1 – parse filename
        meta = parse_filename(name)

        # 2 – download (cached)
        dest = Config.DOWNLOAD_DIR / name
        self.drive.download_file(file_id, dest)

        # 3 – transcribe (cached)
        transcript = self.transcriber.transcribe(dest)
        if not transcript.strip():
            log.warning("  empty transcript, skipping")
            return

        # 4 – AI analysis
        analysis = self.analyzer.analyze(transcript)
        score = sum(analysis.get(k, 0) for k in SCORE_KEYS)
        log.info("  score %d/%d | job: %s | result: %s",
                 score, len(SCORE_KEYS),
                 analysis.get("chosen_job", "—"),
                 analysis.get("final_result", "—"))

        # 5 – write row (ТЕПЕРЬ ПОЛУЧАЕМ И ДАННЫЕ СТРОКИ)
        row_num, row_data = self.sheets.append_row(sheet_id, meta, analysis, tab)

        # 6 – flag cells red if appointment was missed OR Top-100 not adhered to
        appointment_ok = bool(analysis.get("appointment_made", 0))
        top100_ok      = bool(analysis.get("top100_adhered", 0))

        if not appointment_ok or not top100_ok:
            # Вызываем новый метод для точечного окрашивания ячеек
            self.sheets.highlight_cells_red(sheet_id, row_num, row_data, tab)

            comment = analysis.get("comment", "").strip()
            if not comment:
                reasons = []
                if not appointment_ok:
                    reasons.append("не зроблено запис")
                if not top100_ok:
                    reasons.append("не дотримано інструкцій Топ-100")
                comment = "Увага: " + ", ".join(reasons) + "."

            self.sheets.add_note(sheet_id, row_num, comment, tab)

    # ------------------------------------------------------------------
    def run(self, folder_id: str, sheet_id: str, tab: str = "Sheet1"):
        self.sheets.ensure_header(sheet_id, tab)

        files = self.drive.list_audio_files(folder_id)
        log.info("Found %d audio file(s) in Drive folder", len(files))

        for f in files:
            try:
                self.process_file(f, sheet_id, tab)
            except Exception as exc:
                log.error("  FAILED %s: %s", f["name"], exc, exc_info=True)

        log.info("Done.")
