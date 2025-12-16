import json
import sys
from logger import BotLogger
import os
import time
import asyncio
import ccxt

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
from src.json_handler import load_config, load_api_keys, get_config_path

class TradingBot:
    def __init__(self, config_file=None):
        self.log = BotLogger()
        # 1. Load Configs using centralized handler
        try:
            self.config_path = get_config_path(config_file)
            self.config = load_config(config_file)
            if config_file:
                print(f"Using config: {os.path.basename(self.config_path)}")
        except FileNotFoundError as e:
            print(f"\nCRITICAL ERROR: Config file not found!")
            print(f"Looking for: {e}")
            sys.exit(1)
        
        # Handle API keys file with error messaging
        try:
            self.keys = load_api_keys()
        except FileNotFoundError:
            keys_path = os.path.join(PROJECT_ROOT, 'api-keys.json')
            keys_example_path = os.path.join(PROJECT_ROOT, 'api-keys.json.example')
            
            print(f"\nAPI KEYS FILE NOT FOUND!")
            print(f"Could not find: {keys_path}")
            
            if os.path.exists(keys_example_path):
                print(f"\nSETUP INSTRUCTIONS:")
                print(f"1. Copy the example file to create your API keys file:")
                print(f"   copy api-keys.json.example api-keys.json")
                print(f"2. Edit 'api-keys.json' and replace the placeholder values with your real API keys")
                print(f"\nThe example file exists at: {keys_example_path}")
            else:
                print(f"\nEven the example file is missing: {keys_example_path}")
                print(f"Please ensure you have the complete project files.")
            
            print(f"\nBot cannot run without API keys configuration. Exiting...")
            sys.exit(1)

        # 2. Initialize Exchange (The Connection)
        self.log.info("Connecting to Bybit...")
        
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
            self.log.info(f"Authenticated with API key: {api_key[:6]}...{api_key[-4:]}")
        else:
            self.log.warning("No valid API keys found - running in public data mode only")
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
        self.log.info(self.account.get_account_summary())
        
        # Check for existing open positions on startup
        resume_symbol, should_resume = self.tracker.check_and_resume_positions()
        if should_resume:
            self.active_coin = resume_symbol
    
    async def interruptible_sleep(self, seconds):
        """Sleeps for a given duration in 1s chunks to be more responsive to interrupts."""
        for _ in range(int(seconds)):
            await asyncio.sleep(1)

    async def start_cycle(self):
        """Starts the scanning and trading process (async for instant interrupt)."""
        # Skip scanning if we already have an active position
        if self.active_coin:
            self.log.info(f"Resuming monitoring: {self.active_coin}")
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
                self.log.warning("Flip detected during offline period - cleaning up now")
                self.handle_flip_cleanup(self.active_coin, long_pos, short_pos)
                return
            # Check if we should manually trigger flip (price already past trigger level)
            current_position = long_pos or short_pos
            if current_position:
                triggered = self.check_manual_flip_trigger(self.active_coin, current_position)
                if not triggered:
                    self.reconcile_orders(self.active_coin, current_position)
            # Monitoring will be handled by run_async via WebSocket
            return
        # Check if we have ANY open positions on the exchange (prevents multiple pairs)
        all_positions = self.bybit.fetch_open_positions()
        if all_positions is None:
            self.log.warning("Could not verify open positions due to exchange error. Skipping cycle start.")
            return
        if all_positions:
            self.log.warning(f"Found {len(all_positions)} open position(s) - cannot open new pair")
            for pos in all_positions:
                self.log.info(f"   {pos['symbol']}: {pos['side'].upper()} | {abs(float(pos.get('contracts', 0))):.1f} contracts")
            self.log.info("Waiting for existing positions to close...")
            return
        # 1. Find the best coin
        coin_info = self.scanner.get_best_volatile_coin()
        if not coin_info:
            self.log.info("No coin found.")
            return
        self.active_coin = coin_info['symbol']
        self.entry_direction = coin_info['direction']
        # Validate symbol format (remove any whitespace)
        self.active_coin = self.active_coin.strip().replace('\n', '').replace('\r', '')
        self.log.info(f"Starting cycle on {self.active_coin} - Entry Direction: {self.entry_direction}")
        # Check if we actually have an open position on the exchange
        positions = self.bybit.fetch_open_positions()
        has_position = False
        for pos in positions:
            if pos['symbol'] == self.active_coin and abs(float(pos.get('contracts', 0))) > 0:
                has_position = True
                break
        if has_position:
            self.log.info("Detected existing position on exchange. Resuming monitoring...")
        else:
            self.log.info("No existing position. Placing initial entry...")
            self.place_initial_entry(self.active_coin, self.entry_direction)

    def get_dynamic_range_and_price(self, symbol, flip_count=0):
        """
        Calculates dynamic range based on config and current spread.
        Returns (current_price, dynamic_range_pct)
        """
        base_range = self.calculator.calculate_range(flip_count)
        
        try:
            # Use fetch_ticker to get both price and spread in one call
            ticker = self.bybit.exchange.fetch_ticker(symbol)
            current_price = float(ticker.get('last', 0.0))
            
            # Calculate spread
            ask = float(ticker.get('ask', 0.0))
            bid = float(ticker.get('bid', 0.0))
            spread_pct = 0.0
            
            if ask > 0 and bid > 0:
                spread_pct = ((ask - bid) / ask) * 100
                
            # Add spread to base range
            dynamic_range = base_range + spread_pct
            
            return current_price, dynamic_range
            
        except Exception as e:
            # Fallback
            try:
                current_price = self.bybit.get_market_price(symbol)
            except:
                current_price = 0.0
            return current_price, base_range

    def place_initial_entry(self, symbol, direction):
        """Places the initial entry order for a new cycle."""
        try:
            # Calculate position size
            position_size_usd = self.account.calculate_position_size(flip_count=0)
            
            if position_size_usd <= 0:
                print(f"ERROR: Invalid position size ${position_size_usd:.2f}")
                self.active_coin = None
                return
            
            # Get current price and dynamic range
            current_price, range_pct = self.get_dynamic_range_and_price(symbol, flip_count=0)
            base_range = self.calculator.calculate_range(0)
            spread_pct = range_pct - base_range
            print(f"Dynamic Range: {range_pct:.4f}% (Base: {base_range:.4f}% + Spread: {spread_pct:.4f}%)")
            
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
            
            # Fetch actual fill price from position (market orders may have slippage)
            positions = self.bybit.fetch_open_positions()
            actual_entry_price = None
            if positions:
                for pos in positions:
                    if pos['symbol'] == symbol and pos['side'] == position_side:
                        actual_entry_price = float(pos.get('entryPrice', 0))
                        actual_contracts = abs(float(pos.get('contracts', 0)))
                        break
            
            # If we can't get actual entry, use estimated price
            if actual_entry_price is None or actual_entry_price == 0:
                print(f"   WARNING: Could not fetch actual entry price, using estimate")
                actual_entry_price = current_price
                actual_contracts = contracts
            else:
                # Show slippage if any
                slippage_pct = ((actual_entry_price - current_price) / current_price) * 100
                if abs(slippage_pct) > 0.01:
                    print(f"   Actual fill: ${actual_entry_price:.6f} (slippage: {slippage_pct:+.2f}%)")
            
            # Recalculate TP and Flip prices based on ACTUAL entry price
            if position_side == 'long':
                take_profit_price = actual_entry_price * (1 + range_pct / 100)
                flip_trigger_price = actual_entry_price * (1 - range_pct / 100)
            else:
                take_profit_price = actual_entry_price * (1 - range_pct / 100)
                flip_trigger_price = actual_entry_price * (1 + range_pct / 100)
            
            # Calculate next position size (Flip vs Stop Loss decision)
            next_flip_size_usd = self.calculator.calculate_next_position(0, actual_contracts * actual_entry_price, 0)
            
            # 2. Place TP order (reduces position at profit target)
            tp_side = 'sell' if position_side == 'long' else 'buy'
            print(f"\n2. Take Profit: LIMIT at ${take_profit_price:.6f} (based on actual entry)")
            tp_order = self.bybit.create_limit_order(
                symbol=symbol,
                side=tp_side,
                amount=actual_contracts,
                price=take_profit_price,
                position_side=position_side,
                params={'reduceOnly': True}
            )
            print(f"   {tp_order.get('id', 'N/A')}")
            
            # 3. Place flip order or Stop Loss based on calculator decision
            if next_flip_size_usd == 0:
                # Stop Loss Trigger Direction: 1 (Rise) for Short SL, 2 (Fall) for Long SL
                sl_trigger_direction = 2 if position_side == 'long' else 1
                
                print(f"\n3. Stop Loss: CONDITIONAL {flip_side.upper()} at ${flip_trigger_price:.6f}")
                flip_order = self.bybit.create_conditional_order(
                    symbol=symbol,
                    side=flip_side,
                    amount=actual_contracts,
                    trigger_price=flip_trigger_price,
                    position_side=position_side, # Close current position
                    order_type='Market',
                    params={'reduceOnly': True, 'triggerBy': 'LastPrice', 'triggerDirection': sl_trigger_direction}
                )
            else:
                flip_contracts = next_flip_size_usd / flip_trigger_price
                print(f"\n3. Flip Order: CONDITIONAL {flip_side.upper()} at ${flip_trigger_price:.6f} (based on actual entry)")
                flip_order = self.bybit.create_conditional_order(
                    symbol=symbol,
                    side=flip_side,
                    amount=flip_contracts,
                    trigger_price=flip_trigger_price,
                    position_side=flip_position_side,
                    order_type='Limit',
                    limit_price=flip_trigger_price
                )
                
            self.log.info(f"Order ID: {flip_order.get('id', 'N/A')}")
            self.log.info(f"All orders placed successfully")
            
            # Log initial flip count (0 flips)
            self.log.flip_count_status(symbol, 0, self.calculator.max_flips)
            
        except Exception as e:
            print(f"\n ERROR PLACING ORDER: {e}")
            print(f"{'='*50}\n")
            # Clear active coin on error so we can try again
            self.active_coin = None

    def reconcile_orders(self, symbol, current_position):
        """
        Ensures that the correct TP and Flip/StopLoss orders exist for a resumed position.
        Cancels existing orders and places new ones based on current state.
        """
        self.log.info(f"Reconciling orders for {symbol}...")
        
        # 1. Cancel existing orders to ensure clean state
        try:
            open_orders = self.bybit.fetch_open_orders(symbol)
            if open_orders:
                self.log.info(f"Cancelling {len(open_orders)} existing orders to replace them...")
                for order in open_orders:
                    self.bybit.cancel_order(order['id'], symbol)
        except Exception as e:
            self.log.error(f"Error cancelling orders during reconciliation: {e}")

        # 2. Get position details
        side = current_position['side']
        contracts = abs(float(current_position.get('contracts', 0)))
        entry_price = float(current_position.get('entryPrice', 0))
        
        # 3. Get state (flip count)
        state = self.tracker.analyze_position_state(symbol)
        flip_count = state.get('flip_count', 0)
        
        # 4. Calculate prices
        current_price, range_pct = self.get_dynamic_range_and_price(symbol, flip_count)
        
        if side == 'long':
            tp_price = entry_price * (1 + range_pct / 100)
            flip_trigger_price = entry_price * (1 - range_pct / 100)
            tp_side = 'sell'
            flip_side = 'sell'
            flip_position_side = 'short'
        else:
            tp_price = entry_price * (1 - range_pct / 100)
            flip_trigger_price = entry_price * (1 + range_pct / 100)
            tp_side = 'buy'
            flip_side = 'buy'
            flip_position_side = 'long'

        # 5. Calculate Next Position Size (to decide Flip vs SL)
        position_size_usd = contracts * entry_price
        next_flip_size_usd = self.calculator.calculate_next_position(flip_count, position_size_usd, 0)
        
        # 6. Place TP Order
        try:
            self.log.info(f"Placing reconciled TP at ${tp_price:.6f}")
            self.bybit.create_limit_order(symbol, tp_side, contracts, tp_price, side, params={'reduceOnly': True})
        except Exception as e:
            self.log.error(f"Failed to place reconciled TP: {e}")

        # 7. Place Flip or Stop Loss Order
        try:
            should_stop = False
            if next_flip_size_usd == 0:
                should_stop = True
                self.log.warning(f"Max flips ({self.calculator.max_flips}) reached! Placing Stop Loss.")
            elif not self.account.check_sufficient_balance(next_flip_size_usd):
                should_stop = True
                self.log.warning(f"Insufficient balance for next flip! Placing Stop Loss.")
            
            if should_stop:
                sl_trigger_direction = 2 if side == 'long' else 1
                self.bybit.create_conditional_order(symbol, flip_side, contracts, flip_trigger_price, side, 'Market', 
                    params={'reduceOnly': True, 'triggerBy': 'LastPrice', 'triggerDirection': sl_trigger_direction})
                self.log.info(f"Placed Stop Loss at ${flip_trigger_price:.6f}")
            else:
                flip_contracts = next_flip_size_usd / flip_trigger_price
                self.log.info(f"Placing reconciled Flip Order at ${flip_trigger_price:.6f}")
                self.bybit.create_conditional_order(symbol, flip_side, flip_contracts, flip_trigger_price, flip_position_side, 'Limit', flip_trigger_price)
        except Exception as e:
            self.log.error(f"Failed to place reconciled Flip/SL order: {e}")

    def check_manual_flip_trigger(self, symbol, current_position):
        """Check if flip should be manually triggered (price already past trigger level)."""
        triggered = False
        try:
            position_side = current_position['side']
            entry_price = float(current_position.get('entryPrice', 0))
            
            # Get current flip count
            state = self.tracker.analyze_position_state(symbol)
            flip_count = state.get('flip_count', 0)
            
            current_price, range_pct = self.get_dynamic_range_and_price(symbol, flip_count)
            position_contracts = abs(float(current_position.get('contracts', 0)))
            
            # Calculate flip trigger price
            
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
                next_flip_size_usd = self.calculator.calculate_next_position(flip_count, position_size_usd, 0)
                
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
                # Determine if we should stop (Max Flips OR Insufficient Balance)
                should_stop = False
                stop_reason = ""

                if next_flip_size_usd == 0:
                    should_stop = True
                    stop_reason = "Max flips reached"
                elif not self.account.check_sufficient_balance(next_flip_size_usd):
                    should_stop = True
                    stop_reason = "Insufficient balance"

                if should_stop:
                    print(f"   {stop_reason}. Executing STOP LOSS (Market Close).")
                    flip_order = self.bybit.create_market_order(
                        symbol=symbol,
                        side=flip_side,
                        amount=position_contracts,
                        position_side=position_side, # Close current position
                        params={'reduceOnly': True}
                    )
                    print(f"   Stop Loss executed: {flip_order.get('id', 'N/A')}")
                else:
                    flip_contracts = next_flip_size_usd / current_price
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
                # Trigger cleanup
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
                
                triggered = True
                    
        except Exception as e:
            print(f"Error checking manual flip trigger: {e}")
            import traceback
            traceback.print_exc()
        
        return triggered

    async def monitor_position_websocket(self, symbol):
        """Monitor position using WebSocket for instant updates."""
        print(f"WebSocket monitoring active for {symbol}")

        while True:
            # Refresh state in case polling changed it or we are reconnecting
            state = self.tracker.analyze_position_state(symbol)
            current_flip_count = state.get('flip_count', 0)
            
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
                        current_flip_count = self.handle_flip_cleanup(symbol, long_position, short_position)
                        # After cleanup, continue monitoring the new position
                        continue
                    
                    # No positions - cycle complete
                    if not long_position and not short_position:
                        print("Cycle complete - Position closed")
                        
                        # Calculate and log final PnL
                        try:
                            # Small delay to ensure fills are available via REST
                            await asyncio.sleep(1)
                            final_state = self.tracker.analyze_position_state(symbol, lookback_hours=24)
                            final_pnl = final_state.get('realized_pnl', 0.0)
                            self.log.info(f"Cycle Final PnL: ${final_pnl:.2f}")
                        except Exception as e:
                            print(f"Error calculating final PnL: {e}")
                        
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
                        return  # Exit function completely
                    
                    # One position - normal monitoring (silent unless flip or completion)
                    current_position = long_position or short_position
                    position_side = current_position['side']
                    position_contracts = abs(float(current_position.get('contracts', 0)))
                    entry_price = float(current_position.get('entryPrice', 0))
                    current_price, range_pct = self.get_dynamic_range_and_price(symbol, current_flip_count)
                    
                    # CRITICAL: Check if price has moved beyond flip trigger (safety against gaps/slippage)
                    
                    if position_side == 'long':
                        # Long position - flip trigger is BELOW entry (price falling)
                        flip_trigger = entry_price * (1 - range_pct / 100)
                        flip_triggered = current_price <= flip_trigger
                    else:
                        # Short position - flip trigger is ABOVE entry (price rising)
                        flip_trigger = entry_price * (1 + range_pct / 100)
                        flip_triggered = current_price >= flip_trigger
                    
                    if flip_triggered:
                        print(f" PRICE-BASED FLIP TRIGGER! Current: ${current_price:.6f}, Trigger: ${flip_trigger:.6f}")
                        print(f"   Position at risk - executing immediate flip to prevent liquidation")
                        
                        # Cancel existing conditional orders
                        try:
                            open_orders = self.bybit.fetch_open_orders(symbol)
                            for order in open_orders:
                                try:
                                    self.bybit.cancel_order(order['id'], symbol)
                                    print(f"   Cancelled: {order['id']}")
                                except Exception as e:
                                    print(f"   Cancel error: {e}")
                        except Exception as e:
                            print(f"   Error fetching orders: {e}")
                        
                        # Calculate flip details
                        position_size_usd = position_contracts * entry_price
                        next_flip_size_usd = self.calculator.calculate_next_position(current_flip_count, position_size_usd, 0)
                        
                        flip_side = 'sell' if position_side == 'long' else 'buy'
                        flip_position_side = 'short' if position_side == 'long' else 'long'
                        
                        # Determine if we should stop (Max Flips OR Insufficient Balance)
                        should_stop = False
                        stop_reason = ""

                        if next_flip_size_usd == 0:
                            should_stop = True
                            stop_reason = "Max flips reached"
                        elif not self.account.check_sufficient_balance(next_flip_size_usd):
                            should_stop = True
                            stop_reason = "Insufficient balance"

                        if should_stop:
                            print(f"   {stop_reason}. Executing STOP LOSS (Market Close).")
                            flip_order = self.bybit.create_market_order(
                                symbol=symbol,
                                side=flip_side,
                                amount=position_contracts,
                                position_side=position_side, # Close current position
                                params={'reduceOnly': True}
                            )
                            print(f"   Stop Loss executed: {flip_order.get('id', 'N/A')}")
                        else:
                            try:
                                flip_contracts = next_flip_size_usd / current_price
                                # Execute flip at market price
                                print(f"   Flip: {flip_side.upper()} {flip_contracts:.4f} contracts at market")
                                flip_order = self.bybit.create_market_order(
                                    symbol=symbol,
                                    side=flip_side,
                                    amount=flip_contracts,
                                    position_side=flip_position_side
                                )
                                print(f"   Flip executed: {flip_order.get('id', 'N/A')}")
                            except ccxt.InsufficientFunds:
                                print(f"   Insufficient Funds rejected by exchange. Executing STOP LOSS.")
                                flip_order = self.bybit.create_market_order(
                                    symbol=symbol,
                                    side=flip_side,
                                    amount=position_contracts,
                                    position_side=position_side, # Close current position
                                    params={'reduceOnly': True}
                                )
                                print(f"   Stop Loss executed: {flip_order.get('id', 'N/A')}")
                        
                        # Wait for fill then cleanup
                        await asyncio.sleep(2)
                        positions = self.bybit.fetch_open_positions()
                        long_pos = None
                        short_pos = None
                        
                        if positions:
                            for pos in positions:
                                if pos['symbol'] == symbol:
                                    if pos['side'] == 'long':
                                        long_pos = pos
                                    elif pos['side'] == 'short':
                                        short_pos = pos
                        
                        if long_pos and short_pos:
                            current_flip_count = self.handle_flip_cleanup(symbol, long_pos, short_pos)
                        else:
                            print("   WARNING: Expected both positions after flip")
                        
                        continue
                    
                    # No status printing - only flip and cycle completion events are logged
                        
            except Exception as e:
                print(f"WebSocket connection lost: {e}")
                print("Polling via REST API while attempting to reconnect...")
                
                # Run one polling iteration to ensure safety
                await self.manage_active_position_polling(symbol, run_once=True)
                
                # If active_coin is None, cycle finished during polling
                if not self.active_coin:
                    return

                # Small delay before reconnecting to avoid tight loop spam if network is down
                await asyncio.sleep(2)
    
    async def manage_active_position_polling(self, symbol, run_once=False):
        """Fallback polling method if WebSocket fails."""
        if not run_once:
            print(f" Polling mode for {symbol}")
        
        # Initialize flip count
        state = self.tracker.analyze_position_state(symbol)
        current_flip_count = state.get('flip_count', 0)
        
        while self.active_coin:
            try:
                # Get current positions
                positions = self.bybit.fetch_open_positions()
                if positions is None:
                    print(" Error fetching positions. Retrying...")
                    await self.interruptible_sleep(5)
                    continue
                
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
                    current_flip_count = self.handle_flip_cleanup(symbol, long_position, short_position)
                    continue
                
                if not long_position and not short_position:
                    print("Cycle complete - Position closed")
                    
                    # Calculate and log final PnL
                    try:
                        # Small delay to ensure fills are available via REST
                        await asyncio.sleep(1)
                        final_state = self.tracker.analyze_position_state(symbol, lookback_hours=24)
                        final_pnl = final_state.get('realized_pnl', 0.0)
                        self.log.info(f"Cycle Final PnL: ${final_pnl:.2f}")
                    except Exception as e:
                        print(f"Error calculating final PnL: {e}")
                    
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
                current_price, range_pct = self.get_dynamic_range_and_price(symbol, current_flip_count)
                
                # CRITICAL: Check if price has moved beyond flip trigger (safety against gaps/slippage)
                
                if position_side == 'long':
                    flip_trigger = entry_price * (1 - range_pct / 100)
                    flip_triggered = current_price <= flip_trigger
                else:
                    flip_trigger = entry_price * (1 + range_pct / 100)
                    flip_triggered = current_price >= flip_trigger
                
                if flip_triggered:
                    print(f" PRICE-BASED FLIP TRIGGER! Current: ${current_price:.6f}, Trigger: ${flip_trigger:.6f}")
                    print(f"   Position at risk - executing immediate flip to prevent liquidation")
                    
                    # Cancel existing orders
                    try:
                        open_orders = self.bybit.fetch_open_orders(symbol)
                        for order in open_orders:
                            try:
                                self.bybit.cancel_order(order['id'], symbol)
                                print(f"   Cancelled: {order['id']}")
                            except Exception as e:
                                print(f"   Cancel error: {e}")
                    except Exception as e:
                        print(f"   Error fetching orders: {e}")
                    
                    # Calculate flip details
                    position_size_usd = position_contracts * entry_price
                    next_flip_size_usd = self.calculator.calculate_next_position(current_flip_count, position_size_usd, 0)
                    
                    flip_side = 'sell' if position_side == 'long' else 'buy'
                    flip_position_side = 'short' if position_side == 'long' else 'long'
                    
                    # Determine if we should stop (Max Flips OR Insufficient Balance)
                    should_stop = False
                    stop_reason = ""

                    if next_flip_size_usd == 0:
                        should_stop = True
                        stop_reason = "Max flips reached"
                    elif not self.account.check_sufficient_balance(next_flip_size_usd):
                        should_stop = True
                        stop_reason = "Insufficient balance"

                    if should_stop:
                        print(f"   {stop_reason}. Executing STOP LOSS (Market Close).")
                        flip_order = self.bybit.create_market_order(
                            symbol=symbol,
                            side=flip_side,
                            amount=position_contracts,
                            position_side=position_side, # Close current position
                            params={'reduceOnly': True}
                        )
                        print(f"   Stop Loss executed: {flip_order.get('id', 'N/A')}")
                    else:
                        try:
                            flip_contracts = next_flip_size_usd / current_price
                            # Execute flip at market price
                            print(f"   Flip: {flip_side.upper()} {flip_contracts:.4f} contracts at market")
                            flip_order = self.bybit.create_market_order(
                                symbol=symbol,
                                side=flip_side,
                                amount=flip_contracts,
                                position_side=flip_position_side
                            )
                            print(f"   Flip executed: {flip_order.get('id', 'N/A')}")
                        except ccxt.InsufficientFunds:
                            print(f"   Insufficient Funds rejected by exchange. Executing STOP LOSS.")
                            flip_order = self.bybit.create_market_order(
                                symbol=symbol,
                                side=flip_side,
                                amount=position_contracts,
                                position_side=position_side, # Close current position
                                params={'reduceOnly': True}
                            )
                            print(f"   Stop Loss executed: {flip_order.get('id', 'N/A')}")
                    
                    # Wait for fill then cleanup
                    await asyncio.sleep(2)
                    positions = self.bybit.fetch_open_positions()
                    long_pos = None
                    short_pos = None
                    
                    if positions:
                        for pos in positions:
                            if pos['symbol'] == symbol:
                                if pos['side'] == 'long':
                                    long_pos = pos
                                elif pos['side'] == 'short':
                                    short_pos = pos
                    
                    if long_pos and short_pos:
                        current_flip_count = self.handle_flip_cleanup(symbol, long_pos, short_pos)
                    else:
                        print("   WARNING: Expected both positions after flip")
                    
                    continue
                
                # No status printing - only important events logged
                
                if run_once:
                    return
                
                await self.interruptible_sleep(10)  # Poll every 10 seconds
                
            except Exception as e:
                print(f"Error managing position: {e}")
                import traceback
                traceback.print_exc()
                if run_once:
                    return
                await self.interruptible_sleep(10)

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
            self.log.info(f"Order ID: {close_order.get('id', 'N/A')}")
            
            # Wait briefly for fill to be indexed
            time.sleep(1)
            
            # Get current flip count from position tracker
            position_state = self.tracker.analyze_position_state(symbol, lookback_hours=24)
            current_flip_count = position_state.get('flip_count', 0)
            current_pnl = position_state.get('realized_pnl', 0.0)
            max_flips = self.calculator.max_flips
            # Log flip count status 
            self.log.flip_count_status(symbol, current_flip_count, max_flips)
            self.log.info(f"Realized PnL (Current Cycle): ${current_pnl:.2f}")
            
            # Get dynamic range for the NEW flip count
            current_price, range_pct = self.get_dynamic_range_and_price(symbol, current_flip_count)
            
            # Calculate breakdown for logging
            base_range_expanded = self.calculator.calculate_range(current_flip_count)
            spread_pct = range_pct - base_range_expanded
            
            # Now place TP and new Flip orders for the new position
            new_side = new_position['side']
            new_contracts = abs(float(new_position.get('contracts', 0)))
            new_entry = float(new_position.get('entryPrice', 0))
            
            # Calculate TP and Flip prices for new position
            print(f"Dynamic Range: {range_pct:.4f}%")
            print(f"   Base: {base_range_expanded:.4f}% (Config: {self.config['strategy']['range_pct']}% * {self.calculator.range_pct_increase_per_flip}^{current_flip_count})")
            print(f"   Spread: {spread_pct:.4f}%")
            
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
            
            # Calculate next flip size using calculator
            next_flip_size_usd = self.calculator.calculate_next_position(current_flip_count, new_contracts * new_entry, 0)
            
            print(f"\nPlacing new TP + {'Stop Loss' if next_flip_size_usd == 0 else 'Flip'} for {new_side.upper()} position:")
            
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
            
            if next_flip_size_usd == 0:
                self.log.warning(f"Max flips ({max_flips}) reached! Placing Stop Loss instead of Flip.")
                
                # Stop Loss Trigger Direction: 1 (Rise) for Short SL, 2 (Fall) for Long SL
                sl_trigger_direction = 2 if new_side == 'long' else 1
                
                # Place Stop Loss (Close Position)
                sl_order = self.bybit.create_conditional_order(
                    symbol=symbol,
                    side=flip_side,
                    amount=new_contracts,
                    trigger_price=flip_trigger,
                    position_side=new_side,  # Close current position
                    order_type='Market',     # Ensure exit
                    params={'reduceOnly': True, 'triggerBy': 'LastPrice', 'triggerDirection': sl_trigger_direction}
                )
                print(f"  STOP LOSS at ${flip_trigger:.6f} (Close {new_contracts:.4f}): OK")
            else:
                flip_contracts = next_flip_size_usd / flip_trigger
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
            
            return current_flip_count
            
        except Exception as e:
            print(f" ERROR IN FLIP CLEANUP: {e}")
            import traceback
            traceback.print_exc()
            return 0

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
        try:
            while True:
                try:
                    # Start a new cycle (find coin and place entry)
                    await self.start_cycle()
                    # If we now have an active position, monitor it with WebSocket
                    if self.active_coin:
                        await self.monitor_position_websocket(self.active_coin)
                    else:
                        # No position - wait before next scan
                        print("\nWaiting 60 seconds before next scan...")
                        await self.interruptible_sleep(60)
                except KeyboardInterrupt:
                    print("\n\n=== Bot stopped by user ===")
                    break
                except Exception as e:
                    print(f"\nCRITICAL ERROR: {e}")
                    import traceback
                    traceback.print_exc()
                    print("Waiting 10 seconds before retry...")
                    await asyncio.sleep(10)
        finally:
            print("Closing exchange connection...")
            await self.bybit.close()
    
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