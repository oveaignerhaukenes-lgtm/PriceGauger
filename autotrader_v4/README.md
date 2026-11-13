# AutoTrader V4 (isolated local staging)

See [architecture ADR](../docs/AUTOTRADER_V4_LOCAL_FIRST_ADR_20261021.md). This is **not a
live trader**. It is an independent skeleton intended to be extracted into a
fresh repository after the architecture and local deployment are validated.

## On an Ubuntu Server with Docker Engine + Docker Compose installed

1. Clone the project and check out the isolated V4 branch or a reviewed V4 release.
2. Do **not** erase the SSD/4TB disks until separately confirming what they contain.
3. Create a **host-only** credentials file; **never commit or paste this file**:

   ```bash
   cp autotrader_v4/deploy/.env.example /tmp/at4-secrets.env
   chmod 600 /tmp/at4-secrets.env
   # Edit AT4_DB_PASSWORD=... locally to a long random password.
   ```

4. Start local staging (Docker Compose loads only the small V4 app, not any PG V3 runtime):

   ```bash
   docker compose --env-file /tmp/at4-secrets.env \
     -f autotrader_v4/deploy/compose.yaml up --build -d
   curl --fail http://127.0.0.1:18080/healthz
   curl --fail http://127.0.0.1:18080/api/v1/status
   ```

5. Inspect and stop:

   ```bash
   docker compose --env-file /tmp/at4-secrets.env \
     -f autotrader_v4/deploy/compose.yaml ps
   docker compose --env-file /tmp/at4-secrets.env \
     -f autotrader_v4/deploy/compose.yaml logs --tail=60 api
   docker compose --env-file /tmp/at4-secrets.env \
     -f autotrader_v4/deploy/compose.yaml down
   ```

   Never use `down -v` unless you explicitly intend to **delete the new staging
   database**. The V4 database schema SQL is only a reviewed specification,
   **not yet applied**. The status endpoint is intentionally read-only and
   broker-disconnected; there is no Saxo OAuth, no order POST, and no public API.

## Security
- Port 18080 is bound to `127.0.0.1` on the **host**. Reach remotely through a
  private, user-managed Tailscale/SSH tunnel. Do not publish Coolify, Postgres,
  SSH, V4 API or any Saxo token on the public internet.
- Never give ChatGPT a private SSH key or password in a conversation.
- The new database credentials must not equal Railway/V3 database credentials.
- Persistent Postgres volume is Docker-local and must have encrypted **offsite**
  backups before it holds meaningful account data.
- No automatic recovery of LIVE authority, no simultaneous V3/V4 execution on
  the same Saxo account.

## Next separate PRs
1. Add read-only Saxo OAuth refresh-token integration, *in its own process*,
   server-side secret storage and scoped GET-only account/positions/order reads.
2. Collect one instrument's quote stream and verified closed 1m bars.
3. Implement PostgreSQL transaction/position/cost reconciliation and exact
   strategy assignment event history.
4. Build deterministic PAPER strategy runners and an account-value UI.
5. Write and independently review a SINGLE-writer LIVE executor only after
   broker truth and safety gates are tested. Never infer this readiness from the
   current Docker healthcheck.
