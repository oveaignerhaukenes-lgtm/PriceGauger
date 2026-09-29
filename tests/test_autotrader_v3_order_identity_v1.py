from uuid import uuid5,NAMESPACE_URL

def test_close_and_open_of_same_decision_have_distinct_identities():
    pilot='pilot';decision='closed-bar-1'
    def key(action,side,actual,amount):
        return str(uuid5(NAMESPACE_URL,
            f'{pilot}:{decision}:{action}:{side}:{actual:.10g}:{amount:.10g}'))
    assert key('CLOSE','Sell',0.1,0.1)!=key('OPEN','Sell',0.0,0.2)
    assert key('CLOSE','Sell',0.1,0.1)==key('CLOSE','Sell',0.1,0.1)
