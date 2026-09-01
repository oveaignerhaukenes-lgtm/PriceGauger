# AutoManager P/L product history v2

Reporting is product-level while execution remains pilot-level.

- Strategy pilots keep separate ledgers, runtime state and audit identity.
- The P/L view aggregates settled realized Saxo P/L chronologically across all LIVE strategy pilots for the exact account + UIC + AssetType + instrument identity.
- The oldest persisted LIVE pilot defines the historical comparison start and exact position anchor for deterministic paper replay.
- Current/old SHADOW enrollments never define or reset the historical anchor.
- Strategy pilot start times are rendered as epoch markers on the shared timeline.
- LIVE hover identifies the strategy responsible for each realized event.
- LIVE and paper panels share one Plotly x-range; zoom, pan, range buttons and the range slider stay synchronized.
- Display timestamps are converted only at the UI boundary to Europe/Oslo wall clock, including strategy markers, so stored/audit timestamps remain UTC.
- Plotly uirevision is product-based rather than pilot-based so a strategy switch does not reset chart navigation.
- Open/unrealized P/L is not synthesized into the historical LIVE line.

No execution authority or order-path behavior is changed by this reporting capability.
