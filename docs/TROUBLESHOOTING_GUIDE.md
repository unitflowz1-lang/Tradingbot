# Troubleshooting Guide

## Overview

This guide provides comprehensive troubleshooting procedures for the AI Forex Trading Bot. It covers common issues, diagnostic procedures, and resolution steps to help maintain optimal system performance.

## Quick Diagnostic Checklist

Before diving into specific issues, run this quick diagnostic checklist:

```bash
# 1. Check system health
curl http://localhost:8080/health

# 2. Check container status
docker-compose ps

# 3. Check logs for errors
docker-compose logs --tail=50 forex-bot | grep -i error

# 4. Check resource usage
docker stats --no-stream

# 5. Check database connectivity
docker-compose exec postgres pg_isready -U forex_user -d forex_bot_prod

# 6. Check Redis connectivity
docker-compose exec redis redis-cli ping
```

## Common Issues and Solutions

### 1. Application Won't Start

#### Symptoms
- Container exits immediately
- Health check returns connection refused
- No response from API endpoints

#### Diagnostic Steps
```bash
# Check container logs
docker-compose logs forex-bot

# Check container status
docker-compose ps

# Check resource usage
docker stats

# Check port availability
netstat -tulpn | grep :8080
```

#### Common Causes and Solutions

**Missing Environment Variables**
```bash
# Check if .env file exists
ls -la .env

# Validate environment variables
docker-compose config

# Solution: Create or update .env file
cp .env.example .env
# Edit .env with proper values
```

**Database Connection Issues**
```bash
# Check database status
docker-compose exec postgres pg_isready

# Check database logs
docker-compose logs postgres

# Solution: Restart database
docker-compose restart postgres
```

**Port Conflicts**
```bash
# Check what's using port 8080
lsof -i :8080

# Solution: Change port in docker-compose.yml or stop conflicting service
sudo systemctl stop conflicting-service
```

**Insufficient Resources**
```bash
# Check available memory
free -h

# Check disk space
df -h

# Solution: Free up resources or increase limits
docker system prune -f
```

### 2. Database Connection Problems

#### Symptoms
- "Connection refused" errors
- Timeout errors during database operations
- Application starts but can't perform database operations

#### Diagnostic Steps
```bash
# Test database connectivity
docker-compose exec postgres pg_isready -U forex_user -d forex_bot_prod

# Check database logs
docker-compose logs postgres

# Test connection from application container
docker-compose exec forex-bot python -c "
from src.config import get_config_manager
config = get_config_manager()
print('Database connection test:', config.test_database_connection())
"

# Check database processes
docker-compose exec postgres ps aux
```

#### Solutions

**Database Not Running**
```bash
# Start database
docker-compose up -d postgres

# Check if it's healthy
docker-compose exec postgres pg_isready
```

**Wrong Connection Parameters**
```bash
# Verify connection string in .env
grep DB_ .env

# Test with correct parameters
docker-compose exec postgres psql -U forex_user -d forex_bot_prod -c "SELECT 1;"
```

**Database Corruption**
```bash
# Check database integrity
docker-compose exec postgres pg_dump forex_bot_prod > backup.sql

# If corrupted, restore from backup
docker-compose down
docker volume rm tradingbot_postgres_data
docker-compose up -d postgres
# Wait for database to initialize
sleep 30
docker-compose exec -T postgres psql -U forex_user -d forex_bot_prod < backup.sql
```

**Connection Pool Exhaustion**
```bash
# Check active connections
docker-compose exec postgres psql -U forex_user -d forex_bot_prod -c "
SELECT count(*) as active_connections 
FROM pg_stat_activity 
WHERE state = 'active';
"

# Solution: Restart application or increase pool size
docker-compose restart forex-bot
```

### 3. API Rate Limiting Issues

#### Symptoms
- "Rate limit exceeded" errors
- Slow response times
- Failed API calls to external services

#### Diagnostic Steps
```bash
# Check API usage metrics
curl http://localhost:8080/metrics | grep api_calls

# Check logs for rate limit errors
docker-compose logs forex-bot | grep -i "rate limit"

# Check external API status
curl -I https://api.openai.com/v1/models
```

#### Solutions

**LLM API Rate Limits**
```bash
# Check current usage
curl -H "Authorization: Bearer $LLM_API_KEY" \
  https://api.openai.com/v1/usage

# Solution: Implement backoff or upgrade plan
# Edit config/config.prod.json
{
  "llm": {
    "rate_limit": {
      "requests_per_minute": 50,
      "backoff_factor": 2.0
    }
  }
}
```

**Broker API Rate Limits**
```bash
# Check broker API status
# Solution: Reduce request frequency
{
  "broker": {
    "rate_limit": {
      "requests_per_second": 5,
      "burst_limit": 10
    }
  }
}
```

**News API Rate Limits**
```bash
# Solution: Implement caching
{
  "data_collection": {
    "news": {
      "cache_ttl": 3600,
      "batch_size": 10
    }
  }
}
```

### 4. High Memory Usage

#### Symptoms
- Out of memory errors
- Slow performance
- Container restarts due to memory limits

#### Diagnostic Steps
```bash
# Check memory usage
docker stats --no-stream

# Check memory usage inside container
docker-compose exec forex-bot python -c "
import psutil
process = psutil.Process()
print(f'Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB')
print(f'Memory %: {process.memory_percent():.2f}%')
"

# Check for memory leaks
docker-compose exec forex-bot python -c "
import gc
print(f'Objects in memory: {len(gc.get_objects())}')
gc.collect()
print(f'After cleanup: {len(gc.get_objects())}')
"
```

#### Solutions

**Memory Leaks**
```bash
# Enable memory profiling
export PYTHONMALLOC=debug
docker-compose restart forex-bot

# Monitor memory growth
watch -n 5 'docker stats --no-stream | grep forex-bot'
```

**Large Dataset Processing**
```python
# Use generators instead of loading all data
def process_data_stream():
    for chunk in pd.read_csv('large_file.csv', chunksize=1000):
        yield process_chunk(chunk)

# Implement data cleanup
import gc
def cleanup_memory():
    gc.collect()
    # Clear caches
    cache.clear()
```

**Increase Memory Limits**
```yaml
# docker-compose.yml
services:
  forex-bot:
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G
```

### 5. Trading Execution Issues

#### Symptoms
- Orders not being placed
- Execution delays
- Position tracking errors

#### Diagnostic Steps
```bash
# Check trading logs
docker-compose logs forex-bot | grep -i "trade\|order\|execution"

# Check broker API connectivity
curl -X GET \
  -H "Authorization: Bearer $BROKER_API_KEY" \
  https://api.broker.com/v1/account

# Check position status
curl http://localhost:8080/api/v1/positions
```

#### Solutions

**Broker API Issues**
```bash
# Test broker connectivity
python -c "
from src.trading.broker_client import BrokerClient
client = BrokerClient()
print('Broker status:', client.get_account_info())
"

# Check API credentials
grep BROKER_ .env

# Solution: Update credentials or contact broker
```

**Insufficient Funds**
```bash
# Check account balance
curl http://localhost:8080/api/v1/account/balance

# Solution: Deposit funds or reduce position sizes
{
  "risk_management": {
    "max_risk_per_trade": 0.01,
    "max_positions": 5
  }
}
```

**Order Validation Failures**
```bash
# Check order validation logs
docker-compose logs forex-bot | grep -i "validation"

# Common issues:
# - Invalid symbol
# - Minimum lot size
# - Market hours
# - Risk limits exceeded
```

### 6. Performance Issues

#### Symptoms
- Slow response times
- High CPU usage
- Delayed signal processing

#### Diagnostic Steps
```bash
# Check system performance
htop

# Check application performance
curl http://localhost:8080/metrics

# Profile application
docker-compose exec forex-bot python -m cProfile -o profile.stats main.py
```

#### Solutions

**Database Performance**
```sql
-- Check slow queries
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;

-- Add missing indexes
CREATE INDEX CONCURRENTLY idx_trades_symbol_timestamp 
ON trades(symbol, timestamp);
```

**Cache Optimization**
```python
# Implement better caching
@lru_cache(maxsize=1000)
def expensive_calculation(params):
    return result

# Use Redis for shared cache
import redis
cache = redis.Redis(host='redis', port=6379, db=0)
```

**Async Processing**
```python
# Use async for I/O operations
import asyncio
import aiohttp

async def fetch_data(session, url):
    async with session.get(url) as response:
        return await response.json()

async def process_multiple_requests():
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_data(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        return results
```

### 7. Monitoring and Alerting Issues

#### Symptoms
- Missing alerts
- Incorrect metrics
- Dashboard not updating

#### Diagnostic Steps
```bash
# Check monitoring service
curl http://localhost:8080/api/v1/alerts

# Check Prometheus metrics
curl http://localhost:8080/metrics

# Check alert system logs
docker-compose logs forex-bot | grep -i alert
```

#### Solutions

**Alert System Not Working**
```bash
# Check email configuration
python -c "
from src.monitoring.alert_system import AlertSystem
alert_system = AlertSystem()
alert_system.test_email_connection()
"

# Check webhook configuration
curl -X POST $WEBHOOK_URL -d '{"test": "message"}'
```

**Metrics Not Updating**
```bash
# Restart monitoring service
docker-compose restart forex-bot

# Check metrics collection
curl http://localhost:8080/api/v1/performance
```

## Advanced Troubleshooting

### Log Analysis

#### Centralized Logging
```bash
# Aggregate all logs
docker-compose logs > all_logs.txt

# Search for specific errors
grep -i "error\|exception\|failed" all_logs.txt

# Analyze error patterns
awk '/ERROR/ {print $0}' all_logs.txt | sort | uniq -c | sort -nr
```

#### Log Levels
```python
# Adjust log levels for debugging
import logging
logging.getLogger('src.trading').setLevel(logging.DEBUG)
logging.getLogger('src.analysis').setLevel(logging.DEBUG)
```

### Performance Profiling

#### CPU Profiling
```bash
# Profile CPU usage
docker-compose exec forex-bot python -m cProfile -o cpu_profile.stats main.py

# Analyze profile
python -c "
import pstats
p = pstats.Stats('cpu_profile.stats')
p.sort_stats('cumulative').print_stats(20)
"
```

#### Memory Profiling
```bash
# Install memory profiler
pip install memory-profiler

# Profile memory usage
docker-compose exec forex-bot python -m memory_profiler main.py
```

### Network Troubleshooting

#### Connection Testing
```bash
# Test external API connectivity
curl -v https://api.openai.com/v1/models

# Test internal service connectivity
docker-compose exec forex-bot curl -v http://postgres:5432

# Check DNS resolution
docker-compose exec forex-bot nslookup api.openai.com
```

#### Network Monitoring
```bash
# Monitor network traffic
docker-compose exec forex-bot netstat -i

# Check network connections
docker-compose exec forex-bot ss -tuln
```

## Emergency Procedures

### System Recovery

#### Complete System Restart
```bash
# Stop all services
docker-compose down

# Clean up resources
docker system prune -f

# Restart services
docker-compose up -d

# Verify health
./scripts/health_check.sh
```

#### Database Recovery
```bash
# Create backup before recovery
docker-compose exec postgres pg_dump forex_bot_prod > emergency_backup.sql

# Stop application
docker-compose stop forex-bot

# Restore from backup
docker-compose exec -T postgres psql -U forex_user -d forex_bot_prod < latest_backup.sql

# Restart application
docker-compose start forex-bot
```

#### Configuration Rollback
```bash
# Backup current config
cp config/config.prod.json config/config.prod.json.backup

# Restore previous config
git checkout HEAD~1 -- config/config.prod.json

# Restart application
docker-compose restart forex-bot
```

### Data Integrity Checks

#### Database Integrity
```sql
-- Check for data inconsistencies
SELECT 
    COUNT(*) as total_trades,
    COUNT(CASE WHEN status = 'open' THEN 1 END) as open_trades,
    COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed_trades
FROM trades;

-- Check for orphaned records
SELECT * FROM trades t 
LEFT JOIN positions p ON t.trade_id = p.trade_id 
WHERE p.trade_id IS NULL;
```

#### Cache Consistency
```bash
# Clear all caches
docker-compose exec redis redis-cli FLUSHALL

# Restart application to rebuild cache
docker-compose restart forex-bot
```

## Preventive Measures

### Regular Maintenance

#### Daily Tasks
```bash
#!/bin/bash
# daily_maintenance.sh

# Check system health
curl -f http://localhost:8080/health || exit 1

# Check disk space
df -h | awk '$5 > 80 {print "Disk usage high: " $0}'

# Check log sizes
find logs/ -name "*.log" -size +100M -exec ls -lh {} \;

# Backup database
./scripts/backup_database.sh
```

#### Weekly Tasks
```bash
#!/bin/bash
# weekly_maintenance.sh

# Update dependencies
docker-compose pull

# Clean up old logs
find logs/ -name "*.log" -mtime +7 -delete

# Analyze performance
python scripts/performance_analysis.py

# Generate health report
python scripts/health_report.py
```

### Monitoring Setup

#### Health Checks
```yaml
# docker-compose.yml
services:
  forex-bot:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

#### Automated Alerts
```python
# Alert rules
ALERT_RULES = {
    'high_error_rate': {
        'condition': lambda metrics: metrics.error_rate > 0.05,
        'severity': 'warning',
        'message': 'Error rate above 5%'
    },
    'high_drawdown': {
        'condition': lambda metrics: metrics.current_drawdown > 0.15,
        'severity': 'critical',
        'message': 'Drawdown exceeds 15%'
    },
    'system_down': {
        'condition': lambda metrics: not metrics.system_healthy,
        'severity': 'critical',
        'message': 'System health check failed'
    }
}
```

## Getting Help

### Information to Collect

When seeking help, collect the following information:

```bash
#!/bin/bash
# collect_debug_info.sh

echo "=== System Information ===" > debug_info.txt
uname -a >> debug_info.txt
docker --version >> debug_info.txt
docker-compose --version >> debug_info.txt

echo -e "\n=== Container Status ===" >> debug_info.txt
docker-compose ps >> debug_info.txt

echo -e "\n=== Recent Logs ===" >> debug_info.txt
docker-compose logs --tail=100 >> debug_info.txt

echo -e "\n=== System Resources ===" >> debug_info.txt
docker stats --no-stream >> debug_info.txt

echo -e "\n=== Configuration ===" >> debug_info.txt
docker-compose config >> debug_info.txt

echo -e "\n=== Health Status ===" >> debug_info.txt
curl -s http://localhost:8080/health/detailed >> debug_info.txt
```

### Support Channels

1. **Documentation**: Check this guide and other documentation
2. **Logs**: Review application and system logs
3. **Health Endpoints**: Use built-in diagnostic endpoints
4. **Community**: Check GitHub issues and discussions
5. **Professional Support**: Contact support team with debug information

### Best Practices for Issue Reporting

1. **Provide Context**: Describe what you were trying to do
2. **Include Logs**: Attach relevant log files
3. **System Information**: Include system specs and versions
4. **Reproduction Steps**: Provide steps to reproduce the issue
5. **Expected vs Actual**: Describe expected and actual behavior

## Conclusion

This troubleshooting guide covers the most common issues and their solutions. Regular monitoring, preventive maintenance, and following best practices will help minimize issues and ensure smooth operation of the AI Forex Trading Bot.

Remember to always backup your data before making significant changes, and test solutions in a development environment when possible.