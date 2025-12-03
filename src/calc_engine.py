class TradeCalculator:
    def __init__(self, config, bybit_client=None):
        self.initial_entry_pct = config['strategy']['initial_entry_pct']
        self.multiplier = config['strategy']['martingale_multiplier']
        self.max_flips = config['strategy']['max_flips']
        
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