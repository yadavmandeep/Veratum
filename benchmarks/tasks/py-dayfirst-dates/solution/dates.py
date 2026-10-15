"""Date parsing for imported CSV files."""
import datetime as _dt


def parse_date(text):
    """Parse ``YYYY-MM-DD`` or ``DD/MM/YYYY`` into a ``datetime.date``."""
    text = text.strip()
    if "-" in text:
        year, month, day = text.split("-")
    elif "/" in text:
        day, month, year = text.split("/")
    else:
        raise ValueError("unrecognised date: %r" % text)
    return _dt.date(int(year), int(month), int(day))
