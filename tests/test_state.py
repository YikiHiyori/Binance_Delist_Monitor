import tempfile
import unittest
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_delist_monitor.state import StateStore


class StateTests(unittest.TestCase):
    def test_dedup_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            self.assertFalse(store.is_processed("abc"))
            store.mark_processed("abc")
            store.save()
            store2 = StateStore(path)
            self.assertTrue(store2.is_processed("abc"))

    def test_detail_retry_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = StateStore(path)
            pending = store.mark_detail_retry("abc", base_delay_seconds=30, max_delay_seconds=30)
            self.assertEqual(pending["retry_count"], 1)
            self.assertFalse(store.is_detail_retry_due("abc", now=datetime.utcnow()))
            store.save()

            store2 = StateStore(path)
            self.assertIn("abc", store2.state.pending_details)
            store2.state.pending_details["abc"]["next_retry_at"] = (datetime.utcnow() - timedelta(seconds=1)).isoformat()
            self.assertTrue(store2.is_detail_retry_due("abc"))
            store2.mark_processed("abc")
            self.assertNotIn("abc", store2.state.pending_details)


if __name__ == "__main__":
    unittest.main()
