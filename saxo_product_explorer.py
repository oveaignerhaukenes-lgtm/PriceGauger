"""Provider-facing Saxo Product Explorer helpers.

The user-facing Product Explorer currently lives in ``autotrader_product_explorer``.
Runtime discovery imports provider taxonomy through this narrow adapter so category
classification has one implementation while the discovery boundary does not depend
on UI modules.
"""

from autotrader_product_explorer import category_for_asset_type


__all__ = ["category_for_asset_type"]
