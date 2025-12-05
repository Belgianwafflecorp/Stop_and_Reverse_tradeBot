import pandas as pd
import time

class MarketScanner:
    def __init__(self, client, config):
        """
        :param client: Instance of BybitClient (already connected)
        :param config: The full config dictionary
        """
        self.client = client
        self.min_volume = config['scanner_settings']['min_volume_usdt']
        self.lookback = config['scanner_settings']['volatility_lookback_candles']
        self.interval = config['scanner_settings']['interval']
        self.top_k = config['scanner_settings']['top_k_candidates']

    def get_best_volatile_coin(self):
        """
        Main function to find the best coin.
        1. Filters by 24h Spread (High/Low).
        2. Filters top candidates by recent candle volatility.
        """
        print("Scanning market for volatility...")

        # 1. Fetch markets info and tickers
        try:
            markets = self.client.fetch_markets()
            tickers = self.client.fetch_tickers()
            
            # Build a lookup for market info
            market_info = {m['symbol']: m for m in markets}
        except Exception as e:
            print(f"Error fetching market data: {e}")
            return None

        candidates = []

        # 2. Filter loop (Client-side filtering)
        for symbol, data in tickers.items():
            # Filter 1: Must be USDT perp (CCXT usually formats as BTC/USDT:USDT)
            if not symbol.endswith(':USDT'):
                continue
            
            # Filter 2: Check if innovation zone (Bybit-specific, skip for other exchanges)
            market = market_info.get(symbol, {})
            info = market.get('info', {})
            
            # Only apply innovation filter if we have Bybit-specific data
            if info:
                if info.get('innovatorSymbol') == '1' or \
                   info.get('status') == 'PreLaunch' or \
                   'innovation' in str(info.get('category', '')).lower():
                    continue  # Skip innovation zone coins
            
            # Filter 3: Calculate 24h percentage change using CCXT standardized fields
            percentage = data.get('percentage')
            
            # Debug specific problem coins
            if symbol in ['SAND/USDT:USDT', 'MNT/USDT:USDT', 'SOL/USDT:USDT', 'BTC/USDT:USDT']:
                print(f"\nDEBUG {symbol}:")
                print(f"  percentage field: {percentage}")
                print(f"  open: {data.get('open')}")
                print(f"  close: {data.get('close')}")
                print(f"  last: {data.get('last')}")
            
            if percentage is None:
                # Fallback: calculate from CCXT's standardized open/close fields
                open_price = data.get('open')
                close_price = data.get('close') or data.get('last')
                
                if open_price and close_price and open_price != 0:
                    percentage = abs(((close_price - open_price) / open_price) * 100)
                    if symbol in ['SAND/USDT:USDT', 'MNT/USDT:USDT']:
                        print(f"  CALCULATED: {percentage:.2f}%")
                else:
                    continue  # Skip if we can't calculate percentage
            else:
                # CCXT percentage is already in % format, just make it absolute
                percentage = abs(percentage)
                if symbol in ['SAND/USDT:USDT', 'MNT/USDT:USDT', 'SOL/USDT:USDT', 'BTC/USDT:USDT']:
                    print(f"  USING CCXT: {percentage:.2f}%")
            
            # Filter 4: Skip coins that don't move enough (less than 2%)
            if percentage < 2.0:
                continue
            
            # Get volume for informational purposes only
            vol_usdt = data.get('quoteVolume', 0)
            
            candidates.append({
                'symbol': symbol,
                'change_pct': percentage,
                'volume': vol_usdt
            })

        # 3. Sort by percentage change (highest volatility first)
        df = pd.DataFrame(candidates)
        if df.empty:
            print("No coins found with >2% movement in 24h.")
            return None
            
        df = df.sort_values(by='change_pct', ascending=False).head(self.top_k)
        
        print(f"Top {len(df)} most volatile coins (>2% movement):")
        for idx, row in df.iterrows():
            print(f"  {row['symbol']}: {row['change_pct']:.2f}% change, ${row['volume']/1e6:.1f}M volume")
        
        print(f"\nAnalyzing recent candles for confirmation...")

        # 4. Deep Dive: Check recent candles for "Fresh" volatility
        best_coin = None
        highest_recent_vol = -1

        for symbol in df['symbol'].tolist():
            recent_vol = self.calculate_recent_volatility(symbol)
            
            if recent_vol > highest_recent_vol:
                highest_recent_vol = recent_vol
                best_coin = symbol
            
            # Small sleep to respect API rate limits during the loop
            time.sleep(0.1)

        print(f"Winner found: {best_coin} (Recent Vol: {highest_recent_vol:.2f}%)")
        return best_coin

    def calculate_recent_volatility(self, symbol):
        """
        Fetches recent candles and calculates average body size %.
        """
        try:
            candles = self.client.fetch_candles(symbol, self.interval, self.lookback)
            if not candles: return 0

            total_move = 0
            for c in candles:
                # CCXT structure: [time, open, high, low, close, vol]
                high = c[2]
                low = c[3]
                open_p = c[1]
                
                # Calculate candle range percentage
                if open_p > 0:
                    move_pct = ((high - low) / open_p) * 100
                    total_move += move_pct
            
            # Return average volatility per candle
            return total_move / len(candles)

        except Exception as e:
            print(f"Error checking candles for {symbol}: {e}")
            return 0