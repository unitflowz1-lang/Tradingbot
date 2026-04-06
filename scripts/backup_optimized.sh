#!/bin/bash
# Optimized Backup Script for AI Forex Trading Bot

set -e

BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Starting optimized backup process..."

# Database backup with compression
echo "Backing up database..."
docker-compose exec -T postgres pg_dump -U forex_user forex_bot_prod | gzip > "$BACKUP_DIR/database.sql.gz"

# Configuration backup
echo "Backing up configuration..."
tar -czf "$BACKUP_DIR/config.tar.gz" config/

# Logs backup (last 7 days only)
echo "Backing up recent logs..."
find logs/ -name "*.log" -mtime -7 -exec tar -czf "$BACKUP_DIR/logs.tar.gz" {} +

# Trading data backup
echo "Backing up trading data..."
if [ -d "data/" ]; then
    tar -czf "$BACKUP_DIR/data.tar.gz" data/
fi

# Cleanup old backups (keep last 30 days)
echo "Cleaning up old backups..."
find backups/ -type d -mtime +30 -exec rm -rf {} +

echo "Backup completed: $BACKUP_DIR"
echo "Backup size: $(du -sh $BACKUP_DIR | cut -f1)"
