r"""
Counts the rows a plain pg_dump will actually restore, per table.

    python3 count_rows.py praxon-2026-11-23.sql

Prints one "table<TAB>rows" line per table, sorted, then a TOTAL line.

  Q: Why count rows at all? The file exists and the tables are there.
  A: A dump can have every table and no data in any of them — that happens
     when the connection string points at a fresh branch. It looks like a
     perfectly good backup until the day you need it. Counting rows is the
     difference between "a file was created" and "the data is in there".

  Q: Why read the file instead of asking the database?
  A: Because the question is what is IN THE BACKUP, not what is in the
     database. Asking the database would prove nothing about the file.

How a plain dump stores data:

    COPY public.users (id, email, role) FROM stdin;
    1	a@b.com	owner
    2	c@d.com	team
    \.

So: a COPY line starts a table, every line after it is one row, and a line
containing only  \.  ends it.
"""

from __future__ import annotations

import re
import sys

COPY_START = re.compile(r"COPY public\.(\w+) ")
END_OF_DATA = "\\."


def count(path: str) -> list[tuple[str, int]]:
    table: str | None = None
    rows = 0
    out: list[tuple[str, int]] = []

    # errors="replace": a dump holds whatever visitors typed, including broken
    # characters. A backup check must never crash on the data it is checking.
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if table is None:
                match = COPY_START.match(line)
                if match:
                    table, rows = match.group(1), 0
            elif line.rstrip("\n") == END_OF_DATA:
                out.append((table, rows))
                table = None
            else:
                rows += 1

    # A COPY block that never ended means the file was cut short — a truncated
    # dump is worse than no dump, because it looks fine in a listing.
    if table is not None:
        raise SystemExit(f"Dump ends in the middle of table '{table}': it is truncated.")

    return sorted(out)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: count_rows.py <dump.sql>")
    tables = count(sys.argv[1])
    for name, rows in tables:
        print(f"{name}\t{rows}")
    print(f"TOTAL\t{sum(rows for _, rows in tables)}")


if __name__ == "__main__":
    main()
