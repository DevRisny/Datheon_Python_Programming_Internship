import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

import portfolio as app
from portfolio_core import (PriceBook, Portfolio, Quote, append_history, clean_ticker, read_history,
                            to_decimal, write_summary)

DATA = Path(__file__).resolve().parent.parent / "data"
NOW = datetime(2026, 11, 7, 18, 30)


@pytest.fixture
def prices():
    return PriceBook({
        "AAA": Quote("AAA", "Alpha Co", "Tech", Decimal("150")),
        "BBB": Quote("BBB", "Beta Co", "Energy", Decimal("40")),
    })


def test_gain_and_loss_per_holding(prices):
    p = Portfolio()
    p.add("aaa", 10, "100")   # 1,000 -> 1,500  (+50%)
    p.add("BBB", 20, "50")    # 1,000 ->   800  (-20%)
    report = p.report(prices, NOW)
    lines = {l.ticker: l for l in report.lines}
    assert lines["AAA"].gain == Decimal("500.00") and lines["AAA"].gain_pct == Decimal("50.00")
    assert lines["BBB"].gain == Decimal("-200.00") and lines["BBB"].gain_pct == Decimal("-20.00")
    assert report.invested == Decimal("2000.00")
    assert report.value == Decimal("2300.00")
    assert report.gain == Decimal("300.00") and report.gain_pct == Decimal("15.00")
    assert report.best.ticker == "AAA" and report.worst.ticker == "BBB"


def test_weights_add_up_to_100(prices):
    p = Portfolio()
    p.add("AAA", 3, 100)
    p.add("BBB", 7, 30)
    report = p.report(prices, NOW)
    assert sum(l.weight for l in report.lines) == pytest.approx(Decimal("100"), abs=Decimal("0.02"))
    assert set(report.by_sector) == {"Tech", "Energy"}


def test_buying_more_updates_average_cost():
    p = Portfolio()
    p.add("AAA", 10, 100)
    holding = p.add("AAA", 10, 200)
    assert holding.shares == Decimal(20)
    assert holding.buy_price == Decimal(150)


def test_selling_part_and_all():
    p = Portfolio()
    p.add("AAA", 10, 100)
    assert p.remove("AAA", 4)
    assert p.holdings["AAA"].shares == Decimal(6)
    assert p.remove("AAA")
    assert "AAA" not in p.holdings
    assert not p.remove("ZZZ")


def test_money_is_exact():
    p = Portfolio()
    p.add("AAA", "0.1", "0.2")
    assert p.holdings["AAA"].invested == Decimal("0.02")


@pytest.mark.parametrize("bad", ["abc", "-5", "0", "", "nan", "inf"])
def test_bad_numbers_are_rejected(bad):
    with pytest.raises(ValueError):
        to_decimal(bad, "Shares")


def test_numbers_with_commas_and_dollar_sign():
    assert to_decimal("$1,250.50", "Price") == Decimal("1250.50")


@pytest.mark.parametrize("bad", ["", "TOO-LONG-TICKER", "AB CD", "A$"])
def test_bad_tickers_are_rejected(bad):
    with pytest.raises(ValueError):
        clean_ticker(bad)


def test_unknown_ticker_is_reported_not_crashing(prices):
    p = Portfolio()
    p.add("AAA", 1, 100)
    p.add("XYZ", 1, 100)
    report = p.report(prices, NOW)
    assert report.missing == ["XYZ"]
    assert report.invested == Decimal("100.00")


def test_typo_suggestions():
    book = PriceBook.from_csv(DATA / "market_prices.csv")
    assert "AAPL" in book.suggest("APPL")
    assert book.get("msft").company == "Microsoft Corp."


def test_summary_csv(tmp_path, prices):
    p = Portfolio()
    p.add("AAA", 10, 100)
    p.add("BBB", 20, 50)
    path = tmp_path / "portfolio_summary.csv"
    write_summary(p.report(prices, NOW), path)
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert rows[0][:3] == ["ticker", "company", "sector"]
    total = next(r for r in rows if r and r[0] == "TOTAL")
    assert total[6:10] == ["2000.00", "2300.00", "300.00", "15.00"]
    assert rows[-1] == ["generated_at", "2026-11-07 18:30:00"]


def test_history_log_appends(tmp_path, prices):
    p = Portfolio()
    p.add("AAA", 10, 100)
    path = tmp_path / "portfolio_history.csv"
    append_history(p.report(prices, NOW), path)
    append_history(p.report(prices, NOW), path)
    history = read_history(path)
    assert len(history) == 2
    assert history[0]["gain_loss_pct"] == "50.00"


def test_holdings_round_trip(tmp_path):
    p = Portfolio()
    p.add("AAPL", "15", "182.5")
    path = tmp_path / "h.csv"
    p.save(path)
    again = Portfolio.load(path)
    assert again.holdings["AAPL"].shares == Decimal("15")
    assert again.holdings["AAPL"].buy_price == Decimal("182.5")


def test_every_sample_holding_has_a_price():
    book = PriceBook.from_csv(DATA / "market_prices.csv")
    report = Portfolio.load(DATA / "sample_holdings.csv").report(book, NOW)
    assert report.missing == [] and len(report.lines) == 10


def test_demo_writes_both_csv_files(tmp_path, capsys):
    assert app.main(["--demo", "--no-color", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PORTFOLIO PERFORMANCE" in out and "Total gain / loss" in out
    assert (tmp_path / "portfolio_summary.csv").exists()
    assert (tmp_path / "portfolio_history.csv").exists()


def test_interactive_add_view_save(tmp_path, monkeypatch, capsys):
    answers = iter(["1", "APPL", "n", "1", "MSFT", "300", "2", "3", "5", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    holdings = tmp_path / "mine.csv"
    assert app.main(["--no-color", "--holdings", str(holdings), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Did you mean AAPL" in out
    assert "MSFT: 2 shares" in out
    assert (tmp_path / "portfolio_summary.csv").exists()
    assert "MSFT" in holdings.read_text()
