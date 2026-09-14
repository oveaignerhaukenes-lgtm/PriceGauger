# AI baseline freshness semantics v1

The historical AI baseline is analysis-only. A persisted LONG/SHORT decision may contribute simulated P/L only while it remains fresh under `MAX_DECISION_AGE`.

If no newer AI baseline decision arrives before expiry, the reconstructed strategy state becomes `FLAT` at the expiry timestamp and remains flat until a later persisted decision arrives. This prevents disabled, failed, or quota-blocked AI models from receiving indefinite simulated credit from one stale call.

The Strategy Series materializer replaces the legacy indefinitely-held AI baseline replay with the freshness-capped series and versions it separately.
