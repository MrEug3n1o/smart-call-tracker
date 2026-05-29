import re
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from utils.services.analysis_service import SCORE_KEYS

log = logging.getLogger(__name__)

_COMMENT_COL_INDEX = 18  # column S (0-based)


class SheetsService:
    SHEET_HEADERS = [
        "Дата",  # A
        "Тип дзвінку / Причина",  # B
        "Номер телефону",  # C
        "Філія / Відділення",  # D
        "Ім'я менеджера",  # E
        "Привітання",  # F
        "Відомий кузов авто",  # G
        "Відомий рік авто",  # H
        "Відомий пробіг авто",  # I
        "Запропоновано комплексну діагностику",  # J
        "Запитано про попередні роботи",  # K
        "Запис / Завершення дзвінка",  # L
        "Обрана робота / Топ-100",  # M
        "Дотримання інструкцій Топ-100",  # N
        "Рекомендації по Топ-100",  # O
        "Фінальний результат",  # P
        "Оцінка / Бали",  # Q
        "Запчастини",  # R
        "Коментар",  # S
    ]

    _RED = {"red": 0.95, "green": 0.6, "blue": 0.6}

    def __init__(self, creds_file: str):
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = service_account.Credentials.from_service_account_file(
            creds_file, scopes=scopes
        )
        self.service = build("sheets", "v4", credentials=creds)

    # ------------------------------------------------------------------
    # Resolve the real numeric sheetId – always fetches fresh from API
    # ------------------------------------------------------------------
    def _get_tab_id(self, spreadsheet_id: str, tab: str) -> int:
        meta = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties(title,sheetId)"
        ).execute()

        tab_map = {
            s["properties"]["title"]: int(s["properties"]["sheetId"])
            for s in meta.get("sheets", [])
        }
        log.info("  available tabs: %s", tab_map)

        if tab not in tab_map:
            lower_map = {k.lower(): v for k, v in tab_map.items()}
            if tab.lower() in lower_map:
                resolved_id = lower_map[tab.lower()]
                log.warning("  tab '%s' matched case-insensitively → id %d", tab, resolved_id)
                return resolved_id
            raise ValueError(
                f"Tab '{tab}' not found. Available tabs: {list(tab_map.keys())}"
            )

        tab_id = tab_map[tab]
        log.info("  resolved tab '%s' → sheetId %d", tab, tab_id)
        return tab_id

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    def ensure_header(self, sheet_id: str, tab: str = "Sheet1"):
        result = self.service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{tab}!A1:Z1"
        ).execute()

        if not result.get("values"):
            self.service.sheets().values().update(
                spreadsheetId=sheet_id,
                range=f"{tab}!A1",
                valueInputOption="RAW",
                body={"values": [self.SHEET_HEADERS]},
            ).execute()
            log.info("  header row written")

    # ------------------------------------------------------------------
    # Append row — теперь возвращает и номер, и саму строку
    # ------------------------------------------------------------------
    def append_row(self, sheet_id: str, meta: dict, analysis: dict,
                   tab: str = "Sheet1") -> tuple[int, list]:
        score = sum(analysis.get(k, 0) for k in SCORE_KEYS)

        row = [
            meta.get("date", ""),
            analysis.get("call_type", "Вхідний дзвінок"),
            meta.get("phone", ""),
            analysis.get("branch", ""),
            analysis.get("manager_name", ""),
            analysis.get("greeting", 0),
            analysis.get("body_known", 0),
            analysis.get("year_known", 0),
            analysis.get("mileage_known", 0),
            analysis.get("diagnostics", 0),
            analysis.get("history_asked", 0),
            analysis.get("appointment_made", 0),
            analysis.get("chosen_job", "інший варіант"),
            analysis.get("top100_adhered", 0),
            analysis.get("top100_recommended", 0),
            analysis.get("final_result", ""),
            score,
            analysis.get("spare_parts", ""),
            analysis.get("comment", ""),
        ]

        resp = self.service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        updated = resp["updates"]["updatedRange"]
        row_num = int(re.search(r"(\d+):", updated.split("!")[-1]).group(1))
        log.info("  → row %d written (score %d/%d)", row_num, score, len(SCORE_KEYS))
        return row_num, row

    # ------------------------------------------------------------------
    # Точечное окрашивание ячеек со значением 0 или пустой строкой
    # ------------------------------------------------------------------
    def highlight_cells_red(self, sheet_id: str, row_num: int, row_data: list, tab: str = "Sheet1"):
        tab_id = self._get_tab_id(sheet_id, tab)
        requests = []

        for col_idx, value in enumerate(row_data):
            # Пропускаем колонку с комментарием
            if col_idx == _COMMENT_COL_INDEX:
                continue

            # Проверяем условия: строго равен 0, либо пустая строка (после strip), либо None
            is_zero = value == 0 and not isinstance(value, bool)
            is_empty = isinstance(value, str) and not value.strip()

            if is_zero or is_empty or value is None:
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": tab_id,
                            "startRowIndex": row_num - 1,
                            "endRowIndex": row_num,
                            "startColumnIndex": col_idx,
                            "endColumnIndex": col_idx + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": self._RED,
                                "textFormat": {"bold": True},
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)",
                    }
                })

        # Если нашлись проблемные ячейки — отправляем пачку запросов за один раз
        if requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id, body={"requests": requests}
            ).execute()
            log.info("  %d cells in row %d highlighted red", len(requests), row_num)

    def add_note(self, sheet_id: str, row_num: int, note: str, tab: str = "Sheet1"):
        tab_id = self._get_tab_id(sheet_id, tab)
        requests = [{
            "updateCells": {
                "rows": [{"values": [{"note": note}]}],
                "fields": "note",
                "range": {
                    "sheetId": tab_id,
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
