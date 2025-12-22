# Oracle Bot V2 - API Documentation

## Dashboard REST API

The Oracle Bot dashboard exposes a REST API for monitoring and control.

### Base URL
```
http://localhost:5000
```

---

## Endpoints

### GET /api/status

Returns current bot status, balance, and open positions.

**Response:**
```json
{
  "mode": "PAPER",
  "balance": 1000.0,
  "total_pnl": 0.0,
  "total_fees": 0.0,
  "wins": 0,
  "losses": 0,
  "win_rate": 0.0,
  "positions": [],
  "position_count": 0,
  "max_positions": 5,
  "consecutive_losses": 0,
  "daily_pnl": 0.0
}
```

---

### GET /api/trades

Returns trade history.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| limit | int | 50 | Maximum trades to return |
| offset | int | 0 | Skip first N trades |

**Response:**
```json
{
  "trades": [
    {
      "symbol": "BTCUSDT",
      "exchange": "Delta",
      "direction": "LONG",
      "entry_price": 95000.0,
      "exit_price": 96500.0,
      "size_usd": 100.0,
      "gross_pnl": 1.58,
      "net_pnl": 1.46,
      "fees": 0.12,
      "entry_time": "2025-12-22T10:30:00",
      "exit_time": "2025-12-22T12:45:00",
      "exit_reason": "TAKE_PROFIT",
      "duration_minutes": 135
    }
  ],
  "total": 1
}
```

---

### GET /api/positions

Returns currently open positions.

**Response:**
```json
{
  "positions": [
    {
      "symbol": "ETHUSDT",
      "exchange": "Delta",
      "direction": "LONG",
      "entry_price": 3200.0,
      "size_usd": 50.0,
      "leverage": 20,
      "stop_loss": 0.02,
      "take_profit": 0.03,
      "entry_time": "2025-12-22T14:00:00",
      "unrealized_pnl": 2.5,
      "unrealized_pnl_pct": 2.5
    }
  ]
}
```

---

### POST /api/mode

Switch trading mode between PAPER and LIVE.

**Request Body:**
```json
{
  "mode": "LIVE"
}
```

**Response:**
```json
{
  "success": true,
  "mode": "LIVE",
  "message": "Trading mode switched to LIVE"
}
```

---

### GET /api/metrics

Returns performance metrics.

**Response:**
```json
{
  "total_trades": 100,
  "win_rate": 45.0,
  "avg_win": 25.50,
  "avg_loss": -15.30,
  "profit_factor": 1.67,
  "max_drawdown": 8.5,
  "sharpe_ratio": 1.2,
  "best_trade": 150.0,
  "worst_trade": -45.0
}
```

---

### POST /api/close/:symbol

Manually close a position.

**URL Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| symbol | string | Trading pair (e.g., BTCUSDT) |

**Response:**
```json
{
  "success": true,
  "message": "Position BTCUSDT closed",
  "pnl": 12.50
}
```

---

### GET /api/health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "uptime": 3600,
  "last_scan": "2025-12-22T15:00:00",
  "websocket": "connected"
}
```

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "error": true,
  "message": "Description of the error",
  "code": "ERROR_CODE"
}
```

### Error Codes
| Code | Description |
|------|-------------|
| `INVALID_MODE` | Invalid trading mode specified |
| `POSITION_NOT_FOUND` | Position does not exist |
| `STATE_ERROR` | Error reading state file |
| `EXCHANGE_ERROR` | Exchange API error |

---

## Rate Limits

- Dashboard API: 60 requests/minute
- Mode switching: 1 request/minute

---

## WebSocket Events (Future)

```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:5000/ws');

// Events
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch(data.type) {
    case 'position_opened':
      // New position opened
      break;
    case 'position_closed':
      // Position closed
      break;
    case 'status_update':
      // Regular status update
      break;
  }
};
```
