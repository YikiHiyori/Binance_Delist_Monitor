import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_delist_monitor.exchange_client import BinanceFuturesClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if url.endswith("/fapi/v1/ticker/price"):
            return _FakeResponse({"symbol": "BTCUSDT", "price": "123.45"})
        if url.endswith("/fapi/v3/account"):
            return _FakeResponse(
                {
                    "availableBalance": "1800.0",
                    "totalMarginBalance": "1900.0",
                    "totalWalletBalance": "2000.0",
                    "totalUnrealizedProfit": "-100.0",
                }
            )
        if url.endswith("/fapi/v1/exchangeInfo"):
            return _FakeResponse(
                {
                    "timezone": "UTC",
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "status": "TRADING",
                            "deliveryDate": 1767225600000,
                            "filters": [
                                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                                {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                            ],
                        }
                    ],
                }
            )
        if url.endswith("/fapi/v1/income"):
            return _FakeResponse(
                [
                    {
                        "symbol": "BTCUSDT",
                        "incomeType": "REALIZED_PNL",
                        "income": "12.50",
                        "asset": "USDT",
                        "info": "REALIZED_PNL",
                        "time": 1767225600000,
                        "tranId": 1001,
                    },
                    {
                        "symbol": "BTCUSDT",
                        "incomeType": "COMMISSION",
                        "income": "-0.25",
                        "asset": "USDT",
                        "info": "COMMISSION",
                        "time": 1767225601000,
                        "tranId": 1002,
                    },
                ]
            )
        if url.endswith("/fapi/v1/order"):
            return _FakeResponse({"orderId": 123, "status": "FILLED", "executedQty": "0.5", "avgPrice": "123.45"})
        if url.endswith("/fapi/v1/marginType"):
            return _FakeResponse({"code": 200, "msg": "success"})
        if url.endswith("/fapi/v1/leverage"):
            return _FakeResponse({"leverage": 1, "symbol": "BTCUSDT", "maxNotionalValue": "1000000"})
        if url.endswith("/fapi/v1/positionSide/dual"):
            return _FakeResponse({"dualSidePosition": False})
        if url.endswith("/fapi/v3/positionRisk"):
            return _FakeResponse(
                [
                    {
                        "symbol": "BTCUSDT",
                        "positionAmt": "-0.5",
                        "entryPrice": "123.45",
                        "markPrice": "120.00",
                        "unRealizedProfit": "1.725",
                    }
                ]
            )
        return _FakeResponse({})


class BinanceFuturesClientTests(unittest.TestCase):
    def test_testnet_uses_testnet_base_url(self):
        session = _FakeSession()
        client = BinanceFuturesClient(
            api_key="key",
            api_secret="secret",
            live_trading_enabled=True,
            dry_run=False,
            testnet=True,
            session=session,
        )

        price = client.get_price("BTCUSDT")
        self.assertAlmostEqual(price, 123.45)
        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "GET")
        self.assertTrue(url.startswith("https://testnet.binancefuture.com/fapi/v1/ticker/price"))

        snapshot = client.get_account_snapshot()
        self.assertAlmostEqual(snapshot.available_balance, 1800.0)
        self.assertAlmostEqual(snapshot.total_margin_balance, 1900.0)
        self.assertAlmostEqual(client.get_account_balance(), 1900.0)

        order = client.place_short_order("BTCUSDT", 0.5, 123.45)
        self.assertEqual(order.symbol, "BTCUSDT")
        self.assertEqual(order.side, "SHORT")
        self.assertTrue(session.requests[1][1].startswith("https://testnet.binancefuture.com/fapi/v3/account"))
        self.assertTrue(session.requests[2][1].startswith("https://testnet.binancefuture.com/fapi/v1/marginType"))
        self.assertTrue(session.requests[3][1].startswith("https://testnet.binancefuture.com/fapi/v1/leverage"))
        self.assertTrue(session.requests[4][1].startswith("https://testnet.binancefuture.com/fapi/v1/exchangeInfo"))
        self.assertTrue(session.requests[5][1].startswith("https://testnet.binancefuture.com/fapi/v1/positionSide/dual"))
        self.assertTrue(session.requests[6][1].startswith("https://testnet.binancefuture.com/fapi/v1/order"))

    def test_round_quantity_uses_exchange_lot_size(self):
        session = _FakeSession()
        client = BinanceFuturesClient(
            api_key="key",
            api_secret="secret",
            live_trading_enabled=True,
            dry_run=False,
            testnet=True,
            session=session,
        )

        self.assertAlmostEqual(client.round_quantity("BTCUSDT", 0.00625), 0.006)

    def test_get_position_handles_list_response(self):
        session = _FakeSession()
        client = BinanceFuturesClient(
            api_key="key",
            api_secret="secret",
            live_trading_enabled=True,
            dry_run=False,
            testnet=True,
            session=session,
        )

        position = client.get_position("BTCUSDT")
        self.assertIsNotNone(position)
        self.assertEqual(position.side, "SHORT")
        self.assertAlmostEqual(position.mark_price, 120.0)

    def test_delivery_time_and_income_history_use_official_endpoints(self):
        session = _FakeSession()
        client = BinanceFuturesClient(
            api_key="key",
            api_secret="secret",
            live_trading_enabled=True,
            dry_run=False,
            testnet=False,
            session=session,
        )

        self.assertEqual(client.get_symbol_delivery_time("BTCUSDT"), 1767225600000)
        income = client.get_income_history("BTCUSDT", start_time_ms=1767220000000, end_time_ms=1767230000000)

        self.assertEqual(len(income), 2)
        self.assertAlmostEqual(sum(item.income for item in income), 12.25)
        self.assertTrue(any(request[1].startswith("https://fapi.binance.com/fapi/v1/income") for request in session.requests))

    def test_live_mode_uses_live_base_url(self):
        session = _FakeSession()
        client = BinanceFuturesClient(
            api_key="key",
            api_secret="secret",
            live_trading_enabled=True,
            dry_run=False,
            testnet=False,
            session=session,
        )

        price = client.get_price("BTCUSDT")
        self.assertAlmostEqual(price, 123.45)
        self.assertTrue(session.requests[0][1].startswith("https://fapi.binance.com/fapi/v1/ticker/price"))

        snapshot = client.get_account_snapshot()
        self.assertAlmostEqual(snapshot.total_wallet_balance, 2000.0)
        self.assertAlmostEqual(client.get_account_balance(), 1900.0)

        order = client.place_short_order("BTCUSDT", 0.5, 123.45)
        self.assertEqual(order.side, "SHORT")
        self.assertTrue(session.requests[1][1].startswith("https://fapi.binance.com/fapi/v3/account"))
        self.assertTrue(session.requests[2][1].startswith("https://fapi.binance.com/fapi/v1/marginType"))
        self.assertTrue(session.requests[3][1].startswith("https://fapi.binance.com/fapi/v1/leverage"))
        self.assertTrue(session.requests[4][1].startswith("https://fapi.binance.com/fapi/v1/exchangeInfo"))
        self.assertTrue(session.requests[5][1].startswith("https://fapi.binance.com/fapi/v1/positionSide/dual"))
        self.assertTrue(session.requests[6][1].startswith("https://fapi.binance.com/fapi/v1/order"))
        self.assertIsNotNone(client.get_position("BTCUSDT"))


if __name__ == "__main__":
    unittest.main()
