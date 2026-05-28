import json
import re
import logging
import urllib.request
import urllib.error
import time

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Top-100 allowed job list (Ukrainian)
# ---------------------------------------------------------------------------
TOP_100_JOBS = [
    "Комп'ютерна діагностика",
    "Заміна оливи ДВЗ + масляний фільтр",
    "Комплексна діагностика",
    "Ендоскопія",
    "Заміна повітряного фільтра ДВЗ",
    "Заміна фільтра салону в салоновому відділенні",
    "Заміна сайлентблоку",
    "Зняття / встановлення важеля",
    "Заміна еластичної муфти карданного валу",
    "Слюсарні роботи",
    "Діагностика підвіски (НЕ ВИКОРИСТОВУЄМ)ВИКОРИСТОВУЄМ КОМПЛЕКСНУ",
    "Зняття / встановлення важеля прд.",
    "Заміна амортизатора переднього",
    "Заміна оливи АКПП",
    "Мийка / чистка деталі",
    "Зняття / встановлення повітряного патрубка",
    "Заміна охолоджувальної рідини",
    "Заміна гальмівної рідини з прокачкою",
    "Заміна оливи в зд. редукторі",
    "Кодування опцій",
    "Заміна амортизатора зд.",
    "Заміна гальмівних дисків та колодок прд.",
]

_TOP_100_JSON = json.dumps(TOP_100_JOBS, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Fallback result – used only if all retries fail
# ---------------------------------------------------------------------------
_FALLBACK = {
    "call_type":         "Вхідний дзвінок",
    "branch":            "",
    "manager_name":      "",
    "greeting":          0,
    "body_known":        0,
    "year_known":        0,
    "mileage_known":     0,
    "diagnostics":       0,
    "history_asked":     0,
    "appointment_made":  0,
    "chosen_job":        "інший варіант",
    "top100_adhered":    0,
    "top100_recommended":0,
    "final_result":      "",
    "spare_parts":       "",
    "comment":           "PARSE_ERROR – review manually",
}

# Binary score keys that contribute to the total
SCORE_KEYS = [
    "greeting", "body_known", "year_known", "mileage_known",
    "diagnostics", "history_asked", "appointment_made",
    "top100_adhered", "top100_recommended",
]

_REQUIRED_KEYS = set(SCORE_KEYS) | {"call_type", "chosen_job", "final_result", "comment"}


class AnalysisService:
    SYSTEM_PROMPT = (
        "You are a QA analyst for a Ukrainian car-service call centre.\n"
        "Analyse the call transcript and return ONE compact JSON object on a SINGLE LINE "
        "(no indentation, no markdown, no extra text before or after).\n\n"

        "Required JSON template (copy key names exactly, replace values only):\n"
        '{"call_type":"Вхідний дзвінок","branch":"","manager_name":"",'
        '"greeting":0,"body_known":0,"year_known":0,"mileage_known":0,'
        '"diagnostics":0,"history_asked":0,"appointment_made":0,'
        '"chosen_job":"інший варіант","top100_adhered":0,"top100_recommended":0,'
        '"final_result":"","spare_parts":"","comment":""}\n\n'

        "Field rules:\n"
        "call_type      – Classify the call reason/type in Ukrainian (e.g. 'Вхідний дзвінок', "
        "'Запис на сервіс', 'Консультація'). Default: 'Вхідний дзвінок'.\n"
        "branch         – City or branch name if mentioned (e.g. 'Київ'), else empty string.\n"
        "manager_name   – Manager's first name if they introduced themselves, else empty string.\n"
        "greeting       – 1 if the manager introduced themselves by name at the start, else 0.\n"
        "body_known     – 1 if the manager asked or already knew the vehicle body type, else 0.\n"
        "year_known     – 1 if the manager asked or already knew the car manufacture year, else 0.\n"
        "mileage_known  – 1 if the manager asked or already knew the mileage, else 0.\n"
        "diagnostics    – 1 if the manager proposed a comprehensive diagnostics service, else 0.\n"
        "history_asked  – 1 if the manager asked about prior repair/maintenance history, else 0.\n"
        "appointment_made – 1 if the call ended with a booked service appointment, else 0.\n"

        f"chosen_job     – Match the primary service discussed to ONE item from this list:\n"
        f"{_TOP_100_JSON}\n"
        "If no item from that list was discussed, return \"інший варіант\".\n"

        "top100_adhered    – 1 if the manager correctly followed the upsell/script rules "
        "for the matched Top-100 job (proper proposal, pricing, next steps), else 0. "
        "If chosen_job is 'інший варіант', set to 0.\n"
        "top100_recommended – 1 if the manager proactively recommended relevant Top-100 services "
        "beyond what the customer asked for, else 0.\n"
        "final_result   – Short Ukrainian phrase describing the call outcome: "
        "'Запис на сервіс', 'Повторна консультація', 'Відмова', or empty string.\n"
        "spare_parts    – Comma-separated list of any spare parts mentioned, or empty string.\n"
        "comment        – MANDATORY short Ukrainian summary if ANY binary score is 0, "
        "explicitly listing what the manager missed. Empty string only if ALL scores are 1.\n\n"

        "General rules:\n"
        "- Binary scores: 1 = criterion clearly met, 0 = not met or unclear.\n"
        "- Use only straight ASCII double-quotes. No trailing commas.\n"
        "- Output ONLY the single JSON line."
    )

    def __init__(self, api_key: str, max_retries: int = 3):
        self.api_key = api_key
        self.max_retries = max_retries
        self.url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-3.5-flash:generateContent?key={self.api_key}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze(self, transcript: str) -> dict:
        for attempt in range(1, self.max_retries + 1):
            raw = self._call_gemini(transcript)
            log.debug("  Gemini attempt %d raw:\n%s", attempt, raw)

            result = self._parse_json(raw)
            if result is not None:
                return result

            log.warning("  Attempt %d/%d: could not parse response, retrying…",
                        attempt, self.max_retries)
            time.sleep(1)

        log.error("  All %d attempts failed – writing fallback zeros.", self.max_retries)
        return dict(_FALLBACK)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _call_gemini(self, transcript: str) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": self.SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": f"TRANSCRIPT:\n{transcript}"}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            },
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            log.error("  Gemini HTTP %s: %s", exc.code, exc.read().decode())
            raise

        candidate = body["candidates"][0]
        if candidate.get("finishReason") == "MAX_TOKENS":
            log.warning("  Gemini hit MAX_TOKENS – response truncated!")

        return candidate["content"]["parts"][0]["text"].strip()

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        # Normalise smart/curly quotes
        cleaned = (
            raw
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2018", "'").replace("\u2019", "'")
            .replace("\u00ab", '"').replace("\u00bb", '"')
        )

        candidates = [
            cleaned,
            re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip(),
        ]

        m = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if m:
            candidates.append(m.group(0))

        if "{" in cleaned and "}" not in cleaned:
            salvaged = AnalysisService._salvage_truncated(cleaned)
            if salvaged:
                candidates.append(salvaged)

        for text in candidates:
            try:
                obj = json.loads(text)
                if not isinstance(obj, dict):
                    continue
                if _REQUIRED_KEYS.issubset(obj):
                    return obj
                # partial – fill gaps with fallback values
                if any(k in obj for k in _REQUIRED_KEYS):
                    log.warning("  Partial JSON – filling missing keys with defaults.")
                    return {**_FALLBACK, **obj}
            except json.JSONDecodeError:
                continue

        return None

    @staticmethod
    def _salvage_truncated(raw: str) -> str | None:
        kv_re = re.compile(r'"(\w+)"\s*:\s*(\d+|true|false|"[^"]*")')
        found = {}
        for key, val_str in kv_re.findall(raw):
            try:
                found[key] = json.loads(val_str)
            except json.JSONDecodeError:
                pass
        if not found:
            return None
        merged = {**_FALLBACK, **found}
        log.warning("  Salvaged partial keys: %s", list(found.keys()))
        return json.dumps(merged, ensure_ascii=False)
