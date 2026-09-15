# Finance Insights

<img src="brand/icon.png" alt="Finance Insights icon" width="96">

Home Assistant integration that turns your Trade Republic and bank transaction exports into sensors for net worth, portfolio, income, fixed costs, and spending.

> Unofficial. Not affiliated with, endorsed by, or connected to Trade Republic Bank GmbH, the Sparkassen-Finanzgruppe, or any other bank.

## What you get

- **Trade Republic**: net worth, cash, FIFO P&L like the app, one sensor per position with dividends, income, bonds held to maturity, and card spending.
- **Bank accounts** (Sparkasse and other German banks with FinTS): balance, income, salary, spending by group, category, and merchant, detected fixed costs, savings rate, and money moved to your depot.
- **Overview**: net worth, income, spending, and savings rate across all accounts. Transfers between your own accounts don't count as income or spending.
- **Dashboards**: [`dashboards/depot.yaml`](dashboards/depot.yaml) for Trade Republic and [`dashboards/finance.yaml`](dashboards/finance.yaml) for the overview and the bank account.

## Requirements

- Home Assistant 2025.3 or later.
- Transaction exports as CSV. Optional: [pytr](https://github.com/pytr-org/pytr) for Trade Republic and a FinTS product ID for your bank.
- For the charts: [apexcharts-card](https://github.com/RomRider/apexcharts-card) from HACS.

## Installation

### HACS

1. In HACS, open the three-dot menu and select **Custom repositories**.
2. Add `https://github.com/Robing98/finance-insights` with the type **Integration**.
3. Search for **Finance Insights**, select **Download**, and restart Home Assistant.

### Manual

1. Copy `custom_components/finance_insights` to `/config/custom_components/`.
2. Restart Home Assistant.

### Upgrade from Trade Republic Insights

1. Install Finance Insights and restart Home Assistant.
2. Go to **Settings > Devices & services > Add integration**, select **Finance Insights**, then **Import from Trade Republic Insights**.
3. Remove the old `traderepublic_insights` folder from HACS or `/config/custom_components/`, then restart.

The import keeps the folder, the pytr login, the options, and the entity IDs `sensor.trade_republic_*` with their history.

## Setup

Add one entry per account under **Settings > Devices & services > Add integration > Finance Insights**, then optionally the overview.

### Trade Republic

1. In the Trade Republic app, export your transactions as CSV (**Account statements > Transaction export**; menu names can differ by app version).
2. Put the file into `/config/trade_republic/`. The newest CSV in that folder is used.
3. Add **Trade Republic account** and keep the folder `trade_republic`. Select **Also sync automatically via pytr** only if you want live prices and new transactions without exporting again.

#### Optional files in the Trade Republic folder

| File | Columns | Purpose |
|:--|:--|:--|
| `prices.csv` | `symbol,price` | Manual prices in EUR. Bond prices in percent of nominal. Live prices from pytr take precedence. |
| `bonds.csv` | `isin,coupon,maturity,frequency` | Bond terms for the hold-to-maturity view: coupon in percent, maturity as `YYYY-MM-DD`, payments per year. |

Example `bonds.csv`:

```csv
isin,coupon,maturity,frequency
XS1234567890,4.625,2031-04-03,1
```

#### Automatic updates with pytr

- pytr uses the unofficial Trade Republic web API. Trade Republic can change or block it at any time.
- Login uses the web login with confirmation in the Trade Republic app, or a code from your authenticator app.
- Your phone number and PIN are stored in the Home Assistant config entry, and session cookies in `/config/.storage/`.
- When the session expires, Home Assistant asks you to log in again. Sensors keep the last known data.
- New transactions are added on top of the newest CSV export. Card payments from pytr have no merchant category.

Refresh interval (default 30 minutes) and pytr timeline interval (default 6 hours) can be changed under **Configure**. The **Refresh and sync** button forces both.

### Bank account

1. In online banking, open the account transactions, select the period, and export as **CSV-CAMT V2** (Sparkasse: **Umsätze > Export > CSV-CAMT V2**; other banks with the same format work too).
2. Put the file into `/config/sparkasse/`. All CSV files in the folder are merged, so overlapping exports are fine.
3. Add **Bank account**. The name becomes the entity ID prefix, for example `Sparkasse` gives `sensor.sparkasse_balance`.

#### Optional files in the bank folder

| File | Columns | Purpose |
|:--|:--|:--|
| `balance.csv` | `iban,date,balance` | The CSV export has no balance. One known balance per account is enough; later bookings are added to it. With FinTS, the live balance is used. |
| `categories.csv` | `pattern,category` | Your own category rules, checked before the built-in ones. `pattern` is a case-insensitive regular expression. |

Both files accept commas or semicolons, and German number and date formats.

```csv
iban;date;balance
DE12500500000123456789;15.09.2026;2.500,00
```

#### Automatic updates with FinTS

FinTS (formerly HBCI) is the official German online banking interface. It uses [python-fints](https://github.com/raphaelm/python-fints).

1. Register a free FinTS product ID at the [FinTS product registration](https://www.fints.org/de/hersteller/produktregistrierung). Registration takes a few weeks. The ID is personal: don't share it or put it in public code.
2. Look up the FinTS server URL and bank code (BLZ) of your bank.
3. In the bank account setup, select **Also sync automatically via FinTS**, enter the details, and confirm the login in your TAN app (pushTAN) or with a TAN.

- FinTS loads the balance and the last 85 days. Older history comes from the CSV exports; FinTS only adds bookings newer than the newest CSV row.
- Your login name, PIN, and product ID are stored in the Home Assistant config entry, and the FinTS session in `/config/.storage/finance_insights_fints/`.
- Banks ask for a new confirmation from time to time, often every 90 days. Home Assistant then asks you to log in again, and sensors keep the last known data.
- Every sync is a bank login. The default interval is 6 hours and can be changed under **Configure**.

#### Transfers to your depot

Money you move to Trade Republic is shown as **Invested**, not as spending. A booking counts as a transfer when:

- It matches a Trade Republic deposit or withdrawal with the same amount within 4 days, or
- Its name or purpose contains a keyword from **Configure > Keywords** (default `Trade Republic`), or
- It goes to another of your own accounts in Finance Insights.

## Sensors

### Trade Republic sensors

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

### Bank account sensors

| Sensor | Description |
|:--|:--|
| Balance | Live from FinTS, or from `balance.csv` plus later bookings. Attribute `history` has month-end balances. |
| Income this month, last month, Average income per month (12 months), Last salary | Income without transfers from your own accounts or depot |
| Spending this month, last month, Average spending per month (12 months) | Refunds netted. Attributes with 24 months by group, top categories and merchants, and yearly totals. |
| Fixed costs per month | Recurring payments detected from direct debits and standing orders, converted to a monthly amount |
| Invested (12 months) | Money moved to your depot or other own accounts |
| Savings rate (12 months) | Share of income not spent |
| Last transaction, Data status | Diagnostics |

### Overview sensors

| Sensor | Description |
|:--|:--|
| Net worth, Bank balances, Invested | Across all accounts. Bank accounts without a balance count as 0 and are listed in the attributes. |
| Income this month, Spending this month, averages, Savings rate | Bank and Trade Republic combined, without transfers between them |
| Invested (12 months) | Money moved from bank accounts to the depot |

### How the Trade Republic numbers are calculated

- Cost basis uses FIFO, like the Trade Republic app and German tax statements. Buy fees are part of the cost; sell fees reduce proceeds.
- Reverse splits carry the cost basis to the new ISIN. Spin-off shares start with a cost basis of 0, so the parent position can differ slightly from the app.
- Without live or manual prices, positions are valued at their last trade price from the export. The `price_source` attribute shows which price is used.
- Hold-to-maturity figures are gross, before tax, assume the issuer pays in full, and do not reinvest coupons.

### How bank bookings are classified

- Categories come from built-in rules for common German merchants and payees. For PayPal payments, the merchant from the purpose text is used.
- Salary is detected from `LOHN/GEHALT` and similar booking texts. Other credits count as income, refunds reduce spending.
- Cash withdrawals count as spending in the group **Cash**.
- Pending bookings (`Umsatz vorgemerkt`) are not counted.

## Privacy

- All calculations run locally in Home Assistant. Without pytr or FinTS, nothing leaves your network.
- Do not share your CSV exports or `.storage` files when reporting issues. Anonymize the rows that show the problem.

## Development

```console
$ python -m venv .venv && . .venv/bin/activate
$ pip install -r requirements_test.txt
$ pytest
```

`tests/sample.csv` and `tests/sparkasse_sample.csv` are synthetic data.

## License

[MIT](LICENSE). This project is not financial advice.
