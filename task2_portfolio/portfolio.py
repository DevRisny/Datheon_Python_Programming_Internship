#!/usr/bin/env python3
"""
Stock Portfolio Performance Tracker.

Enter the stocks you own (ticker, buy price, number of shares). The tracker values them at the
current price, shows the gain or loss of every holding and of the whole portfolio, and saves
the result to portfolio_summary.csv. Each run is also logged to portfolio_history.csv.

    python portfolio.py              # interactive menu
    python portfolio.py --demo       # sample portfolio: print the report and write the CSV files
    python portfolio.py --live       # use real prices if the optional 'yfinance' package is installed

Datheon Python Programming Internship · Task 2 · J. Risny Suha
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

import term
from portfolio_core import (PriceBook, Portfolio, Report, append_history, live_price_book, normal,
                            read_history, write_summary)
from term import style

HERE = Path(__file__).resolve().parent
PRICES = HERE / "data" / "market_prices.csv"
SAMPLE = HERE / "data" / "sample_holdings.csv"


class Quit(Exception):
    pass


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise Quit from None


def usd(value: Decimal, sign: bool = False) -> str:
    text = f"${abs(value):,.2f}"
    if sign:
        return ("+" if value >= 0 else "−") + text
    return ("−" if value < 0 else "") + text


def pct(value: Decimal) -> str:
    return f"{'+' if value >= 0 else '−'}{abs(value):.2f}%"


def colored(value: Decimal, text: str) -> str:
    return style(text, "green" if value > 0 else "red" if value < 0 else "grey")


def render(report: Report, source: str) -> str:
    out = [term.rule("PORTFOLIO PERFORMANCE"), ""]
    if not report.lines:
        out.append(style("  No holdings yet. Choose 1 to add your first stock.", "yellow"))
        return "\n".join(out)

    rows = []
    for l in report.lines:
        arrow = "▲" if l.gain > 0 else "▼" if l.gain < 0 else "•"
        rows.append([style(l.ticker, "bold"), l.company[:24], normal(l.shares), usd(l.buy_price), usd(l.price),
                     usd(l.invested), usd(l.value), colored(l.gain, usd(l.gain, sign=True)),
                     colored(l.gain, f"{arrow} {pct(l.gain_pct)}")])
    out.append(term.table(["Ticker", "Company", "Shares", "Avg cost", "Price", "Invested", "Value", "Gain/Loss", "Return"],
                          rows, "<<>>>>>>>"))
    out.append("")

    total_color = "green" if report.gain >= 0 else "red"
    summary = [
        f"Invested capital   {style(usd(report.invested), 'bold')}",
        f"Market value       {style(usd(report.value), 'bold')}",
        f"Total gain / loss  {style(usd(report.gain, sign=True) + '  (' + pct(report.gain_pct) + ')', 'bold', total_color)}",
    ]
    if report.best and report.worst and len(report.lines) > 1:
        summary += ["",
                    f"Best performer     {style(report.best.ticker, 'bold')} {colored(report.best.gain_pct, pct(report.best.gain_pct))}",
                    f"Worst performer    {style(report.worst.ticker, 'bold')} {colored(report.worst.gain_pct, pct(report.worst.gain_pct))}"]
    out.append(term.box(summary, title="Summary", color=total_color))
    out.append("")

    out.append(style("  Allocation by holding", "bold"))
    for l in report.lines:
        out.append(f"  {l.ticker:<6} {term.bar(float(l.weight) / 100, 30, 'blue')} {l.weight:>6.2f}%")
    out.append("")
    out.append(style("  Allocation by sector", "bold"))
    for sector, value in report.by_sector.items():
        share = value / report.value * 100 if report.value else Decimal(0)
        out.append(f"  {sector[:22]:<22} {term.bar(float(share) / 100, 22, 'teal')} {share:>6.2f}%")
    if report.missing:
        out.append("")
        out.append(style(f"  No price found for: {', '.join(report.missing)} (left out of the totals)", "yellow"))
    out.append("")
    out.append(style(f"  Prices: {source}  ·  {report.created:%d %b %Y, %H:%M}", "grey"))
    return "\n".join(out)


def save_outputs(report: Report, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary, history = out_dir / "portfolio_summary.csv", out_dir / "portfolio_history.csv"
    write_summary(report, summary)
    append_history(report, history)
    return summary, history


def show_history(path: Path) -> None:
    rows = read_history(path)
    if not rows:
        print(style("  No history yet. Save a summary first (option 5).", "yellow"))
        return
    table_rows = [[r["timestamp"], r["holdings"], usd(Decimal(r["invested"])), usd(Decimal(r["market_value"])),
                   colored(Decimal(r["gain_loss"]), usd(Decimal(r["gain_loss"]), sign=True)),
                   colored(Decimal(r["gain_loss_pct"]), pct(Decimal(r["gain_loss_pct"])))] for r in rows[-10:]]
    print(term.table(["When", "Holdings", "Invested", "Value", "Gain/Loss", "Return"], table_rows, "<>>>>>"))


def add_flow(portfolio: Portfolio, prices: PriceBook) -> None:
    ticker = ask(style("  Ticker symbol (e.g. AAPL): ", "cyan")).upper()
    if not ticker:
        return
    if prices.get(ticker) is None:
        hint = prices.suggest(ticker)
        print(style(f"  '{ticker}' is not in the price list." + (f" Did you mean {', '.join(hint)}?" if hint else ""), "yellow"))
        if not ask(style("  Add it anyway? (y/n): ", "cyan")).lower().startswith("y"):
            return
    else:
        q = prices.get(ticker)
        print(style(f"  {q.company} · {q.sector} · now {usd(q.price)}", "grey"))
    try:
        price = ask(style("  Buy price per share ($): ", "cyan"))
        shares = ask(style("  Number of shares: ", "cyan"))
        holding = portfolio.add(ticker, shares, price)
    except ValueError as error:
        print(style(f"  ✘ {error}. Nothing was added.", "red"))
        return
    print(style(f"  ✔ {holding.ticker}: {normal(holding.shares)} shares, average cost {usd(holding.buy_price)}", "green"))


def remove_flow(portfolio: Portfolio) -> None:
    ticker = ask(style("  Ticker to sell or remove: ", "cyan")).upper()
    if ticker not in portfolio.holdings:
        print(style(f"  You do not hold {ticker or 'that'}.", "yellow"))
        return
    amount = ask(style(f"  Shares to sell (Enter = all {normal(portfolio.holdings[ticker].shares)}): ", "cyan"))
    try:
        portfolio.remove(ticker, amount or None)
    except ValueError as error:
        print(style(f"  ✘ {error}", "red"))
        return
    print(style(f"  ✔ Updated {ticker}.", "green"))


MENU = [("1", "Add a stock"), ("2", "Sell / remove a stock"), ("3", "View performance report"),
        ("4", "Load the sample portfolio"), ("5", "Save summary to CSV"), ("6", "View saved history"),
        ("0", "Save and exit")]


def interactive(portfolio: Portfolio, prices: PriceBook, holdings_file: Path, out_dir: Path) -> None:
    print(term.box([style("Stock Portfolio Performance Tracker", "bold"),
                    "Track what you own, what it is worth now and how it performed."], color="blue"))
    while True:
        print()
        print("  " + "   ".join(f"{style(k, 'cyan', 'bold')} {label}" for k, label in MENU[:4]))
        print("  " + "   ".join(f"{style(k, 'cyan', 'bold')} {label}" for k, label in MENU[4:]))
        choice = ask(style(f"\n  [{len(portfolio.holdings)} holdings] Choose › ", "cyan", "bold"))
        print()
        if choice == "1":
            add_flow(portfolio, prices)
        elif choice == "2":
            remove_flow(portfolio)
        elif choice == "3":
            print(render(portfolio.report(prices), prices.source))
        elif choice == "4":
            sample = Portfolio.load(SAMPLE)
            portfolio.holdings = sample.holdings
            print(style(f"  ✔ Loaded {len(sample.holdings)} sample holdings. Choose 3 to see the report.", "green"))
        elif choice == "5":
            summary, history = save_outputs(portfolio.report(prices), out_dir)
            print(style(f"  ✔ Saved {summary.name} and added a line to {history.name} in {out_dir}", "green"))
        elif choice == "6":
            show_history(out_dir / "portfolio_history.csv")
        elif choice in {"0", "q", "quit", "exit"}:
            break
        else:
            print(style("  Please choose one of the numbers above.", "yellow"))
    portfolio.save(holdings_file)
    print(style(f"  Holdings saved to {holdings_file.name}. See you next time! 📈", "blue"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track a stock portfolio's value and gain/loss.")
    parser.add_argument("--demo", action="store_true", help="value the sample portfolio and write the CSV files")
    parser.add_argument("--holdings", type=Path, default=HERE / "my_portfolio.csv", help="your holdings CSV")
    parser.add_argument("--prices", type=Path, default=PRICES, help="price list CSV (ticker,company,sector,price)")
    parser.add_argument("--out", type=Path, default=HERE, help="folder for portfolio_summary.csv and the history log")
    parser.add_argument("--live", action="store_true", help="fetch real prices with yfinance if it is installed")
    parser.add_argument("--no-color", action="store_true", help="plain text output")
    args = parser.parse_args(argv)
    if args.no_color:
        term.set_color(False)

    try:
        prices = PriceBook.from_csv(args.prices)
    except (OSError, ValueError, KeyError) as error:
        print(style(f"Could not read the price list: {error}", "red"))
        return 1

    if args.demo:
        portfolio = Portfolio.load(SAMPLE)
    elif args.holdings.exists():
        try:
            portfolio = Portfolio.load(args.holdings)
        except (ValueError, KeyError) as error:
            print(style(f"Could not read {args.holdings.name}: {error}", "red"))
            return 1
    else:
        portfolio = Portfolio()

    if args.live:
        prices = live_price_book(list(portfolio.holdings), prices)

    if args.demo:
        report = portfolio.report(prices)
        print(render(report, prices.source))
        summary, history = save_outputs(report, args.out)
        print(style(f"\n  ✔ Wrote {summary.name} and updated {history.name}", "green"))
        return 0

    try:
        interactive(portfolio, prices, args.holdings, args.out)
    except Quit:
        portfolio.save(args.holdings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
