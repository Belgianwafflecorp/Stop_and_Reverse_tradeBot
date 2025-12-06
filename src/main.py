import json
import sys
import os
import time

# Path setup
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)

from src.exchanges.bybit import BybitClient
from src.calc_engine import TradeCalculator
from src.market_scanner import MarketScanner
from src.position_tracker import PositionTracker
from src.account_manager import AccountManager  

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

class TradingBot:
    def __init__(self):
        # 1. Load Configs
        self.config_path = os.path.join(PROJECT_ROOT, 'configs', 'config.json')
        self.keys_path = os.path.join(PROJECT_ROOT, 'api-keys.json')
        self.keys_example_path = os.path.join(PROJECT_ROOT, 'api-keys.json.example')

        try:
            self.config = load_json(self.config_path)
        except FileNotFoundError as e:
            print(f"\nCRITICAL ERROR: Config file not found!")
            print(f"Looking for: {e.filename}")
            sys.exit(1)
        
        # Handle API keys file with better error messaging
        try:
            self.keys = load_json(self.keys_path)
        except FileNotFoundError:
            print(f"\nAPI KEYS FILE NOT FOUND!")
            print(f"Could not find: {self.keys_path}")
            
            if os.path.exists(self.keys_example_path):
                print(f"\n📝 SETUP INSTRUCTIONS:")
                print(f"1. Copy the example file to create your API keys file:")
                print(f"   copy api-keys.json.example api-keys.json")
                print(f"2. Edit 'api-keys.json' and replace the placeholder values with your real API keys")
                print(f"\n💡 The example file exists at: {self.keys_example_path}")
            else:
                print(f"\nEven the example file is missing: {self.keys_example_path}")
                print(f"Please ensure you have the complete project files.")
            
            print(f"\nBot cannot run without API keys configuration. Exiting...")
            sys.exit(1)

        # 2. Initialize Exchange (The Connection)
        print("Connecting to Bybit...")
        
        # Check if API keys are configured (not empty or placeholder values)
        bybit_keys = self.keys.get('bybit', {})
        api_key = bybit_keys.get('api_key', '')
        api_secret = bybit_keys.get('api_secret', '')
        
        # Only use keys if they're actually configured
        if api_key and api_secret and api_key != 'your_api_key_here':
            self.bybit = BybitClient(
                api_key=api_key,
                api_secret=api_secret,
                testnet=self.config['api'].get('testnet', False)
            )
        else:
            print("WARNING: No valid API keys found - running in public data mode only")
            self.bybit = BybitClient(testnet=self.config['api'].get('testnet', False))

        # 3. Initialize Components
        self.calculator = TradeCalculator(self.config, self.bybit)
        
        # Account manager for balance and position sizing
        self.account = AccountManager(self.bybit, self.config)
        
        # Dependency Injection: Pass the 'bybit' client and account manager to the scanner
        self.scanner = MarketScanner(self.bybit, self.config, self.account)
        
        # Position tracker for state management (needs config for cycle detection)
        self.tracker = PositionTracker(self.bybit, self.config)
        
        self.active_coin = None

    def start_cycle(self):
        """Starts the scanning and trading process."""
        
        # 1. Find the best coin
        self.active_coin = self.scanner.get_best_volatile_coin()
        
        if not self.active_coin:
            print("No coin found. Waiting 60 seconds.")
            time.sleep(60)
            return

        print(f"Starting cycle on {self.active_coin}")
        
        # Check current position state before trading
        position_state = self.tracker.analyze_position_state(self.active_coin, lookback_hours=1)
        print(self.tracker.get_position_summary(self.active_coin, lookback_hours=1))
        
        # Here you would trigger the trading logic (Order placement, etc.)
        # self.execute_trade_logic(self.active_coin, position_state)

    def run(self):
        while True:
            try:
                self.start_cycle()
                # For now, break after finding one coin to test
                print("Test run complete.") 
                break 
            except KeyboardInterrupt:
                print("Bot stopped by user.")
                break
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()