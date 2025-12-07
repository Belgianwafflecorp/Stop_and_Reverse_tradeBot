# Stop & Reverse Trading Bot

An automated cryptocurrency trading bot implementing a **Stop & Reverse** strategy with martingale position sizing for Bybit perpetual futures.

## Strategy Overview

### Core Concept

The Stop & Reverse strategy is a variant of Zone Recovery that uses martingale position sizing to recover from losses. Instead of using traditional stop-losses, the bot "flips" the position direction when the market moves against it, increasing position size to recover previous losses.

### How It Works

1. **Market Scanning**
   - Identifies volatile cryptocurrencies using dual timeframe filtering
   - Primary filter: 12h movement > 2%
   - Secondary confirmation: 5min movement > 1%
   - Excludes innovation zone coins (high-risk new listings)
   - Validates minimum order size requirements

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
  "strategy": {
    "initial_entry_pct": 1.0,           // First position size (% of balance)
    "martingale_multiplier": 2.1,       // Size increase per flip
    "max_flips": 5,                     // Maximum flips before exit
    "flip_threshold_pct": 1.0,          // Price move to trigger flip
    "leverage": 10,                     // Position leverage
    "exit_use_trailing": true,          // Trailing vs static TP
    "exit_trailing": {
      "activation_pct": 1.0,            // Profit to activate trailing
      "callback_pct": 0.5               // Retrace to exit
    }
  }
}
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
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `api-keys.json.example` to `api-keys.json`
4. Add your Bybit API credentials
5. Configure strategy parameters in `configs/config.json`
6. Run: `python src/main.py`

## Architecture

- **BybitClient**: Exchange API wrapper (CCXT-based)
- **MarketScanner**: Volatility-based coin selection
- **PositionTracker**: Stateless position state reconstruction
- **TradeCalculator**: Martingale sizing and TP calculations
- **AccountManager**: Balance and position sizing management

## Status

**In Development** - Core scanning and tracking logic complete. Order placement and live trading logic pending implementation.
