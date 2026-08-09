from __future__ import annotations

from datetime import datetime, timezone

from macro_calendar import (
    BEA_SCHEDULE_URL,
    BLS_ICS_URL,
    FED_MONETARY_POLICY_URL,
    calendar_rows,
    load_macro_calendar,
    parse_bea_schedule,
    parse_bls_ics,
    parse_fed_upcoming,
    recurring_eia_events,
)


START = datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)


def test_bls_ics_extracts_core_releases_and_converts_to_oslo_time():
    payload = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260812T083000
SUMMARY:Consumer Price Index
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260813T083000
SUMMARY:Producer Price Index
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260904T083000
SUMMARY:Employment Situation
END:VEVENT
END:VCALENDAR
"""

    events = parse_bls_ics(payload, start=START, end=END)

    assert [event.event_type for event in events] == ["US_CPI", "US_PPI", "US_NFP"]
    assert events[0].scheduled_at_oslo.strftime("%d.%m.%Y %H:%M") == "12.08.2026 14:30"
    assert events[0].source_url.startswith("https://www.bls.gov/")


def test_bea_schedule_extracts_pce_and_gdp_with_source_link():
    html = """
    <table>
      <tr><td>August 26 8:30 AM</td><td>News</td><td>GDP (Second Estimate) and Corporate Profits, 2nd Quarter 2026 <a href="/news/gdp">View</a></td></tr>
      <tr><td>August 26 8:30 AM</td><td>News</td><td>Personal Income and Outlays, July 2026 <a href="/news/pce">View</a></td></tr>
    </table>
    """

    events = parse_bea_schedule(html, start=START, end=END)

    assert {event.event_type for event in events} == {"US_GDP", "US_PCE"}
    assert all(event.scheduled_at_oslo.strftime("%H:%M") == "14:30" for event in events)
    assert {event.source_url for event in events} == {
        "https://www.bea.gov/news/gdp",
        "https://www.bea.gov/news/pce",
    }


def test_fed_upcoming_extracts_decision_and_minutes_at_standard_release_time():
    html = """
    <div>Upcoming Dates</div>
    <div>Aug. 19 FOMC Minutes Meeting of July 28-29</div>
    <div>Sept. 15-16 FOMC Meeting Two-day meeting Press Conference</div>
    """

    events = parse_fed_upcoming(html, start=START, end=END)

    assert [event.event_type for event in events] == ["FOMC_MINUTES", "FOMC_DECISION"]
    assert events[0].scheduled_at_oslo.strftime("%d.%m.%Y %H:%M") == "19.08.2026 20:00"
    assert events[1].scheduled_at_oslo.strftime("%d.%m.%Y %H:%M") == "16.09.2026 20:00"


def test_eia_recurring_events_include_petroleum_and_natural_gas():
    end = datetime(2026, 8, 15, 23, 59, tzinfo=timezone.utc)

    events = recurring_eia_events(start=START, end=end)

    assert {event.event_type for event in events} == {"EIA_WPSR", "EIA_NG_STORAGE"}
    petroleum = next(event for event in events if event.event_type == "EIA_WPSR")
    gas = next(event for event in events if event.event_type == "EIA_NG_STORAGE")
    assert petroleum.scheduled_at_oslo.strftime("%d.%m.%Y %H:%M") == "12.08.2026 16:30"
    assert gas.scheduled_at_oslo.strftime("%d.%m.%Y %H:%M") == "13.08.2026 16:30"


def test_load_calendar_degrades_when_one_official_source_fails():
    bls = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260812T083000
SUMMARY:Consumer Price Index
END:VEVENT
END:VCALENDAR
"""
    fed = "<div>Sept. 15-16 FOMC Meeting</div>"

    def fetcher(url: str) -> str:
        if url == BLS_ICS_URL:
            return bls
        if url == BEA_SCHEDULE_URL:
            raise RuntimeError("temporary BEA outage")
        if url == FED_MONETARY_POLICY_URL:
            return fed
        raise AssertionError(url)

    result = load_macro_calendar(now=START, horizon_days=60, fetcher=fetcher)

    assert any(event.event_type == "US_CPI" for event in result.events)
    assert any(event.event_type == "FOMC_DECISION" for event in result.events)
    assert any(event.event_type == "EIA_WPSR" for event in result.events)
    assert result.source_errors == ("BEA: temporary BEA outage",)


def test_calendar_rows_include_date_time_and_clickable_official_url():
    payload = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260812T083000
SUMMARY:Consumer Price Index
END:VEVENT
END:VCALENDAR
"""
    event = parse_bls_ics(payload, start=START, end=END)[0]

    rows = calendar_rows([event])

    assert rows == [
        {
            "Dato": "12.08.2026",
            "Klokkeslett": "14:30",
            "Hendelse": "CPI",
            "Viktighet": "HIGH",
            "Markeder": "Gold, Silver, DXY, US10Y",
            "Kilde": "BLS",
            "Lenke": "https://www.bls.gov/cpi/",
        }
    ]
