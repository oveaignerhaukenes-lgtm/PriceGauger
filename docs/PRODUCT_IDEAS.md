# PriceGauger product ideas

## Analysis Mixer / routing layer

Future synthesis UI should behave like a DAW/mixer for analysis signals rather than hard-wiring one fixed pipeline.

Principles:

- Every domain should expose clean raw/structured data separately from its AI interpretation.
- Routing should be explicit: raw data, interpreted output, or both can be sent downstream.
- Each routed signal should have independent influence/gain (0–100%), plus mute/solo semantics where useful.
- The same source may be sent to multiple downstream specialists or synthesis buses.
- Synthesis should preserve provenance so it always knows whether an input is an observation or an interpretation.
- Later calibration/meta-learning may recommend or adjust mixer gains without mutating the underlying domain analyzers.
- The output is a distribution of plausible market paths/scenarios rather than an audio signal.

Do not build this before the first useful domain specialists and synthesis contract exist. Revisit when Synthesis input/routing is designed.
