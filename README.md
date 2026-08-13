# Binance Perpetual Delisting Announcement Monitor

This is a locally run Binance announcement monitor and trade execution project. The current version keeps the existing monitoring pipeline and restructures the trading side around these rules:

- Supports only `USD-M Futures`
- Uses real-time Binance account equity when a signal triggers
- Maintains two local capital pools: `A=60% / B=40%`
- Uses `cross margin` and `1x` leverage
- Takes profit only at `45%`
- Otherwise holds until the exchange-side position disappears, then reconciles locally
- Prefers Binance API `deliveryDate` for contract delisting time
- After exchange-side settlement, prefers income history for final realized PnL
- Uses structured logs and SQLite persistence

The default configuration is safe and does not place real orders.

## Current Scope

- Announcement list fetching, detail fetching, keyword checks, symbol matching, and deduplication keep the original structure.
- If an announcement detail page is temporarily unavailable, the monitor delays and retries delisting candidates instead of marking them as processed immediately.
- Trading logic supports only `USD-M`; it does not load or trade `COIN-M` contracts.
- `TOTAL_CAPITAL` is now only a seed value for the local account snapshot in `mock / paper` mode.
- In `testnet / live` modes, strategy capital is based on Binance `USD-M` account `/fapi/v3/account.totalMarginBalance`.
- Delisting time is based on Binance `USD-M` `/fapi/v1/exchangeInfo.symbols[].deliveryDate`.
- Final realized PnL after exchange-side settlement is read first from Binance `USD-M` `/fapi/v1/income`.

## Runtime Flow

The program works in this order:

1. Fetch the Binance announcement list.
2. Filter announcements that have already been processed.
3. Fetch announcement details. If a delisting candidate has missing details, delay and retry it.
4. Check whether the text matches both perpetual-related and delisting-related keywords.
5. Extract mentioned `USD-M` contract symbols from the detail text.
6. Read the Binance account capital snapshot.
7. If both pools A and B are idle, recalculate local pools using `60% / 40%`.
8. Prefer pool A. Use pool B when A is occupied. Skip the signal when both pools are busy.
9. Generate an order plan with a `20%` per-contract cap.
10. Read each contract `deliveryDate` from Binance `USD-M /fapi/v1/exchangeInfo`.
11. Open shorts through `mock / dry-run` or the Binance client.
12. Poll real position state every `PRICE_POLL_INTERVAL_SECONDS`.
13. Actively take profit when return reaches `45%`.
14. If take profit does not trigger, wait for the exchange to close the position due to delisting, then reconcile locally.
15. After the position disappears, query `/fapi/v1/income` first for final realized PnL. If the delisting is confirmed but income history is not visible yet, keep waiting for the next reconciliation cycle instead of falling back to `entry_price`.
16. Release the pool after all positions for a signal are closed.

## Repository Layout

- `main.py` startup entry point
- `src/binance_delist_monitor/config.py` configuration loading
- `src/binance_delist_monitor/announcements.py` announcement fetching
- `src/binance_delist_monitor/contracts.py` `USD-M` contract universe fetching
- `src/binance_delist_monitor/matching.py` keyword and symbol matching
- `src/binance_delist_monitor/state.py` announcement deduplication state
- `src/binance_delist_monitor/trade_orchestrator.py` trade orchestration
- `src/binance_delist_monitor/capital_allocator.py` capital pool management
- `src/binance_delist_monitor/signal_planner.py` signal-to-order planning
- `src/binance_delist_monitor/exchange_client.py` mock and Binance clients
- `src/binance_delist_monitor/execution_engine.py` open and close execution
- `src/binance_delist_monitor/position_store.py` SQLite persistence
- `src/binance_delist_monitor/position_monitor.py` position reconciliation and TP polling
- `src/binance_delist_monitor/signal_lifecycle.py` announcement lifecycle handling
- `src/binance_delist_monitor/structured_logger.py` structured logging
- `tests/` unit tests

## Installation

Create a virtual environment first:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Configuration

Copy [`.env.example`](.env.example) to `.env`, then edit as needed.

### Safe Defaults

- `DRY_RUN=true`
- `LIVE_TRADING_ENABLED=false`
- `EXCHANGE_MODE=mock`
- `LEVERAGE=1`
- `TOTAL_CAPITAL=1000`
- `TAKE_PROFIT_PCT=0.45`
- `ENABLE_TAKE_PROFIT=true`
- `ENABLE_STOP_LOSS=false`
- `PRICE_POLL_INTERVAL_SECONDS=5`
- `ALLOW_SIGNAL_QUEUE=false`

### Common Settings

- `POLL_INTERVAL_SECONDS` announcement polling interval
- `HEARTBEAT_INTERVAL_SECONDS` heartbeat interval
- `MATCH_KEYWORDS_PERPETUAL` perpetual keywords
- `MATCH_KEYWORDS_DELIST` delisting keywords
- `CONTRACT_CACHE_TTL_SECONDS` contract universe cache TTL
- `STATE_FILE` announcement deduplication state file
- `TRADING_DB_FILE` trading state database
- `LOG_FILE` log file

### Important Notes

- `TOTAL_CAPITAL` is only used as the account snapshot seed in `mock / paper` mode.
- `STOP_LOSS_PCT` remains as a compatibility setting, but the current trading logic does not use local active stop loss.
- Live and testnet modes use `totalMarginBalance` as the capital baseline. Logs also record `availableBalance`, `totalWalletBalance`, and `totalUnrealizedProfit`.
- Delisting time is preferably read from `exchangeInfo.deliveryDate`. Falling back to announcement text parsing is only worth considering when the Binance API is unavailable.
- After the exchange automatically closes a position, local reconciliation first checks `income history` for final realized PnL. If the delisting is confirmed but income history is not visible yet, local reconciliation keeps waiting and does not synthesize a settlement price from `entry_price`.

## Running

Single scan:

```powershell
.\.venv\Scripts\python main.py --once
```

Continuous polling:

```powershell
.\.venv\Scripts\python main.py
```

Testnet smoke test:

```powershell
.\.venv\Scripts\python main.py --testnet-smoke --smoke-symbol BTCUSDT
```

This mode covers:

1. Testnet price lookup
2. Signal creation
3. Order placement
4. Position scan
5. Manual close
6. Lifecycle cleanup and capital pool release

With the default configuration, the program runs the full trading flow in `mock / dry-run` mode and does not send real trading requests.

## Verification

### 1. Unit Tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

### 2. Manual Log Review

- Terminal output
- `logs/monitor.log`
- `state/state.json`
- `state/trading.sqlite3`

### 3. Mock End-to-End Flow

With the default `EXCHANGE_MODE=mock`, when a valid announcement is matched, the monitor will:

- Read the local mock account snapshot
- Calculate the `60/40` dual-pool allocation
- Apply the `20%` cap to each contract
- Open mock short positions
- Poll real local position state
- Trigger the `45%` TP or simulate exchange-side position disappearance
- Complete lifecycle cleanup and release the pool

## Trading Safety Gate

The project has two safety gates. The real-order branch is allowed only when both conditions are true:

- `DRY_RUN=false`
- `LIVE_TRADING_ENABLED=true`

If these switches are not explicitly enabled, the code uses `mock / paper` logic or rejects the real trading client.

## Switching To Testnet Or Live

### testnet

Set:

- `EXCHANGE_MODE=testnet`
- `DRY_RUN=false`
- `LIVE_TRADING_ENABLED=true`
- Binance `USD-M Futures testnet` `BINANCE_API_KEY` / `BINANCE_API_SECRET`

This switches the client to Binance `USD-M Futures` testnet REST and does not touch live funds. Start with `--once` or `--testnet-smoke` for validation.

Notes:

- Using live keys against testnet usually returns `-2015 Invalid API-key, IP, or permissions for action` on signed account endpoints.
- If `ticker/price` works but `/fapi/v3/account` does not, first check that you are using testnet-specific keys and that testnet account permissions are enabled.

### live

After testnet validation, set:

- `EXCHANGE_MODE=live`
- Keep `DRY_RUN=false`
- Keep `LIVE_TRADING_ENABLED=true`

The client then switches to Binance `USD-M Futures` live REST. The safety gates remain active:

- No `DRY_RUN=false`, no order placement
- No `LIVE_TRADING_ENABLED=true`, no order placement
- No `BINANCE_API_KEY` / `BINANCE_API_SECRET`, no order placement

In live and testnet modes, every new signal first reads `/fapi/v3/account` and records the account capital snapshot. Pools are recalculated from `totalMarginBalance` only when both A and B are idle.

## Reserved But Not Expanded Yet

- Webhook alerts
- More complex position management strategies

## Future Live Trading Setup

To connect real trading later:

1. Fill in API key and secret.
2. Set `DRY_RUN=false`.
3. Set `LIVE_TRADING_ENABLED=true`.
4. Validate first with `EXCHANGE_MODE=testnet`.
5. Switch to `EXCHANGE_MODE=live`.

Trading-related entry points are concentrated in:

- `src/binance_delist_monitor/trade_orchestrator.py`
- `src/binance_delist_monitor/execution_engine.py`
- `src/binance_delist_monitor/exchange_client.py`
