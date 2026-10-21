"""Strategy Lab v2 AI response diagnostics: no credentials, no invented output."""
import json
from pathlib import Path

import pytest
import requests

from strategy_lab_v2_ai import (
    LabAIError,ask_lab_ai_v2,lab_ai_evidence_fingerprint_v2,
)


EVIDENCE={
    "source":"STRATEGY_LAB_V2_PAPER_ASOF",
    "strategy":"macd-flip","as_of":"2026-10-20T23:56:00+00:00",
    "market":"US Tech100","product":"111","cost_source":"MANUAL_SCENARIO",
    "closed_prices":[{"time":"2026-10-20T23:55:00+00:00",
                      "close":29700,"macd_hist":.12,"lots":.01}],
    "past_paper_trades":[],
}


class FakeResponse:
    def __init__(self,payload,status=200):
        self.payload=payload
        self.status_code=status
    def raise_for_status(self):
        if self.status_code>=400:
            err=requests.HTTPError("HTTP problem")
            err.response=self
            raise err
    def json(self):
        return self.payload


def invoke(post,*,evidence=EVIDENCE,key="dummy-key",question="Hva skjer?"):
    return ask_lab_ai_v2(
        evidence=evidence,question=question,key=key,
        model="gpt-5-mini",post=post)


def test_regular_nested_response_returns_text_and_keeps_asof():
    records=[]
    def post(url,*,headers,json,timeout):
        records.append((url,headers,json,timeout))
        return FakeResponse({"status":"completed","output":[{
            "type":"message","content":[
                {"type":"output_text","text":"Momentum øker; test prisfilter."}]}]})
    assert invoke(post)=="Momentum øker; test prisfilter."
    assert len(records)==1
    url,headers,body,timeout=records[0]
    assert url.endswith("/responses")
    assert body["store"] is False
    assert body["max_output_tokens"]==1600
    assert body["input"][0]["content"].startswith("Evidence (immutable as-of):")
    assert "23:56" in body["input"][0]["content"]
    assert "23:57" not in body["input"][0]["content"]
    assert headers["Authorization"]=="Bearer dummy-key"


def test_top_level_output_text_is_also_supported():
    assert invoke(lambda *a,**k:FakeResponse({
        "status":"completed","output_text":"Dette er et komplett svar."
    }))=="Dette er et komplett svar."


def test_reasoning_budget_exhaustion_retries_once_without_changing_asof():
    payloads=[]
    def post(url,*,json,**kwargs):
        payloads.append(dict(json))
        if len(payloads)==1:
            return FakeResponse({
                "status":"incomplete",
                "incomplete_details":{"reason":"max_output_tokens"},
                "output":[{"type":"reasoning","content":[]}],
            })
        return FakeResponse({"status":"completed","output":[{
            "type":"message","content":[{"type":"output_text","text":"Kausal analyse"}]}]})
    assert invoke(post)=="Kausal analyse"
    assert [x["max_output_tokens"] for x in payloads]==[1600,3200]
    assert payloads[0]["input"]==payloads[1]["input"]


def test_retry_only_once_then_report_why_not_bare_valueerror():
    attempts=[]
    def post(*args,**kwargs):
        attempts.append(1)
        return FakeResponse({
            "status":"incomplete",
            "incomplete_details":{"reason":"max_output_tokens"},"output":[]})
    with pytest.raises(LabAIError,match="fullførte ikke") as exc:
        invoke(post)
    assert exc.value.code=="MODEL_INCOMPLETE"
    assert len(attempts)==2


def test_completed_but_empty_is_classified_and_not_fabricated():
    with pytest.raises(LabAIError) as exc:
        invoke(lambda *a,**kw:FakeResponse({
            "status":"completed","output":[{"type":"reasoning","content":[]}]}))
    assert exc.value.code=="MODEL_EMPTY_RESPONSE"


@pytest.mark.parametrize(("code","status"),[
    ("API_AUTH",401),("API_AUTH",403),("API_LIMIT",429),("API_HTTP",500),
])
def test_http_error_does_not_show_broker_token_or_raw_provider_message(code,status):
    with pytest.raises(LabAIError) as exc:
        invoke(lambda *a,**kw:FakeResponse({},status=status))
    assert exc.value.code==code
    assert "dummy-key" not in str(exc.value)
    assert "HTTP problem" not in str(exc.value)


def test_missing_key_and_invalid_data_have_distinct_reasons():
    with pytest.raises(LabAIError) as exc:
        invoke(lambda *a,**kw:None,key="")
    assert exc.value.code=="API_KEY_MISSING"

    with pytest.raises(LabAIError) as exc:
        invoke(lambda *a,**kw:None,evidence=dict(EVIDENCE,closed_prices=[{
            "close":float("nan"),
        }]))
    assert exc.value.code=="INVALID_NUMERIC_EVIDENCE"

    with pytest.raises(ValueError,match="as-of") as exc:
        invoke(lambda *a,**kw:None,evidence={"source":"BAD"})
    assert isinstance(exc.value,LabAIError)


def test_ui_has_safe_specific_error_instead_of_only_valueerror():
    src=Path("pages/0_Strategy_Lab_V2.py").read_text()
    assert "except LabAIError as exc:" in src
    assert 'st.caption("Diagnose: "+exc.code' in src
    assert 'AI-samtalen kunne ikke fullføres: "+type(exc).__name__' not in src
    backend=Path("strategy_lab_v2_ai.py").read_text()
    assert "strategy_lab_v2_ai_failed code=%s" in backend
    assert "LOGGER.warning(" in backend
    assert "OPENAI_API_KEY" not in backend
    assert "place_order(" not in backend
    assert "_post(" not in backend
