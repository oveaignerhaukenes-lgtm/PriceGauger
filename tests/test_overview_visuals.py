from __future__ import annotations

import math

from overview_visuals import asset_color, bipolar_fill, visual_direction_score


def test_instrument_colors_are_stable():
    assert asset_color("Gold") == "#d88716"
    assert asset_color("Silver") == "#8c96a0"
    assert asset_color("Brent") == "#d6a04a"
    assert asset_color("Natural Gas") == "#168f8a"
    assert asset_color("DXY") == "#4f7fb8"


def test_visual_score_does_not_saturate_raw_unit_score():
    positive = visual_direction_score(1.0)
    negative = visual_direction_score(-1.0)

    assert 0.6 < positive < 0.7
    assert math.isclose(negative, -positive)


def test_bipolar_fill_starts_from_zero():
    left, right, marker = bipolar_fill(1.0)
    assert left == 0.0
    assert 30.0 < right < 35.0
    assert 80.0 < marker < 85.0

    left, right, marker = bipolar_fill(-1.0)
    assert 30.0 < left < 35.0
    assert right == 0.0
    assert 15.0 < marker < 20.0


def test_neutral_score_centers_marker():
    assert bipolar_fill(0.0) == (0.0, 0.0, 50.0)
