# V3 LIVE ownership migration note

Previous behavior required a manual-fill provenance marker before adopting a Saxo inventory conflict. That left a LIVE trader blocked when the user intentionally changed the position manually.

New behavior treats LIVE authority for the exact assigned account + instrument as management ownership. A conflicting exact Saxo inventory retires the stale pending expectation and is managed from the next cycle. The stale request is never retried.

This deliberately changes only conflict reconciliation. A WAIT where inventory is still exactly the pre-order state remains pending, and OPEN/ADD still requires the V3 exposure policy plus Saxo precheck.