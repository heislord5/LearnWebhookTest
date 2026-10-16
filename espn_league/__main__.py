"""Command line for ESPN league reads.

Examples:
  python -m espn_league status
  python -m espn_league rosters --team-id 1
  python -m espn_league waivers --pos WR --limit 25
  python -m espn_league projections --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from espn_league.client import EspnError, EspnFantasy, load_env


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Read an ESPN fantasy football league.")
    parser.add_argument("command", choices=["status", "rosters", "waivers", "projections"])
    parser.add_argument("--week", type=int)
    parser.add_argument("--team-id", type=int, default=_optional_int("ESPN_TEAM_ID"))
    parser.add_argument("--pos", help="QB, RB, WR, TE, FLEX, K, or DST")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        client = EspnFantasy.from_env()
        if args.week:
            client.week = args.week
        if args.command == "status":
            payload = client.summary()
        elif args.command == "waivers":
            payload = client.waivers(position=args.pos, week=args.week, limit=args.limit)
        else:
            payload = client.rosters(week=args.week, team_id=args.team_id)
            if args.command == "projections":
                payload = [row for row in payload if row["slot"] not in {"BE", "IR"}]
    except EspnError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json or args.command == "status":
        print(json.dumps(payload, indent=2))
    else:
        _print_table(payload)
    return 0


def _optional_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else None


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("No players.")
        return
    columns = ["team", "slot", "name", "position", "injury", "projected", "actual"]
    if rows and rows[0].get("team") is None:
        columns = ["name", "position", "injury", "projected", "rostered_pct"]
    widths = {column: len(column) for column in columns}
    for row in rows:
        for column in columns:
            widths[column] = max(widths[column], len(_cell(row.get(column))))
    print("  ".join(column.upper().ljust(widths[column]) for column in columns))
    for row in rows:
        print("  ".join(_cell(row.get(column)).ljust(widths[column]) for column in columns))


def _cell(value: object) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
