# API Reference

## Overview

The AI Forex Trading Bot provides a comprehensive REST API for monitoring, configuration, and control. This document describes all available endpoints, request/response formats, and usage examples.

## Base URL

```
http://localhost:8080/api/v1
```

## Authentication

Currently, the API uses API key authentication. Include your API key in the request headers:

```http
Authorization: Bearer YOUR_API_KEY
```

## Response Format

All API responses follow a consistent format:

```json
{
  "success": true,
  "data": {},
  "message": "Operation completed successfully",
  "timestamp": "2024-01-01T00:00:00Z",
  "request_id": "req_123456789"
}
```

### Error Response Format

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request parameters",
    "details": {}
  },
  "timestamp": "2024-01-01T00:00:00Z",
  "request_id": "req_123456789"
}
```

## Health Endpoints

### GET /health

Basic health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "version": "1.0.0",
  "uptime": 3600
}
```

### GET /health/detailed

Detailed health information including component status.

**Response:**
```json
{
  "status": "healthy",
  "components": {
    "database": {
      "status": "healthy",
      "response_time": 5,
      "last_check": "2024-01-01T00:00:00Z"
    },
    "redis": {
      "status": "healthy",
      "response_time": 2,
      "last_check": "2024-01-01T00:00:00Z"
    },
    "llm_api": {
      "status": "healthy",
      "response_time": 150,
      "last_check": "2024-01-01T00:00:00Z"
    },
    "broker_api": {
      "status": "healthy",
      "response_time": 80,
      "last_check": "2024-01-01T00:00:00Z"
    }
  },
  "system": {
    "cpu_usage": 45.2,
    "memory_usage": 68.5,
    "disk_usage": 23.7
  }
}
```

### GET /metrics

Prometheus-compatible metrics endpoint.

**Response:**
```
# HELP trading_bot_trades_total Total number of trades executed
# TYPE trading_bot_trades_total counter
trading_bot_trades_total 1234

# HELP trading_bot_pnl_total Total profit and loss
# TYPE trading_bot_pnl_total gauge
trading_bot_pnl_total 5678.90
```

## Trading Endpoints

### GET /api/v1/trades

Retrieve trading history.

**Parameters:**
- `limit` (optional): Number of trades to return (default: 100, max: 1000)
- `offset` (optional): Number of trades to skip (default: 0)
- `symbol` (optional): Filter by currency pair
- `start_date` (optional): Start date (ISO 8601 format)
- `end_date` (optional): End date (ISO 8601 format)
- `status` (optional): Filter by trade status (open, closed, cancelled)

**Example Request:**
```http
GET /api/v1/trades?limit=50&symbol=EURUSD&status=closed
```

**Response:**
```json
{
  "success": true,
  "data": {
    "trades": [
      {
        "trade_id": "trade_123456",
        "symbol": "EURUSD",
        "direction": "long",
        "entry_price": 1.0850,
        "exit_price": 1.0875,
        "quantity": 10000,
        "pnl": 250.00,
        "status": "closed",
        "opened_at": "2024-01-01T10:00:00Z",
        "closed_at": "2024-01-01T11:30:00Z",
        "stop_loss": 1.0820,
        "take_profit": 1.0900,
        "commission": 2.50
      }
    ],
    "total_count": 1234,
    "page_info": {
      "has_next": true,
      "has_previous": false,
      "current_page": 1,
      "total_pages": 25
    }
  }
}
```

### GET /api/v1/positions

Get current open positions.

**Response:**
```json
{
  "success": true,
  "data": {
    "positions": [
      {
        "position_id": "pos_123456",
        "symbol": "EURUSD",
        "direction": "long",
        "quantity": 10000,
        "entry_price": 1.0850,
        "current_price": 1.0865,
        "unrealized_pnl": 150.00,
        "stop_loss": 1.0820,
        "take_profit": 1.0900,
        "opened_at": "2024-01-01T10:00:00Z"
      }
    ],
    "total_positions": 5,
    "total_exposure": 50000,
    "total_unrealized_pnl": 750.00
  }
}
```

### GET /api/v1/signals

Get recent trading signals.

**Parameters:**
- `limit` (optional): Number of signals to return (default: 50)
- `symbol` (optional): Filter by currency pair
- `confidence_min` (optional): Minimum confidence level (0.0-1.0)

**Response:**
```json
{
  "success": true,
  "data": {
    "signals": [
      {
        "signal_id": "sig_123456",
        "symbol": "EURUSD",
        "direction": "long",
        "confidence": 0.85,
        "entry_price": 1.0850,
        "stop_loss": 1.0820,
        "take_profit": 1.0900,
        "reasoning": "Strong bullish sentiment combined with technical breakout",
        "created_at": "2024-01-01T10:00:00Z",
        "status": "executed"
      }
    ]
  }
}
```

### POST /api/v1/signals

Create a manual trading signal.

**Request Body:**
```json
{
  "symbol": "EURUSD",
  "direction": "long",
  "confidence": 0.80,
  "entry_price": 1.0850,
  "stop_loss": 1.0820,
  "take_profit": 1.0900,
  "reasoning": "Manual signal based on market analysis"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "signal_id": "sig_789012",
    "status": "created",
    "message": "Signal created successfully"
  }
}
```

## Performance Endpoints

### GET /api/v1/performance

Get performance summary.

**Parameters:**
- `period` (optional): Time period (1d, 7d, 30d, 90d, 1y, all)

**Response:**
```json
{
  "success": true,
  "data": {
    "summary": {
      "total_trades": 1234,
      "winning_trades": 741,
      "losing_trades": 493,
      "win_rate": 0.60,
      "total_pnl": 12500.00,
      "sharpe_ratio": 1.85,
      "max_drawdown": 0.12,
      "current_drawdown": 0.03
    },
    "daily_returns": [
      {
        "date": "2024-01-01",
        "pnl": 250.00,
        "trades": 5,
        "win_rate": 0.80
      }
    ],
    "period": "30d"
  }
}
```

### GET /api/v1/performance/detailed

Get detailed performance metrics.

**Response:**
```json
{
  "success": true,
  "data": {
    "metrics": {
      "total_return": 0.125,
      "annualized_return": 0.15,
      "volatility": 0.08,
      "sharpe_ratio": 1.85,
      "sortino_ratio": 2.10,
      "calmar_ratio": 1.25,
      "max_drawdown": 0.12,
      "max_drawdown_duration": 15,
      "profit_factor": 1.65,
      "average_win": 125.50,
      "average_loss": -75.25,
      "largest_win": 500.00,
      "largest_loss": -250.00
    },
    "by_symbol": {
      "EURUSD": {
        "trades": 456,
        "pnl": 5600.00,
        "win_rate": 0.62
      },
      "GBPUSD": {
        "trades": 389,
        "pnl": 4200.00,
        "win_rate": 0.58
      }
    }
  }
}
```

## Configuration Endpoints

### GET /api/v1/config

Get current configuration.

**Response:**
```json
{
  "success": true,
  "data": {
    "trading": {
      "enabled": true,
      "max_positions": 10,
      "max_risk_per_trade": 0.02,
      "supported_pairs": ["EURUSD", "GBPUSD", "USDJPY"]
    },
    "risk_management": {
      "max_drawdown": 0.15,
      "stop_loss_pct": 0.02,
      "take_profit_pct": 0.04
    },
    "analysis": {
      "sentiment_threshold": 0.6,
      "technical_indicators": ["sma_20", "rsi", "macd"]
    }
  }
}
```

### PUT /api/v1/config

Update configuration.

**Request Body:**
```json
{
  "trading": {
    "max_positions": 15,
    "max_risk_per_trade": 0.025
  },
  "risk_management": {
    "max_drawdown": 0.20
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Configuration updated successfully",
    "changes_applied": 3,
    "restart_required": false
  }
}
```

## Monitoring Endpoints

### GET /api/v1/alerts

Get active alerts.

**Parameters:**
- `level` (optional): Filter by alert level (info, warning, error, critical)
- `limit` (optional): Number of alerts to return

**Response:**
```json
{
  "success": true,
  "data": {
    "alerts": [
      {
        "alert_id": "alert_123456",
        "level": "warning",
        "title": "High Drawdown",
        "message": "Current drawdown (8.5%) approaching limit (15%)",
        "created_at": "2024-01-01T10:00:00Z",
        "acknowledged": false,
        "source": "risk_monitor"
      }
    ],
    "summary": {
      "total": 5,
      "critical": 0,
      "error": 1,
      "warning": 3,
      "info": 1
    }
  }
}
```

### POST /api/v1/alerts/{alert_id}/acknowledge

Acknowledge an alert.

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Alert acknowledged successfully"
  }
}
```

### GET /api/v1/logs

Get application logs.

**Parameters:**
- `level` (optional): Log level (debug, info, warning, error)
- `limit` (optional): Number of log entries
- `start_time` (optional): Start time filter
- `end_time` (optional): End time filter

**Response:**
```json
{
  "success": true,
  "data": {
    "logs": [
      {
        "timestamp": "2024-01-01T10:00:00Z",
        "level": "info",
        "message": "Trade executed successfully",
        "module": "execution_engine",
        "trade_id": "trade_123456"
      }
    ],
    "total_count": 5000
  }
}
```

## System Control Endpoints

### POST /api/v1/system/start

Start the trading system.

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Trading system started successfully",
    "status": "running"
  }
}
```

### POST /api/v1/system/stop

Stop the trading system.

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Trading system stopped successfully",
    "status": "stopped"
  }
}
```

### POST /api/v1/system/restart

Restart the trading system.

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Trading system restarted successfully",
    "status": "running"
  }
}
```

## Error Codes

| Code | Description |
|------|-------------|
| `VALIDATION_ERROR` | Request validation failed |
| `AUTHENTICATION_ERROR` | Invalid or missing API key |
| `AUTHORIZATION_ERROR` | Insufficient permissions |
| `NOT_FOUND` | Resource not found |
| `RATE_LIMIT_EXCEEDED` | API rate limit exceeded |
| `INTERNAL_ERROR` | Internal server error |
| `SERVICE_UNAVAILABLE` | Service temporarily unavailable |
| `TRADING_DISABLED` | Trading is currently disabled |
| `INSUFFICIENT_FUNDS` | Insufficient account balance |
| `INVALID_SYMBOL` | Unsupported currency pair |

## Rate Limits

- **General API**: 1000 requests per hour
- **Trading Operations**: 100 requests per minute
- **Configuration Changes**: 10 requests per minute
- **Logs and Monitoring**: 500 requests per hour

## WebSocket API

### Connection

```javascript
const ws = new WebSocket('ws://localhost:8080/ws');
```

### Subscription

```json
{
  "action": "subscribe",
  "channels": ["trades", "signals", "alerts", "performance"]
}
```

### Real-time Updates

```json
{
  "channel": "trades",
  "type": "trade_executed",
  "data": {
    "trade_id": "trade_123456",
    "symbol": "EURUSD",
    "direction": "long",
    "price": 1.0850,
    "quantity": 10000,
    "timestamp": "2024-01-01T10:00:00Z"
  }
}
```

## SDK Examples

### Python SDK

```python
import requests

class TradingBotAPI:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.headers = {'Authorization': f'Bearer {api_key}'}
    
    def get_trades(self, limit=100, symbol=None):
        params = {'limit': limit}
        if symbol:
            params['symbol'] = symbol
        
        response = requests.get(
            f'{self.base_url}/api/v1/trades',
            headers=self.headers,
            params=params
        )
        return response.json()
    
    def create_signal(self, signal_data):
        response = requests.post(
            f'{self.base_url}/api/v1/signals',
            headers=self.headers,
            json=signal_data
        )
        return response.json()

# Usage
api = TradingBotAPI('http://localhost:8080', 'your_api_key')
trades = api.get_trades(limit=50, symbol='EURUSD')
```

### JavaScript SDK

```javascript
class TradingBotAPI {
    constructor(baseUrl, apiKey) {
        this.baseUrl = baseUrl;
        this.headers = {
            'Authorization': `Bearer ${apiKey}`,
            'Content-Type': 'application/json'
        };
    }
    
    async getTrades(options = {}) {
        const params = new URLSearchParams(options);
        const response = await fetch(
            `${this.baseUrl}/api/v1/trades?${params}`,
            { headers: this.headers }
        );
        return response.json();
    }
    
    async createSignal(signalData) {
        const response = await fetch(
            `${this.baseUrl}/api/v1/signals`,
            {
                method: 'POST',
                headers: this.headers,
                body: JSON.stringify(signalData)
            }
        );
        return response.json();
    }
}

// Usage
const api = new TradingBotAPI('http://localhost:8080', 'your_api_key');
const trades = await api.getTrades({ limit: 50, symbol: 'EURUSD' });
```

## Testing

### API Testing with curl

```bash
# Health check
curl -X GET http://localhost:8080/health

# Get trades
curl -X GET \
  -H "Authorization: Bearer YOUR_API_KEY" \
  "http://localhost:8080/api/v1/trades?limit=10"

# Create signal
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "EURUSD",
    "direction": "long",
    "confidence": 0.80,
    "entry_price": 1.0850
  }' \
  http://localhost:8080/api/v1/signals
```

### Postman Collection

A Postman collection is available at `docs/postman_collection.json` with pre-configured requests for all endpoints.

## Support

For API support:
1. Check the health endpoints for system status
2. Review the error codes and messages
3. Check the logs endpoint for detailed error information
4. Refer to this documentation for proper usage
5. Contact support with specific error details

## Changelog

### v1.0.0
- Initial API release
- Basic trading and monitoring endpoints
- WebSocket support for real-time updates
- Authentication and rate limiting