#!/usr/bin/env python3
"""
Maximum Cycle Loss Calculator

Calculates the theoretical maximum loss for a single trading cycle
based on configuration parameters.

Usage:
    python calc_max_cycle_loss.py [config_file]
    
    If no config file is specified, uses ../configs/config.json
    
Example:
    python calc_max_cycle_loss.py
    python calc_max_cycle_loss.py ../configs/config.json
    python calc_max_cycle_loss.py custom_config.json
"""

import json
import sys
import os


def load_config(config_path):
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)
    
    with open(config_path, 'r') as f:
        return json.load(f)


def calculate_max_cycle_loss(config):
    """
    Calculate maximum theoretical loss for a single trading cycle.
    
    Returns:
        dict with detailed breakdown of calculations
    """
    # Extract parameters
    initial_size = config['account']['fixed_initial_order_usd']
    multiplier = config['strategy']['martingale_multiplier']
    max_flips = config['strategy']['max_flips']
    range_pct = config['strategy']['range_pct']
    leverage = config['strategy']['leverage']
    
    # Calculate position sizes for each flip
    positions = [initial_size]
    for i in range(max_flips):
        positions.append(positions[-1] * multiplier)
    
    # Calculate losses at each flip (each flip loses range_pct)
    flip_losses = []
    for i in range(len(positions) - 1):
        loss = positions[i] * (range_pct / 100)
        flip_losses.append(loss)
    
    # Total capital deployed
    total_capital = sum(positions)
    
    # Total flip losses (accumulated losses from each flip)
    total_flip_losses = sum(flip_losses)
    
    # Worst case final position loss (if price continues against you)
    final_position_size = positions[-1]
    final_position_loss = final_position_size * (range_pct / 100)
    
    # Maximum total loss
    max_loss = total_flip_losses + final_position_loss
    
    # With leverage, actual account margin used
    margin_used = total_capital / leverage
    
    # Loss as percentage of initial capital
    loss_pct_of_initial = (max_loss / initial_size) * 100
    
    # Loss as percentage of total deployed capital
    loss_pct_of_total = (max_loss / total_capital) * 100
    
    return {
        'initial_size': initial_size,
        'multiplier': multiplier,
        'max_flips': max_flips,
        'range_pct': range_pct,
        'leverage': leverage,
        'positions': positions,
        'flip_losses': flip_losses,
        'total_capital': total_capital,
        'total_flip_losses': total_flip_losses,
        'final_position_size': final_position_size,
        'final_position_loss': final_position_loss,
        'max_loss': max_loss,
        'margin_used': margin_used,
        'loss_pct_of_initial': loss_pct_of_initial,
        'loss_pct_of_total': loss_pct_of_total
    }


def print_results(results):
    """Print formatted results."""
    print("\n" + "="*70)
    print("MAXIMUM CYCLE LOSS CALCULATION")
    print("="*70)
    
    print("\nConfiguration:")
    print(f"  Initial Entry Size:      ${results['initial_size']:.2f}")
    print(f"  Martingale Multiplier:   {results['multiplier']}x")
    print(f"  Maximum Flips:           {results['max_flips']}")
    print(f"  Range (Flip Trigger):    {results['range_pct']}%")
    print(f"  Leverage:                {results['leverage']}x")
    
    print("\nPosition Sizes Per Flip:")
    for i, size in enumerate(results['positions']):
        if i == 0:
            print(f"  Entry:   ${size:>10.2f}")
        else:
            print(f"  Flip {i}:  ${size:>10.2f}")
    
    print("\nLoss Per Flip (each flip loses range %):")
    for i, loss in enumerate(results['flip_losses']):
        print(f"  Flip {i+1}: -${loss:>9.2f} ({results['range_pct']}% of ${results['positions'][i]:.2f})")
    
    print("\nCapital Analysis:")
    print(f"  Total Capital Deployed:  ${results['total_capital']:.2f}")
    print(f"  Margin Required ({results['leverage']}x):    ${results['margin_used']:.2f}")
    
    print("\nLoss Breakdown:")
    print(f"  Accumulated Flip Losses: ${results['total_flip_losses']:.2f}")
    print(f"  Final Position Loss:     ${results['final_position_loss']:.2f} (if price moves another {results['range_pct']}%)")
    print(f"  ─────────────────────────────────")
    print(f"  MAXIMUM TOTAL LOSS:      ${results['max_loss']:.2f}")
    
    print("\nLoss Percentages:")
    print(f"  Loss vs Initial Entry:   {results['loss_pct_of_initial']:.2f}%")
    print(f"  Loss vs Total Deployed:  {results['loss_pct_of_total']:.2f}%")
    
    print("\nNotes:")
    print("  - This assumes you hit max_flips and price continues against you")
    print("  - Each flip loses exactly the range percentage")
    print("  - Real losses may vary based on execution and slippage")
    print("  - With leverage, account impact is based on margin, not notional")
    
    print("\n" + "="*70 + "\n")


def main():
    """Main entry point."""
    # Determine config file path
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        # Default to configs/config.json relative to script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, '..', 'configs', 'config.json')
    
    # Resolve to absolute path
    config_path = os.path.abspath(config_path)
    
    print(f"Loading configuration from: {config_path}")
    
    # Load config
    config = load_config(config_path)
    
    # Calculate
    results = calculate_max_cycle_loss(config)
    
    # Print results
    print_results(results)


if __name__ == "__main__":
    main()
