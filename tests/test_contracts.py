import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_delist_monitor.contracts import ContractUniverse


class _FakeHttp:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url):
        return self.payload


class ContractUniverseTests(unittest.TestCase):
    def test_fetch_symbols_filters_to_supported_ascii_perpetual_contracts(self):
        payload = {
            "symbols": [
                {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "status": "TRADING"},
                {"symbol": "ETHUSDC", "contractType": "PERPETUAL", "status": "PENDING_TRADING"},
                {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "status": "TRADING"},
                {"symbol": "龙虾USDT", "contractType": "PERPETUAL", "status": "TRADING"},
                {"symbol": "WIFUSD", "contractType": "CURRENT_QUARTER", "status": "TRADING"},
                {"symbol": "AIUSDT", "contractType": "PERPETUAL", "status": "SETTLING"},
                {"symbol": "", "contractType": "PERPETUAL"},
            ]
        }
        universe = ContractUniverse(_FakeHttp(payload), futures_url="https://fapi.binance.com/fapi/v1/exchangeInfo")

        self.assertEqual(universe.fetch_symbols(), ["BTCUSDT", "ETHUSDC", "AIUSDT"])


if __name__ == "__main__":
    unittest.main()
