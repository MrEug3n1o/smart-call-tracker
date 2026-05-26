import json
import re
import logging
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback result – returned when we cannot parse Gemini's response at all
# ---------------------------------------------------------------------------
_FALLBACK = {
    "greeting": 0,
    "body_known": 0,
    "year_known": 0,
    "mileage_known": 0,
    "diagnostics": 0,
    "history_asked": 0,
    "professionalism_ok": True,
    "comment": "",
}


class AnalysisService:
    SYSTEM_PROMPT = (
        "You are a quality-assurance analyst for a car-service call centre.\n"
        "You receive a transcript of a call between a manager and a customer.\n"
        "Respond ONLY with a single valid JSON object – no markdown, no code fences, "
        "no extra text before or after.\n\n"
        "Schema (all keys required, use only these exact key names):\n"
        "{\n"
        '  "greeting":          0 or 1,\n'
        '  "body_known":        0 or 1,\n'
        '  "year_known":        0 or 1,\n'
        '  "mileage_known":     0 or 1,\n'
        '  "diagnostics":       0 or 1,\n'
        '  "history_asked":     0 or 1,\n'
        '  "professionalism_ok": true or false,\n'
        '  "comment":           "one sentence if professionalism_ok is false, else empty string"\n'
        "}\n\n"
        "Scoring rules:\n"
        "- 1 = criterion clearly met, 0 = not met or unclear.\n"
        "- professionalism_ok = false only if the manager was rude, dismissive, or unprofessional.\n"
        "- comment must use straight ASCII double-quotes only; no curly/smart quotes.\n"
        "- Return NOTHING except the JSON object."
    )

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-3.5-flash:generateContent?key={self.api_key}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze(self, transcript: str) -> dict:
        raw = self._call_gemini(transcript)
        log.debug("  Gemini raw response:\n%s", raw)
        result = self._parse_json(raw)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _call_gemini(self, transcript: str) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": self.SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": f"TRANSCRIPT:\n{transcript}"}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 512,
                "responseMimeType": "application/json",   # force JSON mode
            },
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            log.error("  Gemini HTTP %s: %s", exc.code, exc.read().decode())
            raise

        return body["candidates"][0]["content"]["parts"][0]["text"].strip()

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """
        Multi-stage JSON extraction that survives common Gemini quirks:
          1. Straight parse
          2. Strip markdown fences (```json … ```)
          3. Extract first {...} block via regex
          4. Replace curly/smart quotes with straight ones
          5. Return fallback with a warning
        """
        attempts = [
            raw,
            re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip(),
        ]

        for text in attempts:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # Stage 3 – grab first {...} block
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if m:
            candidate = m.group(0)
            # Stage 4 – normalise smart/curly quotes
            candidate = (
                candidate
                .replace("\u201c", '"').replace("\u201d", '"')   # " "
                .replace("\u2018", "'").replace("\u2019", "'")   # ' '
                .replace("\u00ab", '"').replace("\u00bb", '"')   # « »
            )
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as exc:
                log.warning("  Could not parse extracted JSON block: %s\n  Raw block: %s", exc, candidate)

        log.error("  All JSON parse attempts failed. Raw Gemini output:\n%s", raw)
        return dict(_FALLBACK)  # safe default – row still written, no crash
