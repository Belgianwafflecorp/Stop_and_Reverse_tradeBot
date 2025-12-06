import pandas as pd
import time

class MarketScanner:
    def __init__(self, client, config, account_manager=None):
        """
        :param client: Instance of BybitClient (already connected)
        :param config: The full config dictionary
        :param account_manager: Instance of AccountManager for balance checking
        """
        self.client = client
        self.account_manager = account_manager
        self.min_volume = config['scanner_settings']['min_volume_usdt']
        self.lookback = config['scanner_settings']['volatility_lookback_candles']
        self.interval = config['scanner_settings']['interval']
        self.top_k = config['scanner_settings']['top_k_candidates']
        self.timeframe_1_minutes = config['scanner_settings'].get('timeframe_1_minutes', 1440)  # 24h default
        self.timeframe_1_threshold = config['scanner_settings'].get('timeframe_1_change_pct', 2.0)
        self.timeframe_2_minutes = config['scanner_settings'].get('timeframe_2_minutes', 5)    # 5m default
        self.timeframe_2_threshold = config['scanner_settings'].get('timeframe_2_change_pct', 0.2)
        self.initial_entry_pct = config['strategy']['initial_entry_pct']

    def get_best_volatile_coin(self):
        """
        Main function to find the best coin using dual timeframe filtering.
        1. Filter by timeframe_1 movement (e.g., 1440min/24h > 2%)
        2. Confirm with timeframe_2 movement (e.g., 5min > 0.2%)
        3. Score based on recent volatility + current movement
        """
        tf1_display = self._minutes_to_display(self.timeframe_1_minutes)
        tf2_display = self._minutes_to_display(self.timeframe_2_minutes)
        print(f"Scanning market with dual timeframe filter ({tf1_display} > {self.timeframe_1_threshold}% + {tf2_display} > {self.timeframe_2_threshold}%)...")
        return self.scan_dual_timeframe()

    def scan_dual_timeframe(self):
        """
        Dual timeframe filtering: Primary timeframe filter + secondary timeframe confirmation
        """
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
            
            if percentage is None:
                # Fallback: calculate from CCXT's standardized open/close fields
                open_price = data.get('open')
                close_price = data.get('close') or data.get('last')
                
                if open_price and close_price and open_price != 0:
                    percentage = abs(((close_price - open_price) / open_price) * 100)
                else:
                    continue  # Skip if we can't calculate percentage
            else:
                # CCXT percentage is already in % format, just make it absolute
                percentage = abs(percentage)
            
            # Filter 4: Skip coins that don't move enough (configurable threshold)
            if percentage < self.timeframe_1_threshold:
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
        
        # 4. Filter by minimum order size (if account manager is available)
        if self.account_manager:
            df = self._filter_by_min_order_size(df, market_info)
            if df.empty:
                print("No coins meet minimum order size requirements.")
                return None
        
        tf1_display = self._minutes_to_display(self.timeframe_1_minutes)
        tf2_display = self._minutes_to_display(self.timeframe_2_minutes)
        
        print(f"Top {len(df)} most volatile coins (>{self.timeframe_1_threshold}% {tf1_display} movement):")
        for idx, row in df.iterrows():
            print(f"  {row['symbol']}: {row['change_pct']:.2f}% change, ${row['volume']/1e6:.1f}M volume")
        
        print(f"\nAnalyzing {tf2_display} movement for confirmation...")

        # 4. Deep Dive: Check recent candles + timeframe_2 movement filter
        best_coin = None
        highest_score = -1
        candidates_found = []

        for symbol in df['symbol'].tolist():
            recent_vol = self.calculate_recent_volatility(symbol)
            timeframe_2_move = self.get_timeframe_movement(symbol, self.timeframe_2_minutes)
            
            # Apply timeframe_2 movement filter
            if timeframe_2_move < self.timeframe_2_threshold:
                continue
            
            # Combine both metrics (recent volatility + timeframe_2 movement)
            # Weight: 70% recent volatility + 30% timeframe_2 movement
            combined_score = (recent_vol * 0.7) + (timeframe_2_move * 0.3)
            
            candidates_found.append({
                'symbol': symbol,
                'score': combined_score,
                'recent_vol': recent_vol,
                'tf2_move': timeframe_2_move
            })
            
            if combined_score > highest_score:
                highest_score = combined_score
                best_coin = symbol
            
            # Small sleep to respect API rate limits during the loop
            time.sleep(0.1)
        
        # Print only qualifying candidates
        if candidates_found:
            for candidate in candidates_found:
                print(f"  {candidate['symbol']}: Recent vol: {candidate['recent_vol']:.2f}%, {tf2_display}: {candidate['tf2_move']:.2f}% (Score: {candidate['score']:.2f})")

        if best_coin:
            print(f"\nWinner: {best_coin} (Score: {highest_score:.2f})")
        else:
            print(f"\nNo coins found with sufficient {tf2_display} movement (>{self.timeframe_2_threshold}%)")
        
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
    
    def get_timeframe_movement(self, symbol, minutes):
        """
        Gets the percentage change for a specific timeframe in minutes.
        Converts minutes to exchange format and returns the percentage change.
        """
        try:
            timeframe = self._minutes_to_timeframe(minutes)
            # Fetch just the last 2 candles (current + previous)
            candles = self.client.fetch_candles(symbol, timeframe, 2)
            if len(candles) < 2:
                return 0
            
            # Get the most recent completed candle
            latest_candle = candles[-1]
            open_price = latest_candle[1]  # [time, open, high, low, close, vol]
            close_price = latest_candle[4]
            
            if open_price > 0:
                change_pct = abs(((close_price - open_price) / open_price) * 100)
                return change_pct
            
            return 0
            
        except Exception as e:
            print(f"Error checking {self._minutes_to_display(minutes)} movement for {symbol}: {e}")
            return 0
    
    def _filter_by_min_order_size(self, df, market_info):
        """
        Filters out coins where initial order size is less than exchange minimum.
        
        :param df: DataFrame of candidate coins
        :param market_info: Dictionary mapping symbol to market metadata
        :return: Filtered DataFrame
        """
        balance = self.account_manager.get_available_balance()
        initial_order_size = balance * (self.initial_entry_pct / 100.0)
        
        print(f"\nBalance: ${balance:.2f} | Initial order size: ${initial_order_size:.2f} ({self.initial_entry_pct}%)")
        print("Checking minimum order sizes...")
        
        valid_symbols = []
        skipped_count = 0
        
        for symbol in df['symbol'].tolist():
            market = market_info.get(symbol, {})
            limits = market.get('limits', {})
            cost_limits = limits.get('cost', {})
            min_cost = cost_limits.get('min')
            
            if min_cost is None:
                # No minimum specified - assume tradeable
                valid_symbols.append(symbol)
                continue
            
            if initial_order_size >= min_cost:
                valid_symbols.append(symbol)
            else:
                skipped_count += 1
        
        if skipped_count > 0:
            print(f"Skipped {skipped_count} coin(s) due to insufficient balance for minimum order size.")
        
        # Return filtered dataframe
        return df[df['symbol'].isin(valid_symbols)]
    
    def _minutes_to_timeframe(self, minutes):
        """
        Convert minutes to exchange timeframe format.
        Examples: 1 -> '1m', 5 -> '5m', 60 -> '1h', 1440 -> '1d'
        """
        if minutes < 60:
            return f"{minutes}m"
        elif minutes < 1440:
            hours = minutes // 60
            return f"{hours}h"
        else:
            days = minutes // 1440
            return f"{days}d"
    
    def _minutes_to_display(self, minutes):
        """
        Convert minutes to human-readable display format.
        Examples: 1 -> '1min', 5 -> '5min', 60 -> '1h', 1440 -> '24h'
        """
        if minutes < 60:
            return f"{minutes}min"
        elif minutes < 1440:
            hours = minutes // 60
            if minutes % 60 == 0:
                return f"{hours}h"
            else:
                return f"{hours}h{minutes % 60}min"
        else:
            days = minutes // 1440
            remaining_hours = (minutes % 1440) // 60
            if remaining_hours == 0:
                return f"{days * 24}h"
            else:
                return f"{days * 24 + remaining_hours}h"
