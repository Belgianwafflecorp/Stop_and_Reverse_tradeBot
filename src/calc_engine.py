class TradeCalculator:
    def __init__(self, config, bybit_client=None):
        self.initial_entry_pct = config['strategy']['initial_entry_pct']
        self.multiplier = config['strategy']['martingale_multiplier']
        self.max_flips = config['strategy']['max_flips']
        
        # Range configuration - used for both flips and TP
        self.range_pct = config['strategy']['range_pct']
        
        # Exit mode configuration
        self.exit_use_trailing = config['strategy'].get('exit_use_trailing', True)
        self.trailing_retracement_pct = config['strategy']['trailing_retracement_pct']
        
        # Fetch live fees from exchange if client is provided
        self.client = bybit_client
        if bybit_client:
            fees = bybit_client.fetch_trading_fees()
            self.fee_rate = fees.get('taker', 0.0006)
            print(f"Loaded trading fees from exchange: taker={self.fee_rate*100:.3f}%")
        else:
            # Fallback to config if no client provided
            self.fee_rate = config['strategy']['fees'].get('taker_fee_rate', 0.0006)
            print(f"Using config fee rate: {self.fee_rate*100:.3f}%")
        
        exit_type = "TRAILING" if self.exit_use_trailing else "STATIC"
        print(f"Exit mode: {exit_type}")
        print(f"Range: {self.range_pct}% (flip trigger & TP activation)")

    def calculate_next_position(self, current_flip_count, previous_size, realized_loss):
        """
        Calculates the size for the next trade after a flip.
        """
        # Safety: stop if we've reached max flips
        if current_flip_count >= self.max_flips:
            return 0  # Stop trading
        
        # Bereken de grootte van de volgende positie
        next_size = previous_size * self.multiplier
        
        # Bereken geschatte fees voor deze nieuwe opening
        estimated_fee = next_size * self.fee_rate
        
        return round(next_size, 3)

    def calculate_break_even_price(self, entry_price, direction, total_loss_usdt, position_size):
        """
        Optional: Calculates where the price needs to go to break even.
        Useful for logging or dynamic TP.
        """
        # How much price movement (in $) do we need to recover losses?
        required_profit_usd = total_loss_usdt + (position_size * self.fee_rate * 2) # *2 for open+close fee
        
        required_move_pct = (required_profit_usd / position_size)
        
        if direction == "Long":
            return entry_price * (1 + required_move_pct)
        else:
            return entry_price * (1 - required_move_pct)
    
    def calculate_take_profit_price(self, entry_price, direction):
        """
        Calculates the take profit price based on exit mode.
        Uses range_pct for both static TP and trailing activation.
        
        :param entry_price: Entry price of the position
        :param direction: 'long' or 'short'
        :return: Take profit price (for static mode) or None (for trailing mode)
        """
        if not self.exit_use_trailing:
            # Static TP: Fixed percentage target at range_pct
            if direction.lower() == 'long':
                tp_price = entry_price * (1 + self.range_pct / 100)
            else:
                tp_price = entry_price * (1 - self.range_pct / 100)
            return round(tp_price, 4)
        else:
            # Trailing mode: No fixed TP, managed dynamically
            return None
    
    def check_trailing_exit(self, entry_price, current_price, peak_price, direction):
        """
        Checks if trailing take profit should trigger.
        Activates at range_pct profit, exits on callback_pct drawback.
        
        :param entry_price: Entry price of position
        :param current_price: Current market price
        :param peak_price: Highest (for long) or lowest (for short) price since entry
        :param direction: 'long' or 'short'
        :return: (should_exit, reason)
        """
        if not self.exit_use_trailing:
            return False, None
        
        if direction.lower() == 'long':
            # Calculate profit from entry
            profit_pct = ((current_price - entry_price) / entry_price) * 100
            
            # Check if activation threshold reached (uses range_pct)
            if profit_pct < self.range_pct:
                return False, None
            
            # Calculate drawdown from peak
            if peak_price and peak_price > entry_price:
                drawdown_pct = ((peak_price - current_price) / peak_price) * 100
                
                if drawdown_pct >= self.trailing_retracement_pct:
                    return True, f"Trailing TP triggered: {drawdown_pct:.2f}% callback from peak"
        else:
            # Short position
            profit_pct = ((entry_price - current_price) / entry_price) * 100
            
            if profit_pct < self.range_pct:
                return False, None
            
            # For shorts, peak is the lowest price
            if peak_price and peak_price < entry_price:
                drawdown_pct = ((current_price - peak_price) / peak_price) * 100
                
                if drawdown_pct >= self.trailing_retracement_pct:
                    return True, f"Trailing TP triggered: {drawdown_pct:.2f}% callback from low"
        
        return False, None
    
    def get_exit_info(self):
        """
        Returns human-readable exit configuration.
        """
        if self.exit_use_trailing:
            return f"Trailing TP: Activate at +{self.range_pct}%, callback {self.trailing_retracement_pct}%"
        else:
            return f"Static TP: +{self.range_pct}% target"

