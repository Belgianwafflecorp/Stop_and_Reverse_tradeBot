"""
Test script to inspect all available data for a single coin from Bybit
"""
import ccxt
import json
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def inspect_coin(symbol='BTC/USDT:USDT'):
    """
    Fetches and displays ALL available data for a specific coin
    """
    # Initialize Bybit exchange (no auth needed for public data)
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'}
    })
    
    print("=" * 100)
    print(f"COMPLETE DATA INSPECTION FOR: {symbol}")
    print("=" * 100)
    
    # 1. TICKER DATA
    print("\n\n1. TICKER DATA")
    print("-" * 100)
    try:
        ticker = exchange.fetch_ticker(symbol)
        print("\nAll ticker fields:")
        for key in sorted(ticker.keys()):
            print(f"  {key}: {ticker[key]}")
        
        print("\n\nRaw ticker JSON:")
        print(json.dumps(ticker, indent=2, default=str))
    except Exception as e:
        print(f"Error fetching ticker: {e}")
    
    # 2. MARKET INFO
    print("\n\n2. MARKET INFORMATION")
    print("-" * 100)
    try:
        markets = exchange.fetch_markets()
        market = None
        for m in markets:
            if m['symbol'] == symbol:
                market = m
                break
        
        if market:
            print("\nAll market fields:")
            for key in sorted(market.keys()):
                if key != 'info':  # Show info separately
                    print(f"  {key}: {market[key]}")
            
            print("\n\nRaw market 'info' field (direct from Bybit API):")
            print(json.dumps(market.get('info', {}), indent=2, default=str))
            
            print("\n\nComplete market JSON:")
            print(json.dumps(market, indent=2, default=str))
    except Exception as e:
        print(f"Error fetching market info: {e}")
    
    # 3. OHLCV DATA (Recent candles)
    print("\n\n3. OHLCV DATA (Last 5 candles, 1h timeframe)")
    print("-" * 100)
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=5)
        print("\nStructure: [timestamp, open, high, low, close, volume]")
        for candle in ohlcv:
            timestamp = candle[0]
            from datetime import datetime
            dt = datetime.fromtimestamp(timestamp / 1000)
            print(f"\n  {dt}: O={candle[1]}, H={candle[2]}, L={candle[3]}, C={candle[4]}, V={candle[5]}")
    except Exception as e:
        print(f"Error fetching OHLCV: {e}")
    
    # 4. ORDER BOOK
    print("\n\n4. ORDER BOOK (Top 5 bids/asks)")
    print("-" * 100)
    try:
        orderbook = exchange.fetch_order_book(symbol, limit=5)
        print("\nTop 5 Bids:")
        for bid in orderbook['bids'][:5]:
            print(f"  Price: {bid[0]}, Amount: {bid[1]}")
        
        print("\nTop 5 Asks:")
        for ask in orderbook['asks'][:5]:
            print(f"  Price: {ask[0]}, Amount: {ask[1]}")
        
        print("\n\nComplete orderbook structure:")
        print(json.dumps(orderbook, indent=2, default=str))
    except Exception as e:
        print(f"Error fetching orderbook: {e}")
    
    # 5. RECENT TRADES
    print("\n\n5. RECENT TRADES (Last 5)")
    print("-" * 100)
    try:
        trades = exchange.fetch_trades(symbol, limit=5)
        for trade in trades:
            print(f"\n  ID: {trade.get('id')}")
            print(f"  Timestamp: {trade.get('timestamp')}")
            print(f"  Side: {trade.get('side')}")
            print(f"  Price: {trade.get('price')}")
            print(f"  Amount: {trade.get('amount')}")
        
        if trades:
            print("\n\nComplete trade structure (first trade):")
            print(json.dumps(trades[0], indent=2, default=str))
    except Exception as e:
        print(f"Error fetching trades: {e}")
    
    # 6. FUNDING RATE (for perpetuals)
    print("\n\n6. FUNDING RATE (Perpetual contracts)")
    print("-" * 100)
    try:
        funding = exchange.fetch_funding_rate(symbol)
        print("\nAll funding rate fields:")
        for key in sorted(funding.keys()):
            print(f"  {key}: {funding[key]}")
        
        print("\n\nComplete funding rate JSON:")
        print(json.dumps(funding, indent=2, default=str))
    except Exception as e:
        print(f"Error fetching funding rate: {e}")
    
    # 7. SUMMARY
    print("\n\n7. DATA SUMMARY")
    print("-" * 100)
    print("\nAvailable data types:")
    print("  ✓ Ticker (price, volume, high, low, open, close, etc.)")
    print("  ✓ Market info (trading rules, limits, innovation markers)")
    print("  ✓ OHLCV candles (historical price data)")
    print("  ✓ Order book (current bids and asks)")
    print("  ✓ Recent trades (market activity)")
    print("  ✓ Funding rate (for perpetuals)")
    
    print("\n" + "=" * 100)

if __name__ == "__main__":
    # You can change the symbol here to inspect different coins
    symbol = input("Enter symbol to inspect (default: BTC/USDT:USDT): ").strip()
    if not symbol:
        symbol = 'BTC/USDT:USDT'
    
    inspect_coin(symbol)
