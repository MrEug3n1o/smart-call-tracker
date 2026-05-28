import re
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from utils.services.analysis_service import SCORE_KEYS

log = logging.getLogger(__name__)

# Column index (0-based) of the "Comment" column – used for cell notes
_COMMENT_COL_INDEX = 18   # columns A-S → 0-18


class SheetsService:
    SHEET_HEADERS = [
        "Дата",                              # A  – Date
        "Тип дзвінку / Причина",             # B  – Call Type / Reason
        "Номер телефону",                    # C  – Phone Number
        "Філія / Відділення",                # D  – Branch / Affiliate
        "Ім'я менеджера",                    # E  – Manager Name
        "Привітання",                        # F  – Greeting
        "Відомий кузов авто",                # G  – Car Body Known
        "Відомий рік авто",                  # H  – Car Year Known
        "Відомий пробіг авто",               # I  – Car Mileage Known
        "Запропоновано комплексну діагностику",  # J – Comprehensive Diagnostics Proposed
        "Запитано про попередні роботи",     # K  – Prior Work History Asked
        "Запис / Завершення дзвінка",        # L  – Appointment Made / End of Call
        "Обрана робота / Топ-100",           # M  – Chosen Job / Work from Top-100
        "Дотримання інструкцій Топ-100",     # N  – Adhered to Top-100 Instructions
        "Рекомендації по Топ-100",           # O  – Recommendations for Top-100 Jobs
        "Фінальний результат",               # P  – Final Result
        "Оцінка / Бали",                     # Q  – Score / Evaluation (sum)
        "Запчастини",                        # R  – Spare Parts
        "Коментар",                          # S  – Comment
    ]

    # Soft red for flagged rows
    _RED = {"red": 0.95, "green": 0.6, "blue": 0.6}

    def __init__(self, creds_file: str):
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = service_account.Credentials.from_service_account_file(
            creds_file, scopes=scopes
        )
        self.service = build("sheets", "v4", credentials=creds)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    def ensure_header(self, sheet_id: str, tab: str = "Sheet1"):
        result = self.service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{tab}!A1:Z1"
        ).execute()

        if not result.get("values"):
            self.service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{tab}!A1",
                valueInputOption="RAW",
                body={"values": [self.SHEET_HEADERS]},
            ).execute()
            log.info("  header row written")

    # ------------------------------------------------------------------
    # Append one data row; returns the 1-based row index written
    # ------------------------------------------------------------------
    def append_row(self, sheet_id: str, meta: dict, analysis: dict,
                   tab: str = "Sheet1") -> int:
        score = sum(analysis.get(k, 0) for k in SCORE_KEYS)

        row = [
            meta.get("date", ""),                          # A Date
            analysis.get("call_type", "Вхідний дзвінок"), # B Call Type
            meta.get("phone", ""),                         # C Phone
            analysis.get("branch", ""),                    # D Branch
            analysis.get("manager_name", ""),              # E Manager
            analysis.get("greeting", 0),                   # F Greeting
            analysis.get("body_known", 0),                 # G Body
            analysis.get("year_known", 0),                 # H Year
            analysis.get("mileage_known", 0),              # I Mileage
            analysis.get("diagnostics", 0),                # J Diagnostics
            analysis.get("history_asked", 0),              # K History
            analysis.get("appointment_made", 0),           # L Appointment
            analysis.get("chosen_job", "інший варіант"),   # M Job
            analysis.get("top100_adhered", 0),             # N Top-100 adhered
            analysis.get("top100_recommended", 0),         # O Top-100 recommended
            analysis.get("final_result", ""),              # P Final result
            score,                                         # Q Total score
            analysis.get("spare_parts", ""),               # R Spare parts
            analysis.get("comment", ""),                   # S Comment
        ]

        resp = self.service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        updated = resp["updates"]["updatedRange"]          # e.g. Sheet1!A5:S5
        row_num = int(re.search(r"(\d+):", updated.split("!")[-1]).group(1))
        log.info("  → row %d written (score %d/%d)", row_num, score, len(SCORE_KEYS))
        return row_num

    # ------------------------------------------------------------------
    # Conditional formatting helpers
    # ------------------------------------------------------------------
    def highlight_row_red(self, sheet_id: str, row_num: int,
                          sheet_tab_id: int = 0):
        """Paint the entire row soft red."""
        requests = [{
            "repeatCell": {
                "range": {
                    "sheetId": sheet_tab_id,
                    "startRowIndex": row_num - 1,
                    "endRowIndex": row_num,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(self.SHEET_HEADERS),
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": self._RED,
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        }]
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id, body={"requests": requests}
        ).execute()
        log.info("  row %d highlighted red", row_num)

    def add_note(self, sheet_id: str, row_num: int,
                 note: str, sheet_tab_id: int = 0):
        """Attach a cell note to the Comment column (S)."""
        requests = [{
            "updateCells": {
                "rows": [{"values": [{"note": note}]}],
                "fields": "note",
                "range": {
                    "sheetId": sheet_tab_id,
                    "startRowIndex": row_num - 1,
                    "endRowIndex": row_num,
                    "startColumnIndex": _COMMENT_COL_INDEX,
                    "endColumnIndex": _COMMENT_COL_INDEX + 1,
                },
            }
        }]
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id, body={"requests": requests}
        ).execute()
