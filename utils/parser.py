import re
from datetime import datetime

FILENAME_RE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2})_(?P<phone>\d+)_(?P<direction>\w+)\.\w+$"
)


def parse_filename(name: str) -> dict:
    """Extracts metadata from the standard audio filename pattern."""
    m = FILENAME_RE.search(name)
    if not m:
        return {"date": None, "time": None, "phone": None, "direction": None}

    d = m.groupdict()
    d["datetime"] = datetime.strptime(f"{d['date']} {d['time']}", "%Y-%m-%d %H-%M")
    return d
