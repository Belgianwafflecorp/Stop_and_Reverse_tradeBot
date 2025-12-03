import time

class PositionTracker:
    """
    Analyzes trade fills to determine current position state.
    Enables stateless operation by reconstructing state from exchange data.
    """
    
    def __init__(self, bybit_client, config):
        """
        :param bybit_client: Instance of BybitClient
        :param config: Bot configuration dictionary (needed for base_size and multiplier)
        """
        self.client = bybit_client
        self.base_size = config['strategy']['base_size_usdt']
        self.multiplier = config['strategy']['martingale_multiplier']
    
    def analyze_position_state(self, symbol, lookback_hours=24):
        """
        Analyzes recent fills to determine current trading state.
        Detects cycle boundaries based on position size patterns.
        
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
                'realized_pnl': 0.0,
                'current_cycle_start': None,
                'cycle_complete': False
            }
        
        # Detect current cycle boundary
        cycle_fills = self._get_current_cycle_fills(fills)
        
        # Calculate net position from CURRENT CYCLE fills only
        net_qty = 0.0
        total_buy_cost = 0.0
        total_buy_qty = 0.0
        total_sell_cost = 0.0
        total_sell_qty = 0.0
        
        for fill in cycle_fills:
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
        
        # Count flips (direction reversals) in CURRENT CYCLE only
        flip_count = self._count_flips(cycle_fills)
        
        # Calculate realized PnL for current cycle
        realized_pnl = self._calculate_realized_pnl(cycle_fills)
        
        # Get cycle start time
        cycle_start_time = cycle_fills[0]['timestamp'] if cycle_fills else None
        
        # Determine if cycle is complete (position closed and back to zero)
        cycle_complete = not in_position and len(cycle_fills) > 0
        
        # Get last fill timestamp
        last_fill_time = cycle_fills[-1]['timestamp'] if cycle_fills else None
        
        return {
            'in_position': in_position,
            'flip_count': flip_count,
            'side': current_side,
            'net_quantity': abs(net_qty),
            'average_entry': average_entry,
            'total_fills': len(cycle_fills),
            'last_fill_time': last_fill_time,
            'realized_pnl': realized_pnl,
            'current_cycle_start': cycle_start_time,
            'cycle_complete': cycle_complete
        }
    
    def _get_current_cycle_fills(self, fills):
        """
        Extracts fills belonging to the current trading cycle.
        Detects cycle boundaries by analyzing position closures and size patterns.
        
        Strategy:
        - Cycle ENDS when position closes completely (net position = 0)
        - New cycle STARTS with next position opening
        - Handles both: flipping cycles AND simple open->close->open patterns
        
        :param fills: All fills sorted by timestamp
        :return: List of fills from current cycle only
        """
        if not fills:
            return []
        
        # Track running position through all fills to find closure points
        cycle_boundaries = [0]  # Start of first cycle
        running_position = 0.0
        
        for i, fill in enumerate(fills):
            qty = fill['amount']
            
            prev_position = running_position
            
            # Update running position
            if fill['side'] == 'buy':
                running_position += qty
            else:
                running_position -= qty
            
            # Detect position closure (crossed zero or became zero)
            # Previous position was non-zero, now it's zero or crossed zero
            if abs(prev_position) > 0.001:
                # Position closed completely
                if abs(running_position) < 0.001:
                    # Mark next fill as potential new cycle start
                    if i + 1 < len(fills):
                        cycle_boundaries.append(i + 1)
                # Position flipped sides (also indicates closure + reopening)
                elif (prev_position > 0 and running_position < 0) or \
                     (prev_position < 0 and running_position > 0):
                    # This fill itself starts the new cycle
                    cycle_boundaries.append(i)
        
        # Get fills from the last cycle boundary to end
        if cycle_boundaries:
            last_boundary = cycle_boundaries[-1]
            return fills[last_boundary:]
        
        return fills
    
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
        summary += f"Total Fills (Current Cycle): {state['total_fills']}\n"
        summary += f"Realized PnL (Current Cycle): ${state['realized_pnl']:.2f}\n"
        
        if state['cycle_complete']:
            summary += "Cycle Status: COMPLETE (ready for new cycle)\n"
        elif state['in_position']:
            summary += "Cycle Status: IN PROGRESS\n"
        else:
            summary += "Cycle Status: NO ACTIVE CYCLE\n"
        
        if state['last_fill_time']:
            time_ago = (int(time.time() * 1000) - state['last_fill_time']) / 1000 / 60
            summary += f"Last Fill: {time_ago:.1f} minutes ago\n"
        
        summary += "-----------------------------------\n"
        
        return summary
