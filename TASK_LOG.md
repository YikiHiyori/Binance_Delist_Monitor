# Task Log

Concise record of notable work, failures, validations, and durable lessons.
Use one entry per task or task bundle. Keep one-off observations here instead of promoting them to `LESSONS.md`.

## 2026-04-17

Task summary: Created the reusable execution framework for this repository.
Subagents used: none. This was a single-agent setup task.
Mistakes made: none observed during the setup itself.
Validations performed: inspected the repo root, confirmed existing `WORKFLOW.md`, created the requested framework files, and reviewed the resulting file set.
Deliverables changed: `agents.md`, `WORKFLOW.md`, `LESSONS.md`, `TASK_LOG.md`, `templates/postmortem_template.md`, `templates/task_plan_template.md`, `templates/review_checklist.md`.
Durable lesson promoted: yes. Initial reusable lessons were added to `LESSONS.md`.

## 2026-04-17

Task summary: Incorporated explicit enforcement rules into the framework.
Subagents used: none.
Mistakes made: none observed.
Validations performed: checked that the framework files already existed, updated the operating docs to include the new rules, and kept the changes scoped to framework content.
Deliverables changed: `agents.md`, `WORKFLOW.md`, `LESSONS.md`, `TASK_LOG.md`.
Durable lesson promoted: no. This entry records a framework maintenance update, not a new reusable lesson.

## 2026-04-21

Task summary: Refactored the trading side to use dynamic USD-M account capital, 60/40 dual pools, 20% per-symbol cap, 45% TP only, and exchange-state-based position reconciliation.
Subagents used: none.
Mistakes made: initial tests reused logger names without closing handlers soon enough for Windows temp directory cleanup; the fix was to close existing logger handlers before reinitializing and to make tests close orchestrators explicitly.
Validations performed: ran `python -m unittest tests.test_exchange_client tests.test_matching -v`, then `python -m unittest tests.test_trading tests.test_exchange_client tests.test_matching tests.test_runner -v`.
Deliverables changed: `README.md`, `.env.example`, `src/binance_delist_monitor/capital_allocator.py`, `src/binance_delist_monitor/config.py`, `src/binance_delist_monitor/contracts.py`, `src/binance_delist_monitor/exchange_client.py`, `src/binance_delist_monitor/execution_engine.py`, `src/binance_delist_monitor/matching.py`, `src/binance_delist_monitor/position_monitor.py`, `src/binance_delist_monitor/position_store.py`, `src/binance_delist_monitor/signal_planner.py`, `src/binance_delist_monitor/structured_logger.py`, `src/binance_delist_monitor/trade_executor.py`, `src/binance_delist_monitor/trade_models.py`, `src/binance_delist_monitor/trade_orchestrator.py`, `tests/test_exchange_client.py`, `tests/test_matching.py`, `tests/test_trading.py`, `LESSONS.md`, `TASK_LOG.md`.
Durable lesson promoted: yes. Restart-safe initialization was promoted to `LESSONS.md`.

## 2026-04-21

Task summary: Tightened delist lifecycle handling so the system reads `deliveryDate` from Binance API first and reconciles exchange-side delist closures from income history instead of `entry_price` fallback.
Subagents used: none.
Mistakes made: the first delist reconcile test used a stale 2024 income timestamp, so the new time-window filter correctly excluded it; the test was fixed to emit income near the actual close-detection time.
Validations performed: ran `python -m unittest tests.test_trading.TradeOrchestratorTests.test_exchange_delist_closed_when_symbol_is_no_longer_tradable tests.test_trading.TradeOrchestratorTests.test_delist_reconcile_waits_for_income_history_instead_of_entry_fallback -v`.
Deliverables changed: `README.md`, `src/binance_delist_monitor/exchange_client.py`, `src/binance_delist_monitor/execution_engine.py`, `src/binance_delist_monitor/position_monitor.py`, `src/binance_delist_monitor/position_store.py`, `src/binance_delist_monitor/signal_planner.py`, `src/binance_delist_monitor/trade_models.py`, `src/binance_delist_monitor/trade_orchestrator.py`, `tests/test_exchange_client.py`, `tests/test_trading.py`, `LESSONS.md`, `TASK_LOG.md`.
Durable lesson promoted: yes. API-first exchange metadata usage was promoted to `LESSONS.md`.

## 2026-04-24

Task summary: Ran the next safety layer, a real Binance `USDⓈ-M testnet` smoke attempt with process-local testnet overrides and isolated state/log files.
Subagents used: none.
Mistakes made: the original smoke path logged `signal_id/pool_id` as if it had opened successfully even when `handle_signal()` returned `status=skipped`; the runner was tightened to fail immediately with the upstream status and reason.
Validations performed: confirmed local process overrides forced `EXCHANGE_MODE=testnet`, `DRY_RUN=false`, `LIVE_TRADING_ENABLED=true`, and isolated `LOG_FILE` / `STATE_FILE` / `TRADING_DB_FILE`; ran `python -m unittest tests.test_runner -v`; re-ran the smoke command against Binance testnet and confirmed `ticker/price` succeeded while the first signed account call failed with `-2015 Invalid API-key, IP, or permissions for action`.
Deliverables changed: `README.md`, `src/binance_delist_monitor/runner.py`, `tests/test_runner.py`, `TASK_LOG.md`.
Durable lesson promoted: no. This was a repo-specific validation result and smoke runner refinement.

## 2026-04-27

Task summary: Performed the final pre-live validation pass focused on capital allocation, per-symbol cap enforcement, pool lifecycle behavior, and real Binance `USDⓈ-M testnet` execution.
Subagents used: none.
Mistakes made: none observed in this validation pass.
Validations performed: ran `python -m unittest discover -s tests -v`; ran `python -m unittest tests.test_trading tests.test_runner -v`; then loaded `.env.example` into the current process only, forced `EXCHANGE_MODE=testnet`, `DRY_RUN=false`, and `LIVE_TRADING_ENABLED=true`, and ran `python main.py --testnet-smoke --smoke-symbol BTCUSDT` with isolated log and state files. The smoke run successfully read account capital, computed `60/40` pools from live testnet balance, applied the `20%` single-symbol cap, opened a real testnet short, monitored the open position, manually closed it, and released the pool.
Deliverables changed: `TASK_LOG.md`.
Durable lesson promoted: no. This entry records final validation evidence rather than a broadly reusable lesson.

## 2026-04-29

Task summary: Added delayed retry for detail-unavailable delist candidates so title-only fallback no longer permanently suppresses later body-based symbol extraction, and added coverage around the USDⓈ-M contract universe source.
Subagents used: none.
Mistakes made: none during the fix itself; the root cause investigation confirmed old scans marked delist candidates processed even when both official and mirror article bodies were temporarily unavailable.
Validations performed: ran `python -m unittest tests.test_state tests.test_runner tests.test_contracts tests.test_matching -v`; ran `python -m unittest discover -s tests -v`; then fetched the live Binance `USDⓈ-M /fapi/v1/exchangeInfo` symbol set and confirmed it currently returns `715` symbols including `B3USDT`, `DEGENUSDT`, `BOBUSDT`, `ZKJUSDT`, `IRUSDT`, `DAMUSDT`, `VINEUSDT`, and `AIUSDT`.
Deliverables changed: `README.md`, `src/binance_delist_monitor/runner.py`, `src/binance_delist_monitor/state.py`, `tests/test_contracts.py`, `tests/test_runner.py`, `tests/test_state.py`, `TASK_LOG.md`.
Durable lesson promoted: no. This entry records a repo-specific incident fix and validation trail.
