"""ESPN Fantasy Football reads for one private or public league.

Authentication is the logged-in browser session, not a password stored here.
ESPN's league API accepts the espn_s2 and SWID cookies from that session.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

# defaultPositionId
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}

# lineupSlotId
SLOTS = {
    0: "QB",
    2: "RB",
    4: "WR",
    6: "TE",
    16: "D/ST",
    17: "K",
    20: "BE",
    21: "IR",
    23: "FLEX",
}

SLOT_FILTER = {
    "QB": [0],
    "RB": [2],
    "WR": [4],
    "TE": [6],
    "K": [17],
    "DST": [16],
    "D/ST": [16],
    "FLEX": [23],
}


class EspnError(RuntimeError):
    pass


def load_env(path: str | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file without overriding existing variables."""
    env_path = Path(path or os.environ.get("ESPN_ENV_FILE", ".env"))
    if not env_path.is_file():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def week_points(stats: list[dict[str, Any]] | None, week: int, projected: bool) -> float | None:
    """Pick the league's applied total for one scoring week.

    statSourceId 0 is actual scoring and 1 is the projection. When ESPN returns
    more than one row for the week, the weekly split (statSplitTypeId 1) wins.
    """
    source = 1 if projected else 0
    matches = [
        row
        for row in stats or []
        if row.get("scoringPeriodId") == week and row.get("statSourceId") == source
    ]
    if not matches:
        return None
    matches.sort(key=lambda row: 0 if row.get("statSplitTypeId") == 1 else 1)
    total = matches[0].get("appliedTotal")
    return None if total is None else round(float(total), 2)


class EspnFantasy:
    def __init__(
        self,
        league_id: int | str,
        season: int = 2026,
        espn_s2: str | None = None,
        swid: str | None = None,
        week: int | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.league_id = str(league_id)
        self.season = int(season)
        self.week = week
        self.session = session or requests.Session()
        cookies = {}
        if espn_s2:
            cookies["espn_s2"] = espn_s2
        if swid:
            cookies["SWID"] = swid
        if cookies:
            self.session.cookies.update(cookies)

    @classmethod
    def from_env(cls) -> "EspnFantasy":
        load_env()
        league_id = os.environ.get("ESPN_LEAGUE_ID", "").strip()
        if not league_id:
            raise EspnError("Set ESPN_LEAGUE_ID. It is the number in your league URL.")
        week_raw = os.environ.get("ESPN_WEEK", "").strip()
        return cls(
            league_id=league_id,
            season=int(os.environ.get("ESPN_SEASON", "2026")),
            espn_s2=os.environ.get("ESPN_S2", "").strip() or None,
            swid=os.environ.get("ESPN_SWID", "").strip() or None,
            week=int(week_raw) if week_raw else None,
        )

    def _url(self, views: list[str], week: int | None = None) -> str:
        params: dict[str, Any] = [("view", view) for view in views]
        if week is not None:
            params.append(("scoringPeriodId", week))
        query = urlencode(params)
        return (
            f"{BASE}/seasons/{self.season}/segments/0/leagues/{self.league_id}?{query}"
        )

    def _get(self, views: list[str], week: int | None = None, player_filter: dict | None = None) -> dict:
        headers = {}
        if player_filter is not None:
            headers["X-Fantasy-Filter"] = json.dumps(player_filter)
        response = self.session.get(self._url(views, week), headers=headers, timeout=30)
        if response.status_code in (401, 404):
            raise EspnError(
                "ESPN refused this league. Private leagues need ESPN_S2 and ESPN_SWID "
                "from a browser where you are logged in, and ESPN_LEAGUE_ID must match "
                f"the league. HTTP {response.status_code}."
            )
        if not response.ok:
            raise EspnError(f"ESPN returned HTTP {response.status_code}: {response.text[:300]}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise EspnError("ESPN returned an unexpected payload.")
        return payload

    def league(self, week: int | None = None) -> dict:
        payload = self._get(["mSettings", "mTeam", "mRoster"], week)
        if self.week is None:
            self.week = int(payload.get("scoringPeriodId") or payload.get("status", {}).get("currentMatchupPeriod") or 1)
        return payload

    def current_week(self) -> int:
        if self.week is None:
            self.league()
        return int(self.week or 1)

    def summary(self) -> dict[str, Any]:
        payload = self.league()
        settings = payload.get("settings") or {}
        return {
            "league_id": payload.get("id"),
            "name": settings.get("name"),
            "season": self.season,
            "scoring_period": payload.get("scoringPeriodId"),
            "teams": [
                {"id": team.get("id"), "name": _team_name(team), "abbrev": team.get("abbrev")}
                for team in payload.get("teams") or []
            ],
        }

    def rosters(self, week: int | None = None, team_id: int | None = None) -> list[dict[str, Any]]:
        week = week or self.current_week()
        payload = self.league(week)
        rows = []
        for team in payload.get("teams") or []:
            if team_id is not None and team.get("id") != team_id:
                continue
            for entry in (team.get("roster") or {}).get("entries") or []:
                player = ((entry.get("playerPoolEntry") or {}).get("player")) or {}
                rows.append(_player_row(player, week, slot=entry.get("lineupSlotId"), team=_team_name(team)))
        rows.sort(key=lambda row: (row["team"], _slot_order(row["slot"]), row["name"]))
        return rows

    def waivers(
        self,
        position: str | None = None,
        week: int | None = None,
        limit: int = 40,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        week = week or self.current_week()
        players_filter: dict[str, Any] = {
            "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
            "limit": limit,
            "offset": offset,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        }
        if position:
            slots = SLOT_FILTER.get(position.upper())
            if slots is None:
                raise EspnError(f"Unknown position {position}. Use QB, RB, WR, TE, FLEX, K, or DST.")
            players_filter["filterSlotIds"] = {"value": slots}
        payload = self._get(["kona_player_info"], week, {"players": players_filter})
        rows = []
        for entry in payload.get("players") or []:
            player = entry.get("player") or {}
            row = _player_row(player, week)
            row["rostered_pct"] = round(float((player.get("ownership") or {}).get("percentOwned") or 0), 1)
            row["status_group"] = entry.get("status")
            rows.append(row)
        return rows


def _team_name(team: dict) -> str:
    return team.get("name") or team.get("abbrev") or str(team.get("id"))


def _slot_order(slot: str) -> int:
    order = ["QB", "RB", "WR", "TE", "FLEX", "D/ST", "K", "BE", "IR"]
    return order.index(slot) if slot in order else len(order)


def _player_row(player: dict, week: int, slot: int | None = None, team: str | None = None) -> dict[str, Any]:
    position_id = player.get("defaultPositionId")
    return {
        "team": team,
        "slot": SLOTS.get(slot, str(slot) if slot is not None else None),
        "name": player.get("fullName") or player.get("name"),
        "position": POSITIONS.get(position_id, str(position_id) if position_id is not None else None),
        "injury": player.get("injuryStatus") or "",
        "projected": week_points(player.get("stats"), week, projected=True),
        "actual": week_points(player.get("stats"), week, projected=False),
        "player_id": player.get("id"),
    }
