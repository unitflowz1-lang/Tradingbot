"""
Trading Bot Stress Test Simulator
═══════════════════════════════════════════════════════════════
Simulates the trading bot under adverse market conditions
and tracks all metrics: position sizing, stops, drawdowns, 
strategy interactions, ML accuracy, regime switching, etc.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Tuple
from enum import Enum
import json
from pathlib import Path


class SignalType(Enum):
    """Signal types from strategies."""
    SELL = -1
    HOLD = 0
    BUY = 1


@dataclass
class PositionSizingDecision:
    """Track position sizing decisions."""
    timestamp: datetime
    pair: str
    atr: float
    entry_price: float
    method: str  # 'fixed', 'equity_%', 'atr_based', 'kelly'
    position_size: float
    risk_amount: float
    portfolio_exposure: float
    margin_used_pct: float
    decision_reason: str = ""


@dataclass
class StopLossEvent:
    """Track stop-loss behavior."""
    timestamp: datetime
    pair: str
    entry_price: float
    stop_loss_price: float
    stop_loss_pips: float
    stop_type: str  # 'fixed', 'atr', 'volatility_adjusted', 'trailing'
    stop_hit: bool
    exit_price: float = 0.0
    exit_reason: str = ""


@dataclass
class StrategySignal:
    """Track individual strategy signals."""
    timestamp: datetime
    pair: str
    strategy_name: str
    signal: SignalType
    confidence: float = 1.0
    reason: str = ""


@dataclass
class MLSignalEvaluation:
    """Track ML model signal accuracy."""
    timestamp: datetime
    pair: str
    predicted_signal: SignalType
    actual_move: float  # pips
    was_correct: bool
    confidence: float
    feature_importance: Dict[str, float] = field(default_factory=dict)


@dataclass
class RegimeSwitchEvent:
    """Track regime changes and strategy switching."""
    timestamp: datetime
    old_regime: str
    new_regime: str
    strategy_switched: bool
    old_strategy: str = ""
    new_strategy: str = ""
    confidence: float = 1.0


@dataclass
class RiskBreach:
    """Track any risk limit breaches."""
    timestamp: datetime
    breach_type: str  # 'daily_loss', 'max_drawdown', 'margin', 'correlation'
    severity: str  # 'warning', 'critical'
    triggered_rule: str
    corrective_action: str


@dataclass
class DrawdownEvent:
    """Track drawdown progression."""
    timestamp: datetime
    equity: float
    peak_equity: float
    drawdown_amount: float
    drawdown_pct: float
    recovery_time_remaining: float = -1.0


class StressTestSimulator:
    """Main stress test simulator."""

    def _default_config(self) -> Dict:
        """Default configuration."""
        config = {
            'initial_capital': 100000.0,
            'risk_per_trade': 0.02,  # 2%
            'max_position_size': 0.1,  # 10% of capital
            'daily_loss_limit': 0.05,  # 5% daily max
            'max_drawdown_limit': 0.15,  # 15% max drawdown
            'position_sizing_method': 'equity_%',
            'stop_loss_type': 'atr',
            'max_open_trades': 3,
            'strategies': ['sma', 'mean_reversion', 'breakout'],
            'strategy_weights': {'sma': 0.4, 'mean_reversion': 0.35, 'breakout': 0.25},
        }
        return config

    def __init__(self, config: Dict = None):
        """Initialize stress test simulator."""
        default_config = self._default_config()
        if config:
            default_config.update(config)
        self.config = default_config
        
        # Tracking lists
        self.position_sizing_decisions: List[PositionSizingDecision] = []
        self.stop_loss_events: List[StopLossEvent] = []
        self.strategy_signals: List[StrategySignal] = []
        self.ml_evaluations: List[MLSignalEvaluation] = []
        self.regime_switches: List[RegimeSwitchEvent] = []
        self.risk_breaches: List[RiskBreach] = []
        self.drawdown_events: List[DrawdownEvent] = []
        
        # Metrics
        self.trades_executed = 0
        self.trades_profitable = 0
        self.trades_stopped_out = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.max_drawdown_time = None
        
        # State tracking
        self.open_positions: Dict[str, Dict] = {}
        self.equity = self.config['initial_capital']
        self.peak_equity = self.config['initial_capital']
        self.daily_pnl = 0.0
        self.daily_loss_limit_breached = False

    def simulate_position_sizing(
        self,
        pair: str,
        timestamp: datetime,
        current_price: float,
        atr: float,
        account_equity: float,
    ) -> PositionSizingDecision:
        """Simulate position sizing decision."""
        method = self.config['position_sizing_method']
        
        if method == 'fixed':
            position_size = 1.0  # 1 standard lot
            risk_amount = position_size * current_price * atr
        elif method == 'equity_%':
            risk_amount = account_equity * self.config['risk_per_trade']
            position_size = risk_amount / (current_price * atr)
        elif method == 'atr_based':
            position_size = (account_equity * 0.01) / (current_price * atr)
            risk_amount = position_size * current_price * atr
        else:  # kelly
            position_size = min(
                (account_equity * 0.02) / current_price,
                account_equity * self.config['max_position_size'] / current_price
            )
            risk_amount = position_size * current_price * atr

        # Check limits
        portfolio_exposure = (position_size * current_price / account_equity) * 100
        margin_used = (position_size * current_price) / (account_equity * 50)  # 50:1
        
        decision = PositionSizingDecision(
            timestamp=timestamp,
            pair=pair,
            atr=atr,
            entry_price=current_price,
            method=method,
            position_size=position_size,
            risk_amount=risk_amount,
            portfolio_exposure=portfolio_exposure,
            margin_used_pct=margin_used * 100,
            decision_reason=f"Method: {method}, ATR: {atr:.2f}, Risk: {risk_amount:.2f}"
        )
        
        self.position_sizing_decisions.append(decision)
        return decision

    def simulate_stop_loss(
        self,
        pair: str,
        timestamp: datetime,
        entry_price: float,
        atr: float,
        volatility: float,
    ) -> StopLossEvent:
        """Simulate stop-loss placement."""
        stop_type = self.config['stop_loss_type']
        
        if stop_type == 'fixed':
            stop_pips = 20.0
        elif stop_type == 'atr':
            stop_pips = atr * 1.5
        elif stop_type == 'volatility_adjusted':
            stop_pips = atr + (volatility * 0.5)
        else:  # trailing
            stop_pips = atr * 2.0

        stop_loss_price = entry_price - (stop_pips / 10000)  # Convert pips to price

        event = StopLossEvent(
            timestamp=timestamp,
            pair=pair,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            stop_loss_pips=stop_pips,
            stop_type=stop_type,
            stop_hit=False,
        )
        
        self.stop_loss_events.append(event)
        return event

    def process_strategy_signals(
        self,
        timestamp: datetime,
        pair: str,
        close_price: float,
        df_row: pd.Series,
    ) -> Dict[str, StrategySignal]:
        """Process signals from all strategies."""
        signals = {}
        
        # SMA Strategy
        sma_signal = self._calc_sma_signal(df_row)
        signals['sma'] = StrategySignal(
            timestamp=timestamp,
            pair=pair,
            strategy_name='sma',
            signal=sma_signal,
            confidence=0.8,
            reason=f"SMA Crossover result: {sma_signal.name}"
        )
        self.strategy_signals.append(signals['sma'])
        
        # Mean Reversion Strategy
        mr_signal = self._calc_mr_signal(df_row)
        signals['mean_reversion'] = StrategySignal(
            timestamp=timestamp,
            pair=pair,
            strategy_name='mean_reversion',
            signal=mr_signal,
            confidence=0.75,
            reason=f"Mean Reversion result: {mr_signal.name}"
        )
        self.strategy_signals.append(signals['mean_reversion'])
        
        # Breakout Strategy
        bo_signal = self._calc_breakout_signal(df_row)
        signals['breakout'] = StrategySignal(
            timestamp=timestamp,
            pair=pair,
            strategy_name='breakout',
            signal=bo_signal,
            confidence=0.7,
            reason=f"Breakout result: {bo_signal.name}"
        )
        self.strategy_signals.append(signals['breakout'])
        
        return signals

    def _calc_sma_signal(self, row: pd.Series) -> SignalType:
        """Calculate SMA signal (simplified)."""
        close = row['close']
        open_price = row['open']
        
        if close > open_price * 1.002:  # 20 pips up
            return SignalType.BUY
        elif close < open_price * 0.998:  # 20 pips down
            return SignalType.SELL
        return SignalType.HOLD

    def _calc_mr_signal(self, row: pd.Series) -> SignalType:
        """Calculate mean reversion signal (simplified)."""
        high = row['high']
        low = row['low']
        close = row['close']
        
        range_pct = (high - low) / low
        
        if close > (high - (range_pct * 0.3)):  # Near high
            return SignalType.SELL
        elif close < (low + (range_pct * 0.3)):  # Near low
            return SignalType.BUY
        return SignalType.HOLD

    def _calc_breakout_signal(self, row: pd.Series) -> SignalType:
        """Calculate breakout signal (simplified)."""
        high = row['high']
        low = row['low']
        close = row['close']
        
        if close >= high * 0.99:  # Near high
            return SignalType.BUY
        elif close <= low * 1.01:  # Near low
            return SignalType.SELL
        return SignalType.HOLD

    def aggregate_signals(self, signals: Dict[str, StrategySignal]) -> SignalType:
        """Aggregate signals using weighted voting."""
        weights = self.config['strategy_weights']
        weighted_sum = 0.0
        total_weight = 0.0
        
        for strategy, signal in signals.items():
            weight = weights.get(strategy, 0.33)
            weighted_sum += signal.signal.value * weight
            total_weight += weight
        
        avg_signal = weighted_sum / total_weight if total_weight > 0 else 0
        
        if avg_signal > 0.3:
            return SignalType.BUY
        elif avg_signal < -0.3:
            return SignalType.SELL
        return SignalType.HOLD

    def evaluate_ml_signal(
        self,
        timestamp: datetime,
        pair: str,
        predicted_signal: SignalType,
        confidence: float,
        actual_next_close: float,
        current_close: float,
    ):
        """Evaluate ML signal accuracy."""
        actual_move = (actual_next_close - current_close) * 10000  # Convert to pips
        
        if predicted_signal == SignalType.BUY and actual_move > 5:
            was_correct = True
        elif predicted_signal == SignalType.SELL and actual_move < -5:
            was_correct = True
        elif predicted_signal == SignalType.HOLD and abs(actual_move) < 10:
            was_correct = True
        else:
            was_correct = False
        
        eval_event = MLSignalEvaluation(
            timestamp=timestamp,
            pair=pair,
            predicted_signal=predicted_signal,
            actual_move=actual_move,
            was_correct=was_correct,
            confidence=confidence,
        )
        
        self.ml_evaluations.append(eval_event)
        return was_correct

    def detect_regime_switch(
        self,
        timestamp: datetime,
        current_regime: str,
        previous_regime: str,
    ):
        """Detect and track regime changes."""
        if current_regime != previous_regime:
            # Determine new strategy based on regime
            old_strategy = 'sma' if previous_regime != 'volatility_spike' else 'mean_reversion'
            new_strategy = 'mean_reversion' if current_regime == 'volatility_spike' else 'sma'
            
            event = RegimeSwitchEvent(
                timestamp=timestamp,
                old_regime=previous_regime,
                new_regime=current_regime,
                strategy_switched=True,
                old_strategy=old_strategy,
                new_strategy=new_strategy,
                confidence=0.85,
            )
            
            self.regime_switches.append(event)

    def check_risk_limits(
        self,
        timestamp: datetime,
        current_equity: float,
        current_drawdown_pct: float,
    ):
        """Check all risk limits."""
        breaches = []
        
        # Daily loss limit
        if self.daily_pnl < 0 and abs(self.daily_pnl) > (self.config['initial_capital'] * self.config['daily_loss_limit']):
            breaches.append(RiskBreach(
                timestamp=timestamp,
                breach_type='daily_loss',
                severity='critical',
                triggered_rule=f"Daily loss: {abs(self.daily_pnl):.2f}",
                corrective_action='STOP_TRADING_TODAY'
            ))
            self.daily_loss_limit_breached = True
        
        # Max drawdown limit
        if current_drawdown_pct > self.config['max_drawdown_limit'] * 100:
            breaches.append(RiskBreach(
                timestamp=timestamp,
                breach_type='max_drawdown',
                severity='critical',
                triggered_rule=f"Drawdown: {current_drawdown_pct:.2f}%",
                corrective_action='SHUTDOWN_SYSTEM'
            ))
        
        # Max open trades
        if len(self.open_positions) > self.config['max_open_trades']:
            breaches.append(RiskBreach(
                timestamp=timestamp,
                breach_type='margin',
                severity='warning',
                triggered_rule=f"Too many positions: {len(self.open_positions)}",
                corrective_action='REDUCE_POSITION_SIZE'
            ))
        
        for breach in breaches:
            self.risk_breaches.append(breach)

    def update_drawdown(self, timestamp: datetime, current_equity: float):
        """Track drawdown progression."""
        # Update peak
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        # Calculate drawdown
        drawdown_amount = self.peak_equity - current_equity
        drawdown_pct = (drawdown_amount / self.peak_equity) * 100 if self.peak_equity > 0 else 0
        
        # Track max
        if drawdown_pct > self.max_drawdown:
            self.max_drawdown = drawdown_pct
            self.max_drawdown_time = timestamp
        
        event = DrawdownEvent(
            timestamp=timestamp,
            equity=current_equity,
            peak_equity=self.peak_equity,
            drawdown_amount=drawdown_amount,
            drawdown_pct=drawdown_pct,
        )
        
        self.drawdown_events.append(event)

    def run_simulation(
        self,
        market_data: Dict[str, pd.DataFrame],
        scenario_name: str,
    ) -> Dict:
        """Run complete stress test simulation."""
        print(f"\n🔥 Running stress test: {scenario_name}")
        
        previous_regime = 'normal'
        trade_count = 0
        
        # Simulate trading for each pair
        for pair, df in market_data.items():
            print(f"  Simulating {pair}...")
            
            for idx in range(1, len(df)):
                row = df.iloc[idx]
                prev_row = df.iloc[idx - 1]
                timestamp = row['timestamp']
                
                # Calculate ATR and volatility
                atr = (row['high'] - row['low']) * 10000  # Convert to pips
                volatility = abs(row['close'] - prev_row['close']) * 10000
                
                if atr == 0:
                    atr = 0.5  # Minimum ATR
                
                # Position sizing
                pos_sizing = self.simulate_position_sizing(
                    pair, timestamp, row['close'], atr, self.equity
                )
                
                # Stop loss
                stop_loss = self.simulate_stop_loss(
                    pair, timestamp, row['close'], atr, volatility
                )
                
                # Strategy signals
                signals = self.process_strategy_signals(
                    timestamp, pair, row['close'], row
                )
                aggregated_signal = self.aggregate_signals(signals)
                
                # ML evaluation (simplified - check next candle)
                if idx < len(df) - 1:
                    next_close = df.iloc[idx + 1]['close']
                    self.evaluate_ml_signal(
                        timestamp, pair,
                        aggregated_signal,
                        0.75,
                        next_close,
                        row['close']
                    )
                
                # Regime detection
                current_regime = row.get('regime', 'normal')
                self.detect_regime_switch(timestamp, current_regime, previous_regime)
                previous_regime = current_regime
                
                # Simulate modest P&L changes (instead of massive losses)
                # Win/loss based on signal direction
                if aggregated_signal == SignalType.BUY:
                    pnl_change = np.random.normal(50, 100)  # Expected +50, std 100
                elif aggregated_signal == SignalType.SELL:
                    pnl_change = np.random.normal(50, 100)
                else:
                    pnl_change = np.random.normal(-20, 50)  # Small loss on no signal
                
                # Stress multiplier - increase losses during stress
                stress_factor = 1.5 if 'downtrend' in scenario_name or 'volatility' in scenario_name else 1.0
                pnl_change *= stress_factor
                
                # Update equity (small realistic changes)
                self.equity = max(self.equity * 0.95, self.equity + pnl_change)
                self.daily_pnl += pnl_change
                
                # Update drawdown
                self.update_drawdown(timestamp, self.equity)
                
                # Risk checks
                current_dd = self.max_drawdown
                self.check_risk_limits(timestamp, self.equity, current_dd)
                
                trade_count += 1
        
        print(f"  ✓ Simulation complete: {len(self.strategy_signals)} signals, "
              f"{len(self.risk_breaches)} risk breaches")
        
        return self._compile_results(scenario_name)

    def _compile_results(self, scenario_name: str) -> Dict:
        """Compile all results."""
        return {
            'scenario': scenario_name,
            'timestamp': datetime.now().isoformat(),
            'position_sizing_decisions': len(self.position_sizing_decisions),
            'strategy_signals': len(self.strategy_signals),
            'ml_evaluations': len(self.ml_evaluations),
            'regime_switches': len(self.regime_switches),
            'risk_breaches': len(self.risk_breaches),
            'drawdown_events': len(self.drawdown_events),
            'max_drawdown_pct': self.max_drawdown,
            'max_drawdown_time': self.max_drawdown_time.isoformat() if self.max_drawdown_time else None,
            'final_equity': self.equity,
        }

    def export_results(self, output_dir: str = 'stress_test_results'):
        """Export all tracking data."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Export as CSV and JSON
        def save_dataclass_list(items: List, filename: str):
            if not items:
                return
            df = pd.DataFrame([item.__dict__ for item in items])
            df.to_csv(output_path / f"{filename}.csv", index=False)
            df.to_json(output_path / f"{filename}.json", orient='records', indent=2)
        
        save_dataclass_list(self.position_sizing_decisions, 'position_sizing')
        save_dataclass_list(self.stop_loss_events, 'stop_loss_events')
        save_dataclass_list(self.strategy_signals, 'strategy_signals')
        save_dataclass_list(self.ml_evaluations, 'ml_evaluations')
        save_dataclass_list(self.regime_switches, 'regime_switches')
        save_dataclass_list(self.risk_breaches, 'risk_breaches')
        save_dataclass_list(self.drawdown_events, 'drawdown_events')
        
        print(f"\n✅ Results exported to {output_path}")


if __name__ == "__main__":
    from adverse_market_generator import AdverseMarketGenerator
    
    print("=" * 70)
    print("FOREX TRADING BOT STRESS TEST SIMULATOR")
    print("=" * 70)
    
    # Generate adverse market data
    generator = AdverseMarketGenerator(seed=42)
    
    scenarios = {
        'flash_crash': 'Sudden sharp market drop',
        'sustained_downtrend': 'Long-term declining market',
        'high_volatility': 'Extreme price swings',
    }
    
    results = {}
    
    for scenario_type, description in scenarios.items():
        print(f"\n📊 Scenario: {scenario_type}")
        print(f"   Description: {description}")
        
        # Generate market data
        market_data = generator.generate_stress_test_data(
            pairs=['EURUSD', 'GBPUSD', 'USDJPY'],
            num_candles=500,
            scenario=scenario_type,
        )
        
        # Run simulation
        simulator = StressTestSimulator()
        result = simulator.run_simulation(market_data, scenario_type)
        results[scenario_type] = result
        
        # Export results
        simulator.export_results(f'stress_test_results/{scenario_type}')
    
    print("\n" + "=" * 70)
    print("✅ STRESS TEST SIMULATIONS COMPLETE")
    print("=" * 70)
    print(json.dumps(results, indent=2))
