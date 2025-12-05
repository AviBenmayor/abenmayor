
# Polymarket Order Book Summary API Schema

## Endpoint
**GET /book**

Returns a snapshot of the order book for a specific token.

---

## Request Parameters

### `token_id` (string, required)
Unique identifier for the token/market whose order book you want.

---

## Response Schema

### Top-level fields:
- **market** (string): Market / condition ID.
- **asset_id** (string): Token ID.
- **timestamp** (ISO datetime): When this snapshot was generated.
- **hash** (string): Hash representing the current state of the order book.
- **bids** (array of objects): Bid levels.
- **asks** (array of objects): Ask levels.
- **min_order_size** (string): Minimum order size for the market.
- **tick_size** (string): Price increment allowed.
- **neg_risk** (boolean): Whether negative-risk is enabled.

---

## Order Level Objects (`bids` / `asks`)
Each entry contains:
- **price** (string): Price level.
- **size** (string): Quantity available at that price.

---

## Example Response

```json
{
  "market": "0x1b6f76e5b8587ee896c35847e12d11e75290a8c3934c5952e8a9d6e4c6f03cfa",
  "asset_id": "1234567890",
  "timestamp": "2023-10-01T12:00:00Z",
  "hash": "0xabc123def456...",
  "bids": [
    { "price": "1800.50", "size": "10.5" }
  ],
  "asks": [
    { "price": "1800.50", "size": "10.5" }
  ],
  "min_order_size": "0.001",
  "tick_size": "0.01",
  "neg_risk": false
}
```

---

## Usage Notes
- Use `bids` and `asks` to compute market depth, spread, and liquidity.
- `min_order_size` and `tick_size` are needed for placing valid orders.
- `timestamp` tells you data freshness.
- `hash` can be used for verifying snapshot integrity.
