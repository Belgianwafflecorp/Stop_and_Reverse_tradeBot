import ccxt
import time

class BybitClient:
    def __init__(self, api_key=None, api_secret=None, testnet=False):
        """
        Initializes the connection with Bybit via CCXT.
        API keys are optional - only needed for trading operations.
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
        else:
            print("Public data mode (no authentication)")
        
        self.exchange = ccxt.bybit(config)
        
        if testnet:
            self.exchange.set_sandbox_mode(True)
            print("WARNING: Bybit Client running in TESTNET mode!")

    def get_market_price(self, symbol):
        """Returns the current price of a symbol."""
        ticker = self.exchange.fetch_ticker(symbol)
        return float(ticker['last'])

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

    def fetch_candles(self, symbol, timeframe, limit):
        """
        Fetches OHLCV data.
        :param timeframe: e.g., '15m', '1h'
        :param limit: number of candles
        """
        return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)