# Stop & Reverse Trading Bot

An automated cryptocurrency trading bot implementing a **Stop & Reverse** strategy with martingale position sizing for Bybit perpetual futures.

## Strategy Overview

### Core Concept

The Stop & Reverse strategy is a variant of Zone Recovery that uses martingale position sizing to recover from losses. Instead of using traditional stop-losses, the bot "flips" the position direction when the market moves against it, increasing position size to recover previous losses.

### How It Works

1. **Market Scanning**
   - Identifies volatile cryptocurrencies using dual timeframe filtering
   - Primary filter: Configurable timeframe (default: 720min/12h) with minimum % movement
   - Secondary confirmation: Shorter timeframe (default: 5min) ensures coin is still actively moving
   - Timeframes specified in minutes for precise control
   - Excludes innovation zone coins (high-risk new listings)
   - Validates minimum order size and volume requirements

2. **Position Entry**
   - Initial position: 1% of account balance
   - Direction determined by recent momentum

3. **Position Management (The "Flip")**
   - When price moves 1% against the position, instead of closing at a loss:
     - Close the losing position
     - Open a new position in the OPPOSITE direction
     - New position size = previous size × 2.1 (martingale multiplier)
   - Each flip attempts to recover all previous losses plus profit

4. **Exit Strategy**

   **Trailing Take Profit Mode** (default):
   - Activates when position is +1% in profit
   - Exits when price retraces 0.5% from the peak
   - Allows profits to run while protecting gains

   **Static Take Profit Mode**:
   - Simple fixed target exit at +1% profit
   - More predictable but caps potential gains

5. **Risk Management**
   - Maximum 5 flips per cycle (prevents runaway losses)
   - After max flips reached, bot exits and finds new coin
   - Position tracking ensures recovery across bot restarts
   - 10x leverage amplifies returns (and risks)

### Example Cycle

```
Entry: Long BTC @ $100,000 with $10 (1% of $1,000 balance)

Flip 1: Price drops to $99,000 (-1%)
  → Close long at $99,000 (loss: -$1)
  → Open short @ $99,000 with $21 ($10 × 2.1)

Flip 2: Price rises to $99,990 (-1% against short)
  → Close short at $99,990 (loss: -$2.10)
  → Open long @ $99,990 with $44.10 ($21 × 2.1)

Exit: Price rises to $100,990 (+1% from entry)
  → Close long at $100,990
  → Total profit: ~$4.41 - fees
  → Recovered all previous losses + profit
```

## Key Features

- **Exchange-agnostic design**: Built with CCXT for easy multi-exchange support
- **Stateless position tracking**: Reconstructs trading state from exchange fill history
- **Cycle detection**: Automatically identifies position closures and flip counts
- **Simulated balance**: Test strategies without live funds
- **Automatic coin selection**: Continuously scans for optimal volatile pairs
- **Position resumption**: Resumes trading on existing positions after crashes
- **Dynamic fee fetching**: Uses real-time exchange fee rates

## Configuration

Key parameters in `configs/config.json`:

```json
{
  "api": {
    "testnet": false                    // Use testnet or live trading
  },
  
  "account": {
    "simulated_balance_usd": 1000.0,   // Simulated balance for testing
    "use_live_balance": true,          // Use real account balance
    "balance_compound": false,         // Compound profits into balance
    "fixed_initial_order_usd": 5.0     // Fixed order size (if not using %)
  },
  
  "scanner_settings": {
    "min_volume_usd": 1000000,         // Minimum 24h volume (liquidity filter)
    "volatility_lookback_candles": 10, // Candles to analyze for volatility
    "interval": "5m",                  // Candle interval for volatility check
    "top_k_candidates": 20,            // Top volatile coins to analyze
    "timeframe_1_minutes": 720,        // Primary timeframe (720min = 12h)
    "timeframe_1_change_pct": 2.0,     // Min % change for primary timeframe
    "timeframe_2_minutes": 5,          // Secondary timeframe (5min)
    "timeframe_2_change_pct": 1.5      // Min % change to confirm movement
  },
  
  "strategy": {
    "initial_entry_pct": 1.0,          // First position size (% of balance)
    "max_flips": 5,                    // Maximum flips before exit
    "leverage": 10,                    // Position leverage
    "martingale_multiplier": 2.1,      // Size increase per flip (next = prev × 2.1)
    "range_pct": 1.0,                  // Price range % to trigger flip
    "trailing_retracement_pct": 0.5,   // Retrace % from peak to exit
    "market_orders_cycle_start": true, // Use market orders at cycle start
    "exit_use_trailing": false         // Use trailing TP (true) or static (false)
  }
}
```

### Timeframe Configuration Examples

The scanner uses integer minutes for precise timeframe control:

**Conservative (Default):**
```json
"timeframe_1_minutes": 720,   // 12 hours
"timeframe_2_minutes": 5      // 5 minutes
```

**Aggressive Scalping:**
```json
"timeframe_1_minutes": 60,    // 1 hour
"timeframe_2_minutes": 1      // 1 minute
```

**Day Trading:**
```json
"timeframe_1_minutes": 240,   // 4 hours
"timeframe_2_minutes": 15     // 15 minutes
```

**Swing Trading:**
```json
"timeframe_1_minutes": 1440,  // 24 hours (1 day)
"timeframe_2_minutes": 60     // 1 hour
```

## Risk Warning

⚠️ **This strategy carries significant risk:**

- Martingale sizing can lead to large positions
- Volatile markets can trigger rapid flip sequences
- Maximum drawdown occurs after several flips
- Leverage amplifies both gains and losses
- Not suitable for all market conditions

**Only use with capital you can afford to lose. Backtest thoroughly before live trading.**


## Setup

1. Clone repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```
3. Activate the virtual environment:
   - **Windows (PowerShell)**: `.\venv\Scripts\Activate.ps1`
   - **Windows (CMD)**: `venv\Scripts\activate`
   - **Linux/Mac**: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `api-keys.json.example` to `api-keys.json`
6. Add your Bybit API credentials
7. Configure strategy parameters in `configs/config.json`
8. Run: `python src/main.py`

## Architecture

- **BybitClient**: Exchange API wrapper (CCXT-based)
- **MarketScanner**: Volatility-based coin selection
- **PositionTracker**: Stateless position state reconstruction
- **TradeCalculator**: Martingale sizing and TP calculations
- **AccountManager**: Balance and position sizing management

## Status

**Live Trading - Unstable** - Core functionality is operational including market scanning, position tracking, and order execution. However, the bot requires active supervision as it may exhibit unexpected behavior in certain market conditions. Thoroughly test with small positions and monitor closely during operation.

## Disclaimer

**USE AT YOUR OWN RISK**

This software is provided for educational and research purposes only. The authors and contributors are not responsible for any financial losses incurred through the use of this trading bot. Cryptocurrency trading involves substantial risk of loss and is not suitable for every investor.

- **No Investment Advice**: Nothing in this repository constitutes financial, investment, legal, or tax advice.
- **No Warranty**: This software is provided "as is" without warranty of any kind, express or implied.
- **No Liability**: By using this software, you accept full responsibility for any trading decisions and their outcomes.
- **Understand the Risks**: Ensure you fully understand the strategy, risks, and mechanics before deploying real capital.

Always conduct thorough testing, risk assessment, and due diligence before live trading.
