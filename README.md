# Trade Republic Insights
   <img src="brand/icon.png" alt="Trade Republic Insights icon" width="96">

Home Assistant integration that turns your Trade Republic transaction history into sensors for your portfolio, income, bonds, and card spending.

> Unofficial. Not affiliated with, endorsed by, or connected to Trade Republic Bank GmbH.

## What you get

- **Portfolio**: net worth, cash, holdings value and cost, realized and unrealized P&L (FIFO, like the app), total return, and one sensor per open position with dividends.
- **Income**: dividends, interest, bond coupons, Saveback, and taxes, per year.
- **Bonds held to maturity**: coupons received and still due, repayment, profit, and annualized return per bond. Bonds with missed coupons or extreme market yields are flagged.
- **Spending**: card spending per month and year, by category and merchant, and a 12-month average.
- **Dashboard**: a ready-made dashboard with three views in [`dashboards/depot.yaml`](dashboards/depot.yaml).

## Requirements

- Home Assistant 2025.3 or later.
- A Trade Republic transaction export (CSV), and optionally a login for automatic updates through [pytr](https://github.com/pytr-org/pytr).
- For the charts in the dashboard: [apexcharts-card](https://github.com/RomRider/apexcharts-card) from HACS.

## Installation

### HACS

1. In HACS, open the three-dot menu and select **Custom repositories**.
2. Add `https://github.com/Robing98/traderepublic-insights` with the type **Integration**.
3. Search for **Trade Republic Insights**, select **Download**, and restart Home Assistant.

### Manual

1. Copy `custom_components/traderepublic_insights` to `/config/custom_components/`.
2. Restart Home Assistant.

## Setup

1. In the Trade Republic app, export your transactions as CSV (**Account statements > Transaction export**; menu names can differ by app version).
2. Put the file into `/config/trade_republic/`. The newest CSV in that folder is used.
3. Go to **Settings > Devices & services > Add integration** and select **Trade Republic Insights**.
4. Keep the folder `trade_republic`. Select **Also sync automatically via pytr** only if you want live prices and new transactions without exporting again.

### Optional files in the export folder

| File | Columns | Purpose |
|:--|:--|:--|
| `prices.csv` | `symbol,price` | Manual prices in EUR. Bond prices in percent of nominal. Live prices from pytr take precedence. |
| `bonds.csv` | `isin,coupon,maturity,frequency` | Bond terms for the hold-to-maturity view: coupon in percent, maturity as `YYYY-MM-DD`, payments per year. |

Example `bonds.csv`:

```csv
isin,coupon,maturity,frequency
XS1234567890,4.625,2031-04-03,1
```

### Automatic updates with pytr

- pytr uses the unofficial Trade Republic web API. Trade Republic can change or block it at any time.
- Login uses the web login with confirmation in the Trade Republic app, or a code from your authenticator app.
- Your phone number and PIN are stored in the Home Assistant config entry, and session cookies in `/config/.storage/`.
- When the session expires, Home Assistant asks you to log in again. Sensors keep the last known data.
- New transactions are added on top of the newest CSV export. Card payments from pytr have no merchant category.

Refresh interval (default 30 minutes) and pytr timeline interval (default 6 hours) can be changed under **Configure**. The **Refresh and sync** button forces both.

## Sensors

| Sensor | Description |
|:--|:--|
| Net worth | Holdings value plus cash |
| Cash | From Trade Republic with pytr, otherwise calculated from the export |
| Holdings value, Holdings cost | Current value and FIFO cost of open positions |
| Unrealized P&L, Unrealized P&L % | Since purchase |
| Realized P&L, Realized P&L this year | After fees, before tax |
| Total return | Realized + unrealized + income + taxes |
| Income, Income this year, Dividends this year, Taxes this year | Gross income and taxes withheld or refunded |
| Net contributions | Deposits minus withdrawals minus card spending |
| Spending this month, last month, this year, Average spending per month (12 months) | Card spending, refunds netted |
| Bonds profit to maturity, Next bond coupon | Hold-to-maturity view, without doubtful bonds |
| Open positions, Last transaction, Data status | Diagnostics |
| One sensor per position | Value, with shares, buy-in, price source, P&L, and dividends as attributes |

## How the numbers are calculated

- Cost basis uses FIFO, like the Trade Republic app and German tax statements. Buy fees are part of the cost; sell fees reduce proceeds.
- Reverse splits carry the cost basis to the new ISIN. Spin-off shares start with a cost basis of 0, so the parent position can differ slightly from the app.
- Without live or manual prices, positions are valued at their last trade price from the export. The `price_source` attribute shows which price is used.
- Hold-to-maturity figures are gross, before tax, assume the issuer pays in full, and do not reinvest coupons.

## Privacy

- All calculations run locally in Home Assistant. Without pytr, nothing leaves your network.
- Do not share your CSV export or `.storage` files when reporting issues. Anonymize the rows that show the problem.

## Development

```console
$ python -m venv .venv && . .venv/bin/activate
$ pip install -r requirements_test.txt
$ pytest
```

`tests/sample.csv` is synthetic data.

## License

[MIT](LICENSE). This project is not financial advice.
