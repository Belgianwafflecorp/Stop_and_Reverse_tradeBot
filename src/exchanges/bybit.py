import ccxt
import asyncio
import time

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
                'adjustForTimeDifference': True
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
        
        self.exchange = ccxt.bybit(config)
        
        # Set sandbox mode ONLY if authenticated AND testnet requested
        if api_key and api_secret and testnet:
            self.exchange.set_sandbox_mode(True)
            print("Testnet sandbox mode activated for trading")

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
            return []

    def set_leverage(self, symbol, leverage):
        """Sets the leverage for a specific symbol."""
        try:
            self.exchange.set_leverage(leverage, symbol)
            print(f"Leverage set to {leverage}x for {symbol}")
        except Exception as e:
            pass # Ignore if leverage is already set

    def create_market_order(self, symbol, side, amount, params={}):
        """Places a market order."""
        return self.exchange.create_order(symbol, 'market', side, amount, params=params)

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