class AccountManager:
    """
    Manages account balance and position sizing calculations.
    """
    
    def __init__(self, bybit_client, config):
        """
        :param bybit_client: Instance of BybitClient
        :param config: Bot configuration dictionary
        """
        self.client = bybit_client
        self.initial_entry_pct = config['strategy']['initial_entry_pct']
        self.leverage = config['strategy']['leverage']
        self.use_live_balance = config['account']['use_live_balance']
        self.simulated_balance = config['account']['simulated_balance_usd']
        self.balance_compound = config['account']['balance_compound']
        self.fixed_initial_order = config['account']['fixed_initial_order_usd']
    
    def get_available_balance(self):
        """
        Fetches the available USDT balance from the exchange or uses simulated balance.
        
        :return: Available balance in USDT
        """
        # Use simulated balance for backtesting/testing
        if not self.use_live_balance:
            return float(self.simulated_balance)
        
        # Fetch live balance from exchange
        try:
            balance = self.client.exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {})
            available = usdt_balance.get('free', 0.0)
            return float(available)
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return 0.0
    
    def calculate_position_size(self, flip_count=0, previous_size=None, multiplier=None):
        """
        Calculates position size based on account balance and flip count.
        
        :param flip_count: Current number of flips (0 for initial entry)
        :param previous_size: Previous position size in USDT (for martingale calculation)
        :param multiplier: Martingale multiplier (if None, uses config value)
        :return: Position size in USDT
        """
        # Initial entry: use percentage of balance OR fixed amount
        if flip_count == 0:
            if self.balance_compound:
                # Compound mode: calculate from current balance
                balance = self.get_available_balance()
                
                if balance == 0:
                    print("WARNING: Account balance is 0")
                    return 0.0
                
                base_size = balance * (self.initial_entry_pct / 100.0)
                return round(base_size, 2)
            else:
                # Fixed mode: use configured fixed amount
                return round(self.fixed_initial_order, 2)
        
        # Subsequent entries: apply martingale to previous size
        if previous_size and multiplier:
            next_size = previous_size * multiplier
            return round(next_size, 2)
        
        # Fallback: return initial size
        if self.balance_compound:
            balance = self.get_available_balance()
            return round(balance * (self.initial_entry_pct / 100.0), 2)
        else:
            return round(self.fixed_initial_order, 2)
    
    def get_account_summary(self):
        """
        Returns a formatted summary of account status.
        
        :return: String summary
        """
        balance = self.get_available_balance()
        
        summary = "\n--- Account Summary ---\n"
        summary += f"Available Balance: ${balance:.2f} USD\n"
        
        if self.balance_compound:
            base_size = balance * (self.initial_entry_pct / 100.0)
            summary += f"Mode: COMPOUND\n"
            summary += f"Initial Entry %: {self.initial_entry_pct}%\n"
            summary += f"Initial Entry Size: ${base_size:.2f} USD\n"
        else:
            summary += f"Mode: FIXED\n"
            summary += f"Initial Entry Size: ${self.fixed_initial_order:.2f} USD (fixed)\n"
        
        summary += f"Leverage: {self.leverage}x\n"
        summary += "----------------------\n"
        
        return summary
        
        return summary
