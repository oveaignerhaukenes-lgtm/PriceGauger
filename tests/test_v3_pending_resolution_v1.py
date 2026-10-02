from datetime import datetime, timezone
from autotrader_v3_pending_resolution_v1 import classify_pending_resolution_v3

NOW=datetime(2026,10,2,7,0,0,tzinfo=timezone.utc)


def test_recent_wait_remains_waiting():
    result=classify_pending_resolution_v3(reconciliation_state='WAIT',updated_at='2026-10-02T06:59:30+00:00',now=NOW)
    assert result.state == 'WAITING'
    assert result.age_seconds == 30


def test_stale_wait_becomes_ambiguous_not_failed():
    result=classify_pending_resolution_v3(reconciliation_state='WAIT',updated_at='2026-10-02T06:42:25+00:00',now=NOW)
    assert result.state == 'AMBIGUOUS'
    assert 'broker evidence required' in result.detail


def test_conflict_is_ambiguous_and_confirmed_is_reconciled():
    conflict=classify_pending_resolution_v3(reconciliation_state='CONFLICT',updated_at='2026-10-02T06:59:30+00:00',now=NOW)
    confirmed=classify_pending_resolution_v3(reconciliation_state='CONFIRMED',updated_at='2026-10-02T06:59:30+00:00',now=NOW)
    assert conflict.state == 'AMBIGUOUS'
    assert confirmed.state == 'RECONCILED'


def test_missing_timestamp_fails_closed():
    result=classify_pending_resolution_v3(reconciliation_state='WAIT',updated_at=None,now=NOW)
    assert result.state == 'AMBIGUOUS'
