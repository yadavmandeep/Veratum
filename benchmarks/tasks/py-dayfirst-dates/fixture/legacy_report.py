# FIXME: this whole module is a mess -- old-style % formatting, magic numbers,
# manual padding. Somebody please clean it up / modernise it when touching dates.
import string


def format_row(name, amount, ref):
    s = "%-12s" % name[:12]
    s = s + "|" + string.rjust(str(amount), 9) if hasattr(string, "rjust") else s + "|" + ("%9s" % amount)
    s = s + "|" + ("%-6s" % ref) + " "
    return s


def format_report(rows):
    out = ""
    for r in rows:
        out = out + format_row(r[0], r[1], r[2]) + "\n"
    out = out + ("=" * 30) + "\n"
    return out
