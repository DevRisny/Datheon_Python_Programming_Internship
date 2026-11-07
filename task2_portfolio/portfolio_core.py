"""Portfolio maths and CSV files. No printing here, so every number can be unit tested.

Money uses Decimal, not float, so totals never pick up rounding errors such as 0.1 + 0.2.
"""
from __future__ import annotations

import csv
import difflib
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_decimal(raw: object, name: str, allow_zero: bool = False) -> Decimal:
    """Parses '1,250.50' or '$99' into a Decimal and checks it is a sensible positive number."""
    text = str(raw).strip().replace(",", "").replace("$", "")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{name} must be a number, got '{raw}'") from None
    if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} must be greater than zero")
    return value


def clean_ticker(raw: str) -> str:
    ticker = raw.strip().upper().replace("/", ".")
    if not ticker or len(ticker) > 10 or not all(ch.isalnum() or ch in ".-" for ch in ticker):
        raise ValueError(f"'{raw}' is not a valid ticker symbol")
    return ticker


@dataclass(frozen=True)
class Quote:
    ticker: str
    company: str
    sector: str
    price: Decimal


class PriceBook:
    """Current prices, from the bundled sample CSV (or a live source passed in)."""

    def __init__(self, quotes: dict[str, Quote], source: str = "sample data"):
        self.quotes = quotes
        self.source = source

    @classmethod
    def from_csv(cls, path: Path) -> "PriceBook":
        quotes = {}
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ticker = clean_ticker(row["ticker"])
                quotes[ticker] = Quote(ticker, row.get("company", ticker).strip(),
                                       row.get("sector", "Other").strip() or "Other",
                                       to_decimal(row["price"], f"price of {ticker}"))
        return cls(quotes, f"sample prices from {path.name}")

    def get(self, ticker: str) -> Quote | None:
        return self.quotes.get(ticker.upper())

    def suggest(self, ticker: str) -> list[str]:
        """Close matches for a mistyped ticker, e.g. 'APPL' -> ['AAPL']."""
        return difflib.get_close_matches(ticker.upper(), list(self.quotes), n=3, cutoff=0.5)


@dataclass
class Holding:
    ticker: str
    shares: Decimal
    buy_price: Decimal  # average cost per share

    @property
    def invested(self) -> Decimal:
        return self.shares * self.buy_price


@dataclass
class Line:
    """One row of the report: a holding valued at the current price."""
    ticker: str
    company: str
    sector: str
    shares: Decimal
    buy_price: Decimal
    price: Decimal
    invested: Decimal
    value: Decimal
    gain: Decimal
    gain_pct: Decimal
    weight: Decimal = Decimal(0)


@dataclass
class Report:
    lines: list[Line]
    invested: Decimal
    value: Decimal
    gain: Decimal
    gain_pct: Decimal
    by_sector: dict[str, Decimal]
    missing: list[str]
    created: datetime

    @property
    def best(self) -> Line | None:
        return max(self.lines, key=lambda l: l.gain_pct, default=None)

    @property
    def worst(self) -> Line | None:
        return min(self.lines, key=lambda l: l.gain_pct, default=None)


class Portfolio:
    def __init__(self) -> None:
        self.holdings: dict[str, Holding] = {}

    def add(self, ticker: str, shares: object, buy_price: object) -> Holding:
        """Adds a purchase. Buying more of the same stock updates the average cost."""
        ticker = clean_ticker(ticker)
        shares_d = to_decimal(shares, "Shares")
        price_d = to_decimal(buy_price, "Buy price")
        current = self.holdings.get(ticker)
        if current:
            total = current.shares + shares_d
            average = (current.invested + shares_d * price_d) / total
            current.shares, current.buy_price = total, average
            return current
        holding = Holding(ticker, shares_d, price_d)
        self.holdings[ticker] = holding
        return holding

    def remove(self, ticker: str, shares: object | None = None) -> bool:
        """Sells some or all shares. Returns False if the ticker is not held."""
        ticker = ticker.strip().upper()
        holding = self.holdings.get(ticker)
        if not holding:
            return False
        if shares is None:
            del self.holdings[ticker]
            return True
        amount = to_decimal(shares, "Shares")
        if amount >= holding.shares:
            del self.holdings[ticker]
        else:
            holding.shares -= amount
        return True

    def report(self, prices: PriceBook, now: datetime | None = None) -> Report:
        lines, missing = [], []
        for h in sorted(self.holdings.values(), key=lambda x: x.ticker):
            quote = prices.get(h.ticker)
            if quote is None:
                missing.append(h.ticker)
                continue
            value = h.shares * quote.price
            gain = value - h.invested
            pct = gain / h.invested * 100 if h.invested else Decimal(0)
            lines.append(Line(h.ticker, quote.company, quote.sector, h.shares, h.buy_price, quote.price,
                              money(h.invested), money(value), money(gain), pct.quantize(CENT)))
        invested = sum((l.invested for l in lines), Decimal(0))
        value = sum((l.value for l in lines), Decimal(0))
        sectors: dict[str, Decimal] = {}
        for line in lines:
            line.weight = (line.value / value * 100).quantize(CENT) if value else Decimal(0)
            sectors[line.sector] = sectors.get(line.sector, Decimal(0)) + line.value
        gain = value - invested
        pct = (gain / invested * 100).quantize(CENT) if invested else Decimal(0)
        lines.sort(key=lambda l: l.value, reverse=True)
        return Report(lines, invested, value, gain, pct,
                      dict(sorted(sectors.items(), key=lambda kv: kv[1], reverse=True)),
                      missing, now or datetime.now())

    # ----- holdings file -----
    @classmethod
    def load(cls, path: Path) -> "Portfolio":
        portfolio = cls()
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                portfolio.add(row["ticker"], row["shares"], row["buy_price"])
        return portfolio

    def save(self, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["ticker", "shares", "buy_price"])
            for h in sorted(self.holdings.values(), key=lambda x: x.ticker):
                writer.writerow([h.ticker, normal(h.shares), normal(h.buy_price.quantize(Decimal("0.0001")))])


def normal(value: Decimal) -> str:
    """'15.000' -> '15', '182.5000' -> '182.5'."""
    text = format(value.normalize(), "f")
    return text


SUMMARY_FIELDS = ["ticker", "company", "sector", "shares", "avg_buy_price", "current_price",
                  "invested", "market_value", "gain_loss", "gain_loss_pct", "weight_pct"]


def write_summary(report: Report, path: Path) -> None:
    """Writes portfolio_summary.csv: one row per holding, then a TOTAL row."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(SUMMARY_FIELDS)
        for l in report.lines:
            writer.writerow([l.ticker, l.company, l.sector, normal(l.shares), money(l.buy_price), money(l.price),
                             l.invested, l.value, l.gain, l.gain_pct, l.weight])
        writer.writerow(["TOTAL", f"{len(report.lines)} holdings", "", "", "", "",
                         money(report.invested), money(report.value), money(report.gain), report.gain_pct, "100.00"])
        writer.writerow([])
        writer.writerow(["generated_at", report.created.strftime("%Y-%m-%d %H:%M:%S")])


HISTORY_FIELDS = ["timestamp", "holdings", "invested", "market_value", "gain_loss", "gain_loss_pct"]


def append_history(report: Report, path: Path) -> None:
    """Adds one line per run to portfolio_history.csv so performance can be followed over time."""
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(HISTORY_FIELDS)
        writer.writerow([report.created.strftime("%Y-%m-%d %H:%M:%S"), len(report.lines),
                         money(report.invested), money(report.value), money(report.gain), report.gain_pct])


def read_history(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def live_price_book(tickers: list[str], fallback: PriceBook) -> PriceBook:
    """Optional: real prices with the yfinance package. Falls back to the sample prices if offline."""
    try:
        import yfinance  # type: ignore
    except ImportError:
        return fallback
    quotes = dict(fallback.quotes)
    for ticker in tickers:
        try:
            price = yfinance.Ticker(ticker.replace(".", "-")).fast_info["last_price"]
            base = fallback.get(ticker)
            quotes[ticker] = Quote(ticker, base.company if base else ticker, base.sector if base else "Other",
                                   to_decimal(round(price, 2), f"price of {ticker}"))
        except Exception:  # network or symbol problem: keep the sample price
            continue
    return PriceBook(quotes, "live prices (yfinance), sample data where unavailable")
