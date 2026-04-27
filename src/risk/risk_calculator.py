"""Risk calculation and assessment for trading operations"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import traceback
from typing import Dict, List, Optional, Set, Tuple
from utils.safe_format import format_float, safe_float
from src.models import (
    TradingSignal, Portfolio, Position, RiskAssessment, Direction, MarketData
)
from src.exceptions import DataValidationError


@dataclass
class RiskConfig:
    """Configuration for risk management calculations"""
    max_portfolio_risk: float = 0.02  # 2% max portfolio risk per trade
    max_correlation: float = 0.7      # Maximum correlation between positions
    max_drawdown: float = 0.15        # 15% maximum drawdown threshold
    max_total_positions: int = 20           # Increased to 20 for Maxout mode
    max_exposure_per_currency: float = 50.0 # Increased to 5000% (50x leverage) to allow stacking
    volatility_lookback: int = 20     # Days for volatility calculation
    correlation_lookback: int = 50    # Days for correlation calculation
    
    def __post_init__(self):
        """Validate configuration after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate risk configuration"""
        if not 0.0 < self.max_portfolio_risk <= 0.1:
            raise DataValidationError(
                f"Max portfolio risk must be between 0 and 0.1: {self.max_portfolio_risk}",
                error_code="INVALID_MAX_PORTFOLIO_RISK",
                context={"max_portfolio_risk": self.max_portfolio_risk}
            )
        
        if not 0.0 < self.max_correlation <= 1.0:
            raise DataValidationError(
                f"Max correlation must be between 0 and 1.0: {self.max_correlation}",
                error_code="INVALID_MAX_CORRELATION",
                context={"max_correlation": self.max_correlation}
            )
        
        if not 0.0 < self.max_drawdown <= 0.5:
            raise DataValidationError(
                f"Max drawdown must be between 0 and 0.5: {self.max_drawdown}",
                error_code="INVALID_MAX_DRAWDOWN",
                context={"max_drawdown": self.max_drawdown}
            )
        
        if not 1 <= self.max_total_positions <= 20:
            raise DataValidationError(
                f"Max positions must be between 1 and 20: {self.max_total_positions}",
                error_code="INVALID_MAX_POSITIONS",
                context={"max_total_positions": self.max_total_positions}
            )
        
        if not 0.0 < self.max_exposure_per_currency <= 100.0:
            raise DataValidationError(
                f"Max exposure per currency must be between 0 and 100.0: {self.max_exposure_per_currency}",
                error_code="INVALID_MAX_EXPOSURE",
                context={"max_exposure_per_currency": self.max_exposure_per_currency}
            )
        
        if not 5 <= self.volatility_lookback <= 100:
            raise DataValidationError(
                f"Volatility lookback must be between 5 and 100: {self.volatility_lookback}",
                error_code="INVALID_VOLATILITY_LOOKBACK",
                context={"volatility_lookback": self.volatility_lookback}
            )
        
        if not 10 <= self.correlation_lookback <= 200:
            raise DataValidationError(
                f"Correlation lookback must be between 10 and 200: {self.correlation_lookback}",
                error_code="INVALID_CORRELATION_LOOKBACK",
                context={"correlation_lookback": self.correlation_lookback}
            )


@dataclass
class EquityPoint:
    """Single point in equity curve tracking"""
    timestamp: datetime
    balance: float
    equity: float
    drawdown: float
    
    def __post_init__(self):
        """Validate equity point after initialization"""
        self.validate()
    
    def validate(self) -> None:
        """Validate equity point data"""
        if self.balance < 0:
            raise DataValidationError(
                f"Balance cannot be negative: {self.balance}",
                error_code="NEGATIVE_BALANCE",
                context={"balance": self.balance}
            )
        
        if self.equity < 0:
            raise DataValidationError(
                f"Equity cannot be negative: {self.equity}",
                error_code="NEGATIVE_EQUITY",
                context={"equity": self.equity}
            )
        
        if not 0.0 <= self.drawdown <= 1.0:
            raise DataValidationError(
                f"Drawdown must be between 0.0 and 1.0: {self.drawdown}",
                error_code="INVALID_DRAWDOWN",
                context={"drawdown": self.drawdown}
            )
        
        # Allow 1 day in future for historical data and server time differences
        max_future_time = datetime.now(timezone.utc) + timedelta(days=1)
        if self.timestamp > max_future_time:
            raise DataValidationError(
                f"Timestamp cannot be in the future: {self.timestamp}",
                error_code="FUTURE_TIMESTAMP",
                context={"timestamp": self.timestamp}
            )


class RiskCalculator:
    """Risk calculation and assessment for trading operations"""
    
    def __init__(self, config: RiskConfig):
        self.config = config
        self.equity_curve: List[EquityPoint] = []
        self.peak_equity = 0.0
        self.initial_balance = 0.0
        self.account_history: List[Dict[str, float]] = []
    
    def assess_trade_risk(
        self,
        signal: TradingSignal,
        portfolio: Portfolio,
        market_data: Optional[Dict[str, MarketData]] = None
    ) -> RiskAssessment:
        """Assess risk for a potential trade"""
        warnings = []
        risk_score = 0.0
        
        try:
            # Validate inputs
            self._validate_trade_inputs(signal, portfolio)
            
            # Check position limits
            # ===== TOTAL TRIGGER RELEASE V11 FIX #2: ELITE-OVER-ALLOCATION =====
            # If forced_execution=True, bypass Max Positions and Correlation checks
            if getattr(signal, 'forced_execution', False):
                import logging
                logger = logging.getLogger(__name__)
                logger.critical(f"[ELITE_OVER_ALLOCATION] {signal.symbol} | forced_execution=True. Bypassing Max Positions and Correlation Throttle.")
                position_risk = 0.0
                correlation_risk = 0.0
            else:
                # Standard risk checks
                position_risk = self._assess_position_limits(portfolio, warnings)
                correlation_risk = self._assess_correlation_risk(signal, portfolio, market_data, warnings)
            
            risk_score += position_risk * 0.3
            risk_score += correlation_risk * 0.2
            
            # Check exposure risk
            exposure_risk = self._assess_exposure_risk(signal, portfolio, warnings, market_data)
            risk_score += exposure_risk * 0.2
            
            # Check drawdown risk
            drawdown_risk = self._assess_drawdown_risk(portfolio, warnings)
            risk_score += drawdown_risk * 0.3
            
            # Normalize risk score
            risk_score = min(risk_score, 1.0)
            
            # Determine if trade is valid
            is_valid = risk_score < 0.7 and len([w for w in warnings if "CRITICAL" in w]) == 0
            
            # Calculate adjusted position size
            position_size = signal.position_size * (1.0 - risk_score) if is_valid else 0.0
            
            # Clamp position size to valid 0-1.0 range (represents 0-100% of max allowed position)
            position_size = max(0.0, min(position_size, 1.0))
            
            if not is_valid:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"[RISK REJECTED] {signal.symbol} | Score: {format_float(risk_score, '.2f')} | "
                    f"Warnings: {', '.join(warnings)}"
                )
            
            return RiskAssessment(
                is_valid=is_valid,
                risk_score=risk_score,
                position_size=position_size,
                warnings=warnings,
                timestamp=datetime.now(timezone.utc)
            )
            
        except Exception as e:
            stack_trace = traceback.format_exc()
            logger = logging.getLogger(__name__)
            logger.error(f"[RISK_SYSTEM_ERROR] {signal.symbol} | Risk assessment FAILED due to programming or logic error: {e}\n{stack_trace}")
            
            return RiskAssessment(
                is_valid=False,
                risk_score=1.0,
                position_size=0.0,
                warnings=[f"CRITICAL: Risk assessment failed: {str(e)}"],
                timestamp=datetime.now(timezone.utc)
            )
    
    def calculate_portfolio_exposure(self, portfolio: Portfolio, market_data: Optional[Dict[str, MarketData]] = None) -> Dict[str, float]:
        """
        Calculate exposure by currency.
        Formula: Notional = volume × contract_size × price(base/acc)
        """
        exposure = {}
        logger = logging.getLogger(__name__)
        
        # Assume account currency is USD for conversion price lookups
        # In a real environment, this should be fetched from the broker
        ACC_CURRENCY = "USD"
        
        for position in portfolio.positions:
            try:
                # Extract base and quote currencies
                if '/' in position.symbol:
                    base_currency, quote_currency = position.symbol.split('/')
                else:
                    # Handle MT5 format (EURUSD) - assume 3+3
                    base_currency = position.symbol[:3]
                    quote_currency = position.symbol[3:6]
                
                # Standard lot size is 100,000 units
                CONTRACT_SIZE = getattr(position, 'contract_size', 100000.0)
                
                # Get price of base currency in account currency (USD)
                price_base_acc = 1.0
                if base_currency != ACC_CURRENCY:
                    if market_data:
                        # Try A/USD
                        pair = f"{base_currency}/{ACC_CURRENCY}"
                        if pair in market_data:
                            price_base_acc = market_data[pair].close
                        # Try USD/A
                        elif f"{ACC_CURRENCY}/{base_currency}" in market_data:
                            price_base_acc = 1.0 / market_data[f"{ACC_CURRENCY}/{base_currency}"].close
                        else:
                            # Fallback if we have current_price and it's XXX/USD
                            if quote_currency == ACC_CURRENCY:
                                price_base_acc = position.current_price
                            else:
                                logger.warning(f"[EXPOSURE] Missing conversion price for {base_currency}. Using 1.0 (Inaccurate).")
                    else:
                        # Fallback to current_price if it's XXX/USD
                        if quote_currency == ACC_CURRENCY:
                            price_base_acc = position.current_price
                        else:
                            price_base_acc = 1.0
                
                # Correct notional exposure calculation
                # notional_in_acc = volume * contract_size * price(base/acc)
                notional_in_acc = position.quantity * CONTRACT_SIZE * price_base_acc
                
                # Structured debug logging
                logger.debug(
                    f"[EXPOSURE_DEBUG] {position.symbol} | Vol: {position.quantity} | "
                    f"Price(B/ACC): {format_float(price_base_acc, '.5f')} | "
                    f"Contract: {CONTRACT_SIZE} | Equity: {format_float(portfolio.equity, '.2f')} | "
                    f"Notional: {format_float(notional_in_acc, '.2f')}"
                )
                
                # Add to base currency exposure (Long means positive base, Short means negative base)
                if position.direction == Direction.LONG:
                    exposure[base_currency] = exposure.get(base_currency, 0.0) + notional_in_acc
                    exposure[quote_currency] = exposure.get(quote_currency, 0.0) - notional_in_acc
                else:  # SHORT
                    exposure[base_currency] = exposure.get(base_currency, 0.0) - notional_in_acc
                    exposure[quote_currency] = exposure.get(quote_currency, 0.0) + notional_in_acc
                    
            except Exception as e:
                logger.error(f"[EXPOSURE_ERROR] Failed to calculate exposure for {position.symbol}: {e}")
                continue
        
        # Convert to percentages of equity
        if portfolio.equity > 0:
            for currency in exposure:
                exposure[currency] = abs(exposure[currency]) / portfolio.equity
        
        return exposure
    
    def calculate_correlation_matrix(
        self,
        symbols: List[str],
        market_data: Dict[str, List[MarketData]]
    ) -> Dict[Tuple[str, str], float]:
        """Calculate correlation matrix between currency pairs"""
        correlations = {}
        
        for i, symbol1 in enumerate(symbols):
            for j, symbol2 in enumerate(symbols[i+1:], i+1):
                correlation = self._calculate_pair_correlation(
                    market_data.get(symbol1, []),
                    market_data.get(symbol2, [])
                )
                correlations[(symbol1, symbol2)] = correlation
                correlations[(symbol2, symbol1)] = correlation
        
        return correlations
    
    def update_equity_curve(self, portfolio: Portfolio) -> None:
        """Update equity curve with current portfolio state"""
        current_time = datetime.now(timezone.utc)
        
        # Set initial balance if not set
        if self.initial_balance == 0.0:
            self.initial_balance = portfolio.balance
        
        # Calculate current drawdown
        if portfolio.equity > self.peak_equity:
            self.peak_equity = portfolio.equity
        
        drawdown = (self.peak_equity - portfolio.equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        
        # Add new equity point
        equity_point = EquityPoint(
            timestamp=current_time,
            balance=portfolio.balance,
            equity=portfolio.equity,
            drawdown=drawdown
        )
        
        self.equity_curve.append(equity_point)
        
        # Track account history for performance analysis
        account_snapshot = {
            'timestamp': current_time.isoformat(),
            'balance': portfolio.balance,
            'equity': portfolio.equity,
            'margin_used': portfolio.margin_used,
            'margin_available': portfolio.margin_available,
            'num_positions': len(portfolio.positions),
            'drawdown': drawdown,
            'total_return': (portfolio.equity - self.initial_balance) / self.initial_balance if self.initial_balance > 0 else 0.0
        }
        self.account_history.append(account_snapshot)
        
        # Keep only recent history (last 1000 points)
        if len(self.equity_curve) > 1000:
            self.equity_curve = self.equity_curve[-1000:]
        
        if len(self.account_history) > 1000:
            self.account_history = self.account_history[-1000:]
    
    def get_current_drawdown(self) -> float:
        """Get current drawdown percentage"""
        if not self.equity_curve:
            return 0.0
        
        return self.equity_curve[-1].drawdown
    
    def get_max_drawdown(self, days: int = 30) -> float:
        """Get maximum drawdown over specified period"""
        if not self.equity_curve:
            return 0.0
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        recent_points = [
            point for point in self.equity_curve 
            if point.timestamp >= cutoff_time
        ]
        
        if not recent_points:
            return 0.0
        
        return max(point.drawdown for point in recent_points)
    
    def get_account_performance_metrics(self) -> Dict[str, float]:
        """Calculate comprehensive account performance metrics"""
        if not self.equity_curve or len(self.equity_curve) < 2:
            return {
                'total_return': 0.0,
                'max_drawdown': 0.0,
                'current_drawdown': 0.0,
                'peak_equity': 0.0,
                'volatility': 0.0,
                'sharpe_ratio': 0.0
            }
        
        # Calculate returns
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev_equity = self.equity_curve[i-1].equity
            curr_equity = self.equity_curve[i].equity
            if prev_equity > 0:
                returns.append((curr_equity - prev_equity) / prev_equity)
        
        # Calculate metrics
        total_return = (self.equity_curve[-1].equity - self.initial_balance) / self.initial_balance if self.initial_balance > 0 else 0.0
        max_drawdown = max(point.drawdown for point in self.equity_curve)
        current_drawdown = self.get_current_drawdown()
        peak_equity = self.peak_equity
        
        # Calculate volatility (standard deviation of returns)
        if len(returns) > 1:
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
            volatility = math.sqrt(variance)
            
            # Calculate Sharpe ratio (assuming risk-free rate of 0)
            sharpe_ratio = mean_return / volatility if volatility > 0 else 0.0
        else:
            volatility = 0.0
            sharpe_ratio = 0.0
        
        return {
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'current_drawdown': current_drawdown,
            'peak_equity': peak_equity,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio
        }
    
    def get_balance_history(self, days: int = 30) -> List[Dict[str, float]]:
        """Get account balance history for specified period"""
        if not self.account_history:
            return []
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        
        return [
            snapshot for snapshot in self.account_history
            if datetime.fromisoformat(snapshot['timestamp'].replace('Z', '+00:00')) >= cutoff_time
        ]
    
    def calculate_position_size_with_kelly(
        self,
        signal: TradingSignal,
        portfolio: Portfolio,
        trade_history: Optional[List] = None
    ) -> float:
        """Calculate position size using Kelly criterion with risk management overlay"""
        # Use the existing position sizer for Kelly calculation
        from src.risk.position_sizer import KellyCriterionSizer, PositionSizingConfig
        
        # Create position sizing config based on risk config
        pos_config = PositionSizingConfig(
            max_risk_per_trade=self.config.max_portfolio_risk,
            max_position_size=0.1,  # 10% max position size
            kelly_lookback_periods=50
        )
        
        kelly_sizer = KellyCriterionSizer(pos_config)
        
        # Calculate Kelly position size
        kelly_size = kelly_sizer.calculate_position_size(
            signal, portfolio.balance, trade_history
        )
        
        # Apply additional risk management overlay
        risk_assessment = self.assess_trade_risk(signal, portfolio)
        
        # Reduce position size based on risk score
        adjusted_size = kelly_size * (1.0 - risk_assessment.risk_score)
        
        return max(0.0, adjusted_size)
    
    def _validate_trade_inputs(self, signal: TradingSignal, portfolio: Portfolio) -> None:
        """Validate inputs for trade risk assessment"""
        if not isinstance(signal, TradingSignal):
            raise DataValidationError(
                "Signal must be a TradingSignal instance",
                error_code="INVALID_SIGNAL_TYPE",
                context={"signal_type": type(signal)}
            )
        
        if not isinstance(portfolio, Portfolio):
            raise DataValidationError(
                "Portfolio must be a Portfolio instance",
                error_code="INVALID_PORTFOLIO_TYPE",
                context={"portfolio_type": type(portfolio)}
            )
    
    def _assess_position_limits(self, portfolio: Portfolio, warnings: List[str]) -> float:
        """Assess position limit risks"""
        risk_score = 0.0
        
        # Check number of positions
        num_positions = len(portfolio.positions)
        if num_positions >= self.config.max_total_positions:
            warnings.append("CRITICAL: Maximum number of positions reached")
            risk_score += 0.5
        elif num_positions >= self.config.max_total_positions * 0.8:
            warnings.append("WARNING: Approaching maximum position limit")
            risk_score += 0.2
        
        return risk_score
    
    def _assess_correlation_risk(
        self,
        signal: TradingSignal,
        portfolio: Portfolio,
        market_data: Optional[Dict[str, MarketData]],
        warnings: List[str]
    ) -> float:
        """Assess correlation risk with existing positions"""
        risk_score = 0.0
        
        # Check correlation with existing positions
        for position in portfolio.positions:
            if position.symbol == signal.symbol:
                # If direction matches (Pyramiding), smaller penalty
                if position.direction == signal.direction:
                     warnings.append(f"NOTE: Adding to position in {signal.symbol}")
                     risk_score += 0.1 # Small penalty for concentration
                else:
                     warnings.append(f"WARNING: Opposing position in {signal.symbol} (Hedging?)")
                     risk_score += 0.3
                continue
            
            # Only do correlation analysis if we have market data
            if market_data:
                # Simple correlation check based on currency pairs
                correlation = self._estimate_currency_correlation(signal.symbol, position.symbol)
                
                if correlation > self.config.max_correlation:
                    warnings.append(
                        f"WARNING: High correlation ({format_float(correlation, '.2f')}) with {position.symbol}"
                    )
                    risk_score += 0.2
        
        # Add warning if no market data for correlation analysis
        if not market_data:
            warnings.append("WARNING: No market data for correlation analysis")
            risk_score += 0.1
        
        return min(risk_score, 1.0)
    
    def _assess_exposure_risk(
        self,
        signal: TradingSignal,
        portfolio: Portfolio,
        warnings: List[str],
        market_data: Optional[Dict[str, MarketData]] = None
    ) -> float:
        """Assess currency exposure risk"""
        risk_score = 0.0
        
        # Calculate current exposures
        exposures = self.calculate_portfolio_exposure(portfolio, market_data)
        
        # Check exposure for signal's currencies
        if '/' in signal.symbol:
            base_currency, quote_currency = signal.symbol.split('/')
        else:
            base_currency = signal.symbol[:3]
            quote_currency = signal.symbol[3:6]
        
        base_exposure = exposures.get(base_currency, 0.0)
        quote_exposure = exposures.get(quote_currency, 0.0)
        
        # Calculate additional exposure from new trade
        # Formula: additional = (volume * contract_size * price_base_acc) / equity
        CONTRACT_SIZE = 100000.0
        
        # Try to get conversion price for new trade
        price_base_acc = signal.entry_price # Default if signal is XXX/USD
        if not signal.symbol.endswith('/USD') and not signal.symbol.endswith('USD'):
            base_currency = signal.symbol.split('/')[0] if '/' in signal.symbol else signal.symbol[:3]
            price_base_acc = 1.0 # Fallback
            if market_data:
                pair = f"{base_currency}/USD"
                if pair in market_data:
                    price_base_acc = market_data[pair].close
                elif f"USD/{base_currency}" in market_data:
                    price_base_acc = 1.0 / market_data[f"USD/{base_currency}"].close
        
        trade_value = signal.position_size * CONTRACT_SIZE * price_base_acc
        additional_exposure = trade_value / portfolio.equity if portfolio.equity > 0 else 0
        
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(
            f"[EXPOSURE_CALC] {signal.symbol} | base_exposure: {format_float(base_exposure, '.4f')} | "
            f"trade_value: {format_float(trade_value, '.2f')} | Price(B/ACC): {format_float(price_base_acc, '.5f')} | "
            f"Add_Exp: {format_float(additional_exposure, '.4f')}"
        )
        
        if signal.direction == Direction.LONG:
            new_base_exposure = base_exposure + additional_exposure
        else:
            new_base_exposure = base_exposure + additional_exposure  # Short also increases exposure
        
        if new_base_exposure > self.config.max_exposure_per_currency:
            warnings.append(
                f"CRITICAL: {base_currency} exposure would exceed limit "
                f"({format_float(new_base_exposure, '.1%')} > {format_float(self.config.max_exposure_per_currency, '.1%')})"
            )
            risk_score += 0.5
        elif new_base_exposure > self.config.max_exposure_per_currency * 0.8:
            warnings.append(
                f"WARNING: {base_currency} exposure approaching limit ({format_float(new_base_exposure, '.1%')})"
            )
            risk_score += 0.2
        
        return risk_score
    
    def _assess_drawdown_risk(self, portfolio: Portfolio, warnings: List[str]) -> float:
        """Assess drawdown risk"""
        risk_score = 0.0
        
        current_drawdown = self.get_current_drawdown()
        
        if current_drawdown >= self.config.max_drawdown:
            warnings.append(
                f"CRITICAL: Maximum drawdown exceeded ({format_float(current_drawdown, '.1%')})"
            )
            risk_score += 1.0
        elif current_drawdown >= self.config.max_drawdown * 0.8:
            warnings.append(
                f"WARNING: Approaching maximum drawdown ({format_float(current_drawdown, '.1%')})"
            )
            risk_score += 0.3
        
        return risk_score
    
    def _calculate_pair_correlation(
        self,
        data1: List[MarketData],
        data2: List[MarketData]
    ) -> float:
        """Calculate correlation between two currency pairs"""
        if len(data1) < 10 or len(data2) < 10:
            return 0.0
        
        # Align data by timestamp and calculate returns
        returns1 = []
        returns2 = []
        
        # Simple correlation based on price changes
        for i in range(1, min(len(data1), len(data2), self.config.correlation_lookback)):
            if i < len(data1) and i < len(data2):
                ret1 = (data1[i].close - data1[i-1].close) / data1[i-1].close
                ret2 = (data2[i].close - data2[i-1].close) / data2[i-1].close
                returns1.append(ret1)
                returns2.append(ret2)
        
        if len(returns1) < 10:
            return 0.0
        
        # Calculate correlation coefficient
        mean1 = sum(returns1) / len(returns1)
        mean2 = sum(returns2) / len(returns2)
        
        numerator = sum((r1 - mean1) * (r2 - mean2) for r1, r2 in zip(returns1, returns2))
        
        sum_sq1 = sum((r1 - mean1) ** 2 for r1 in returns1)
        sum_sq2 = sum((r2 - mean2) ** 2 for r2 in returns2)
        
        denominator = math.sqrt(sum_sq1 * sum_sq2)
        
        return numerator / denominator if denominator > 0 else 0.0
    
    def _estimate_currency_correlation(self, symbol1: str, symbol2: str) -> float:
        """Estimate correlation between currency pairs based on shared currencies"""
        if '/' in symbol1:
            base1, quote1 = symbol1.split('/')
        else:
            base1, quote1 = symbol1[:3], symbol1[3:6]
            
        if '/' in symbol2:
            base2, quote2 = symbol2.split('/')
        else:
            base2, quote2 = symbol2[:3], symbol2[3:6]
        
        # High correlation if same pair
        if symbol1 == symbol2:
            return 1.0
        
        # High correlation if inverse pairs
        if base1 == quote2 and quote1 == base2:
            return 0.9
        
        # Medium correlation if sharing one currency
        if base1 == base2 or base1 == quote2 or quote1 == base2 or quote1 == quote2:
            return 0.6
        
        # Low correlation for unrelated pairs
        return 0.1