# Codebase Structure & Functionality

This document provides an overview of the project structure and describes the logic and functionality residing in each file. It is intended to help contributors and users understand how the Stop & Reverse Trading Bot operates.

## Directory Structure

```text
Stop_and_Reverse_tradeBot/
├── configs/             # Configuration files (strategy, account settings)
├── docs/                # Project documentation
├── src/                 # Source code
│   ├── exchanges/       # Exchange-specific adapters (e.g., Bybit)
│   ├── account_manager.py
│   ├── calc_engine.py
│   ├── json_handler.py
│   ├── logger.py
│   ├── main.py
│   ├── market_scanner.py
│   └── position_tracker.py
├── api-keys.json        # API credentials (git-ignored)
└── requirements.txt     # Python dependencies
```

## Core Components (`src/`)

### 1. `src/main.py`
**Role:** The Brain & Orchestrator.
This is the entry point of the application. It ties all other components together and manages the main execution loop.

**Key Functionality:**
- **Lifecycle Management:** Starts the bot, initializes connections, and handles graceful shutdowns.
- **Trade Cycle Orchestration:**
    1.  Calls `MarketScanner` to find a target coin.
    2.  Places the initial entry order.
    3.  Monitors the position via WebSockets.
    4.  Executes Flips (Reverse) or Exits based on triggers.
- **WebSocket Monitoring:** Listens for real-time position updates to detect flips instantly.
- **Safety Logic:** Implements connection retries, fallback to REST polling if WebSockets fail, and manual flip triggers if price gaps occur.
- **Order Execution:** Sends final order instructions to the exchange wrapper.

### 2. `src/calc_engine.py`
**Role:** Strategy Logic & Mathematics.
This file contains the pure logic for the trading strategy. It calculates *numbers* but does not execute trades.

**Key Functionality:**
- **Range Calculation:** Determines the percentage distance for TP and Flip triggers. Handles the `range_pct_increase_per_flip` logic (expanding the range after every flip).
- **Position Sizing:** Calculates the size of the *next* trade using the Martingale multiplier.
- **Stop Loss Decision:** Checks `max_flips` to determine if the next move should be a Flip (Reverse) or a Hard Stop (Close).
- **Exit Calculations:** Determines static Take Profit prices or Trailing Stop parameters.

### 3. `src/position_tracker.py`
**Role:** State & Memory.
Since the bot is designed to be restartable, it needs to know the current state of a trade cycle (e.g., "Is this the 1st flip or the 3rd?").

**Key Functionality:**
- **Fill Analysis:** Fetches historical trade fills from the exchange.
- **State Reconstruction:** Reconstructs the current cycle state (Flip Count, Realized PnL, Current Side) by analyzing the sequence of buys and sells.
- **Cycle Detection:** Identifies when a trade cycle has started and when it has completed.

### 4. `src/market_scanner.py`
**Role:** Opportunity Finder.
Responsible for scanning the market to find the best coin to trade next.

**Key Functionality:**
- **Market Filtering:** Filters coins based on volume, trading status, and specific exchange phases (e.g., skipping "Reduce Only" phases).
- **Dual Timeframe Analysis:**
    - Checks macro trend (e.g., 24h change).
    - Confirms with micro momentum (e.g., 5m change).
- **Volatility Scoring:** Scores candidates based on recent volatility to ensure the bot enters coins that are moving.
    - Applies a minimum score threshold (`min_candidate_score`) to filter out weak candidates.

### 5. `src/account_manager.py`
**Role:** Wallet & Risk Management.
Manages account balance data and initial risk sizing.

**Key Functionality:**
- **Balance Fetching:** Retrieves available USDT balance from the exchange.
- **Initial Sizing:** Calculates the size of the *first* entry in a cycle (Flip 0) based on config (Fixed USD amount or % of Balance).
- **Safety Checks:** `check_sufficient_balance` verifies if the wallet has enough funds for the next trade (including a buffer for fees) to prevent "Insufficient Funds" errors.

### 6. `src/logger.py`
**Role:** Output & Logging.
Provides a standardized way to log events to both the console and files.

**Key Functionality:**
- **Dual Logging:** Writes detailed debug logs to `logs/` files and readable info logs to the console.
- **Formatting:** Formats trade events (Orders, Flips, PnL) for better readability.

### 7. `src/json_handler.py`
**Role:** Configuration Utility.
Helper functions for loading JSON files.

**Key Functionality:**
- Centralizes logic for loading `config.json` and `api-keys.json`.
- Handles path resolution to ensure files are found regardless of where the script is run from.

### 8. `src/exchanges/bybit.py`
**Role:** API Adapter.
A wrapper around the `ccxt` library specifically for Bybit.

**Key Functionality:**
- **Authentication:** Manages API keys and connection setup.
- **Order Management:** Provides simplified methods for creating Market, Limit, and Conditional orders.
- **Data Fetching:** Fetches candles, tickers, and account info.