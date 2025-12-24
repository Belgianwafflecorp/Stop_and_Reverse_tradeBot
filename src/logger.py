import logging
from datetime import datetime
import os
import sys

class BotLogger:
    """
    Professional logging system for the trading bot.
    Handles timestamps, formatting, and different log levels.
    """
    
    def __init__(self, name="TradingBot", log_dir="logs", save_to_file=False):
        """Initialize the logger with file and console output."""
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Professional formatter with timestamps
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        if save_to_file:
            # Create logs directory if it doesn't exist
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            # File handler (debug level - captures everything)
            log_file = os.path.join(log_dir, f"trading_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # Console handler (info level and above)
        # Force UTF-8 encoding for console output on Windows
        if sys.platform == 'win32':
            console_handler = logging.StreamHandler(sys.stdout)
        else:
            console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        console_handler.setFormatter(formatter)
        
        # Add handlers
        self.logger.addHandler(console_handler)
    
    def info(self, message):
        """Log info level message."""
        self.logger.info(message)
    
    def debug(self, message):
        """Log debug level message."""
        self.logger.debug(message)
    
    def warning(self, message):
        """Log warning level message."""
        self.logger.warning(message)
    
    def error(self, message):
        """Log error level message."""
        self.logger.error(message)
    
    def critical(self, message):
        """Log critical level message."""
        self.logger.critical(message)
    
    # Convenience methods for common trading operations
    def order_placed(self, order_type, symbol, side, amount, price=None):
        """Log order placement."""
        price_str = f" @ ${price:.6f}" if price else ""
        self.info(f"[ORDER] {order_type} | {symbol} {side.upper()} {amount:.4f} contracts{price_str}")
    
    def order_cancelled(self, order_id, symbol):
        """Log order cancellation."""
        self.info(f"[CANCELLED] Order {order_id} for {symbol}")
    
    def position_opened(self, symbol, side, contracts, entry_price):
        """Log position opening."""
        self.info(f"[POSITION OPEN] {symbol} {side.upper()} | {contracts:.4f} contracts @ ${entry_price:.6f}")
    
    def position_closed(self, symbol, side, contracts, exit_price, reason=""):
        """Log position closing."""
        reason_str = f" ({reason})" if reason else ""
        self.info(f"[POSITION CLOSED] {symbol} {side.upper()} | {contracts:.4f} contracts @ ${exit_price:.6f}{reason_str}")
    
    def flip_triggered(self, symbol, old_side, new_side, entry_price, trigger_price):
        """Log flip event."""
        self.info(f"[FLIP] {symbol} | {old_side.upper()} → {new_side.upper()} | Entry: ${entry_price:.6f} | Trigger: ${trigger_price:.6f}")
    
    def flip_count_status(self, symbol, current_flip, max_flips):
        """Log flip count progress."""
        self.info(f"[FLIP STATUS] {symbol} | Flip {current_flip}/{max_flips}")
    
    def section(self, title):
        """Log a section header."""
        self.info(f"\n{'='*70}")
        self.info(f"  {title}")
        self.info(f"{'='*70}")
    
    def subsection(self, title):
        """Log a subsection header."""
        self.info(f"\n{'-'*70}")
        self.info(f"  {title}")
        self.info(f"{'-'*70}")
