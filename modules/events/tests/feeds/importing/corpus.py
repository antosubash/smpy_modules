"""Hostile and ordinary ``.ics`` files, built as bytes (no binary fixtures are committed).

Every builder returns a complete file; the hostile ones are each one bound over its limit. The
sizes are the constants' own, so the corpus follows them.
"""

from __future__ import annotations

CRLF = "\r\n"


def lines(*body: str) -> bytes:
    return (CRLF.join(body) + CRLF).encode()


def vevent(uid: str = "a@x", *extra: str, start: str = "20260701T100000Z", end="20260701T110000Z"):
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART:{start}",
        f"DTEND:{end}",
        "SUMMARY:Talk",
        *extra,
        "END:VEVENT",
    ]


def calendar(*components: str, head: tuple[str, ...] = ("VERSION:2.0", "PRODID:-//x//EN")) -> bytes:
    return lines("BEGIN:VCALENDAR", *head, *components, "END:VCALENDAR")


def simple(count: int = 1) -> bytes:
    body = [line for n in range(count) for line in vevent(f"u{n}@x")]
    return calendar(*body)


def with_event_lines(count: int, kind: str = "ATTENDEE;CN=A:mailto:a@example.com") -> bytes:
    return calendar(*vevent("a@x", *[f"{kind}" for _ in range(count)]))


def invalid_utf8() -> bytes:
    return simple().replace(b"Talk", b"T\xff\xfeak")


def nul_byte() -> bytes:
    return simple().replace(b"Talk", b"Ta\x00lk")


def long_line(size: int) -> bytes:
    return calendar(*vevent("a@x", "DESCRIPTION:" + "x" * (size - len("DESCRIPTION:"))))


def folded(total: int) -> bytes:
    """One DESCRIPTION of ``total`` bytes, folded at 75 octets (it unfolds to ``total``)."""
    text = "DESCRIPTION:" + "y" * (total - len("DESCRIPTION:"))
    parts = [text[i : i + 74] for i in range(0, len(text), 74)]
    folded_lines = [parts[0], *(" " + part for part in parts[1:])]
    return calendar(*vevent("a@x", *folded_lines))


def nested_alarms(count: int) -> bytes:
    inner = "BEGIN:VALARM\r\n" * count
    return (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a@x\r\nDTSTART:20260701T100000Z\r\n"
        + inner
        + "END:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()


def sequential_alarms(count: int) -> bytes:
    alarms = ["BEGIN:VALARM", "ACTION:DISPLAY", "END:VALARM"]
    body = ["BEGIN:VEVENT", "UID:a@x", "DTSTART:20260701T100000Z", *(alarms * 0)]
    body += ["BEGIN:VALARM", "END:VALARM"] * count
    return calendar(*body, "END:VEVENT")


def depth(levels: int) -> bytes:
    """VCALENDAR > VEVENT > VALARM > ... ``levels`` deep in all."""
    names = ["VCALENDAR", "VEVENT", "VALARM", "X-A", "X-B", "X-C"][:levels]
    begin = "".join(f"BEGIN:{n}\r\n" for n in names)
    end = "".join(f"END:{n}\r\n" for n in reversed(names))
    return (begin + end).encode()


def two_calendars() -> bytes:
    return simple() + simple()


def unbalanced_end() -> bytes:
    return simple().replace(b"END:VEVENT\r\n", b"")


def mismatched_end() -> bytes:
    return simple().replace(b"END:VEVENT", b"END:VTODO")


def content_before_begin() -> bytes:
    return b"PRODID:x\r\n" + simple()


def trailing_after_end() -> bytes:
    return simple() + b"BEGIN:VEVENT\r\nEND:VEVENT\r\n"


def properties(count: int) -> bytes:
    return calendar(*vevent("a@x", *[f"X-P{n}:v" for n in range(count - 4)]))


def big_event(size: int) -> bytes:
    """One VEVENT of about ``size`` bytes in lines of 1,000 bytes."""
    n = size // 1000
    return calendar(*vevent("a@x", *[f"X-B{i % 400}:" + "z" * 990 for i in range(n)]))


def timezones(count: int) -> bytes:
    zone = ["BEGIN:VTIMEZONE", "TZID:Z", "END:VTIMEZONE"]
    return calendar(*(zone * count))


def vtimezone_observances(count: int) -> bytes:
    inner = ["BEGIN:STANDARD", "DTSTART:19700101T000000", "TZOFFSETFROM:+0100", "END:STANDARD"]
    return calendar("BEGIN:VTIMEZONE", "TZID:Bomb", *(inner * count), "END:VTIMEZONE")


def vtimezone_rdates(count: int) -> bytes:
    rdates = [f"RDATE:2026{n % 12 + 1:02d}01T000000" for n in range(count)]
    return calendar(
        "BEGIN:VTIMEZONE", "TZID:Bomb", "BEGIN:STANDARD", *rdates, "END:STANDARD", "END:VTIMEZONE"
    )


def events(count: int) -> bytes:
    return calendar(
        *[line for n in range(count) for line in ("BEGIN:VEVENT", f"UID:{n}", "END:VEVENT")]
    )


def one_giant_line(megabytes: int) -> bytes:
    return (
        b"BEGIN:VCALENDAR\r\nX-BIG:" + b"a" * (megabytes * 1024 * 1024) + b"\r\nEND:VCALENDAR\r\n"
    )


def many_exdates(count: int) -> bytes:
    dates = ",".join(f"{2000 + n // 365}{n % 12 + 1:02d}01T100000Z" for n in range(count))
    return calendar(*vevent("a@x", "RRULE:FREQ=DAILY", f"EXDATE:{dates}"))


def empty_lines(count: int) -> bytes:
    return b"BEGIN:VCALENDAR\r\n" + b"\r\n" * count + b"END:VCALENDAR\r\n"
