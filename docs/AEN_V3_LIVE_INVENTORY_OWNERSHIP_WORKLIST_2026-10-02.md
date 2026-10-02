# V3 LIVE inventory ownership worklist

- [x] Define LIVE ownership as exact account + instrument boundary.
- [x] Adopt conflicting Saxo exact inventory instead of blocking on manual provenance.
- [x] Retire stale pending expectation after adoption; never retry the stale request.
- [x] Preserve full REDUCE/CLOSE authority over adopted inventory.
- [x] Preserve separate OPEN/ADD exposure-policy and Saxo-precheck authority.
- [x] Add regression coverage for oversized same-side reduction and opposite-side close-first behavior.
- [x] Add compile and contract tests.
- [ ] Merge only after CI is green.
- [ ] Verify Railway production worker deploy.
- [ ] Verify live runtime retires the existing +0.12 / -0.01 conflict and resumes management from Saxo actual.