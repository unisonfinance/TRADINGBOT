# Crypto RBI Trading Bot

An algorithmic trading bot for crypto exchanges using the **Research → Backtest → Incubate** methodology. Supports **100+ exchanges** via ccxt (Binance, Bybit, OKX, Kraken, Bitget, etc.)

## Features

- **3 Trading Strategies**: MACD Histogram, RSI Mean Reversion, CVD (Cumulative Volume Delta)
- **Full Backtesting Engine**: Test strategies against historical data before risking real money
- **Risk Management**: Position sizing, stop-loss, max drawdown limits, daily loss caps
- **Incubation Mode**: Start with $10 trades, scale up only after proven performance
- **Multi-Account Support**: Run multiple bots in parallel on separate accounts
- **100+ Exchanges**: Works with any exchange supported by ccxt

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your exchange API key and secret
```

### 3. Run a Backtest
```bash
python deploy/run_backtest.py --strategy macd
python deploy/run_backtest.py --strategy rsi
python deploy/run_backtest.py --strategy cvd
```

### 4. Launch Bot in Incubation Mode
```bash
python deploy/run_bot.py --strategy macd --symbol BTC/USDT --size 10
python deploy/run_bot.py --strategy rsi --symbol ETH/USDT --size 10
```

### 5. Monitor Performance
```bash
python deploy/run_monitor.py
```

## Project Structure

```
polymarket-rbi-bot/
├── config/           # Settings and multi-account config
├── data/             # Exchange client (ccxt), data download, storage
├── strategies/       # Trading strategies (MACD, RSI, CVD)
├── backtesting/      # Backtest engine and metrics
├── bot/              # Trade execution, risk management, order management
├── incubation/       # Monitoring, scaling, logging
├── deploy/           # Entry points for bot, backtest, monitor
└── tests/            # Unit tests
```

## Strategy Benchmarks (pass/fail criteria)

| Metric          | Minimum |
|-----------------|---------|
| Win Rate        | > 55%   |
| Profit Factor   | > 1.5   |
| Max Drawdown    | < 20%   |
| Sample Trades   | ≥ 100   |

## Supported Exchanges

Any exchange supported by [ccxt](https://github.com/ccxt/ccxt), including:
- **Binance** / Binance US
- **Bybit**
- **OKX**
- **Kraken**
- **Bitget**
- **KuCoin**
- **Gate.io**
- And 100+ more

## Important Notes

- **Start small** — $10 → $25 → $50 → $100 → $250. Never skip incubation.
- **A backtest is not a guarantee** — past performance ≠ future results.
- **Each bot should use its own account** to avoid order conflicts.
- **Use sandbox mode** for testing — set `EXCHANGE_SANDBOX=true` in .env.

## Environment Variables

| Variable                | Description                                        |
|-------------------------|----------------------------------------------------|
| `EXCHANGE_ID`           | Exchange name (binance, bybit, okx, kraken, etc.)  |
| `EXCHANGE_API_KEY`      | API key from your exchange                         |
| `EXCHANGE_API_SECRET`   | API secret from your exchange                      |
| `EXCHANGE_PASSWORD`     | Passphrase (OKX, KuCoin — leave blank otherwise)   |
| `EXCHANGE_SANDBOX`      | `true` for testnet, `false` for live               |
| `DEFAULT_SYMBOL`        | Default trading pair (e.g. `BTC/USDT`)             |
| `DEFAULT_POSITION_SIZE` | Default USD position size                          |
| `QUOTE_CURRENCY`        | Balance currency (USDT, USDC, etc.)                |

## License

Private — for personal use only.
