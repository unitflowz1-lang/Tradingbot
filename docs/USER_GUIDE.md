# AI Forex Trading Bot - User Guide

## Table of Contents

1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Configuration](#configuration)
4. [Operating the Bot](#operating-the-bot)
5. [Monitoring Performance](#monitoring-performance)
6. [Risk Management](#risk-management)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Features](#advanced-features)
9. [Best Practices](#best-practices)
10. [FAQ](#faq)

## Introduction

The AI Forex Trading Bot is an automated trading system that combines artificial intelligence, sentiment analysis, and technical analysis to make informed trading decisions in the forex market. This guide will help you set up, configure, and operate the bot effectively.

### Key Features

- **AI-Powered Analysis**: Uses Large Language Models (LLMs) for sentiment analysis
- **Technical Analysis**: Comprehensive technical indicators and pattern recognition
- **Risk Management**: Advanced position sizing and drawdown protection
- **Real-time Monitoring**: Performance tracking and alerting system
- **Multi-Currency Support**: Trade major forex pairs
- **Backtesting**: Test strategies on historical data

### System Requirements

- **Hardware**: Minimum 4GB RAM, 8GB recommended
- **Operating System**: Linux, macOS, or Windows
- **Internet**: Stable broadband connection
- **Accounts**: Broker account, LLM API access

## Getting Started

### 1. Initial Setup

#### Prerequisites
Before starting, ensure you have:
- Docker and Docker Compose installed
- API keys for your chosen LLM provider (OpenAI, Anthropic, etc.)
- Broker API credentials
- Email account for alerts (optional)

#### Installation Steps

1. **Download and Extract**
   ```bash
   # Download the trading bot package
   # Extract to your desired directory
   cd TradingBot
   ```

2. **Environment Configuration**
   ```bash
   # Copy the example environment file
   cp .env.example .env
   
   # Edit the environment file with your credentials
   nano .env
   ```

3. **Configure Environment Variables**
   ```bash
   # Database
   DB_PASSWORD=your_secure_password
   
   # LLM Provider (OpenAI example)
   LLM_API_KEY=sk-your-openai-api-key
   
   # Broker (example)
   BROKER_API_KEY=your_broker_api_key
   BROKER_API_SECRET=your_broker_secret
   
   # Email Alerts (optional)
   SMTP_HOST=smtp.gmail.com
   SMTP_USERNAME=your_email@gmail.com
   SMTP_PASSWORD=your_app_password
   FROM_EMAIL=your_email@gmail.com
   ADMIN_EMAIL=admin@yourdomain.com
   ```

4. **Start the System**
   ```bash
   # Start all services
   docker-compose up -d
   
   # Check status
   docker-compose ps
   
   # View logs
   docker-compose logs -f forex-bot
   ```

5. **Verify Installation**
   ```bash
   # Check system health
   curl http://localhost:8080/health
   
   # Expected response:
   # {"status": "healthy", "timestamp": "...", "version": "1.0.0"}
   ```

### 2. First-Time Configuration

#### Access the Configuration Interface

The bot can be configured through:
- Configuration files in the `config/` directory
- Environment variables
- API endpoints (for runtime changes)

#### Basic Configuration

Edit `config/config.prod.json` for production settings:

```json
{
  "trading": {
    "enabled": true,
    "max_positions": 5,
    "max_risk_per_trade": 0.02,
    "supported_pairs": ["EURUSD", "GBPUSD", "USDJPY"],
    "trading_hours": {
      "start": "00:00",
      "end": "23:59",
      "timezone": "UTC"
    }
  },
  "risk_management": {
    "max_drawdown": 0.15,
    "stop_loss_pct": 0.02,
    "take_profit_pct": 0.04,
    "position_sizing_method": "fixed_fractional"
  },
  "analysis": {
    "sentiment": {
      "confidence_threshold": 0.6,
      "sources": ["news", "social_media"]
    },
    "technical": {
      "indicators": ["sma_20", "sma_50", "rsi", "macd"],
      "timeframes": ["1h", "4h", "1d"]
    }
  }
}
```

## Configuration

### Trading Configuration

#### Supported Currency Pairs
The bot supports major forex pairs:
- **EUR/USD**: Euro vs US Dollar
- **GBP/USD**: British Pound vs US Dollar
- **USD/JPY**: US Dollar vs Japanese Yen
- **USD/CHF**: US Dollar vs Swiss Franc
- **AUD/USD**: Australian Dollar vs US Dollar
- **USD/CAD**: US Dollar vs Canadian Dollar

#### Position Limits
```json
{
  "trading": {
    "max_positions": 10,           // Maximum open positions
    "max_daily_trades": 50,        // Maximum trades per day
    "max_risk_per_trade": 0.02,    // 2% risk per trade
    "min_confidence": 0.7          // Minimum signal confidence
  }
}
```

#### Trading Hours
```json
{
  "trading_hours": {
    "monday": {"start": "00:00", "end": "23:59"},
    "tuesday": {"start": "00:00", "end": "23:59"},
    "wednesday": {"start": "00:00", "end": "23:59"},
    "thursday": {"start": "00:00", "end": "23:59"},
    "friday": {"start": "00:00", "end": "22:00"},
    "saturday": {"enabled": false},
    "sunday": {"start": "22:00", "end": "23:59"}
  }
}
```

### Risk Management Configuration

#### Position Sizing Methods

**Fixed Fractional**
```json
{
  "position_sizing": {
    "method": "fixed_fractional",
    "risk_per_trade": 0.02,        // 2% of account per trade
    "max_position_size": 0.1       // Maximum 10% of account
  }
}
```

**Kelly Criterion**
```json
{
  "position_sizing": {
    "method": "kelly_criterion",
    "win_rate": 0.6,               // Historical win rate
    "avg_win": 1.5,                // Average win ratio
    "avg_loss": 1.0,               // Average loss ratio
    "kelly_fraction": 0.25         // Use 25% of Kelly recommendation
  }
}
```

#### Stop Loss and Take Profit
```json
{
  "risk_management": {
    "stop_loss": {
      "method": "atr",             // ATR-based or fixed percentage
      "atr_multiplier": 2.0,       // 2x ATR for stop loss
      "fixed_percentage": 0.02     // Or 2% fixed stop loss
    },
    "take_profit": {
      "method": "risk_reward",     // Risk-reward ratio
      "ratio": 2.0,                // 2:1 reward to risk ratio
      "trailing": true             // Enable trailing take profit
    }
  }
}
```

### Analysis Configuration

#### Sentiment Analysis
```json
{
  "sentiment": {
    "llm_provider": "openai",      // openai, anthropic, etc.
    "model": "gpt-4",              // Model to use
    "confidence_threshold": 0.6,    // Minimum confidence
    "sources": {
      "news": {
        "enabled": true,
        "weight": 0.6,             // 60% weight for news
        "max_age_hours": 24        // Consider news up to 24h old
      },
      "social_media": {
        "enabled": true,
        "weight": 0.4,             // 40% weight for social media
        "max_age_hours": 6         // Consider posts up to 6h old
      }
    }
  }
}
```

#### Technical Analysis
```json
{
  "technical": {
    "indicators": {
      "sma_20": {"enabled": true, "weight": 0.2},
      "sma_50": {"enabled": true, "weight": 0.2},
      "rsi": {"enabled": true, "weight": 0.3, "period": 14},
      "macd": {"enabled": true, "weight": 0.3}
    },
    "patterns": {
      "support_resistance": {"enabled": true, "weight": 0.4},
      "trend_lines": {"enabled": true, "weight": 0.3},
      "chart_patterns": {"enabled": true, "weight": 0.3}
    }
  }
}
```

## Operating the Bot

### Starting and Stopping

#### Start the Bot
```bash
# Start all services
docker-compose up -d

# Start only the trading bot
docker-compose up -d forex-bot

# Start with logs visible
docker-compose up forex-bot
```

#### Stop the Bot
```bash
# Stop all services
docker-compose down

# Stop only the trading bot
docker-compose stop forex-bot

# Emergency stop (immediate)
docker-compose kill forex-bot
```

#### Restart the Bot
```bash
# Restart all services
docker-compose restart

# Restart only the trading bot
docker-compose restart forex-bot
```

### Monitoring Operations

#### Check System Status
```bash
# Basic health check
curl http://localhost:8080/health

# Detailed health information
curl http://localhost:8080/health/detailed

# System metrics
curl http://localhost:8080/metrics
```

#### View Logs
```bash
# View recent logs
docker-compose logs --tail=100 forex-bot

# Follow logs in real-time
docker-compose logs -f forex-bot

# View specific log files
tail -f logs/trading.log
tail -f logs/errors.log
```

#### Check Trading Activity
```bash
# Get recent trades
curl http://localhost:8080/api/v1/trades?limit=10

# Get current positions
curl http://localhost:8080/api/v1/positions

# Get recent signals
curl http://localhost:8080/api/v1/signals?limit=10
```

### Manual Operations

#### Create Manual Signal
```bash
curl -X POST http://localhost:8080/api/v1/signals \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "EURUSD",
    "direction": "long",
    "confidence": 0.8,
    "entry_price": 1.0850,
    "stop_loss": 1.0820,
    "take_profit": 1.0900,
    "reasoning": "Manual signal based on market analysis"
  }'
```

#### Emergency Stop Trading
```bash
# Stop all trading immediately
curl -X POST http://localhost:8080/api/v1/system/stop

# Close all positions (if supported by broker)
curl -X POST http://localhost:8080/api/v1/positions/close-all
```

## Monitoring Performance

### Performance Metrics

#### Key Performance Indicators (KPIs)
- **Total Return**: Overall profit/loss percentage
- **Win Rate**: Percentage of profitable trades
- **Sharpe Ratio**: Risk-adjusted return measure
- **Maximum Drawdown**: Largest peak-to-trough decline
- **Profit Factor**: Ratio of gross profit to gross loss
- **Average Trade**: Average profit/loss per trade

#### Accessing Performance Data
```bash
# Get performance summary
curl http://localhost:8080/api/v1/performance

# Get detailed metrics
curl http://localhost:8080/api/v1/performance/detailed

# Get performance for specific period
curl http://localhost:8080/api/v1/performance?period=30d
```

### Real-time Monitoring

#### Dashboard Access
The bot provides real-time monitoring through:
- Web dashboard (if enabled): `http://localhost:8080/dashboard`
- API endpoints for custom dashboards
- Log files for detailed analysis

#### Key Metrics to Monitor
1. **Trading Performance**
   - Current P&L
   - Open positions
   - Recent trades
   - Win/loss ratio

2. **System Health**
   - CPU and memory usage
   - API response times
   - Error rates
   - Database connectivity

3. **Risk Metrics**
   - Current drawdown
   - Position exposure
   - Risk per trade
   - Correlation risk

### Alerts and Notifications

#### Email Alerts
Configure email alerts for important events:
```json
{
  "alerts": {
    "email": {
      "enabled": true,
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "username": "your_email@gmail.com",
      "password": "your_app_password",
      "from_email": "your_email@gmail.com",
      "to_emails": ["admin@yourdomain.com"]
    },
    "rules": {
      "high_drawdown": {
        "threshold": 0.10,
        "enabled": true,
        "severity": "warning"
      },
      "system_error": {
        "enabled": true,
        "severity": "critical"
      },
      "large_loss": {
        "threshold": 500.0,
        "enabled": true,
        "severity": "warning"
      }
    }
  }
}
```

#### Webhook Notifications
```json
{
  "alerts": {
    "webhook": {
      "enabled": true,
      "url": "https://your-webhook-url.com/alerts",
      "headers": {
        "Authorization": "Bearer your-token"
      }
    }
  }
}
```

## Risk Management

### Understanding Risk Parameters

#### Risk Per Trade
- **Conservative**: 1-2% per trade
- **Moderate**: 2-3% per trade
- **Aggressive**: 3-5% per trade (not recommended)

#### Maximum Drawdown
- **Conservative**: 10-15% maximum drawdown
- **Moderate**: 15-20% maximum drawdown
- **Aggressive**: 20-25% maximum drawdown

#### Position Sizing
The bot automatically calculates position sizes based on:
- Account balance
- Risk per trade setting
- Stop loss distance
- Currency pair volatility

### Risk Monitoring

#### Daily Risk Checks
```bash
# Check current risk exposure
curl http://localhost:8080/api/v1/risk/exposure

# Check drawdown status
curl http://localhost:8080/api/v1/risk/drawdown

# Check position correlation
curl http://localhost:8080/api/v1/risk/correlation
```

#### Risk Alerts
The system automatically monitors:
- **Drawdown Limits**: Alerts when approaching maximum drawdown
- **Position Limits**: Prevents exceeding maximum positions
- **Correlation Risk**: Monitors currency correlation exposure
- **Volatility Spikes**: Adjusts position sizes during high volatility

### Emergency Procedures

#### High Drawdown Response
1. **Automatic Actions**:
   - Reduce position sizes
   - Increase signal confidence threshold
   - Limit new positions

2. **Manual Actions**:
   - Review and adjust risk parameters
   - Consider temporary trading halt
   - Analyze recent trades for issues

#### System Failure Response
1. **Immediate Actions**:
   - Check all open positions
   - Verify broker connectivity
   - Review system logs

2. **Recovery Actions**:
   - Restart system components
   - Verify data integrity
   - Resume trading gradually

## Troubleshooting

### Common Issues

#### Bot Not Starting
**Symptoms**: Container exits immediately or health check fails

**Solutions**:
1. Check environment variables in `.env` file
2. Verify Docker and Docker Compose installation
3. Check port availability (8080)
4. Review container logs: `docker-compose logs forex-bot`

#### No Trading Activity
**Symptoms**: Bot runs but doesn't place trades

**Possible Causes**:
1. **Low Signal Confidence**: Signals below confidence threshold
2. **Risk Limits**: Risk management preventing trades
3. **Market Hours**: Outside configured trading hours
4. **API Issues**: Broker or data provider problems

**Solutions**:
1. Lower confidence threshold temporarily
2. Check risk management settings
3. Verify trading hours configuration
4. Test API connectivity

#### High Memory Usage
**Symptoms**: System becomes slow or crashes

**Solutions**:
1. Restart the bot: `docker-compose restart forex-bot`
2. Increase memory limits in `docker-compose.yml`
3. Check for memory leaks in logs
4. Reduce data retention periods

#### API Rate Limiting
**Symptoms**: "Rate limit exceeded" errors

**Solutions**:
1. Reduce API call frequency in configuration
2. Implement longer delays between calls
3. Upgrade API plan if necessary
4. Use caching to reduce API calls

### Getting Help

#### Log Analysis
```bash
# Check for errors
docker-compose logs forex-bot | grep -i error

# Check recent activity
tail -f logs/trading.log

# Check system performance
docker stats forex-bot
```

#### Health Diagnostics
```bash
# Run health check
curl http://localhost:8080/health/detailed

# Check database connectivity
docker-compose exec postgres pg_isready

# Check Redis connectivity
docker-compose exec redis redis-cli ping
```

#### Support Information
When contacting support, provide:
1. System information (OS, Docker version)
2. Configuration files (remove sensitive data)
3. Recent log files
4. Error messages
5. Steps to reproduce the issue

## Advanced Features

### Backtesting

#### Running Backtests
```bash
# Run backtest on historical data
python scripts/run_backtest.py \
  --start-date 2023-01-01 \
  --end-date 2023-12-31 \
  --symbols EURUSD,GBPUSD \
  --strategy default

# Generate backtest report
python scripts/generate_backtest_report.py \
  --backtest-id bt_20240101_001
```

#### Backtest Configuration
```json
{
  "backtesting": {
    "initial_balance": 10000,
    "commission": 2.5,
    "slippage": 0.0001,
    "data_source": "historical_data",
    "timeframe": "1h"
  }
}
```

### Paper Trading

#### Enable Paper Trading
```json
{
  "trading": {
    "mode": "paper",              // paper, live
    "paper_trading": {
      "initial_balance": 10000,
      "realistic_slippage": true,
      "commission_simulation": true
    }
  }
}
```

#### Monitor Paper Trading
```bash
# Check paper trading performance
curl http://localhost:8080/api/v1/paper-trading/performance

# Compare with live trading
curl http://localhost:8080/api/v1/paper-trading/comparison
```

### Custom Strategies

#### Strategy Configuration
```json
{
  "strategies": {
    "sentiment_momentum": {
      "enabled": true,
      "weight": 0.6,
      "parameters": {
        "sentiment_threshold": 0.7,
        "momentum_period": 14,
        "confirmation_required": true
      }
    },
    "mean_reversion": {
      "enabled": true,
      "weight": 0.4,
      "parameters": {
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "bollinger_period": 20
      }
    }
  }
}
```

### API Integration

#### Custom Applications
You can build custom applications using the bot's API:

```python
import requests

class TradingBotClient:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url
    
    def get_performance(self, period="30d"):
        response = requests.get(f"{self.base_url}/api/v1/performance?period={period}")
        return response.json()
    
    def get_positions(self):
        response = requests.get(f"{self.base_url}/api/v1/positions")
        return response.json()
    
    def create_signal(self, signal_data):
        response = requests.post(
            f"{self.base_url}/api/v1/signals",
            json=signal_data
        )
        return response.json()

# Usage
client = TradingBotClient()
performance = client.get_performance()
print(f"Total P&L: {performance['data']['summary']['total_pnl']}")
```

## Best Practices

### Configuration Best Practices

1. **Start Conservative**
   - Begin with low risk per trade (1-2%)
   - Use high confidence thresholds (0.7+)
   - Limit maximum positions (5-10)

2. **Gradual Optimization**
   - Make small incremental changes
   - Test changes in paper trading first
   - Monitor results for at least 1 week

3. **Regular Reviews**
   - Review performance weekly
   - Adjust parameters based on market conditions
   - Keep detailed records of changes

### Operational Best Practices

1. **Daily Monitoring**
   - Check system health every morning
   - Review overnight trading activity
   - Monitor risk metrics

2. **Weekly Analysis**
   - Analyze trading performance
   - Review and adjust risk parameters
   - Check for system updates

3. **Monthly Optimization**
   - Comprehensive performance review
   - Strategy optimization
   - System maintenance

### Risk Management Best Practices

1. **Never Risk More Than You Can Afford to Lose**
   - Only trade with risk capital
   - Set strict maximum drawdown limits
   - Have an exit strategy

2. **Diversification**
   - Trade multiple currency pairs
   - Use different timeframes
   - Don't over-concentrate positions

3. **Continuous Monitoring**
   - Set up proper alerts
   - Monitor correlation risk
   - Regular system health checks

### Security Best Practices

1. **Secure Your Credentials**
   - Use strong, unique passwords
   - Enable 2FA where possible
   - Regularly rotate API keys

2. **System Security**
   - Keep system updated
   - Use secure networks
   - Regular security audits

3. **Data Protection**
   - Regular backups
   - Secure data storage
   - Monitor access logs

## FAQ

### General Questions

**Q: How much money do I need to start?**
A: We recommend starting with at least $1,000-$5,000 to allow for proper risk management and position sizing.

**Q: What currency pairs does the bot trade?**
A: The bot supports major forex pairs including EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, and USD/CAD.

**Q: Can I run the bot on a VPS?**
A: Yes, the bot is designed to run on VPS or cloud servers. See the deployment guide for details.

### Technical Questions

**Q: How often does the bot analyze the market?**
A: The bot continuously monitors market data and news feeds, typically analyzing new information within minutes of availability.

**Q: Can I customize the trading strategy?**
A: Yes, the bot allows extensive customization through configuration files and supports multiple trading strategies.

**Q: What happens if my internet connection is lost?**
A: The bot includes reconnection logic and will attempt to reconnect automatically. Open positions remain with the broker.

### Performance Questions

**Q: What kind of returns can I expect?**
A: Returns vary based on market conditions, risk settings, and configuration. Past performance doesn't guarantee future results.

**Q: How does the bot handle market volatility?**
A: The bot automatically adjusts position sizes based on volatility and can reduce trading activity during extreme market conditions.

**Q: Can I backtest strategies before going live?**
A: Yes, the bot includes comprehensive backtesting capabilities using historical data.

### Support Questions

**Q: How do I get help if something goes wrong?**
A: Check the troubleshooting guide, review logs, and use the health check endpoints. Contact support with detailed information if needed.

**Q: How often is the bot updated?**
A: Updates are released regularly with bug fixes, performance improvements, and new features. Check the changelog for details.

**Q: Is there a community or forum?**
A: Yes, check the GitHub repository for discussions, issues, and community contributions.

---

## Conclusion

This user guide provides comprehensive information for operating the AI Forex Trading Bot effectively. Remember that forex trading involves substantial risk, and you should never trade with money you cannot afford to lose. Always start with paper trading or small amounts to familiarize yourself with the system before scaling up.

For additional support, refer to the other documentation files:
- [API Reference](API_REFERENCE.md)
- [System Architecture](SYSTEM_ARCHITECTURE.md)
- [Troubleshooting Guide](TROUBLESHOOTING_GUIDE.md)
- [Performance Optimization](PERFORMANCE_OPTIMIZATION.md)

Happy trading! 🚀