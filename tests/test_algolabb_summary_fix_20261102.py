"""UI regression and aggregate AI-summary evidence tests."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from strategy_lab_v2_saxo_costs import account_label_v2, saxobank_accounts_v2
from analysis_digest_v1 import prepare_metrics, parse_ai_summary, summarize_metrics


class Client:
    def _get(self, path):
        assert path == "port/v1/accounts/me"
        return {"Data": [
            {"AccountKey": "private-1", "AccountId": "123456",
             "Currency": "NOK", "AccountName": "Tech100-A"},
            {"AccountKey": "private-2", "AccountId": "987654",
             "Currency": "NOK", "DisplayName": "Tech100-B"},
            {"AccountKey": "private-3", "AccountId": "101010",
             "Currency": "NOK"},
        ]}


def test_account_names_are_untruncated_and_only_name_or_number():
    rows = saxobank_accounts_v2(Client())
    assert [account_label_v2(x) for x in rows] == [
        "Tech100-A", "Tech100-B", "101010",
    ]
    assert rows[0]["account_key"] == "private-1"


def test_algolabb_controls_exist_before_number_inputs():
    page = Path("pages/0_Algorithm_Lab.py").read_text()
    assert page.index("k1, k2, k3, k4 = st.columns(4)") < page.index("capital = k1.number_input")
    assert "verified_replay_costs_v2(raw)" not in page
    assert 'float(raw.minimum_trade_size)' in page
    assert "account_label_v2" in page
    nav = Path("navigation_config.py").read_text()
    assert '"title": "Algolabb"' in nav


def test_metrics_reject_nonfinite_unknown_and_duplicate():
    base = {"id": "net_pnl", "label": "PAPER", "value": -8,
            "reference": 100, "unit": "%"}
    assert prepare_metrics([base])[0]["value"] == -8
    with pytest.raises(ValueError):
        prepare_metrics([base, base])
    with pytest.raises(ValueError):
        prepare_metrics([{**base, "value": float("nan") }])
    with pytest.raises(ValueError):
        prepare_metrics([{**base, "reference": 0}])


def test_ai_cannot_inject_unmeasured_metric_or_numeric_claims():
    metric = prepare_metrics([{"id":"paper_pnl","label":"P/L",
                               "value":-5,"unit":"%", "reference":100}])
    payload = ('{"title":"Kritisk funn","points":['
               '{"metric_id":"fake_field","insight":"Dette er bare en oppdiktet verdi"},'
               '{"metric_id":"paper_pnl","insight":"Resultatet er 98 prosent sikkert"},'
               '{"metric_id":"paper_pnl","insight":"Resultatet er scenarioavhengig og krever holdout"}]}')
    out = parse_ai_summary(payload, metric)
    assert len(out["points"]) == 1
    assert out["points"][0]["metric_id"] == "paper_pnl"
    assert "98" not in str(out)


def test_ai_api_failure_does_not_interrupt_analysis():
    metric = [{"id":"paper_pnl","label":"P/L", "value":-5,
               "unit":"%", "reference":100}]
    result = summarize_metrics(title="Test",metrics=metric,caveat="Scenario",key="")
    assert result["generated"] is False
    assert result["points"][0]["metric_id"] == "paper_pnl"
