import unittest

from espn_league.client import week_points


class WeekPointsTest(unittest.TestCase):
    def test_weekly_projection_beats_other_splits(self):
        _weekly_projection_beats_other_splits()

    def test_missing_week_is_none(self):
        _missing_week_is_none()


def _weekly_projection_beats_other_splits():
    stats = [
        {"scoringPeriodId": 8, "statSourceId": 1, "statSplitTypeId": 0, "appliedTotal": 4.0},
        {"scoringPeriodId": 8, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": 14.84},
        {"scoringPeriodId": 8, "statSourceId": 0, "statSplitTypeId": 1, "appliedTotal": 0},
        {"scoringPeriodId": 7, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": 17.64},
    ]
    assert week_points(stats, 8, projected=True) == 14.84
    assert week_points(stats, 8, projected=False) == 0
    assert week_points(stats, 7, projected=True) == 17.64


def _missing_week_is_none():
    assert week_points([], 8, projected=True) is None
