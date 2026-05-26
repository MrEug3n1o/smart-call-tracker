import re
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build

log = logging.getLogger(__name__)


class SheetsService:
    SHEET_HEADERS = [
        "Date", "Time", "Phone", "Direction",
        "Greeting", "Body Known", "Year Known", "Mileage Known",
        "Diagnostics Proposed", "History Asked",
        "Total Score", "Professionalism OK", "Comment",
    ]

    def __init__(self, creds_file: str):
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = service_account.Credentials.from_service_account_file(creds_file, scopes=scopes)
        self.service = build("sheets", "v4", credentials=creds)

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

    def append_row(self, sheet_id: str, meta: dict, analysis: dict, tab: str = "Sheet1") -> int:
        criteria_keys = ["greeting", "body_known", "year_known", "mileage_known", "diagnostics", "history_asked"]
        scores = [analysis.get(k, 0) for k in criteria_keys]
        total = sum(scores)

        row = [
            meta.get("date", ""), meta.get("time", ""), meta.get("phone", ""), meta.get("direction", ""),
            *scores, total,
            "OK" if analysis.get("professionalism_ok", True) else "NOT OK",
            analysis.get("comment", ""),
        ]

        resp = self.service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        updated_range = resp["updates"]["updatedRange"]
        return int(re.search(r"(\d+):", updated_range.split("!")[-1]).group(1))

    def highlight_row_red(self, sheet_id: str, row_num: int, num_cols: int = 13):
        RED = {"red": 0.9, "green": 0.2, "blue": 0.2}
        requests = [{
            "repeatCell": {
                "range": {
                    "sheetId": 0,
                    "startRowIndex": row_num - 1, "endRowIndex": row_num,
                    "startColumnIndex": 0, "endColumnIndex": num_cols,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": RED, "textFormat": {"bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        }]
        self.service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": requests}).execute()

    def add_note(self, sheet_id: str, row_num: int, col_index: int, note: str):
        requests = [{
            "updateCells": {
                "rows": [{"values": [{"note": note}]}],
                "fields": "note",
                "range": {
                    "sheetId": 0,
                    "startRowIndex": row_num - 1, "endRowIndex": row_num,
                    "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
                },
            }
        }]
        self.service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": requests}).execute()
