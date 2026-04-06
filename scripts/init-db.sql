-- Database initialization script for AI Forex Trading Bot
-- This script creates the necessary database schema

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Create schemas
CREATE SCHEMA IF NOT EXISTS trading;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS monitoring;

-- Set search path
SET search_path TO trading, public;

-- Market data table
CREATE TABLE IF NOT EXISTS market_data (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    open_price DECIMAL(10, 5) NOT NULL,
    high_price DECIMAL(10, 5) NOT NULL,
    low_price DECIMAL(10, 5) NOT NULL,
    close_price DECIMAL(10, 5) NOT NULL,
    volume BIGINT NOT NULL DEFAULT 0,
    bid_price DECIMAL(10, 5),
    ask_price DECIMAL(10, 5),
    spread DECIMAL(10, 5),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for market data
CREATE INDEX IF NOT EXISTS idx_market_data_symbol_timestamp ON market_data(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_market_data_timestamp ON market_data(timestamp DESC);

-- News data table
CREATE TABLE IF NOT EXISTS news_data (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    content TEXT,
    source VARCHAR(100) NOT NULL,
    url TEXT,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    symbols TEXT[], -- Array of related symbols
    sentiment_score DECIMAL(3, 2), -- -1.0 to 1.0
    confidence_score DECIMAL(3, 2), -- 0.0 to 1.0
    processed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for news data
CREATE INDEX IF NOT EXISTS idx_news_data_published_at ON news_data(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_data_symbols ON news_data USING GIN(symbols);
CREATE INDEX IF NOT EXISTS idx_news_data_source ON news_data(source);

-- Trading signals table
CREATE TABLE IF NOT EXISTS trading_signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(10) NOT NULL,
    signal_type VARCHAR(10) NOT NULL CHECK (signal_type IN ('BUY', 'SELL', 'HOLD')),
    strength DECIMAL(3, 2) NOT NULL CHECK (strength >= 0 AND strength <= 1),
    entry_price DECIMAL(10, 5),
    stop_loss DECIMAL(10, 5),
    take_profit DECIMAL(10, 5),
    confidence DECIMAL(3, 2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    reasoning TEXT,
    technical_indicators JSONB,
    sentiment_data JSONB,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for trading signals
CREATE INDEX IF NOT EXISTS idx_trading_signals_symbol ON trading_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_trading_signals_created_at ON trading_signals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trading_signals_expires_at ON trading_signals(expires_at);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    broker_order_id VARCHAR(100),
    symbol VARCHAR(10) NOT NULL,
    order_type VARCHAR(10) NOT NULL CHECK (order_type IN ('MARKET', 'LIMIT', 'STOP')),
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    quantity DECIMAL(10, 2) NOT NULL,
    price DECIMAL(10, 5),
    stop_loss DECIMAL(10, 5),
    take_profit DECIMAL(10, 5),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED')),
    filled_quantity DECIMAL(10, 2) DEFAULT 0,
    filled_price DECIMAL(10, 5),
    commission DECIMAL(10, 2) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    filled_at TIMESTAMP WITH TIME ZONE
);

-- Create indexes for orders
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_broker_order_id ON orders(broker_order_id);

-- Positions table
CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(10) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    quantity DECIMAL(10, 2) NOT NULL,
    entry_price DECIMAL(10, 5) NOT NULL,
    current_price DECIMAL(10, 5),
    unrealized_pnl DECIMAL(10, 2) DEFAULT 0,
    realized_pnl DECIMAL(10, 2) DEFAULT 0,
    stop_loss DECIMAL(10, 5),
    take_profit DECIMAL(10, 5),
    commission DECIMAL(10, 2) DEFAULT 0,
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    closed_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED'))
);

-- Create indexes for positions
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_opened_at ON positions(opened_at DESC);

-- Analytics schema tables
SET search_path TO analytics, public;

-- Performance metrics table
CREATE TABLE IF NOT EXISTS performance_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    date DATE NOT NULL,
    total_return DECIMAL(10, 4),
    daily_return DECIMAL(10, 4),
    sharpe_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(10, 4),
    win_rate DECIMAL(5, 2),
    profit_factor DECIMAL(10, 4),
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    avg_win DECIMAL(10, 2),
    avg_loss DECIMAL(10, 2),
    largest_win DECIMAL(10, 2),
    largest_loss DECIMAL(10, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for performance metrics
CREATE UNIQUE INDEX IF NOT EXISTS idx_performance_metrics_date ON performance_metrics(date);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_created_at ON performance_metrics(created_at DESC);

-- Monitoring schema tables
SET search_path TO monitoring, public;

-- System health table
CREATE TABLE IF NOT EXISTS system_health (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    component VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('healthy', 'degraded', 'unhealthy')),
    message TEXT,
    response_time_ms DECIMAL(10, 2),
    details JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for system health
CREATE INDEX IF NOT EXISTS idx_system_health_component ON system_health(component);
CREATE INDEX IF NOT EXISTS idx_system_health_timestamp ON system_health(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_system_health_status ON system_health(status);

-- Error logs table
CREATE TABLE IF NOT EXISTS error_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    component VARCHAR(100),
    stack_trace TEXT,
    context JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for error logs
CREATE INDEX IF NOT EXISTS idx_error_logs_level ON error_logs(level);
CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp ON error_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_error_logs_component ON error_logs(component);

-- Create functions for automatic timestamp updates
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at columns
CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON trading.orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create views for common queries
SET search_path TO trading, public;

-- Active positions view
CREATE OR REPLACE VIEW active_positions AS
SELECT 
    p.*,
    (p.current_price - p.entry_price) * p.quantity * 
    CASE WHEN p.direction = 'LONG' THEN 1 ELSE -1 END as unrealized_pnl_calc
FROM positions p
WHERE p.status = 'OPEN';

-- Recent signals view
CREATE OR REPLACE VIEW recent_signals AS
SELECT *
FROM trading_signals
WHERE created_at >= NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- Daily performance view
CREATE OR REPLACE VIEW daily_performance AS
SELECT 
    DATE(closed_at) as trade_date,
    COUNT(*) as total_trades,
    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
    SUM(realized_pnl) as total_pnl,
    AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl END) as avg_win,
    AVG(CASE WHEN realized_pnl < 0 THEN realized_pnl END) as avg_loss,
    MAX(realized_pnl) as largest_win,
    MIN(realized_pnl) as largest_loss
FROM positions
WHERE status = 'CLOSED' AND closed_at IS NOT NULL
GROUP BY DATE(closed_at)
ORDER BY trade_date DESC;

-- Grant permissions
GRANT USAGE ON SCHEMA trading TO forex_user;
GRANT USAGE ON SCHEMA analytics TO forex_user;
GRANT USAGE ON SCHEMA monitoring TO forex_user;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA trading TO forex_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA analytics TO forex_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA monitoring TO forex_user;

GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA trading TO forex_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA analytics TO forex_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA monitoring TO forex_user;

-- Reset search path
SET search_path TO public;