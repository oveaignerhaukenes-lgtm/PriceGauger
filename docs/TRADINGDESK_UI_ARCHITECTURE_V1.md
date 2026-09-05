# TradingDesk UI architecture v1

## Purpose

`tradingdesk_ui/` is the bounded presentation context for the TradingDesk cockpit.
The migration starts with responsive layout and chart presentation because the prior
wide-screen composition became unusable on narrow devices.

This is **not** a second TradingDesk implementation. Desktop and mobile must consume the
same canonical workspace/read models and the same AutoManager state. Responsive behavior
changes presentation only.

## Boundary

Allowed here:

- responsive layout and breakpoints
- chart presentation profiles
- browser-local chart interaction state
- reusable TradingDesk view components
- presentation/workspace state that is safe to persist
- read-only adapters into Technical Core, Strategy Series, Spring, AutoManager read models

Forbidden here:

- direct Saxo POST/order authority
- strategy target generation
- Product Admission bypass
- sizing/leverage authority
- Position Guardian/risk decisions
- approval/arming authority hidden in generic workspace state

Execution still flows through the existing AutoManager/AutoTrader lifecycle.

## Initial hierarchy

```text
tradingdesk_ui/
    layout/
        responsive.py
    charts/
        profile.py
        responsive_runtime.py
    components/
    state/
    adapters/
```

The existing `pages/0_TradingDesk.py` remains the composition root during the first
migration step. Existing flat `tradingdesk_*` modules are moved only when a bounded
capability is being touched; there is no broad rewrite.

## Responsive contract

Desktop retains the current wide cockpit. At `<= 760px` the TradingDesk presentation
becomes a one-column flow and Plotly charts use a mobile profile:

- Streamlit columns stack to full width
- chart right margin is reclaimed from the desktop legend/inspector rail
- legend becomes compact/horizontal
- chart height grows so the actual plot is not crushed by mobile controls
- the existing linked inspector is repositioned into reserved space below the plot
- mobile/desktop switching is browser-local and does not change strategy or execution
  state

The first implementation is intentionally conservative about composition ordering.
Component extraction will follow so Live Chart, AutoManager, analysis, and controls can
be explicitly ordered per presentation profile without DOM hacks.

## Migration sequence

1. **Responsive foundation** — this capability.
2. **Component extraction** — Live Chart, Analysis, AutoManager, Strategy Comparison.
3. **Thin page composition root** — `pages/0_TradingDesk.py` delegates to
   `tradingdesk_ui.page`.
4. **Adapter cleanup** — existing flat modules move behind explicit read-only adapters as
   they are touched.

TradingDesk remains in the existing `pricegauger-web` Railway service. Unlike Spring Trade
Engine, UI composition does not benefit from a separate process and should not create a
second session/auth/routing surface.
