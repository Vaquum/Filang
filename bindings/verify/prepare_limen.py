"""Convert a Limen spot-kline fixture to the engine's lossless nine-column CSV."""

import argparse
import csv
from pathlib import Path

import polars as pl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--tail", type=int)
    args = parser.parse_args()
    frame = pl.read_parquet(args.parquet).select(
        pl.col("datetime").dt.epoch("ms"), "open", "high", "low", "close", "volume",
        "liquidity_sum", (pl.col("liquidity_sum") - pl.col("maker_liquidity")).alias("taker_buy"),
        "no_of_trades",
    ).sort("datetime")
    if args.tail is not None:
        frame = frame.tail(args.tail)
    with args.csv.open("w", newline="") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow((
            "open_ms", "open", "high", "low", "close", "base_volume", "volume",
            "taker_buy_volume", "trade_count",
        ))
        for t, o, h, low, c, btc, quote, buy, trades in frame.iter_rows():
            prices = tuple(f"{price:.2f}" for price in (o, h, low, c))
            if any(float(ticks) != price for ticks, price in zip(prices, (o, h, low, c))):
                raise ValueError(f"price at {t} is outside the exact cent grid")
            writer.writerow((t, *prices, btc, quote, buy, trades))
    print(f"{frame.height} original Limen rows")


if __name__ == "__main__":
    main()
