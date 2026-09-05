"""Presentation adapters into existing PriceGauger bounded contexts.

Adapters translate read models for TradingDesk UI consumption. They must not turn UI
state into direct Saxo execution or bypass AutoTrader/Product Admission.
"""
