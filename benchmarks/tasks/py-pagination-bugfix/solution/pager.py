"""Offset pagination helpers used by the list endpoints."""
import math


def page_count(total, per_page):
    """Number of pages needed to show ``total`` items."""
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    if total == 0:
        return 0
    return math.ceil(total / per_page)


def paginate(items, page, per_page):
    """Return the items shown on 1-based ``page``."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end]
