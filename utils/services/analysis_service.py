import json
import re
import logging
import urllib.request
import urllib.error
import time

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback result – used only if all retries fail
# ---------------------------------------------------------------------------
_FALLBACK = {
    "greeting": 0,
    "body_known": 0,
    "year_known": 0,
    "mileage_known": 0,
    "diagnostics": 0,
    "history_asked": 0,
    "professionalism_ok": True,
    "comment": "PARSE_ERROR – review manually",
}

# Keys that must be present in a valid response
_REQUIRED_KEYS = {"greeting", "body_known", "year_known",
                  "mileage_known", "diagnostics", "history_asked",
                  "professionalism_ok"}


class AnalysisService:
    # -----------------------------------------------------------------------
    # Prompt asks for a COMPACT single-line JSON so the model wastes no tokens
    # on indentation and is far less likely to be cut off.
    # -----------------------------------------------------------------------
    SYSTEM_PROMPT = (
        "You are a QA analyst for a car-service call centre.\n"
        "Analyse the transcript and return ONE compact JSON object on a single line "
        "(no indentation, no markdown, no extra text).\n\n"
        'Required format (copy exactly, replace values only):\n'
        '{"greeting":0,"body_known":0,"year_known":0,"mileage_known":0,'
        '"diagnostics":0,"history_asked":0,"professionalism_ok":true,"comment":""}\n\n'
        "Rules:\n"
        "- Each score: 1 = clearly met, 0 = not met or unclear.\n"
        "- greeting: manager introduced themselves at the start.\n"
        "- body_known: manager asked/knew the vehicle body type.\n"
        "- year_known: manager asked/knew the car year.\n"
        "- mileage_known: manager asked/knew the mileage.\n"
        "- diagnostics: manager proposed a comprehensive diagnostics service.\n"
        "- history_asked: manager asked what work was done before.\n"
        "- professionalism_ok: false ONLY if the manager was rude or unprofessional.\n"
        "- comment: one short English sentence if professionalism_ok is false; "
        'empty string "" otherwise.\n'
        "- Use only straight ASCII double-quotes. No trailing commas.\n"
        "Output ONLY the JSON line."
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
                "maxOutputTokens": 1024,           # plenty of headroom; schema is ~80 tokens
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

        # Check finish reason – MAX_TOKENS means response was cut off
        candidate = body["candidates"][0]
        finish = candidate.get("finishReason", "")
        if finish == "MAX_TOKENS":
            log.warning("  Gemini hit MAX_TOKENS – response truncated!")

        return candidate["content"]["parts"][0]["text"].strip()

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        """
        Try progressively looser strategies to extract valid JSON.
        Returns a dict on success, None on failure (so caller can retry).
        """
        # Normalise smart/curly quotes everywhere before any attempt
        cleaned = (
            raw
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2018", "'").replace("\u2019", "'")
            .replace("\u00ab", '"').replace("\u00bb", '"')
        )

        candidates = [
            cleaned,
            # strip markdown fences
            re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip(),
        ]

        # Also try extracting the first complete {...} block
        m = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if m:
            candidates.append(m.group(0))

        # If the JSON is truncated, try to salvage it by closing the object
        # and filling missing keys with 0/defaults
        if "{" in cleaned and "}" not in cleaned:
            salvaged = AnalysisService._salvage_truncated(cleaned)
            if salvaged:
                candidates.append(salvaged)

        for text in candidates:
            try:
                obj = json.loads(text)
                if isinstance(obj, dict) and _REQUIRED_KEYS.issubset(obj):
                    return obj
                # partial dict – fill missing keys with defaults and accept
                if isinstance(obj, dict) and any(k in obj for k in _REQUIRED_KEYS):
                    log.warning("  Partial JSON – filling missing keys with 0.")
                    return {**_FALLBACK, **obj}
            except json.JSONDecodeError:
                continue

        return None  # signal failure to caller

    @staticmethod
    def _salvage_truncated(raw: str) -> str | None:
        """
        When Gemini returns something like:
            {"greeting": 1, "body_known": 0, "year_known":
        parse what we have, fill the rest with 0/defaults, re-serialise.
        """
        # Collect all key:value pairs that DID parse cleanly
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
        merged.pop("comment", None)
        merged["comment"] = found.get("comment", "")
        log.warning("  Salvaged partial keys: %s", list(found.keys()))
        return json.dumps(merged)
