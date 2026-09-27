from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_strategy_discussion_has_persistent_shared_memory() -> None:
    store=(ROOT/"strategy_discussion_store_v1.py").read_text(encoding="utf-8")
    page=(ROOT/"pages/0_Strategy_Lab.py").read_text(encoding="utf-8")
    assert "pg_v2_strategy_discussion_messages" in store
    assert "load_strategy_messages_v1" in page
    assert "st.chat_input" in page

def test_strategy_ai_receives_hypothesis_and_trade_plan_history() -> None:
    source=(ROOT/"strategy_discussion_ai_v1.py").read_text(encoding="utf-8")
    assert "hypothesis_timeline" in source
    assert "trade_plans" in source
    assert "Never silently rewrite prior hypotheses" in source
    assert '"store":False' in source
