# AutoManage shadow benchmark v2

The shadow benchmark is a deterministic, read-only replay over exact canonical 1m history aggregated to fully closed 30m bars.

It compares active AutoManage strategies from one common product cohort start and one observed managed-position direction. It does not run an order daemon, write a shadow equity ledger, or participate in Saxo execution.

The first fully closed 30m bar after enrollment establishes the common benchmark price baseline. A MACD cross confirmed on that bar may change the paper state at that close, but pre-enrollment price return is deliberately excluded. Historical MACD regime never replaces the observed starting exposure.

Paper results omit spread, slippage, margin financing and execution costs. Authoritative LIVE realized P/L remains exclusively sourced from Saxo closed-position reconciliation.
