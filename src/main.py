import json
import sys
import os
import time
import asyncio

# Fix for Windows event loop (required for WebSocket on Windows)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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
    def __init__(self, config_file=None):
        # 1. Load Configs
        if config_file:
            # Use provided config file path
            if os.path.isabs(config_file):
                self.config_path = config_file
            else:
                self.config_path = os.path.join(PROJECT_ROOT, config_file)
            print(f"Using config: {os.path.basename(self.config_path)}")
        else:
            # Default to config.json
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
        api_key = bybit_keys.get('key', '')
        api_secret = bybit_keys.get('secret', '')
        
        # Only use keys if they're actually configured
        if api_key and api_secret and api_key != 'your_key_here':
            self.bybit = BybitClient(
                api_key=api_key,
                api_secret=api_secret,
                testnet=self.config['api'].get('testnet', False)
            )
            print(f"Authenticated with API key: {api_key[:6]}...{api_key[-4:]}")
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
        
        # Display account summary at startup
        print(self.account.get_account_summary())
        
        # Check for existing open positions on startup
        self._check_existing_positions()
    
    def _check_existing_positions(self):
        """
        Checks if there are any open positions on startup.
        If found, sets the active coin to resume trading.
        """
        print("\nChecking for existing open positions...")
        
        try:
            open_positions = self.bybit.fetch_open_positions()
            
            if not open_positions:
                print("No open positions found. Starting fresh.")
                return
            
            # Display all open positions
            print(f"Found {len(open_positions)} open position(s):")
            for pos in open_positions:
                symbol = pos.get('symbol')
                side = pos.get('side')  # 'long' or 'short'
                contracts = pos.get('contracts', 0)
                notional = pos.get('notional', 0)
                entry_price = pos.get('entryPrice', 0)
                unrealized_pnl = pos.get('unrealizedPnl', 0)
                
                print(f"  {symbol}: {side.upper()} | Size: {contracts} contracts (${notional:.2f}) | Entry: ${entry_price:.4f} | PnL: ${unrealized_pnl:.2f}")
                
                # Set the first open position as active coin
                if not self.active_coin:
                    self.active_coin = symbol
                    print(f"\nResuming trading on existing position: {symbol}")
                    
                    # Get detailed position state
                    position_state = self.tracker.analyze_position_state(symbol, lookback_hours=24)
                    print(self.tracker.get_position_summary(symbol, lookback_hours=24))
            
            if len(open_positions) > 1:
                print(f"\nWARNING: Multiple open positions detected. Bot will focus on: {self.active_coin}")
                print("Consider closing other positions manually or updating bot logic to handle multiple positions.")
        
        except Exception as e:
            print(f"Error checking positions: {e}")
            print("Continuing with fresh start...")

    def start_cycle(self):
        """Starts the scanning and trading process."""
        
        # Skip scanning if we already have an active position
        if self.active_coin:
            print(f"\nResuming monitoring: {self.active_coin}")
            
            # Check if flip already triggered while bot was offline
            positions = self.bybit.fetch_open_positions()
            long_pos = None
            short_pos = None
            
            for pos in positions:
                if pos['symbol'] == self.active_coin:
                    if pos['side'] == 'long':
                        long_pos = pos
                    elif pos['side'] == 'short':
                        short_pos = pos
            
            # If both positions exist, flip happened while offline
            if long_pos and short_pos:
                print("WARNING: Flip detected during offline period - cleaning up now")
                self.handle_flip_cleanup(self.active_coin, long_pos, short_pos)
                return
            
            # Check if we should manually trigger flip (price already past trigger level)
            current_position = long_pos or short_pos
            if current_position:
                self.check_manual_flip_trigger(self.active_coin, current_position)
            
            # Monitoring will be handled by run_async via WebSocket
            return
        
        # Check if we have ANY open positions on the exchange (prevents multiple pairs)
        all_positions = self.bybit.fetch_open_positions()
        if all_positions:
            print(f"\nWARNING: Found {len(all_positions)} open position(s) - cannot open new pair")
            for pos in all_positions:
                print(f"   {pos['symbol']}: {pos['side'].upper()} | {abs(float(pos.get('contracts', 0))):.1f} contracts")
            print("Waiting for existing positions to close...")
            time.sleep(60)
            return
        
        # 1. Find the best coin
        coin_info = self.scanner.get_best_volatile_coin()
        
        if not coin_info:
            print("No coin found. Waiting 60 seconds.")
            time.sleep(60)
            return

        self.active_coin = coin_info['symbol']
        self.entry_direction = coin_info['direction']
        
        # Validate symbol format (remove any whitespace)
        self.active_coin = self.active_coin.strip().replace('\n', '').replace('\r', '')
        
        print(f"\nStarting cycle on {self.active_coin} - Entry Direction: {self.entry_direction}")
        
        # Check if we actually have an open position on the exchange
        positions = self.bybit.fetch_open_positions()
        has_position = False
        for pos in positions:
            if pos['symbol'] == self.active_coin and abs(float(pos.get('contracts', 0))) > 0:
                has_position = True
                break
        
        if has_position:
            print("Detected existing position on exchange. Resuming monitoring...")
        else:
            print("No existing position. Placing initial entry...")
            self.place_initial_entry(self.active_coin, self.entry_direction)

    def place_initial_entry(self, symbol, direction):
        """Places the initial entry order for a new cycle."""
        try:
            # Calculate position size
            position_size_usd = self.account.calculate_position_size(flip_count=0)
            
            if position_size_usd <= 0:
                print(f"ERROR: Invalid position size ${position_size_usd:.2f}")
                self.active_coin = None
                return
            
            # Get current price
            current_price = self.bybit.get_market_price(symbol)
            
            # Calculate contracts (quantity)
            # For USDT perpetuals: contracts = USD value / price
            contracts = position_size_usd / current_price
            
            # Set leverage
            leverage = self.config['strategy']['leverage']
            self.bybit.set_leverage(symbol, leverage)
            
            # Determine order side (buy for LONG, sell for SHORT)
            side = 'buy' if direction == 'LONG' else 'sell'
            position_side = 'long' if direction == 'LONG' else 'short'
            
            # Calculate TP and Flip trigger prices
            range_pct = self.config['strategy']['range_pct']
            multiplier = self.config['strategy']['martingale_multiplier']
            
            if position_side == 'long':
                take_profit_price = current_price * (1 + range_pct / 100)
                flip_trigger_price = current_price * (1 - range_pct / 100)
                flip_side = 'sell'  # Opens SHORT when triggered
                flip_position_side = 'short'
            else:
                take_profit_price = current_price * (1 - range_pct / 100)
                flip_trigger_price = current_price * (1 + range_pct / 100)
                flip_side = 'buy'  # Opens LONG when triggered
                flip_position_side = 'long'
            
            # Calculate flip order size (martingale)
            flip_size_usd = position_size_usd * multiplier
            flip_contracts = flip_size_usd / flip_trigger_price
            
            print(f"\n{'='*50}")
            print(f"PLACING ENTRY + TP + FLIP ORDERS")
            print(f"{'='*50}")
            print(f"Symbol: {symbol}")
            print(f"Direction: {direction} ({side.upper()})")
            print(f"Entry Size: ${position_size_usd:.2f} ({contracts:.4f} contracts)")
            print(f"Entry Price: ${current_price:.6f}")
            print(f"TP: ${take_profit_price:.6f} (+{range_pct}%)")
            print(f"Flip Trigger: ${flip_trigger_price:.6f} (-{range_pct}%)")
            print(f"Flip Size: ${flip_size_usd:.2f} ({flip_contracts:.4f} contracts, {multiplier}x)")
            print(f"Leverage: {leverage}x")
            
            # 1. Place entry order
            use_market_order = self.config['strategy'].get('market_orders_cycle_start', True)
            
            if use_market_order:
                print(f"\n1. Entry: MARKET")
                entry_order = self.bybit.create_market_order(
                    symbol=symbol,
                    side=side,
                    amount=contracts,
                    position_side=position_side
                )
            else:
                print(f"\n1. Entry: LIMIT at ${current_price:.6f}")
                entry_order = self.bybit.create_limit_order(
                    symbol=symbol,
                    side=side,
                    amount=contracts,
                    price=current_price,
                    position_side=position_side
                )
            print(f"   {entry_order.get('id', 'N/A')}")
            
            # Wait for entry to fill
            time.sleep(2)
            
            # 2. Place TP order (reduces position at profit target)
            tp_side = 'sell' if position_side == 'long' else 'buy'
            print(f"\n2. Take Profit: LIMIT at ${take_profit_price:.6f}")
            tp_order = self.bybit.create_limit_order(
                symbol=symbol,
                side=tp_side,
                amount=contracts,
                price=take_profit_price,
                position_side=position_side,
                params={'reduceOnly': True}
            )
            print(f"   {tp_order.get('id', 'N/A')}")
            
            # 3. Place flip order (conditional order - only triggers when price hits level)
            print(f"\n3. Flip Order: CONDITIONAL {flip_side.upper()} at ${flip_trigger_price:.6f}")
            flip_order = self.bybit.create_conditional_order(
                symbol=symbol,
                side=flip_side,
                amount=flip_contracts,
                trigger_price=flip_trigger_price,
                position_side=flip_position_side,
                order_type='Limit',
                limit_price=flip_trigger_price
            )
            print(f"   {flip_order.get('id', 'N/A')}")
            
            print(f"\n ALL ORDERS PLACED SUCCESSFULLY")
            print(f"{'='*50}\n")
            
        except Exception as e:
            print(f"\n ERROR PLACING ORDER: {e}")
            print(f"{'='*50}\n")
            # Clear active coin on error so we can try again
            self.active_coin = None

    def check_manual_flip_trigger(self, symbol, current_position):
        """Check if flip should be manually triggered (price already past trigger level)."""
        try:
            position_side = current_position['side']
            entry_price = float(current_position.get('entryPrice', 0))
            current_price = self.bybit.get_market_price(symbol)
            position_contracts = abs(float(current_position.get('contracts', 0)))
            
            # Calculate flip trigger price
            range_pct = self.config['strategy']['range_pct']
            
            if position_side == 'long':
                flip_trigger = entry_price * (1 - range_pct / 100)
                flip_triggered = current_price <= flip_trigger
            else:
                flip_trigger = entry_price * (1 + range_pct / 100)
                flip_triggered = current_price >= flip_trigger
            
            if flip_triggered:
                print(f"MANUAL FLIP TRIGGER DETECTED!")
                print(f"   Entry: ${entry_price:.6f}")
                print(f"   Current: ${current_price:.6f}")
                print(f"   Flip Trigger: ${flip_trigger:.6f}")
                print(f"   Position: {position_side.upper()} {position_contracts:.4f} contracts")
                print(f"\nExecuting flip manually...")
                
                # Cancel any existing orders
                open_orders = self.bybit.fetch_open_orders(symbol)
                for order in open_orders:
                    try:
                        self.bybit.cancel_order(order['id'], symbol)
                        print(f"   Cancelled order: {order['id']}")
                    except Exception as e:
                        print(f"   Error cancelling {order['id']}: {e}")
                
                # Calculate flip order details
                multiplier = self.config['strategy']['martingale_multiplier']
                position_size_usd = position_contracts * entry_price
                flip_size_usd = position_size_usd * multiplier
                flip_contracts = flip_size_usd / current_price
                
                # Determine flip side
                flip_side = 'sell' if position_side == 'long' else 'buy'
                flip_position_side = 'short' if position_side == 'long' else 'long'
                
                # Place flip order at market
                print(f"\n   Placing flip order: {flip_side.upper()} {flip_contracts:.4f} contracts")
                flip_order = self.bybit.create_market_order(
                    symbol=symbol,
                    side=flip_side,
                    amount=flip_contracts,
                    position_side=flip_position_side
                )
                print(f"   Flip order placed: {flip_order.get('id', 'N/A')}")
                
                # Wait a moment for order to fill
                time.sleep(2)
                
                # Now both positions should exist - trigger cleanup
                positions = self.bybit.fetch_open_positions()
                long_pos = None
                short_pos = None
                
                for pos in positions:
                    if pos['symbol'] == symbol:
                        if pos['side'] == 'long':
                            long_pos = pos
                        elif pos['side'] == 'short':
                            short_pos = pos
                
                if long_pos and short_pos:
                    self.handle_flip_cleanup(symbol, long_pos, short_pos)
                else:
                    print("   WARNING: Expected both positions after flip, cleanup may be needed")
                    
        except Exception as e:
            print(f"Error checking manual flip trigger: {e}")
            import traceback
            traceback.print_exc()

    async def monitor_position_websocket(self, symbol):
        """Monitor position using WebSocket for instant updates."""
        print(f"WebSocket monitoring active for {symbol}")
        
        try:
            last_status_print = 0  # Initialize to 0 to ensure first check happens after 60s
            
            async for positions in self.bybit.watch_positions(symbol):
                # Parse positions for this symbol
                long_position = None
                short_position = None
                
                for pos in positions:
                    if pos['symbol'] == symbol:
                        if pos['side'] == 'long' and abs(float(pos.get('contracts', 0))) > 0:
                            long_position = pos
                        elif pos['side'] == 'short' and abs(float(pos.get('contracts', 0))) > 0:
                            short_position = pos
                
                # INSTANT flip detection - both positions exist
                if long_position and short_position:
                    print(" FLIP DETECTED (WebSocket) - Both positions open!")
                    self.handle_flip_cleanup(symbol, long_position, short_position)
                    # After cleanup, continue monitoring the new position
                    continue
                
                # No positions - cycle complete
                if not long_position and not short_position:
                    print("Cycle complete - Position closed")
                    
                    # Cancel any remaining orders before clearing active coin
                    try:
                        open_orders = self.bybit.fetch_open_orders(symbol)
                        if open_orders:
                            print(f"Cleaning up {len(open_orders)} remaining order(s)...")
                            for order in open_orders:
                                try:
                                    self.bybit.cancel_order(order['id'], symbol)
                                    print(f"  Cancelled: {order['id']}")
                                except Exception as e:
                                    print(f"  Error cancelling {order['id']}: {e}")
                    except Exception as e:
                        print(f"Error cleaning up orders: {e}")
                    
                    self.active_coin = None
                    break
                
                # One position - normal monitoring (silent unless flip or completion)
                current_position = long_position or short_position
                position_side = current_position['side']
                position_contracts = abs(float(current_position.get('contracts', 0)))
                entry_price = float(current_position.get('entryPrice', 0))
                current_price = self.bybit.get_market_price(symbol)
                
                # No status printing - only flip and cycle completion events are logged
                    
        except Exception as e:
            print(f"WebSocket monitoring error: {e}")
            import traceback
            traceback.print_exc()
            # Fall back to polling if WebSocket fails
            print(" Falling back to REST API polling...")
            self.manage_active_position_polling(symbol)
    
    def manage_active_position_polling(self, symbol):
        """Fallback polling method if WebSocket fails."""
        print(f" Polling mode for {symbol}")
        
        while self.active_coin:
            try:
                # Get current positions
                positions = self.bybit.fetch_open_positions()
                long_position = None
                short_position = None
                
                for pos in positions:
                    if pos['symbol'] == symbol:
                        if pos['side'] == 'long' and abs(float(pos.get('contracts', 0))) > 0:
                            long_position = pos
                        elif pos['side'] == 'short' and abs(float(pos.get('contracts', 0))) > 0:
                            short_position = pos
                
                # Determine current state
                if long_position and short_position:
                    print("WARNING: Both long and short positions detected - flip occurred!")
                    self.handle_flip_cleanup(symbol, long_position, short_position)
                    continue
                
                if not long_position and not short_position:
                    print("Cycle complete - Position closed")
                    
                    # Cancel any remaining orders
                    try:
                        open_orders = self.bybit.fetch_open_orders(symbol)
                        if open_orders:
                            print(f"Cleaning up {len(open_orders)} remaining order(s)...")
                            for order in open_orders:
                                try:
                                    self.bybit.cancel_order(order['id'], symbol)
                                    print(f"  Cancelled: {order['id']}")
                                except Exception as e:
                                    print(f"  Error cancelling {order['id']}: {e}")
                    except Exception as e:
                        print(f"Error cleaning up orders: {e}")
                    
                    self.active_coin = None
                    break
                
                # We have one active position - silent monitoring
                current_position = long_position or short_position
                position_side = current_position['side']
                position_contracts = abs(float(current_position.get('contracts', 0)))
                entry_price = float(current_position.get('entryPrice', 0))
                current_price = self.bybit.get_market_price(symbol)
                
                # No status printing - only important events logged
                
                time.sleep(10)  # Poll every 10 seconds
                
            except Exception as e:
                print(f"Error managing position: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(10)

    def handle_flip_cleanup(self, symbol, long_position, short_position):
        """Handles cleanup when both long and short positions exist (flip just occurred)."""
        try:
            # Determine which is the old position (smaller one) and which is new
            long_contracts = abs(float(long_position.get('contracts', 0)))
            short_contracts = abs(float(short_position.get('contracts', 0)))
            
            # The newer position should be larger (due to martingale)
            if long_contracts > short_contracts:
                # Long is new, short is old
                old_position = short_position
                new_position = long_position
                close_side = 'buy'
            else:
                # Short is new, long is old
                old_position = long_position
                new_position = short_position
                close_side = 'sell'
            
            old_side = old_position['side']
            old_contracts = abs(float(old_position.get('contracts', 0)))
            current_price = self.bybit.get_market_price(symbol)
            
            print(f"\n{'='*50}")
            print(f"FLIP CLEANUP - Closing old {old_side.upper()} position")
            print(f"{'='*50}")
            
            # Cancel all open orders first
            print("Cancelling all open orders...")
            open_orders = self.bybit.fetch_open_orders(symbol)
            for order in open_orders:
                try:
                    self.bybit.cancel_order(order['id'], symbol)
                    print(f"  Cancelled order: {order['id']}")
                except Exception as e:
                    print(f"  Error cancelling {order['id']}: {e}")
            
            # Close the old position
            print(f"Closing old position: {close_side.upper()} {old_contracts:.4f} contracts")
            close_order = self.bybit.create_market_order(
                symbol=symbol,
                side=close_side,
                amount=old_contracts,
                position_side=old_side
            )
            print(f" Old position closed")
            
            # Now place TP and new Flip orders for the new position
            new_side = new_position['side']
            new_contracts = abs(float(new_position.get('contracts', 0)))
            new_entry = float(new_position.get('entryPrice', 0))
            
            # Calculate TP and Flip prices for new position
            range_pct = self.config['strategy']['range_pct']
            multiplier = self.config['strategy']['martingale_multiplier']
            
            if new_side == 'long':
                tp_price = new_entry * (1 + range_pct / 100)
                flip_trigger = new_entry * (1 - range_pct / 100)
                tp_side = 'sell'
                flip_side = 'sell'
                flip_position_side = 'short'
            else:
                tp_price = new_entry * (1 - range_pct / 100)
                flip_trigger = new_entry * (1 + range_pct / 100)
                tp_side = 'buy'
                flip_side = 'buy'
                flip_position_side = 'long'
            
            # Calculate next flip size
            flip_size_usd = (new_contracts * new_entry) * multiplier
            flip_contracts = flip_size_usd / flip_trigger
            
            print(f"\nPlacing new TP + Flip for {new_side.upper()} position:")
            
            # Place TP order
            tp_order = self.bybit.create_limit_order(
                symbol=symbol,
                side=tp_side,
                amount=new_contracts,
                price=tp_price,
                position_side=new_side,
                params={'reduceOnly': True}
            )
            print(f"  TP at ${tp_price:.6f}: ")
            
            # Place Flip order (conditional - only triggers at price level)
            flip_order = self.bybit.create_conditional_order(
                symbol=symbol,
                side=flip_side,
                amount=flip_contracts,
                trigger_price=flip_trigger,
                position_side=flip_position_side,
                order_type='Limit',
                limit_price=flip_trigger
            )
            print(f"  Flip at ${flip_trigger:.6f} ({flip_contracts:.4f} contracts): OK")
            
            print(f"{'='*50}\n")
            
        except Exception as e:
            print(f" ERROR IN FLIP CLEANUP: {e}")
            import traceback
            traceback.print_exc()

    def exit_position(self, symbol, current_position, reason):
        """Exits the current position and ends the cycle."""
        try:
            current_side = current_position['side']
            current_contracts = abs(float(current_position.get('contracts', 0)))
            current_price = self.bybit.get_market_price(symbol)
            
            # Determine closing side
            close_side = 'sell' if current_side == 'long' else 'buy'
            
            print(f"\n{'='*50}")
            print(f"EXITING POSITION")
            print(f"{'='*50}")
            print(f"Reason: {reason}")
            print(f"Closing: {current_side.upper()} {current_contracts:.4f} contracts")
            print(f"Order: {close_side.upper()} {current_contracts:.4f} contracts at ${current_price:.6f}")
            
            # Place exit order
            order = self.bybit.create_market_order(
                symbol=symbol,
                side=close_side,
                amount=current_contracts,
                position_side=current_side
            )
            
            print(f"\n EXIT ORDER PLACED")
            print(f"Order ID: {order.get('id', 'N/A')}")
            print(f"Cycle ended for {symbol}")
            print(f"{'='*50}\n")
            
            # Clear active coin to start fresh
            self.active_coin = None
            
        except Exception as e:
            print(f"\n❌ ERROR EXITING POSITION: {e}")
            print(f"{'='*50}\n")

    async def run_async(self):
        """Main async run loop with WebSocket support."""
        print("\n=== Trading Bot Started ===")
        print(" WebSocket mode enabled for instant updates")
        print("Press Ctrl+C to stop\n")
        
        while True:
            try:
                # Start a new cycle (find coin and place entry)
                self.start_cycle()
                
                # If we now have an active position, monitor it with WebSocket
                if self.active_coin:
                    await self.monitor_position_websocket(self.active_coin)
                else:
                    # No position - wait before next scan
                    print("\nWaiting 60 seconds before next scan...")
                    await asyncio.sleep(60)
                    
            except KeyboardInterrupt:
                print("\n\n=== Bot stopped by user ===")
                break
            except Exception as e:
                print(f"\nCRITICAL ERROR: {e}")
                import traceback
                traceback.print_exc()
                print("Waiting 10 seconds before retry...")
                await asyncio.sleep(10)
    
    def run(self):
        """Wrapper to run async event loop."""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            print("\n\n=== Bot stopped ===")

if __name__ == "__main__":
    # Check for command-line argument for config file
    config_file = None
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    
    bot = TradingBot(config_file)
    bot.run()