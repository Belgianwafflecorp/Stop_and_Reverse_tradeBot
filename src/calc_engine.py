class TradeCalculator:
    def __init__(self, config):
        self.base_size = config['strategy']['base_size_usdt']
        self.multiplier = config['strategy']['martingale_multiplier']
        self.fee_rate = config['strategy']['fees']['taker_fee_rate']
        self.max_flips = config['strategy']['max_flips']

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