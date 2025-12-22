# Configuration Guide

Complete documentation for all configuration parameters in `config.json`.

---

## API Settings

### `api.testnet`
- **Default:** `false`
- **Description:** Controls whether to use exchange testnet for trading operations. Market data is always fetched from mainnet for accuracy.

---

## Account Settings

### `account.simulated_balance_usd`
- **Default:** `1000.0`
- **Description:** Simulated account balance in USD for backtesting and testing without live funds.
- **Used when:** `use_live_balance` is `false`

### `account.use_live_balance`
- **Default:** `false`
- **Description:** When `true`, fetches real balance from exchange. When `false`, uses `simulated_balance_usd`.
- **Warning:** Set to `true` only for live trading with real funds.

### `account.balance_compound`
- **Default:** `true`
- **Description:** Determines how initial position size is calculated:
  - `true`: Position size = current balance × `initial_entry_pct` (compounds profits)
  - `false`: Position size = `fixed_initial_order_usd` (constant size)

### `account.fixed_initial_order_usd`
- **Default:** `10.0`
- **Description:** Fixed position size in USD when `balance_compound` is `false`.
- **Used when:** `balance_compound` is `false`

---

## Scanner Settings

### `scanner_settings.min_volume_usd`
- **Default:** `1000000`
- **Description:** Minimum 24h trading volume in USD. Filters out low-liquidity coins.
- **Recommended:** At least 1M for reliable execution.

### `scanner_settings.volatility_lookback_candles`
- **Default:** `10`
- **Description:** Number of recent candles to analyze for volatility calculation.
- **Higher values:** More stable volatility readings, slower to react.
- **Lower values:** More responsive to recent price action.

### `scanner_settings.interval`
- **Default:** `"5m"`
- **Description:** Candle interval for volatility analysis.
- **Valid values:** `"1m"`, `"5m"`, `"15m"`, `"1h"`, etc.

### `scanner_settings.top_k_candidates`
- **Default:** `20`
- **Description:** Maximum number of candidate coins to analyze in detail.
- **Higher values:** More options but slower scanning.

### `scanner_settings.timeframe_1_minutes`
- **Default:** `720` (12 hours)
- **Description:** Primary timeframe filter in minutes. Identifies coins with significant movement.
- **Aggressive config:** `60` (1 hour) for more current opportunities.
- **Conservative config:** `1440` (24 hours) for established trends.

### `scanner_settings.timeframe_1_change_pct`
- **Default:** `2.0`
- **Description:** Minimum percentage change required over `timeframe_1_minutes`.
- **Higher values:** Only extreme volatility coins.
- **Lower values:** More candidates but less volatile.

### `scanner_settings.timeframe_2_minutes`
- **Default:** `5`
- **Description:** Secondary timeframe for momentum confirmation in minutes.
- **Purpose:** Ensures coin is moving RIGHT NOW, not just historically.

### `scanner_settings.timeframe_2_change_pct`
- **Default:** `1.0`
- **Description:** Minimum percentage change required over `timeframe_2_minutes`.
- **This is your "moving now" filter** - confirms current momentum.

### `scanner_settings.min_candidate_score`
- **Default:** `1.5`
- **Description:** Minimum combined score required for a candidate to be selected.
- **Calculation:** Score = (Recent Volatility × 0.7) + (Timeframe 2 Movement × 0.3).
- **Purpose:** Ensures candidates have a healthy mix of historical volatility and current momentum.

---

## Strategy Settings

### `strategy.initial_entry_pct`
- **Default:** `1.0`
- **Description:** First position size as percentage of account balance (when `balance_compound` is `true`).
- **Example:** With $1000 balance and 1.0%, first position = $10.
- **Risk:** Higher values = larger positions but faster capital depletion on flips.

### `strategy.max_flips`
- **Default:** `5`
- **Description:** Maximum number of position flips before exiting cycle.
- **Risk management:** Prevents runaway martingale losses.
- **Calculate max drawdown per cycle:** initial_size × (multiplier^max_flips - 1) / (multiplier - 1)

### `strategy.leverage`
- **Default:** `10`
- **Description:** Position leverage multiplier.
- **Warning:** Higher leverage = higher risk. 10x means 10% move = 100% gain/loss.

### `strategy.martingale_multiplier`
- **Default:** `2.1`
- **Description:** Size multiplier for each flip.
- **Example:** If position 1 is $10, position 2 is $21, position 3 is $44.10, etc.
- **Higher values:** Faster recovery but larger positions.
- **Lower values:** Safer but slower recovery.

### `strategy.range_pct`
- **Default:** `1.0`
- **Description:** **Critical parameter** - controls multiple behaviors:
  1. **Flip trigger:** Price moves `range_pct` against position → flip
  2. **Trailing TP activation:** Profit reaches `range_pct` → trailing starts
  3. **Static TP target:** Exit at `range_pct` profit
- **Example:** 1.0% means flip every 1% move, take profit at 1% gain.
- **Tighter ranges (0.5%):** More flips, smaller moves.
- **Wider ranges (2.0%):** Fewer flips, larger moves.

### `strategy.trailing_retracement_pct`
- **Default:** `0.5`
- **Description:** How much price can retrace from peak before trailing TP triggers.
- **Only used when:** `exit_use_trailing` is `true`
- **Example:** Position peaks at +2%, retraces to +1.5% → exits (0.5% retracement).
- **Tighter values (0.3%):** Exit sooner, lock profits faster.
- **Wider values (1.0%):** Let it run more, risk giving back more profit.

### `strategy.market_orders_cycle_start`
- **Default:** `true`
- **Description:** Order type for first entry of each cycle:
  - `true`: Market order (instant execution, slight slippage)
  - `false`: Limit order at current price (better fill, risk of missing entry)
- **Note:** Flips and TPs always use limit orders since prices are known.

### `strategy.exit_use_trailing`
- **Default:** `true`
- **Description:** Exit strategy mode:
  - `true`: Trailing take profit (lets profits run, exits on retracement)
  - `false`: Static take profit (exits at fixed `range_pct` target)
- **Trailing:** Better for trending markets, captures larger moves.
- **Static:** More predictable, good for ranging markets.

---

## Configuration Presets

### Default Config (`config.json`)
- **Timeframe:** 12h + 5min (balanced)
- **Volatility threshold:** 2% + 1%
- **Best for:** Moderate volatility, established trends

### Aggressive Config (`aggressive.json`)
- **Timeframe:** 1h + 5min (current momentum)
- **Volatility threshold:** 3% + 0.5%
- **Best for:** High frequency, current market conditions, scalping volatile moves

---

## Risk Calculator

Calculate maximum possible loss before hitting `max_flips`:

```
Total Capital Required = initial_size × Σ(multiplier^i) for i=0 to max_flips

Example with defaults:
- Initial: $10
- Multiplier: 2.1
- Max flips: 5

Position sizes: $10, $21, $44.10, $92.61, $194.48, $408.41
Total: $770.60 of capital needed to execute full sequence
```

---

## Exchange Compatibility

All USD-denominated settings (`simulated_balance_usd`, `min_volume_usd`, `fixed_initial_order_usd`) work with any stablecoin:
- Bybit: USDT
- Hyperliquid: USDC
- Other exchanges: USDT, USDC, BUSD, etc.

The configuration uses generic "USD" naming for multi-exchange compatibility.

---

## Tips for Configuration

1. **Start conservative:** Small `initial_entry_pct`, wide `range_pct`, low `leverage`
2. **Test with simulated balance first:** Set `use_live_balance: false`
3. **Match timeframes to strategy:** Day trading → 1h/5m, Swing trading → 24h/15m
4. **Balance risk/reward:** Tighter ranges = more flips but faster recovery
5. **Monitor max_flips:** Ensure you have capital for full martingale sequence
6. **Backtest:** Run with `simulated_balance_usd` on different timeframes before live trading

---

## Advanced: Creating Custom Configs

1. Copy `config.json` or `aggressive.json`
2. Name it descriptively (e.g., `scalping.json`, `swing.json`)
3. Adjust parameters for your strategy
4. Run with: `python src/main.py configs/your_config.json`

Remember: Smaller timeframes need tighter ranges, larger timeframes can use wider ranges.
