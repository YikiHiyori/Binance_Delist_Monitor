import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_delist_monitor.matching import (
    detect_keywords,
    extract_explicit_symbols,
    looks_like_supported_futures_delist_title,
    match_announcement,
    match_symbols,
)


class MatchingTests(unittest.TestCase):
    def test_detect_keywords(self):
        result = detect_keywords(
            "Binance Futures Will Delist BTCUSDT Perpetual Contract",
            ["perpetual contract", "futures"],
            ["delist", "will delist"],
        )
        self.assertTrue(result.is_candidate)
        self.assertIn("perpetual contract", result.perpetual_keywords)
        self.assertIn("delist", result.delist_keywords)

    def test_symbol_matching(self):
        symbols = ["BTCUSDT", "ETHUSDT", "SNDKUSDT"]
        text = "Binance Futures Will Delist BTC/USDT and SNDK USDT Perpetual Contracts."
        hits = match_symbols(text, symbols)
        self.assertEqual(hits, ["BTCUSDT", "SNDKUSDT"])

    def test_symbol_matching_exact(self):
        symbols = ["MUUSDT", "SNDKUSDT", "AIUSDT"]
        text = "Binance Futures Will Delist MUUSDT, SNDKUSDT and AIUSDT Perpetual Contracts."
        hits = match_symbols(text, symbols)
        self.assertEqual(hits, ["MUUSDT", "SNDKUSDT", "AIUSDT"])

    def test_explicit_list_extraction(self):
        text = (
            "Binance Futures will close all positions and conduct an automatic settlement the following perpetual contract(s) as below:"
            "2026-04-08 09:00 (UTC): USDⓈ-M OLUSDT, HIPPOUSDT, RLSUSDT and PUFFERUSDT Perpetual Contracts"
            "2026-04-09 09:00 (UTC): COIN-M WIFUSD and WLDUSD Perpetual Contracts"
        )
        self.assertEqual(
            extract_explicit_symbols(text),
            ["OLUSDT", "HIPPOUSDT", "RLSUSDT", "PUFFERUSDT"],
        )

    def test_explicit_symbols_filter_to_contract_universe(self):
        symbols = ["OLUSDT", "HIPPOUSDT"]
        text = "Binance Futures will delist USDⓈ-M OLUSDT, HIPPOUSDT and WIFUSD Perpetual Contracts."
        hits = match_symbols(text, symbols)
        self.assertEqual(hits, ["OLUSDT", "HIPPOUSDT"])

    def test_margin_notice_does_not_match_chinese_symbols_from_usdt_text(self):
        symbols = ["币安人生USDT", "我踏马来了USDT", "龙虾USDT", "AIUSDT"]
        text = (
            "Binance Margin And Binance Loans Will Delist AEUR and AI on 2026-05-22. "
            "Please Note: For futures perpetual contracts, please refer to the relevant futures announcements. "
            "Any remaining collateral assets will be sold for USDT after the delisting is completed."
        )
        self.assertEqual(extract_explicit_symbols(text), [])
        self.assertEqual(match_symbols(text, symbols), [])

    def test_non_futures_title_is_rejected_even_if_body_mentions_futures(self):
        title = "Binance Margin And Binance Loans Will Delist AEUR and AI on 2026-05-22"
        text = (
            title
            + "\nPlease Note: For futures perpetual contracts, please refer to the relevant futures announcements."
        )
        result = match_announcement(
            text,
            ["perpetual contract", "perpetual", "futures"],
            ["delist", "will delist", "remove"],
            ["AIUSDT"],
            title=title,
        )
        self.assertFalse(result.is_candidate)
        self.assertEqual(result.symbols, [])

    def test_supported_title_gate_is_strict(self):
        self.assertTrue(
            looks_like_supported_futures_delist_title(
                "Binance Futures Will Delist USDⓈ-M Multiple Perpetual Contracts (2026-04-28)"
            )
        )
        self.assertFalse(
            looks_like_supported_futures_delist_title(
                "Binance Margin And Loan Will Delist BAR, PIVX, XVG on 2026-04-17"
            )
        )


if __name__ == "__main__":
    unittest.main()
