import sys
import argparse
import logging
from config import Config
from utils.services.drive_service import DriveService
from utils.services.sheets_service import SheetsService
from utils.services.transcription import TranscriptionService
from utils.services.analysis_service import AnalysisService
from pipeline import CallAnalyticsPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Call analytics pipeline")
    parser.add_argument("--folder-id", required=True, help="Google Drive folder ID")
    parser.add_argument("--sheet-id", required=True, help="Google Sheets spreadsheet ID")
    parser.add_argument("--tab", default="Sheet1", help="Sheet tab name")
    args = parser.parse_args()

    if not Config.GEMINI_API_KEY:
        sys.exit("ERROR: set GEMINI_API_KEY environment variable")

    Config.ensure_directories()

    # Initialize Services (Dependency Injection)
    drive_service = DriveService(Config.GOOGLE_CREDS_FILE)
    sheets_service = SheetsService(Config.GOOGLE_CREDS_FILE)

    transcription_service = TranscriptionService(
        model_size=Config.WHISPER_MODEL,
        device=Config.WHISPER_DEVICE,
        compute_type=Config.WHISPER_COMPUTE
    )

    analysis_service = AnalysisService(Config.GEMINI_API_KEY)

    # Initialize Pipeline
    pipeline = CallAnalyticsPipeline(
        drive=drive_service,
        sheets=sheets_service,
        transcriber=transcription_service,
        analyzer=analysis_service
    )

    # Execute
    pipeline.run(folder_id=args.folder_id, sheet_id=args.sheet_id, tab=args.tab)
    log.info("Done.")


if __name__ == "__main__":
    main()
