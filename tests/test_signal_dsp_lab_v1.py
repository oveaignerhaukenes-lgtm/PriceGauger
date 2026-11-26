from datetime import datetime,timedelta,timezone
import pytest
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote
from signal_dsp_lab_v1 import Stage,State,process_sample,process_quotes
from navigation_config import PAGE_GROUPS

T=datetime(2026,11,25,12,tzinfo=timezone.utc)

def test_audio_dynamics_transfer_and_sign():
    c=Stage("compressor",threshold=2.,ratio=4.,attack_s=.01)
    value,gain=process_sample(-16.,1.,c,State())
    assert value<0 and abs(value)==pytest.approx(2*8**.25)
    assert 0<gain<1
    e=Stage("expander",threshold=2.,ratio=2.,attack_s=.01)
    assert process_sample(-1.,1.,e,State())[0]==pytest.approx(-.5)
    g=Stage("gate",threshold=2.,attack_s=.01,release_s=.01)
    assert process_sample(1.,1.,g,State())[0]==0.
    assert process_sample(3.,1.,g,State())[0]==3.

def test_bypass_causality_and_gap_reset():
    quotes=[ImpulseQuote(T+timedelta(seconds=i),p-.5,p+.5)
        for i,p in ((0,100.),(1,101.),(2,110.),(15,150.),(16,151.))]
    raw=list(process_quotes(quotes,()))
    assert [r["raw"] for r in raw]==[None,1.,9.,None,1.]
    assert all(r["raw"]==r["processed"] for r in raw)
    chain=[Stage("gate",threshold=2.,attack_s=.01),Stage("compressor",threshold=2.)]
    rows=list(process_quotes(quotes,chain))
    assert list(process_quotes(quotes[:3],chain))==rows[:3]
    assert rows[3]["gap"] and rows[3]["processed"] is None
    assert rows[4]["processed"]==0.
    assert [r["mid"] for r in rows]==[q.mid for q in quotes]
    with pytest.raises(ValueError):list(process_quotes(quotes[::-1],chain))

def test_signal_studio_registered():
    pages=[p for group in PAGE_GROUPS.values() for p in group]
    assert sum(p["page"]=="pages/0_IC14_Control.py" for p in pages)==1
