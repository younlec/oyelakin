"""
Generates sample tick data for backtesting and development.

Usage:
  python generate_sample_data.py                      # Default: 5000 ticks
  python generate_sample_data.py --ticks 10000        # Custom count
  python generate_sample_data.py --output my_data.csv # Custom output
"""

import argparse

import numpy as np
import pandas as pd


def generate_synthetic_ticks(
    n_ticks: int = 5000,
    start_price: float = 1000.0,
    volatility: float = 0.002,
    trend: float = 0.0001,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate synthetic price data with realistic tick-level behaviour.
    Uses geometric Brownian motion with mean reversion.
    """
    rng = np.random.RandomState(seed)
    prices = np.zeros(n_ticks)
    prices[0] = start_price

    mean_price = start_price
    reversion_speed = 0.001

    for i in range(1, n_ticks):
        shock = rng.normal(0, volatility)
        reversion = reversion_speed * (mean_price - prices[i - 1]) / mean_price
        prices[i] = prices[i - 1] * (1 + trend + shock + reversion)
        if i % 500 == 0:
            mean_price = prices[i]

    return prices


def main():
    parser = argparse.ArgumentParser(description="Generate sample tick data")
    parser.add_argument("--ticks", type=int, default=5000, help="Number of ticks")
    parser.add_argument("--output", type=str, default="data.csv", help="Output file")
    parser.add_argument("--start-price", type=float, default=1000.0)
    parser.add_argument("--volatility", type=float, default=0.002)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    prices = generate_synthetic_ticks(
        n_ticks=args.ticks,
        start_price=args.start_price,
        volatility=args.volatility,
        seed=args.seed,
    )

    df = pd.DataFrame({"price": prices})
    df.to_csv(args.output, index=False)
    print(f"Generated {len(prices)} ticks → {args.output}")
    print(f"  Start: {prices[0]:.5f}")
    print(f"  End:   {prices[-1]:.5f}")
    print(f"  Min:   {prices.min():.5f}")
    print(f"  Max:   {prices.max():.5f}")


if __name__ == "__main__":
    main()
