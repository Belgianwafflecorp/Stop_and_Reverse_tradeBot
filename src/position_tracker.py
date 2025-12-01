import time

class PositionTracker:
    """
    Analyzes trade fills to determine current position state.
    Enables stateless operation by reconstructing state from exchange data.
    """
    
    def __init__(self, bybit_client):
        """
        :param bybit_client: Instance of BybitClient
        """
        self.client = bybit_client
    
    def analyze_position_state(self, symbol, lookback_hours=24):
        """
        Analyzes recent fills to determine current trading state.
        
        :param symbol: Trading pair (e.g., 'BTC/USDT:USDT')
        :param lookback_hours: How far back to look for fills
        :return: Dictionary with position state information
        """
        # Calculate start time for fill fetching
        start_time_ms = int(time.time() * 1000) - (lookback_hours * 60 * 60 * 1000)
        
        # Fetch all fills in the lookback period
        fills = self.client.fetch_all_fills(symbol, start_time_ms)
        
        if not fills:
            return {
                'in_position': False,
                'flip_count': 0,
                'side': None,
                'net_quantity': 0.0,
                'average_entry': 0.0,
                'total_fills': 0,
                'last_fill_time': None,
                'realized_pnl': 0.0
            }
        
        # Calculate net position from fills
        net_qty = 0.0
        total_buy_cost = 0.0
        total_buy_qty = 0.0
        total_sell_cost = 0.0
        total_sell_qty = 0.0
        
        for fill in fills:
            qty = fill['amount']
            price = fill['price']
            
            if fill['side'] == 'buy':
                net_qty += qty
                total_buy_cost += (qty * price)
                total_buy_qty += qty
            else:  # sell
                net_qty -= qty
                total_sell_cost += (qty * price)
                total_sell_qty += qty
        
        # Determine if currently in a position (account for floating point precision)
        in_position = abs(net_qty) > 0.001
        
        # Determine current side
        current_side = None
        if in_position:
            current_side = 'long' if net_qty > 0 else 'short'
        
        # Calculate average entry price for current position
        average_entry = 0.0
        if in_position:
            if current_side == 'long' and total_buy_qty > 0:
                average_entry = total_buy_cost / total_buy_qty
            elif current_side == 'short' and total_sell_qty > 0:
                average_entry = total_sell_cost / total_sell_qty
        
        # Count flips (direction reversals)
        flip_count = self._count_flips(fills)
        
        # Calculate realized PnL (closed positions)
        realized_pnl = self._calculate_realized_pnl(fills)
        
        # Get last fill timestamp
        last_fill_time = fills[-1]['timestamp'] if fills else None
        
        return {
            'in_position': in_position,
            'flip_count': flip_count,
            'side': current_side,
            'net_quantity': abs(net_qty),
            'average_entry': average_entry,
            'total_fills': len(fills),
            'last_fill_time': last_fill_time,
            'realized_pnl': realized_pnl
        }
    
    def _count_flips(self, fills):
        """
        Counts the number of position direction changes (flips).
        
        :param fills: List of fill objects sorted by timestamp
        :return: Number of flips
        """
        if len(fills) < 2:
            return 0
        
        flip_count = 0
        running_position = 0.0
        previous_side = None
        
        for fill in fills:
            qty = fill['amount']
            
            # Update running position
            if fill['side'] == 'buy':
                running_position += qty
            else:  # sell
                running_position -= qty
            
            # Determine current side
            current_side = None
            if abs(running_position) > 0.001:
                current_side = 'long' if running_position > 0 else 'short'
            
            # Detect flip: side changed from long to short or vice versa
            if previous_side and current_side and previous_side != current_side:
                flip_count += 1
            
            # Update previous side only when we have a clear direction
            if current_side:
                previous_side = current_side
        
        return flip_count
    
    def _calculate_realized_pnl(self, fills):
        """
        Calculates realized PnL from closed portions of positions.
        Uses FIFO (First In, First Out) accounting.
        
        :param fills: List of fill objects sorted by timestamp
        :return: Realized PnL in USDT
        """
        buy_queue = []  # Queue of (qty, price) tuples
        sell_queue = []
        realized_pnl = 0.0
        
        for fill in fills:
            qty = fill['amount']
            price = fill['price']
            fee = fill.get('fee', {}).get('cost', 0.0)
            
            if fill['side'] == 'buy':
                buy_queue.append((qty, price, fee))
            else:  # sell
                sell_queue.append((qty, price, fee))
        
        # Match buys with sells to calculate realized PnL
        while buy_queue and sell_queue:
            buy_qty, buy_price, buy_fee = buy_queue[0]
            sell_qty, sell_price, sell_fee = sell_queue[0]
            
            # Determine matched quantity
            matched_qty = min(buy_qty, sell_qty)
            
            # Calculate PnL for this matched portion
            pnl = matched_qty * (sell_price - buy_price) - (buy_fee + sell_fee) * matched_qty / (buy_qty + sell_qty)
            realized_pnl += pnl
            
            # Update queues
            buy_queue[0] = (buy_qty - matched_qty, buy_price, buy_fee)
            sell_queue[0] = (sell_qty - matched_qty, sell_price, sell_fee)
            
            # Remove fully matched entries
            if buy_queue[0][0] < 0.001:
                buy_queue.pop(0)
            if sell_queue[0][0] < 0.001:
                sell_queue.pop(0)
        
        return realized_pnl
    
    def get_position_summary(self, symbol, lookback_hours=24):
        """
        Returns a formatted summary of the current position state.
        
        :param symbol: Trading pair
        :param lookback_hours: How far back to look
        :return: String summary
        """
        state = self.analyze_position_state(symbol, lookback_hours)
        
        summary = f"\n--- Position Summary for {symbol} ---\n"
        summary += f"In Position: {state['in_position']}\n"
        
        if state['in_position']:
            summary += f"Side: {state['side'].upper()}\n"
            summary += f"Quantity: {state['net_quantity']:.4f}\n"
            summary += f"Average Entry: ${state['average_entry']:.2f}\n"
        
        summary += f"Flip Count: {state['flip_count']}\n"
        summary += f"Total Fills: {state['total_fills']}\n"
        summary += f"Realized PnL: ${state['realized_pnl']:.2f}\n"
        
        if state['last_fill_time']:
            time_ago = (int(time.time() * 1000) - state['last_fill_time']) / 1000 / 60
            summary += f"Last Fill: {time_ago:.1f} minutes ago\n"
        
        summary += "-----------------------------------\n"
        
        return summary
