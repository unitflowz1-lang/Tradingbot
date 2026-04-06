# AI Forex Trading Bot - Production Deployment Guide

This guide provides comprehensive instructions for deploying the AI Forex Trading Bot to production environments.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Setup](#environment-setup)
3. [Configuration](#configuration)
4. [Database Setup](#database-setup)
5. [Docker Deployment](#docker-deployment)
6. [Health Checks](#health-checks)
7. [Monitoring Setup](#monitoring-setup)
8. [Security Configuration](#security-configuration)
9. [Backup Strategy](#backup-strategy)
10. [Troubleshooting](#troubleshooting)
11. [Maintenance](#maintenance)

## Prerequisites

### System Requirements

- **Operating System**: Linux (Ubuntu 20.04+ recommended) or macOS
- **Docker**: Version 20.10+ with Docker Compose
- **Python**: 3.12+ (for local development and testing)
- **Memory**: Minimum 4GB RAM, 8GB+ recommended
- **Storage**: Minimum 20GB free space
- **Network**: Stable internet connection for API access

### Required Accounts and API Keys

1. **LLM Provider** (OpenAI, Anthropic, etc.)
   - API key for sentiment analysis
   - Rate limits and quotas configured

2. **Broker Account**
   - API credentials for trade execution
   - Sandbox environment for testing
   - Real account for production

3. **Data Providers**
   - Market data API keys (Alpha Vantage, Polygon, etc.)
   - News data API keys (NewsAPI, etc.)
   - Social media API access (if applicable)

4. **Monitoring Services** (Optional)
   - Email service for alerts
   - Webhook endpoints
   - Slack integration

## Environment Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd TradingBot
```

### 2. Set Environment Variables

Create a `.env` file in the project root:

```bash
# Database Configuration
DB_PASSWORD=your_secure_db_password

# LLM Configuration
LLM_API_KEY=your_llm_api_key

# Broker Configuration
BROKER_API_KEY=your_broker_api_key
BROKER_API_SECRET=your_broker_api_secret

# Email Configuration (for alerts)
SMTP_HOST=smtp.gmail.com
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
FROM_EMAIL=your_email@gmail.com
ADMIN_EMAIL=admin@yourdomain.com

# Optional: Webhook and Slack
WEBHOOK_URL=https://your-webhook-url.com
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/your/webhook/url
```

### 3. Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install additional deployment dependencies
pip install docker requests pyyaml
```

## Configuration

### 1. Production Configuration

The production configuration is located in `config/config.prod.json`. Key settings to review:

- **Trading Parameters**: Adjust risk management settings
- **API Rate Limits**: Configure based on your provider limits
- **Monitoring**: Set up alert thresholds
- **Security**: Configure authentication and encryption

### 2. Validate Configuration

```bash
# Run configuration validation
python -c "from src.config import get_config_manager; print(get_config_manager().get_validation_summary())"
```

## Database Setup

### 1. Initialize Database

```bash
# Start database container
docker-compose up -d postgres

# Wait for database to be ready
sleep 10

# Run database initialization
docker-compose exec -T postgres psql -U forex_user -d forex_bot_prod -f /docker-entrypoint-initdb.d/init-db.sql
```

### 2. Verify Database Connection

```bash
# Test database connectivity
docker-compose exec postgres pg_isready -U forex_user -d forex_bot_prod
```

## Docker Deployment

### 1. Build Docker Image

```bash
# Build the production image
docker build -t ai-forex-trading-bot:latest --target production .
```

### 2. Deploy with Docker Compose

```bash
# Deploy all services
docker-compose up -d

# Check service status
docker-compose ps
```

### 3. Verify Deployment

```bash
# Check container logs
docker-compose logs forex-bot

# Check container health
docker-compose ps
```

## Health Checks

### 1. Application Health

```bash
# Check application health endpoint
curl http://localhost:8080/health

# Expected response:
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00Z",
  "version": "1.0.0"
}
```

### 2. Database Health

```bash
# Check database connectivity
docker-compose exec postgres pg_isready -U forex_user -d forex_bot_prod
```

### 3. Redis Health

```bash
# Check Redis connectivity
docker-compose exec redis redis-cli ping
```

### 4. Automated Health Checks

The deployment script includes comprehensive health checks:

```bash
# Run automated deployment with health checks
python scripts/deploy_production.py
```

## Monitoring Setup

### 1. Performance Monitoring

The system automatically collects:
- Trading performance metrics
- System resource usage
- API response times
- Error rates

### 2. Alert Configuration

Configure alerts in `config/config.prod.json`:

```json
{
  "monitoring": {
    "alerts": {
      "rules": {
        "high_error_rate": {
          "threshold": 0.1,
          "level": "error"
        },
        "high_drawdown": {
          "threshold": 0.15,
          "level": "warning"
        }
      }
    }
  }
}
```

### 3. Log Monitoring

```bash
# Monitor application logs
docker-compose logs -f forex-bot

# Monitor error logs
tail -f logs/errors.log

# Monitor trading logs
tail -f logs/trading.log
```

## Security Configuration

### 1. Network Security

```bash
# Configure firewall (Ubuntu/Debian)
sudo ufw allow 8080/tcp
sudo ufw allow 5432/tcp
sudo ufw enable
```

### 2. SSL/TLS Configuration

For production, configure SSL certificates:

```bash
# Create certificates directory
mkdir -p certs

# Add your SSL certificates
cp your-cert.pem certs/
cp your-key.pem certs/
```

### 3. API Security

- Use strong API keys
- Implement rate limiting
- Enable input validation
- Configure CORS properly

## Backup Strategy

### 1. Automated Backups

The system includes automated backup scripts:

```bash
# Run manual backup
./scripts/backup.sh

# Setup automated daily backups
crontab -e
# Add: 0 2 * * * /path/to/TradingBot/scripts/backup.sh
```

### 2. Backup Contents

- Database dumps
- Configuration files
- Log files
- Trading data

### 3. Backup Verification

```bash
# Verify backup integrity
docker-compose exec postgres pg_restore --list /backups/latest.sql
```

## Troubleshooting

### Common Issues

#### 1. Container Won't Start

```bash
# Check container logs
docker-compose logs forex-bot

# Check resource usage
docker stats

# Restart container
docker-compose restart forex-bot
```

#### 2. Database Connection Issues

```bash
# Check database status
docker-compose exec postgres pg_isready

# Check database logs
docker-compose logs postgres

# Reset database (WARNING: Data loss)
docker-compose down
docker volume rm tradingbot_postgres_data
docker-compose up -d postgres
```

#### 3. API Rate Limiting

```bash
# Check API usage
curl http://localhost:8080/metrics

# Adjust rate limits in configuration
# Restart application
docker-compose restart forex-bot
```

#### 4. Memory Issues

```bash
# Check memory usage
docker stats

# Increase memory limits in docker-compose.yml
# Restart containers
docker-compose down && docker-compose up -d
```

### Debug Mode

Enable debug mode for troubleshooting:

```bash
# Set debug environment variable
export DEBUG=true

# Restart application
docker-compose restart forex-bot
```

## Maintenance

### 1. Regular Maintenance Tasks

#### Daily
- Monitor system health
- Check trading performance
- Review error logs

#### Weekly
- Run performance analysis
- Update dependencies
- Review backup integrity

#### Monthly
- Security updates
- Configuration review
- Performance optimization

### 2. Update Procedures

```bash
# Pull latest code
git pull origin main

# Rebuild and deploy
docker-compose down
docker build -t ai-forex-trading-bot:latest .
docker-compose up -d

# Run health checks
python scripts/deploy_production.py --dry-run
```

### 3. Scaling

#### Horizontal Scaling

```bash
# Scale application instances
docker-compose up -d --scale forex-bot=3
```

#### Vertical Scaling

Update resource limits in `docker-compose.yml`:

```yaml
services:
  forex-bot:
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: '2.0'
```

### 4. Performance Optimization

#### Database Optimization

```sql
-- Analyze table performance
ANALYZE;

-- Create indexes for frequently queried columns
CREATE INDEX idx_trades_timestamp ON trades(timestamp);
CREATE INDEX idx_signals_symbol ON signals(symbol);
```

#### Application Optimization

- Monitor memory usage
- Optimize API calls
- Implement caching strategies
- Review logging levels

## Production Checklist

Before going live, ensure:

- [ ] All environment variables are set
- [ ] Configuration is validated
- [ ] Database is initialized
- [ ] Health checks are passing
- [ ] Monitoring is configured
- [ ] Alerts are working
- [ ] Backups are scheduled
- [ ] Security measures are in place
- [ ] SSL certificates are configured
- [ ] Rate limits are appropriate
- [ ] Error handling is tested
- [ ] Performance is acceptable
- [ ] Documentation is complete

## Support

For deployment issues:

1. Check the logs: `docker-compose logs`
2. Review this documentation
3. Run health checks: `python scripts/deploy_production.py --dry-run`
4. Check system resources: `docker stats`
5. Verify configuration: `python -c "from src.config import get_config_manager; print(get_config_manager().get_validation_summary())"`

## Security Notes

- Never commit API keys to version control
- Use strong passwords for all services
- Regularly update dependencies
- Monitor for security vulnerabilities
- Implement proper access controls
- Use HTTPS in production
- Regular security audits

## Performance Notes

- Monitor resource usage regularly
- Optimize database queries
- Implement caching where appropriate
- Use connection pooling
- Monitor API rate limits
- Regular performance testing

---

**Important**: This is a financial trading system. Always test thoroughly in a sandbox environment before deploying to production with real money. Monitor the system continuously and have proper risk management in place.