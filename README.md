# Finance Insights

<img src="brand/icon.png" alt="Finance Insights icon" width="96">

Home Assistant integration that turns your Trade Republic and bank transaction exports into sensors for net worth, portfolio, income, fixed costs, and spending.

> Unofficial. Not affiliated with, endorsed by, or connected to Trade Republic Bank GmbH, the Sparkassen-Finanzgruppe, or any other bank.

## What you get

- **Trade Republic**: net worth, cash, FIFO P&L like the app, one sensor per position with dividends, income, bonds held to maturity, and card spending.
- **Bank accounts** (Sparkasse and other German banks with FinTS): balance, income, salary, spending by group, category, and merchant, detected fixed costs, savings rate, and money moved to your depot.
- **Dividends**: expected income per year and month, yield and yield on cost, payback, growth, years without a cut, next ex and pay dates, and a comparison with your watchlist, the ECB deposit rate, inflation, your cash interest, and your bonds.
- **Energy and water**: costs per day, month, and year from your meters in Home Assistant, the expected refund or extra payment at the annual bill, a suggested advance payment, the notice deadline for switching, and costs per device.
- **Several people**: accounts belong to Home Assistant users, with overviews per person or household, and a generated dashboard that shows each person their own views.
- **Overview**: net worth, income, spending, and savings rate across all accounts. Transfers between your own accounts don't count as income or spending.
- **Dashboard**: one action builds an overview and detail tabs per person, and keeps the tabs you customize.

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
- It goes to another of your own accounts in Finance Insights, or to a Trade Republic account (BIC `TRBKDEBB`), for example a transfer in your own name, or
- Your bank already marked it as an investment (Sparkasse category **Geldanlage**).

Money coming back from the depot is subtracted, so **Invested** is the net amount.

#### Credits that offset spending

Some credits pay for a specific expense, for example a family contribution to the semester fee. Under **Configure > Credits that offset spending**, add one rule per line:

```text
Semester => Education
Mietanteil => Rent and housing
```

A credit whose payee or purpose contains the text counts as a refund in that category instead of income. The text is matched literally and case-insensitively.

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

- Categories come from your `categories.csv`, then built-in rules for common German merchants and payees, then the category column of the Sparkasse export. For PayPal payments, the shop from the purpose text is used.
- PayPal credits count as refunds. Recurring PayPal payments are detected per shop.
- Averages use the months your exports cover, up to 12. With 3 months of history, the average is over 3 months.
- Salary is detected from `LOHN/GEHALT` and similar booking texts. Other credits count as income, refunds reduce spending.
- Cash withdrawals count as spending in the group **Cash**.
- Pending bookings (`Umsatz vorgemerkt`) are not counted.

## Dividends

The dividend analysis works from your own payments alone. External data adds ex dates, pay dates, long history, and stocks you don't hold yet. Configure it under **Configure** on the Trade Republic entry.

| Setting | What it does |
|:--|:--|
| Dividend data provider | [EODHD](https://eodhd.com) (free key, 20 calls per day, 1 year of history), [Alpha Vantage](https://www.alphavantage.co) (free key, 25 calls per day), or [Finnhub](https://finnhub.io) (plans with dividend data). You create the key on the provider's website. |
| Use Yahoo Finance as fallback | Unofficial endpoints without a key. Adds up to 10 years of history and covers stocks the provider doesn't know. Can stop working at any time. |
| Load ECB interest rate, inflation, and exchange rates | Official [ECB data](https://data.ecb.europa.eu): deposit facility rate, euro area HICP inflation, and reference rates to convert dividends into euros. |
| Compare with my Trade Republic watchlist | Loads the watchlist through pytr and adds those stocks to the comparison. |
| Dividend data refresh interval | Every dividend stock uses one or two calls per refresh. Results are cached, and the integration stops at the provider's daily limit. |

If a provider picks the wrong listing, set the symbol yourself in `symbols.csv` in the Trade Republic folder:

```csv
isin,symbol
CH0038863350,NESN.SW
```

What the numbers mean:

- **Dividend yield**: dividends of the last 12 months per share, in euros, over today's price.
- **Yield on cost**: the same dividends over your average buy-in.
- **Paid back**: dividends received over what you paid for the position. **Payback in**: years until dividends cover the rest at today's rate.
- **Growth p.a.**: average yearly growth of the dividend per share over up to 5 complete years. **Years without cut**: consecutive years in which the dividend did not fall.
- **Real dividend yield**: dividend yield minus euro area inflation.
- **Cash interest rate**: derived from your last Trade Republic interest payment and your average cash balance before it.
- Dates marked **est.** are estimated from the usual rhythm. All amounts are gross, before tax. The **Dividends** tab shows the calendar, tables, and comparisons.

## Energy and water costs

1. Add **Energy and water costs** under **Add integration > Finance Insights**, choose the type, and select the consumption sensor. Sensors from the energy dashboard are suggested.
2. Open the new entry and select **Add contract**: supplier, start, end, price per kWh or m³, base price, monthly advance payment, and optionally bonus and notice period.
3. When you switch supplier, add a new contract that starts on the switch date. Old contracts stay for past costs.

What you get per meter, in the **Running costs** tab next to your fixed costs:

- Cost today, this month, and this year, and cost per month for the last 13 months.
- Billing year from the contract start: cost so far, expected cost, advance payments, and **expected refund** (negative means extra payment), including a bonus.
- **Suggested advance payment** that would bring the bill to about zero.
- **Notice deadline**: contract end minus notice period, as a date for reminders.
- Cost per device for the devices in the energy dashboard.

The forecast uses the same days last year when the meter has a year of history, otherwise the average of the last 30 days. Gas meters that count m³ need the conversion factor from your gas bill (calorific value times z-number). Energy costs are information only and are not added to spending, because the advance payments already appear in your bank account.

## Dashboard

1. Create an empty dashboard under **Settings > Dashboards**, for example `Finances` with the URL `dashboard-finances`.
2. Under **Developer tools > Actions**, run **Finance Insights: Build dashboard** with `dashboard: dashboard-finances`.
   The dashboard texts are in English or German: set **Language**, or leave it empty to use the Home Assistant language.

Every person gets these tabs, combining all of their accounts:

| Tab | Content |
|:--|:--|
| Overview | Personal overview, if one exists with only this person, and the key numbers of each account |
| Portfolio | Value, return, holdings with dividends, and allocation |
| Bonds | Bonds held to maturity |
| Dividends | Calendar, yields, payback, comparison, and benchmarks |
| Spending | Card spending and bank spending by group, category, merchant, and year |
| Running costs | Fixed costs from the bank account, and energy and water costs with annual bill forecast, contracts, and devices |
| Income | Investment income, salary, and other income |
| Charts | Depot history, money in and out, bank balance |
| Data | Sync status, files, and warnings |

Overviews with several people, or without people, get their own tab. Tabs without content are left out.

**Customizing**: change the dashboard as you like. When accounts change, the integration updates only the tabs you haven't touched:

- Tabs you changed stay as they are.
- Tabs you added yourself are kept.
- Tabs you deleted don't come back.

To get the original tabs back, run the action again with **Restore generated tabs** switched on. Your own tabs are kept.

## Several people in one Home Assistant

1. Add one Trade Republic entry per account, each with its own name and folder, for example `Trade Republic Anna` in `trade_republic_anna`. Entity IDs follow the name: `sensor.trade_republic_anna_net_worth`. The first account with the default name keeps `sensor.trade_republic_*`.
2. Every account belongs to the user who added it. Change it under **Configure > Owner**, and share it under **Also visible to**.
3. Add overviews under **Overview across all accounts** with a name and **People**: one per person, and one for a couple or household. An overview without people includes all accounts.
4. Build the dashboard as described in [Dashboard](#dashboard).

Transfers are matched only between accounts of the same owner.

> **Not a security boundary**: Home Assistant has no per-user permissions for entities. Hidden views only tidy up the dashboard. Every user can still read all sensors, for example through the history or the API, and administrators can see stored PINs. Use it within a household that trusts each other.

Child savings accounts (Frühstart-Rente) are not supported yet: pytr can't read them ([pytr issue #228](https://github.com/pytr-org/pytr/issues/228)).

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
