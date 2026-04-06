#!/bin/bash

# AI Forex Trading Bot Deployment Script
# This script deploys the trading bot to a VPS or cloud server

set -e  # Exit on any error

# Configuration
APP_NAME="ai-forex-trading-bot"
APP_USER="forex-bot"
APP_DIR="/opt/${APP_NAME}"
SERVICE_NAME="${APP_NAME}"
BACKUP_DIR="/opt/backups/${APP_NAME}"
LOG_FILE="/var/log/${APP_NAME}-deploy.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

# Check if running as root
check_root() {
    if [[ $EUID -eq 0 ]]; then
        error "This script should not be run as root. Please run as a regular user with sudo privileges."
    fi
}

# Check system requirements
check_requirements() {
    log "Checking system requirements..."
    
    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed. Please install Docker first."
    fi
    
    # Check if Docker Compose is installed
    if ! command -v docker-compose &> /dev/null; then
        error "Docker Compose is not installed. Please install Docker Compose first."
    fi
    
    # Check available disk space (minimum 5GB)
    available_space=$(df / | awk 'NR==2 {print $4}')
    if [[ $available_space -lt 5242880 ]]; then  # 5GB in KB
        warning "Less than 5GB of disk space available. Consider freeing up space."
    fi
    
    success "System requirements check passed"
}

# Create application user
create_app_user() {
    log "Creating application user..."
    
    if ! id "$APP_USER" &>/dev/null; then
        sudo useradd -r -s /bin/false -d "$APP_DIR" "$APP_USER"
        success "Created user: $APP_USER"
    else
        log "User $APP_USER already exists"
    fi
}

# Create directories
create_directories() {
    log "Creating application directories..."
    
    sudo mkdir -p "$APP_DIR"
    sudo mkdir -p "$BACKUP_DIR"
    sudo mkdir -p "/var/log/${APP_NAME}"
    sudo mkdir -p "/etc/${APP_NAME}"
    
    # Set ownership
    sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"
    sudo chown -R "$APP_USER:$APP_USER" "/var/log/${APP_NAME}"
    sudo chown -R "$APP_USER:$APP_USER" "$BACKUP_DIR"
    
    success "Directories created successfully"
}

# Backup existing installation
backup_existing() {
    if [[ -d "$APP_DIR" ]] && [[ "$(ls -A $APP_DIR)" ]]; then
        log "Backing up existing installation..."
        
        backup_name="${APP_NAME}-backup-$(date +%Y%m%d-%H%M%S)"
        sudo -u "$APP_USER" cp -r "$APP_DIR" "$BACKUP_DIR/$backup_name"
        
        success "Backup created: $BACKUP_DIR/$backup_name"
    fi
}

# Deploy application files
deploy_files() {
    log "Deploying application files..."
    
    # Copy application files
    sudo -u "$APP_USER" cp -r . "$APP_DIR/"
    
    # Set correct permissions
    sudo chmod +x "$APP_DIR/scripts/"*.sh
    
    success "Application files deployed"
}

# Setup environment file
setup_environment() {
    log "Setting up environment configuration..."
    
    env_file="/etc/${APP_NAME}/.env"
    
    if [[ ! -f "$env_file" ]]; then
        sudo tee "$env_file" > /dev/null <<EOF
# AI Forex Trading Bot Environment Configuration
ENVIRONMENT=prod

# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_DATABASE=forex_bot_prod
DB_USERNAME=forex_user
DB_PASSWORD=

# LLM Configuration
LLM_API_KEY=

# Broker Configuration
BROKER_API_KEY=
BROKER_API_SECRET=

# Trading Configuration
TRADING_MAX_POSITIONS=3
TRADING_RISK_PER_TRADE=0.01
TRADING_MAX_DRAWDOWN=0.05

# Risk Management
RISK_MAX_POSITION_SIZE=0.03
RISK_DRAWDOWN_LIMIT=0.05
EOF
        
        sudo chown "$APP_USER:$APP_USER" "$env_file"
        sudo chmod 600 "$env_file"
        
        warning "Environment file created at $env_file. Please update with your actual configuration."
    else
        log "Environment file already exists at $env_file"
    fi
}

# Setup systemd service
setup_systemd_service() {
    log "Setting up systemd service..."
    
    sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null <<EOF
[Unit]
Description=AI Forex Trading Bot
After=network.target docker.service
Requires=docker.service

[Service]
Type=forking
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/${APP_NAME}/.env
ExecStart=/usr/bin/docker-compose up -d
ExecStop=/usr/bin/docker-compose down
ExecReload=/usr/bin/docker-compose restart
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload systemd and enable service
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    
    success "Systemd service configured"
}

# Setup log rotation
setup_log_rotation() {
    log "Setting up log rotation..."
    
    sudo tee "/etc/logrotate.d/${APP_NAME}" > /dev/null <<EOF
/var/log/${APP_NAME}/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 $APP_USER $APP_USER
    postrotate
        systemctl reload $SERVICE_NAME > /dev/null 2>&1 || true
    endscript
}
EOF
    
    success "Log rotation configured"
}

# Setup firewall rules
setup_firewall() {
    log "Setting up firewall rules..."
    
    if command -v ufw &> /dev/null; then
        # Allow health check port
        sudo ufw allow 8080/tcp comment "AI Forex Trading Bot Health Check"
        
        # Allow SSH (if not already allowed)
        sudo ufw allow ssh
        
        success "Firewall rules configured"
    else
        warning "UFW not found. Please configure firewall manually to allow port 8080."
    fi
}

# Build and start application
start_application() {
    log "Building and starting application..."
    
    cd "$APP_DIR"
    
    # Build Docker images
    sudo -u "$APP_USER" docker-compose build
    
    # Start services
    sudo systemctl start "$SERVICE_NAME"
    
    # Wait for services to start
    sleep 10
    
    # Check if services are running
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        success "Application started successfully"
    else
        error "Failed to start application. Check logs: journalctl -u $SERVICE_NAME"
    fi
}

# Verify deployment
verify_deployment() {
    log "Verifying deployment..."
    
    # Check health endpoint
    max_attempts=30
    attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        if curl -f http://localhost:8080/health > /dev/null 2>&1; then
            success "Health check endpoint is responding"
            break
        fi
        
        log "Waiting for health check endpoint... (attempt $attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done
    
    if [[ $attempt -gt $max_attempts ]]; then
        error "Health check endpoint is not responding after $max_attempts attempts"
    fi
    
    # Show service status
    sudo systemctl status "$SERVICE_NAME" --no-pager
}

# Main deployment function
main() {
    log "Starting deployment of AI Forex Trading Bot..."
    
    check_root
    check_requirements
    create_app_user
    create_directories
    backup_existing
    deploy_files
    setup_environment
    setup_systemd_service
    setup_log_rotation
    setup_firewall
    start_application
    verify_deployment
    
    success "Deployment completed successfully!"
    
    echo ""
    echo "Next steps:"
    echo "1. Update environment configuration: /etc/${APP_NAME}/.env"
    echo "2. Restart the service: sudo systemctl restart $SERVICE_NAME"
    echo "3. Monitor logs: journalctl -u $SERVICE_NAME -f"
    echo "4. Check health: curl http://localhost:8080/health"
}

# Run main function
main "$@"