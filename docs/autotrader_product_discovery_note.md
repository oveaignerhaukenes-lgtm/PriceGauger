# AutoTrader leveraged product discovery

Product discovery is intentionally broader than one Saxo display label. PriceGauger searches a small set of market aliases per underlying and restricts results to supported Mini/knock-out asset types. Results are de-duplicated by `(UIC, AssetType)`.

The search result remains account/environment dependent. Saxo OpenAPI only returns instruments available to the authenticated setup, so an empty SIM result after all aliases/types are tried is treated as genuine absence for that session rather than guessed into a tradable product.
