# V3 LIVE inventory ownership worklist

- [x] Define LIVE ownership as exact account + instrument boundary.
- [x] Adopt conflicting Saxo exact inventory instead of blocking on manual provenance.
- [x] Retire stale pending expectation after adoption; never retry the stale request.
- [x] Preserve full REDUCE/CLOSE authority over adopted inventory.
- [x] Preserve separate OPEN/ADD exposure-policy and Saxo-precheck authority.
- [x] Add regression coverage for oversized same-side reduction and opposite-side close-first behavior.
- [x] Add compile and contract tests.
- [x] Merge after CI is green.
- [x] Verify Railway production worker deploy.
- [x] Verify live runtime retires the existing +0.12 / -0.01 conflict and resumes management from Saxo actual.

## Production verification — 2026-10-02

Railway production verified the complete ownership/reconciliation lifecycle:

1. Historical state was blocked at `actual=0.12 expected=-0.01 pending=conflict`.
2. After the ownership deployment, V3 reported `RECONCILED ... pending=inventory-adopted`.
3. On the following cycle V3 evaluated the adopted `actual=0.12` against `target=0` and executed `CLOSE Sell 0.12`.
4. Saxo reconciliation then confirmed `actual=0 expected=0`.
5. V3 subsequently evaluated `target=0.01`, passed the normal expansion path, and executed `OPEN Buy 0.01` with `cap_nok=500`.
6. A later inventory difference (`actual=0.05 expected=0.01`) was again adopted rather than blocked, confirming that the behavior is a durable ownership rule rather than a one-off stale-state cleanup.

Ownership migration is therefore complete end-to-end: implementation, CI/merge, Railway deployment, Saxo execution, and post-order reconciliation are all verified.