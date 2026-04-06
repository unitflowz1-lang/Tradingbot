"""
Adverse Market Generator
═══════════════════════════════════════════════════════════════
Generates realistic downtrend data with high volatility, 
widening spreads, and sudden slippage events for stress testing.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple


class AdverseMarketGenerator:
    """Generates synthetic market data for stress testing."""

    def __init__(self, seed: int = 42):
        np.random.seed(seed)
        self.seed = seed

    def generate_downtrend_candles(
        self,
        pair: str,
        num_candles: int,
        start_price: float,
        downtrend_strength: float = -0.5,  # pips per candle
        volatility: float = 50.0,  # pips std dev
        vol_regime_changes: bool = True,
    ) -> pd.DataFrame:
        """
        Generate OHLC data with prolonged downtrend.

        Args:
            pair: Currency pair name
            num_candles: Number of candles to generate
            start_price: Starting price
            downtrend_strength: Average pips down per candle
            volatility: Standard deviation of random movement
            vol_regime_changes: Include volatility regime changes

        Returns:
            DataFrame with OHLC data
        """
        candles = []
        current_close = start_price

        for i in range(num_candles):
            # Volatility regime changes (spike volatility 20% of time)
            vol_multiplier = 1.0
            if vol_regime_changes and np.random.random() < 0.2:
                vol_multiplier = np.random.uniform(1.5, 3.0)

            # Generate OHLC
            open_price = current_close
            
            # Downtrend bias + random walk
            downtrend_move = downtrend_strength + np.random.normal(0, volatility * vol_multiplier)
            
            # High/low with volatility
            high_noise = np.abs(np.random.normal(0, volatility * vol_multiplier * 0.7))
            low_noise = np.abs(np.random.normal(0, volatility * vol_multiplier * 0.7))
            
            high_price = max(open_price, current_close + downtrend_move) + high_noise
            low_price = min(open_price, current_close + downtrend_move) - low_noise
            
            close_price = current_close + downtrend_move
            close_price = max(low_price, min(high_price, close_price))
            
            # Volume increases during downtrend stress
            base_volume = 100000
            volume = base_volume * np.random.uniform(0.8, 1.5)
            if vol_multiplier > 1.5:
                volume *= 1.5  # Higher volume during volatility spikes

            candles.append({
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': int(volume),
                'pair': pair,
            })

            current_close = close_price

        df = pd.DataFrame(candles)
        return df

    def add_widening_spreads(
        self,
        df: pd.DataFrame,
        base_spread_bps: float = 2.0,
        stress_spread_bps: float = 10.0,
        stress_frequency: float = 0.1,
    ) -> pd.DataFrame:
        """
        Add realistic spread widening during market stress.

        Args:
            df: OHLC dataframe
            base_spread_bps: Normal spread in basis points
            stress_spread_bps: Stress spread in basis points
            stress_frequency: How often spreads widen (0-1)

        Returns:
            DataFrame with bid/ask prices
        """
        df = df.copy()
        
        spreads = []
        for i in range(len(df)):
            # Normal spread
            if np.random.random() < stress_frequency:
                # Stress event
                spread = stress_spread_bps
            else:
                spread = base_spread_bps
            spreads.append(spread)

        df['spread_bps'] = spreads
        
        # Convert spread bps to pips (assuming 5 decimal places for majors)
        df['spread_pips'] = df['spread_bps'] / 10.0
        
        # Bid/ask prices
        df['bid'] = df['close'] - (df['spread_pips'] / 2)
        df['ask'] = df['close'] + (df['spread_pips'] / 2)
        
        return df

    def add_slippage_events(
        self,
        df: pd.DataFrame,
        base_slippage_bps: float = 0.5,
        stress_slippage_bps: float = 5.0,
        spike_probability: float = 0.05,
    ) -> pd.DataFrame:
        """
        Add realistic slippage with occasional spikes.

        Args:
            df: OHLC dataframe with spreads
            base_slippage_bps: Normal slippage
            stress_slippage_bps: Slippage during stress
            spike_probability: Probability of slippage spike

        Returns:
            DataFrame with slippage values
        """
        df = df.copy()
        
        slippages = []
        for i in range(len(df)):
            if np.random.random() < spike_probability:
                # Sudden slippage spike
                slippage = stress_slippage_bps
            else:
                slippage = base_slippage_bps
            slippages.append(slippage)

        df['slippage_bps'] = slippages
        df['slippage_pips'] = df['slippage_bps'] / 10.0
        
        return df

    def add_regime_changes(
        self,
        num_candles: int,
        num_regimes: int = 3,
    ) -> List[str]:
        """
        Generate regime changes (trending, high-vol, ranging).

        Args:
            num_candles: Number of candles
            num_regimes: Number of regimes to switch between

        Returns:
            List of regime labels
        """
        regime_names = ['downtrend_strong', 'volatility_spike', 'volatile_range']
        regimes = []
        
        candles_per_regime = num_candles // num_regimes
        for regime_idx in range(num_regimes):
            start = regime_idx * candles_per_regime
            end = start + candles_per_regime if regime_idx < num_regimes - 1 else num_candles
            
            regime = regime_names[regime_idx % len(regime_names)]
            regimes.extend([regime] * (end - start))

        return regimes

    def generate_stress_test_data(
        self,
        pairs: List[str] = ['EURUSD', 'GBPUSD', 'USDJPY'],
        num_candles: int = 500,
        scenario: str = 'flash_crash',  # or 'sustained_downtrend', 'high_volatility'
        start_date: datetime = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Generate complete stress test dataset for multiple pairs.

        Args:
            pairs: List of currency pairs
            num_candles: Number of candles to generate
            scenario: Type of stress scenario
            start_date: Starting date

        Returns:
            Dict with data for each pair
        """
        if start_date is None:
            start_date = datetime(2024, 1, 1)

        data = {}

        for pair in pairs:
            # Base prices for each pair
            base_prices = {
                'EURUSD': 1.0800,
                'GBPUSD': 1.2650,
                'USDJPY': 150.25,
                'XAUUSD': 2050.0,
                'GBPJPY': 190.50,
            }
            start_price = base_prices.get(pair, 100.0)

            # Generate candles based on scenario
            if scenario == 'flash_crash':
                # Sudden sharp drop
                df = self.generate_downtrend_candles(
                    pair, num_candles, start_price,
                    downtrend_strength=-2.0,  # Sharp drop
                    volatility=80.0,  # High volatility
                )
            elif scenario == 'sustained_downtrend':
                # Long slow decline
                df = self.generate_downtrend_candles(
                    pair, num_candles, start_price,
                    downtrend_strength=-0.3,  # Slow decline
                    volatility=35.0,
                )
            elif scenario == 'high_volatility':
                # Wild swings
                df = self.generate_downtrend_candles(
                    pair, num_candles, start_price,
                    downtrend_strength=-0.1,
                    volatility=100.0,  # Extreme volatility
                )
            else:
                raise ValueError(f"Unknown scenario: {scenario}")

            # Add market stress
            df = self.add_widening_spreads(
                df, base_spread_bps=2.0, stress_spread_bps=15.0, stress_frequency=0.15
            )
            df = self.add_slippage_events(
                df, base_slippage_bps=0.5, stress_slippage_bps=8.0, spike_probability=0.08
            )

            # Add timestamps
            timestamps = [start_date + timedelta(hours=i) for i in range(num_candles)]
            df['timestamp'] = timestamps

            # Add regime
            df['regime'] = self.add_regime_changes(num_candles, num_regimes=3)

            data[pair] = df

        return data

    def generate_comparison_baseline(
        self,
        pairs: List[str] = ['EURUSD', 'GBPUSD', 'USDJPY'],
        num_candles: int = 500,
        start_date: datetime = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Generate normal market conditions (baseline for comparison).

        Args:
            pairs: List of currency pairs
            num_candles: Number of candles
            start_date: Starting date

        Returns:
            Dict with baseline data
        """
        if start_date is None:
            start_date = datetime(2024, 1, 1)

        data = {}

        for pair in pairs:
            base_prices = {
                'EURUSD': 1.0800,
                'GBPUSD': 1.2650,
                'USDJPY': 150.25,
                'XAUUSD': 2050.0,
                'GBPJPY': 190.50,
            }
            start_price = base_prices.get(pair, 100.0)

            # Generate normal conditions (slight uptrend)
            df = self.generate_downtrend_candles(
                pair, num_candles, start_price,
                downtrend_strength=0.2,  # Slight uptrend (positive)
                volatility=15.0,  # Normal volatility
            )

            # Normal spreads
            df = self.add_widening_spreads(
                df, base_spread_bps=2.0, stress_spread_bps=4.0, stress_frequency=0.02
            )
            df = self.add_slippage_events(
                df, base_slippage_bps=0.3, stress_slippage_bps=1.0, spike_probability=0.01
            )

            # Add timestamps
            timestamps = [start_date + timedelta(hours=i) for i in range(num_candles)]
            df['timestamp'] = timestamps
            df['regime'] = ['normal'] * num_candles

            data[pair] = df

        return data


if __name__ == "__main__":
    # Example usage
    generator = AdverseMarketGenerator(seed=42)

    print("🔥 Generating adverse market scenarios...")
    
    scenarios = ['flash_crash', 'sustained_downtrend', 'high_volatility']
    
    for scenario in scenarios:
        print(f"\n  {scenario.upper()}")
        data = generator.generate_stress_test_data(
            pairs=['EURUSD', 'GBPUSD', 'USDJPY'],
            num_candles=500,
            scenario=scenario,
        )
        
        for pair, df in data.items():
            print(f"    {pair}: {len(df)} candles, "
                  f"Open={df['open'].iloc[0]:.4f}, "
                  f"Close={df['close'].iloc[-1]:.4f}, "
                  f"Drawdown={((df['close'].min() - df['open'].iloc[0]) / df['open'].iloc[0] * 100):.2f}%")

    print("\n✅ Adverse market data generation complete!")
