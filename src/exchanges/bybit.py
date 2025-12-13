import ccxt
import ccxt.pro as ccxtpro
import asyncio
import time
from ccxt.base.errors import NetworkError, ExchangeError

class BybitClient:
    def __init__(self, api_key=None, api_secret=None, testnet=False):
        """
        Initializes the connection with Bybit via CCXT.
        API keys are optional - only needed for trading operations.
        
        Note: Market data is ALWAYS fetched from mainnet for accuracy.
        Testnet only affects trading operations when API keys are provided.
        """
        config = {
            'enableRateLimit': True, 
            'options': {
                'defaultType': 'swap',  # Force Derivatives/Perpetuals
                'adjustForTimeDifference': True,
                'recvWindow': 10000  # Increased to prevent timestamp errors
            }
        }
        
        # Only add credentials if provided
        if api_key and api_secret:
            config['apiKey'] = api_key
            config['secret'] = api_secret
            print("Authenticated mode enabled")
            
            # Only use testnet if we have API keys (for trading)
            if testnet:
                self.testnet_mode = True
                print("WARNING: Testnet mode enabled for TRADING operations")
            else:
                self.testnet_mode = False
        else:
            print("Public data mode (no authentication)")
            self.testnet_mode = False  # Always use mainnet for public data
        
        # Regular CCXT for REST API (trading)
        self.exchange = ccxt.bybit(config)
        
        # CCXT Pro for WebSocket (monitoring)
        self.exchange_ws = ccxtpro.bybit(config)
        
        # Set sandbox mode ONLY if authenticated AND testnet requested
        if api_key and api_secret and testnet:
            self.exchange.set_sandbox_mode(True)
            print("Testnet sandbox mode activated for trading")
        
        # Set position mode to Hedge Mode if authenticated
        if api_key and api_secret:
            try:
                # Set position mode to Hedge Mode (allows separate long/short positions)
                self.exchange.set_position_mode(True)  # True = Hedge Mode
                print("Position mode set to Hedge Mode")
            except Exception as e:
                print(f"Note: Position mode setting: {e}")

    def get_market_price(self, symbol):
        """Returns the current price of a symbol."""
        ticker = self.exchange.fetch_ticker(symbol)
        return float(ticker['last'])
    
    def fetch_open_positions(self):
        """
        Fetches all open positions from the exchange.
        
        :return: List of open position dictionaries
        """
        try:
            positions = self.exchange.fetch_positions()
            # Filter to only positions with actual size
            open_positions = [p for p in positions if float(p.get('contracts', 0)) != 0]
            return open_positions
        except Exception as e:
            print(f"Error fetching open positions: {e}")
            return None
    
    async def watch_positions(self, symbol=None):
        """
        Watch positions in real-time using WebSocket (CCXT Pro).
        Uses watch_ticker for real-time price updates and checks positions.
        
        :param symbol: Symbol to monitor (e.g., 'BTC/USDT:USDT')
        :return: Generator yielding position updates
        """
        try:
            last_position_check = 0
            
            while True:
                # Watch ticker for real-time price updates using CCXT Pro
                ticker = await self.exchange_ws.watch_ticker(symbol)
                
                # Check positions every 1.5 seconds for faster flip detection
                current_time = time.time()
                if current_time - last_position_check >= 1.5:
                    positions = self.fetch_open_positions()
                    
                    if positions is None:
                        continue
                    
                    # Filter to symbol
                    if symbol:
                        positions = [p for p in positions if p['symbol'] == symbol]
                    
                    yield positions
                    last_position_check = current_time
                    
        except Exception as e:
            print(f"WebSocket error in watch_positions: {e}")
            raise

    def set_leverage(self, symbol, leverage):
        """Sets the leverage for a specific symbol."""
        try:
            self.exchange.set_leverage(leverage, symbol)
            print(f"Leverage set to {leverage}x for {symbol}")
        except Exception as e:
            pass # Ignore if leverage is already set

    def create_market_order(self, symbol, side, amount, position_side='long', take_profit=None, stop_loss=None, params={}):
        """
        Places a market order with optional TP/SL.
        Uses Hedge Mode: positionIdx=1 for long, positionIdx=2 for short
        
        :param take_profit: Take profit price (optional)
        :param stop_loss: Stop loss price (optional)
        """
        # Bybit Hedge Mode requires positionIdx parameter
        # 1 = Long position, 2 = Short position
        default_params = {'positionIdx': 1 if position_side == 'long' else 2}
        
        # Add TP/SL if provided
        if take_profit:
            default_params['takeProfit'] = take_profit
        if stop_loss:
            default_params['stopLoss'] = stop_loss
        
        default_params.update(params)
        return self.exchange.create_order(symbol, 'market', side, amount, params=default_params)
    
    def create_limit_order(self, symbol, side, amount, price, position_side='long', take_profit=None, stop_loss=None, params={}):
        """
        Places a limit order at a specific price with optional TP/SL.
        Uses Hedge Mode: positionIdx=1 for long, positionIdx=2 for short
        
        :param take_profit: Take profit price (optional)
        :param stop_loss: Stop loss price (optional)
        """
        # Bybit Hedge Mode requires positionIdx parameter
        default_params = {'positionIdx': 1 if position_side == 'long' else 2}
        
        # Add TP/SL if provided
        if take_profit:
            default_params['takeProfit'] = take_profit
        if stop_loss:
            default_params['stopLoss'] = stop_loss
        
        default_params.update(params)
        return self.exchange.create_order(symbol, 'limit', side, amount, price, params=default_params)
    
    def create_conditional_order(self, symbol, side, amount, trigger_price, position_side='long', order_type='Limit', limit_price=None, params={}):
        """
        Places a conditional (trigger) order that only executes when price hits trigger_price.
        This is used for flip orders - opens opposite position when triggered.
        
        :param trigger_price: Price that triggers the order
        :param position_side: The position this order will OPEN ('long' or 'short')
        :param order_type: 'Market' or 'Limit' (capitalized for Bybit)
        :param limit_price: If order_type='Limit', the execution price after trigger
        """
        # For Bybit conditional orders, we need:
        # - triggerPrice: When to activate the order
        # - triggerDirection: 1=rise above, 2=fall below
        # - orderType: Market or Limit
        # - price: Execution price (for Limit orders)
        
        # Determine trigger direction based on the POSITION being opened:
        # - Opening LONG position (flip from short): price must RISE to trigger → triggerDirection=1
        # - Opening SHORT position (flip from long): price must FALL to trigger → triggerDirection=2
        if position_side == 'long':
            trigger_direction = 1  # Opening LONG: trigger when price rises above trigger_price
        else:
            trigger_direction = 2  # Opening SHORT: trigger when price falls below trigger_price
        
        # Execution price for limit orders
        exec_price = limit_price if limit_price else trigger_price
        
        default_params = {
            'positionIdx': 1 if position_side == 'long' else 2,
            'triggerPrice': str(trigger_price),
            'triggerDirection': trigger_direction,
            'orderType': order_type,
            'triggerBy': 'LastPrice',
        }
        
        default_params.update(params)
        
        # Use CCXT's create_order with conditional parameters
        # For Bybit, conditional orders use regular create_order with trigger params
        return self.exchange.create_order(
            symbol, 
            order_type.lower(),  # 'limit' or 'market'
            side, 
            amount, 
            exec_price if order_type == 'Limit' else None,
            params=default_params
        )
    
    def cancel_order(self, order_id, symbol):
        """Cancels an open order."""
        return self.exchange.cancel_order(order_id, symbol)
    
    def fetch_open_orders(self, symbol=None):
        """Fetches all open orders, optionally filtered by symbol."""
        return self.exchange.fetch_open_orders(symbol)

    # Scanner methods

    def fetch_tickers(self):
        """Fetches 24h ticker data for all symbols."""
        return self.exchange.fetch_tickers()
    
    def fetch_markets(self):
        """
        Fetches market information including innovation zone markers.
        Returns detailed market info for all trading pairs.
        """
        return self.exchange.fetch_markets()

    def fetch_candles(self, symbol, timeframe, limit):
        """
        Fetches OHLCV data.
        :param timeframe: e.g., '15m', '1h'
        :param limit: number of candles
        """
        return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    
    def fetch_trading_fees(self, symbol=None):
        """
        Fetches trading fees from the exchange.
        
        :param symbol: Optional specific symbol to get fees for
        :return: Dictionary with maker and taker fee rates
        """
        try:
            if symbol:
                # Fetch fees for specific symbol
                fees = self.exchange.fetch_trading_fee(symbol)
                return {
                    'maker': fees.get('maker', 0.0001),
                    'taker': fees.get('taker', 0.0006)
                }
            else:
                # Fetch general trading fees
                fees = self.exchange.fetch_trading_fees()
                # Bybit usually returns a dict with symbol keys or a 'trading' key
                if 'trading' in fees:
                    return {
                        'maker': fees['trading'].get('maker', 0.0001),
                        'taker': fees['trading'].get('taker', 0.0006)
                    }
                # Return default structure
                return {
                    'maker': 0.0001,  # 0.01%
                    'taker': 0.0006   # 0.06%
                }
        except Exception as e:
            print(f"Error fetching trading fees: {e}")
            print("Using default fees: maker=0.01%, taker=0.06%")
            return {
                'maker': 0.0001,
                'taker': 0.0006
            }

    def fetch_all_fills(self, symbol, start_time_ms):
        """
        Fetches all trade fills for a symbol from start_time_ms to now.
        Implements backward-fetching logic to handle pagination.
        
        :param symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT')
        :param start_time_ms: Start time in milliseconds
        :return: List of all fills sorted by timestamp
        """
        all_trades = []
        end_time = int(time.time() * 1000)  # Start fetching from NOW
        limit = 200  # Bybit max limit per request
        
        print(f"Fetching trade history for {symbol}...")

        while True:
            try:
                # Fetch a page of trades
                params = {'endTime': end_time}
                trades = self.exchange.fetch_my_trades(symbol, limit=limit, params=params)
                
                if not trades:
                    break

                # Sort to ensure we handle time correctly
                trades.sort(key=lambda x: x['timestamp'])
                
                # Add to our master list
                all_trades.extend(trades)
                
                first_trade_time = trades[0]['timestamp']

                # BREAK CONDITIONS
                # 1. We went back further than our start_time
                if first_trade_time < start_time_ms:
                    break
                
                # 2. We received fewer trades than the limit, meaning we reached the end of history
                if len(trades) < limit:
                    break
                
                # UPDATE POINTER: Set end_time to just before the oldest trade we found
                # This prevents duplicates and moves the window back
                end_time = first_trade_time - 1
                
                # Rate limit safety
                time.sleep(0.1)

            except Exception as e:
                print(f"Error fetching trade history: {e}")
                break
        
        # Filter exact start time and dedup
        unique_trades = {t['id']: t for t in all_trades if t['timestamp'] >= start_time_ms}
        final_trades = sorted(unique_trades.values(), key=lambda x: x['timestamp'])
        
        print(f"Retrieved {len(final_trades)} fills for {symbol}")
        return final_trades

    async def close(self):
        """Closes the WebSocket connection."""
        await self.exchange_ws.close()