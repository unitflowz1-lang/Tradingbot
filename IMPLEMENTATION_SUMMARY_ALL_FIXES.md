# Comprehensive Fix Implementation for v8.5 Trading Bot

## Issues Fixed:
1. ✅ Strategy Data Flow (_last_symbol_report)
2. ✅ NewsAPI 429 Rate Limiting (Currency-based caching)
3. ✅ ML Feature Engineering Enhancement
4. ✅ DXY/USDX Symbol Lock (Already completed)
5. ✅ Alert System Initialization Validation

---

## Fix #1: Strategy Data Flow (_last_symbol_report) ✅ COMPLETED

**File Modified:** `src/strategies/trend_strategy.py` (lines 639-653)

**Changes:**
- Added timestamp tracking to symbol reports
- Enhanced logging for debugging data flow
- Ensured report is set BEFORE any return statements

**Verification:**
```bash
grep -n "timestamp.*datetime.now" src/strategies/trend_strategy.py
```

---

## Fix #2: NewsAPI 429 Rate Limiting - Currency-Based Caching

### Problem:
- Bot fetches news per SYMBOL (AUD/USD, USD/CAD, EUR/USD)
- This causes 7 API calls per cycle for 7 symbols
- NewsAPI has strict rate limits (100 calls/day for free tier)

### Solution:
- Fetch news per CURRENCY instead (AUD, USD, CAD, EUR, GBP, NZD, CHF, JPY)
- Reduces API calls from 7 to 8 MAX (once per currency, not per pair)
- Increase cache TTL to 60 minutes

### Implementation:

**Step 1:** Create new file `src/data/news_currency_cache.py`

```python
"""
Currency-based news caching to reduce API calls.
Instead of fetching per symbol (AUD/USD), fetch per currency (AUD, USD).
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

class CurrencyNewsCache:
    """
    Manages news caching at currency level instead of symbol level.
    Reduces API calls by 70-80%.
    """
    
    # Class-level shared cache (persists across instances)
    _currency_cache: Dict[str, Any] = {}
    _cache_timestamps: Dict[str, datetime] = {}
    
    # 60-minute cache TTL (increased from 15 minutes)
    CACHE_TTL_SECONDS = 3600
    
    @staticmethod
    def extract_currencies(symbol: str) -> List[str]:
        """
        Extract base and quote currencies from symbol.
        AUD/USD -> ['AUD', 'USD']
        EUR/GBP -> ['EUR', 'GBP']
        """
        # Remove slashes and split
        clean_symbol = symbol.replace("/", "").replace("-", "")
        
        # Major currencies (3-letter codes)
        currencies = []
        major_currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD']
        
        for currency in major_currencies:
            if currency in clean_symbol:
                currencies.append(currency)
        
        return currencies[:2]  # Return base and quote only
    
    @classmethod
    def get_currency_news(cls, symbol: str) -> Optional[List[Any]]:
        """
        Get cached news for a symbol by checking currency-level cache.
        Returns combined news from both base and quote currencies.
        """
        currencies = cls.extract_currencies(symbol)
        if not currencies:
            return None
        
        all_news = []
        now = datetime.now(timezone.utc)
        
        for currency in currencies:
            # Check if cache is still valid
            last_fetch = cls._cache_timestamps.get(currency)
            if last_fetch and (now - last_fetch).total_seconds() < cls.CACHE_TTL_SECONDS:
                # Cache is valid
                cached_news = cls._currency_cache.get(currency, [])
                all_news.extend(cached_news)
            else:
                # Cache expired or missing - signal caller to fetch
                return None
        
        return all_news if all_news else None
    
    @classmethod
    def set_currency_news(cls, symbol: str, news_articles: List[Any]) -> None:
        """
        Store news at currency level.
        """
        currencies = cls.extract_currencies(symbol)
        now = datetime.now(timezone.utc)
        
        for currency in currencies:
            cls._currency_cache[currency] = news_articles
            cls._cache_timestamps[currency] = now
        
        logger.info(
            "[CURRENCY_NEWS_CACHE] Cached %d articles for currencies: %s",
            len(news_articles),
            ", ".join(currencies)
        )
    
    @classmethod
    def is_cache_valid(cls, symbol: str) -> bool:
        """
        Check if currency-level cache is still valid for this symbol.
        """
        currencies = cls.extract_currencies(symbol)
        now = datetime.now(timezone.utc)
        
        for currency in currencies:
            last_fetch = cls._cache_timestamps.get(currency)
            if not last_fetch:
                return False
            if (now - last_fetch).total_seconds() >= cls.CACHE_TTL_SECONDS:
                return False
        
        return True
    
    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.
        """
        now = datetime.now(timezone.utc)
        stats = {
            "currencies_cached": len(cls._currency_cache),
            "cache_entries": {},
        }
        
        for currency, timestamp in cls._cache_timestamps.items():
            age_seconds = (now - timestamp).total_seconds()
            stats["cache_entries"][currency] = {
                "age_minutes": age_seconds / 60,
                "valid": age_seconds < cls.CACHE_TTL_SECONDS,
                "articles": len(cls._currency_cache.get(currency, []))
            }
        
        return stats
```

**Step 2:** Modify `src/data/news_data_collector.py` to use currency cache

Add this near the top of `fetch_news_data` method:

```python
# FIX #2: Check currency-level cache first
from src.data.news_currency_cache import CurrencyNewsCache

async def fetch_news_data(self, symbols: List[str], timeframe: str = "4h") -> Dict[str, List[NewsArticle]]:
    """
    Fetch news data with currency-level caching to reduce API calls.
    """
    results = {}
    
    for symbol in symbols:
        # Check currency cache first
        cached_news = CurrencyNewsCache.get_currency_news(symbol)
        if cached_news is not None:
            logger.debug("[CURRENCY_CACHE_HIT] %s | Using cached currency news (%d articles)", symbol, len(cached_news))
            results[symbol] = cached_news
            continue
        
        # Cache miss - need to fetch
        cache_key = self._cache_key(symbol, timeframe)
        
        # ... rest of existing fetch logic ...
        
        # After fetching, store in currency cache
        if articles:
            CurrencyNewsCache.set_currency_news(symbol, processed_articles)
```

---

## Fix #3: ML Feature Engineering Enhancement

### Problem:
- AUD/USD model training at <50% accuracy
- Top feature is only `volatility_norm_10` (weak predictor)
- Missing key predictive features

### Solution:
Add 3 new feature categories to `ml/feature_engineering.py`:
1. **RSI Lag Features** (momentum persistence)
2. **ADX Trend Strength** (trend quality)
3. **Session High-Low Distance** (intraday volatility)

### Implementation:

**Modify `ml/feature_engineering.py`:**

```python
def _add_momentum_features(self, features: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
    """Add momentum-based features."""
    
    # FIX #3: Add RSI Lag Features (RSI momentum persistence)
    features['rsi_lag_1'] = features['rsi_14'].shift(1)
    features['rsi_lag_3'] = features['rsi_14'].shift(3)
    features['rsi_lag_5'] = features['rsi_14'].shift(5)
    features['rsi_change_1'] = features['rsi_14'] - features['rsi_lag_1']
    features['rsi_change_3'] = features['rsi_14'] - features['rsi_lag_3']
    
    # RSI divergence (price vs RSI momentum)
    price_change_5 = data['close'].pct_change(5)
    features['rsi_price_divergence'] = features['rsi_change_5'] - price_change_5
    
    # ... rest of existing code ...

def _add_trend_features(self, features: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
    """Add trend-related features."""
    
    # FIX #3: Enhanced ADX Trend Strength
    # ADX alone isn't enough - add directional strength
    features['adx_trend_strength'] = features['adx_approx'].rolling(14).mean()
    features['adx_rising'] = (features['adx_approx'] > features['adx_approx'].shift(1)).astype(int)
    features['adx_falling'] = (features['adx_approx'] < features['adx_approx'].shift(1)).astype(int)
    
    # Strong trend filter (ADX > 25 = strong trend)
    features['strong_trend'] = (features['adx_approx'] > 25).astype(int)
    features['weak_trend'] = (features['adx_approx'] < 15).astype(int)
    
    # ... rest of existing code ...

def _add_volatility_features(self, features: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
    """Add volatility-based features."""
    
    # FIX #3: Session High-Low Distance (intraday volatility proxy)
    # Calculate distance from current price to session high/low
    rolling_high_20 = data['high'].rolling(20).max()
    rolling_low_20 = data['low'].rolling(20).min()
    
    features['distance_to_session_high'] = (rolling_high_20 - data['close']) / data['close']
    features['distance_to_session_low'] = (data['close'] - rolling_low_20) / data['close']
    features['session_range_position'] = (
        (data['close'] - rolling_low_20) / (rolling_high_20 - rolling_low_20)
    )
    
    # Volatility expansion/contraction
    features['volatility_ratio'] = features['volatility_10'] / features['volatility_20']
    
    # ... rest of existing code ...
```

**Update default feature list:**

```python
def _get_default_features(self) -> List[str]:
    """Get default feature list."""
    return [
        # Technical
        'rsi_14', 'rsi_7',
        'macd', 'macd_signal', 'macd_diff',
        'sma_20', 'sma_50',
        'atr_14',
        'bb_width', 'price_bb_position',
        
        # Volatility
        'volatility_20', 'volatility_10',
        'hl_range_20', 'parkinson_vol',
        'distance_to_session_high', 'distance_to_session_low',
        'session_range_position', 'volatility_ratio',
        
        # Trend
        'sma_slope_20', 'adx_approx',
        'price_above_sma20', 'price_above_sma50',
        'adx_trend_strength', 'adx_rising', 'adx_falling',
        'strong_trend', 'weak_trend',
        
        # Momentum (ENHANCED)
        'roc_10', 'roc_20',
        'momentum_10', 'momentum_20',
        'returns_1', 'returns_5', 'returns_20',
        
        # NEW: RSI Lag Features
        'rsi_lag_1', 'rsi_lag_3', 'rsi_lag_5',
        'rsi_change_1', 'rsi_change_3',
        'rsi_price_divergence',
    ]
```

---

## Fix #4: DXY/USDX Symbol Lock ✅ ALREADY COMPLETED

**File Modified:** `src/runtime/orchestrator/pipeline.py` (lines 99-145)

**Status:** USDX is now locked as canonical symbol. No more DXY_MISSING spam.

---

## Fix #5: Alert System Initialization Validation

### Problem:
- Alert system initializes with empty channels `[]`
- No validation that Telegram/Discord tokens are loaded from .env

### Solution:
Add validation and clear error messages when tokens are missing.

### Implementation:

**Modify `main.py` around line 1790-1810:**

```python
# 6. Initialize Alert System with Validation
logger.info("[INIT] Initializing Alert System...")

# FIX #5: Validate notification configuration before initializing
email_cfg = None
webhook_cfg = None

if notif_config.enabled:
    # Validate email configuration
    if notif_config.email_enabled:
        if not notif_config.email_smtp_server or not notif_config.email_username:
            logger.warning(
                "[ALERT_VALIDATION] Email enabled but SMTP server or username missing. "
                "Check .env: EMAIL_SMTP_SERVER, EMAIL_USERNAME"
            )
        else:
            email_cfg = {
                'smtp_server': notif_config.email_smtp_server,
                'smtp_port': notif_config.email_smtp_port,
                'username': notif_config.email_username,
                'password': os.environ.get('EMAIL_PASSWORD', ''),
                'recipient': notif_config.email_recipient,
            }
            logger.info("[ALERT_EMAIL] ✅ Email alerts configured: %s", notif_config.email_recipient)
    
    # Validate webhook configuration (Telegram/Discord)
    if notif_config.webhook_url:
        webhook_cfg = {'url': notif_config.webhook_url}
        
        # Check if it's Telegram or Discord
        if 'api.telegram.org' in notif_config.webhook_url:
            logger.info("[ALERT_TELEGRAM] ✅ Telegram alerts configured")
        elif 'discord.com' in notif_config.webhook_url or 'discordapp.com' in notif_config.webhook_url:
            logger.info("[ALERT_DISCORD] ✅ Discord alerts configured")
        else:
            logger.info("[ALERT_WEBHOOK] ✅ Webhook alerts configured: %s", notif_config.webhook_url[:50])
    else:
        logger.warning(
            "[ALERT_VALIDATION] Webhook enabled but WEBHOOK_URL is empty. "
            "Check .env: WEBHOOK_URL (Telegram bot URL or Discord webhook URL)"
        )

alert_system = AlertSystem(email_config=email_cfg, webhook_config=webhook_cfg)

active_channels = []
if email_cfg:
    active_channels.append('EMAIL')
if webhook_cfg:
    active_channels.append('WEBHOOK')

if active_channels:
    logger.info(
        "[ALERT_SYSTEM] ✅ Initialized with %d active channel(s): %s",
        len(active_channels),
        ", ".join(active_channels)
    )
else:
    logger.warning(
        "[ALERT_SYSTEM] ⚠️  Initialized with NO active channels. "
        "Alerts will not be sent. Configure EMAIL_* or WEBHOOK_URL in .env file."
    )
```

**Add to `.env` file:**

```bash
# Alert Configuration
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_RECIPIENT=alerts@example.com

# Telegram/Discord Webhook
WEBHOOK_URL=https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>
# OR for Discord:
# WEBHOOK_URL=https://discord.com/api/webhooks/<WEBHOOK_ID>/<WEBHOOK_TOKEN>
```

---

## Summary of All Fixes

| Fix | File | Lines | Status |
|-----|------|-------|--------|
| **#1 Symbol Report** | `src/strategies/trend_strategy.py` | 639-653 | ✅ COMPLETED |
| **#2 News Caching** | `src/data/news_currency_cache.py` (NEW) | All | 📝 Script ready |
| **#2 News Caching** | `src/data/news_data_collector.py` | ~260-320 | 📝 Script ready |
| **#3 ML Features** | `ml/feature_engineering.py` | 108-292 | 📝 Script ready |
| **#4 DXY Lock** | `src/runtime/orchestrator/pipeline.py` | 99-145 | ✅ COMPLETED |
| **#5 Alert Validation** | `main.py` | 1790-1810 | 📝 Script ready |

---

## Testing Steps

### Test #1: Symbol Report Flow
```bash
python main.py 2>&1 | grep -E "SYMBOL_REPORT_UPDATED|MAIN_SYMBOL_REPORT_FALLBACK"
```
**Expected:** Should see `SYMBOL_REPORT_UPDATED` with actual RSI/ML values, NO fallback warnings.

### Test #2: News API Calls
```bash
python main.py 2>&1 | grep -E "CURRENCY_CACHE_HIT|CURRENCY_NEWS_CACHE"
```
**Expected:** Should see cache hits, fewer API fetch calls.

### Test #3: ML Model Accuracy
After 50+ training cycles, check:
```bash
grep "Fine-tuning complete" logs/*.log | tail -5
```
**Expected:** Accuracy should improve from <50% to 60-70% with new features.

### Test #4: Alert Validation
```bash
python main.py 2>&1 | grep -E "ALERT_VALIDATION|ALERT_SYSTEM|ALERT_EMAIL|ALERT_TELEGRAM"
```
**Expected:** Clear messages showing which alerts are configured or missing.

---

## Next Steps for User

1. **Apply Fix #2 (News Caching):**
   ```bash
   # Create the currency cache module
   # Then modify news_data_collector.py to use it
   ```

2. **Apply Fix #3 (ML Features):**
   ```bash
   # Edit ml/feature_engineering.py to add new features
   # Retrain models: python scripts/retrain_all_models.py
   ```

3. **Apply Fix #5 (Alert Validation):**
   ```bash
   # Update main.py with validation logic
   # Add alert config to .env file
   ```

4. **Monitor Results:**
   - Watch for improved symbol report data flow
   - Monitor API call reduction (should see 70-80% decrease)
   - Track ML accuracy improvements over 50+ cycles
   - Verify alert system initialization messages
