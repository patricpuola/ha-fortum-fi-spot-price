#!/usr/bin/env python3
"""Fetch and print Fortum spot-price data for a given date."""

import argparse
import datetime
import json
from urllib.parse import urlencode
from urllib.request import urlopen


API_URL = "https://www.fortum.com/fi/sahkoa/api/trpc/shared.spotPrices.listPriceAreaSpotPrices"
RESOLUTIONS = ("PER_15_MIN", "HOUR")


def build_api_url(date, price_area, resolution):
    input_data = {
        "0": {
            "json": {
                "priceArea": price_area,
                "fromDate": date,
                "toDate": date,
                "resolution": resolution,
            }
        }
    }
    query = urlencode({
        "batch": 1,
        "input": json.dumps(input_data, separators=(",", ":")),
    })
    return f"{API_URL}?{query}"


def fetch_prices(date, price_area, resolution):
    url = build_api_url(date, price_area, resolution)
    with urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"Fortum API returned HTTP {response.status}")
        payload = json.load(response)

    try:
        series = payload[0]["result"]["data"]["json"][0]["spotPriceSeries"]
        return {
            item["atUTC"]: item["spotPrice"]["total"]
            for item in series
        }
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("Unexpected Fortum API response structure") from error


def calculate_ranks(prices):
    sorted_prices = sorted(prices.items(), key=lambda item: item[1])
    ranks_by_timestamp = {
        timestamp: rank
        for rank, (timestamp, _price) in enumerate(sorted_prices)
    }
    return dict(sorted(ranks_by_timestamp.items()))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Print the complete Fortum FI spot-price dataset for a date."
    )
    parser.add_argument(
        "date",
        type=datetime.date.fromisoformat,
        help="Date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--price-area",
        default="FI",
        help="Fortum price area (default: FI)",
    )
    parser.add_argument(
        "--resolution",
        choices=("PER_15_MIN", "HOUR", "both"),
        default="both",
        help="Resolution to fetch (default: both)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    resolutions = RESOLUTIONS if args.resolution == "both" else (args.resolution,)
    dataset = {
        resolution: fetch_prices(
            args.date.isoformat(), args.price_area, resolution
        )
        for resolution in resolutions
    }
    ranks = {
        resolution: calculate_ranks(prices)
        for resolution, prices in dataset.items()
    }
    print(json.dumps({
        "date": args.date.isoformat(),
        "price_area": args.price_area,
        "prices": dataset,
        "ranks": ranks,
    }, indent=2))


if __name__ == "__main__":
    main()
