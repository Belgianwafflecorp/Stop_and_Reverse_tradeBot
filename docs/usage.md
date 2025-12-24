# Usage Guide

How to run and control the Stop & Reverse Trading Bot.

## Installation

Before running the bot, ensure you have the required dependencies installed:

```bash
pip install -r requirements.txt
```

## Basic Execution

To run the bot with the default configuration:

```bash
python src/main.py
```

## Command Line Arguments

The bot accepts command-line arguments to control its behavior at startup.

### 1. Specify Configuration File
You can load a specific configuration preset by passing the file path as an argument.

**Syntax:**
```bash
python src/main.py [path_to_config]
```

**Examples:**
```bash
# Run with aggressive settings
python src/main.py configs/aggressive.json

# Run with a custom config
python src/main.py configs/my_scalping_strategy.json
```

### 2. Enable File Logging (`-logs`)
By default, the bot only logs to the console to keep disk usage low. Use the `-logs` flag to save detailed debug logs to the `logs/` directory.

**Syntax:**
```bash
python src/main.py -logs
```

**Behavior:**
- Creates a `logs/` directory if it doesn't exist.
- Generates a timestamped log file (e.g., `trading_bot_20231025_120000.log`).
- Saves `DEBUG` level logs (including raw API responses) to the file.
- Console output remains at `INFO` level.

### 3. Combining Arguments
You can combine configuration files and flags in any order.

**Example:**
```bash
python src/main.py configs/aggressive.json -logs
```
