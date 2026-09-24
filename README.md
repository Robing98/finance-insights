# Finance Insights

<img src="custom_components/finance_insights/brand/icon.png" alt="Finance Insights icon" width="96">

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/robinlabs)

Home Assistant integration that turns your Trade Republic and bank transaction exports into sensors for net worth, portfolio, income, fixed costs, and spending.

> Unofficial. Not affiliated with, endorsed by, or connected to Trade Republic Bank GmbH, the Sparkassen-Finanzgruppe, or any other bank.

## What you get

- **Trade Republic**: net worth, cash, FIFO P&L like the app, one sensor per position with dividends, income, bonds held to maturity, and card spending.
- **Bank accounts** (Sparkasse and other German banks with FinTS): balance, income, salary, spending by group, category, and merchant, detected fixed costs, savings rate, and money moved to your depot.
- **Dividends**: expected income per year and month, yield and yield on cost, payback, growth, years without a cut, next ex and pay dates, and a comparison with your watchlist, the ECB deposit rate, inflation, your cash interest, and your bonds.
- **Taxes** (Germany): unused Sparerpauschbetrag, simulated loss pots, positions to sell and buy back before December 31, and estimates for the Günstigerprüfung and the NV-Bescheinigung. Estimates only, not tax advice.
- **Energy and water**: costs per day, month, and year from your meters in Home Assistant, the expected refund or extra payment at the annual bill, a suggested advance payment, the notice deadline for switching, and costs per device.
- **Several people**: accounts belong to Home Assistant users, with overviews per person or household, and a generated dashboard that shows each person their own views.
- **Overview**: net worth, income, spending, and savings rate across all accounts. Transfers between your own accounts don't count as income or spending.
- **Dashboard**: one action builds an overview and detail tabs per person, and keeps the tabs you customize.

## Requirements

- Home Assistant 2025.3 or later.
- Transaction exports as CSV. Optional: [pytr](https://github.com/pytr-org/pytr) for Trade Republic and a FinTS product ID for your bank.

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

### Try the demo first

Select **Try the demo with sample data**. Finance Insights adds a Trade Republic and a Sparkasse account with invented bookings, so you can build the dashboard and look around before you connect anything. The sample files are in `finance_insights_demo` in your config folder, and their dates move up to the current month on every start. To remove the demo, delete both entries and that folder.

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

1. Register a free FinTS product ID at the [FinTS product registration](https://www.fints.org/de/hersteller/produktregistrierung). Registration takes a few weeks, and banks accept a new ID only several working days after the confirmation email. You are the registered contact for your ID, so keep it private. The ID has exactly 25 characters.
2. In the bank account setup, select **Also sync automatically via FinTS**.
3. Search for your bank by name, bank code, or IBAN. The bank code is filled in for you.
4. Enter the FinTS server URL of your bank, usually listed on its online banking help page. If you are a registered FinTS manufacturer yourself, put your FinTS bank list as `fints_banks.csv` into the config folder, and the URL is filled in too. The bank list itself is not included, because it must not be shipped with software.
5. Enter your login details and confirm the login in your TAN app (pushTAN) or with a TAN.

- FinTS loads the balance and the last 85 days. Older history comes from the CSV exports; FinTS only adds bookings newer than the newest CSV row.
- Your login name, PIN, and product ID are stored in the Home Assistant config entry, and the FinTS session in `/config/.storage/finance_insights_fints/`.
- Banks ask for a new confirmation from time to time, often every 90 days. Home Assistant then asks you to log in again, and sensors keep the last known data.
- Every sync is a bank login. The default interval is 6 hours and can be changed under **Configure**.
- If the bank rejects the login, the setup form shows the bank's own message, for example `9010` with a reason. Most common causes: a wrong FinTS server URL for your bank code, a product ID that the banks don't know yet, or wrong login details.

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
| Lowest balance, next 30 days; Balance in 30 days | Cash flow forecast from fixed costs, savings plans, salary, scheduled bookings, and the average other spending of the last 90 days. Attributes `series` (per day) and `items` (expected bookings). |
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

## Automations

Finance Insights fires events you can use in automations:

| Event | When | Data |
|---|---|---|
| `finance_insights_transaction` | A new booking arrives on a bank or Trade Republic account | `entry_id`, `account`, `owner`, `date`, `amount`, `kind`, `type`, `name`, `category`, and `purpose` for bank bookings |
| `finance_insights_new_recurring` | A new recurring payment shows up on a bank account | `entry_id`, `account`, `name`, `category`, `cadence`, `amount`, `monthly`, `next_date` |

Bookings older than 45 days never fire, and adding an account fires nothing for its existing history.

Blueprints for common automations:

| Blueprint | Import |
|---|---|
| New booking, with filters for account, direction, and amount | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRobing98%2Ffinance-insights%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffinance_insights%2Fnew_booking.yaml) |
| Salary received | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRobing98%2Ffinance-insights%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffinance_insights%2Fsalary.yaml) |
| New subscription or fixed cost | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRobing98%2Ffinance-insights%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffinance_insights%2Fnew_subscription.yaml) |
| Low balance, now or in the next 30 days | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRobing98%2Ffinance-insights%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffinance_insights%2Flow_balance.yaml) |
| Unused tax allowance in December | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FRobing98%2Ffinance-insights%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffinance_insights%2Ftax_allowance.yaml) |

## Taxes

For people taxed in Germany. The **Taxes** tab and three sensors per Trade Republic account estimate the capital gains tax of the current year from your exports:

| Sensor | Meaning |
|---|---|
| Tax allowance left | Unused part of your Freistellungsauftrag at Trade Republic, after dividends and interest still expected this year. Attributes hold everything the tab shows. |
| Expected capital gains tax | Flat tax (Abgeltungsteuer with Soli and church tax) on the rest of the year's taxable capital income. |
| Refund via Günstigerprüfung | What the Günstigerprüfung in the tax return would save. Only filled when you enter your other taxable income. |

The tab shows:

- **Tips** that apply to you: unused allowance before December 31, the NV-Bescheinigung and the Günstigerprüfung for low incomes, the stock loss pot, the loss certificate deadline on December 15, the Vorabpauschale, and crypto holding periods and limits.
- **Sell and buy back**: how many shares of which position realize the unused allowance, oldest purchases first like Trade Republic. Gains realized this way stay tax free for good. Selling and buying back on the same day is not an abuse of law (BFH, IX R 60/07).
- **Positions with losses** and the tax a realized loss would save this year.
- **This year** and previous years: taxable income, tax withheld, and the simulated loss pots.

Set these under **Configure** on the Trade Republic entry:

- **Freistellungsauftrag at Trade Republic**: the amount in the app, 1,000 € by default.
- **Expected taxable income without capital income**: optional. Needed for the Günstigerprüfung and the NV-Bescheinigung. Last year's value is on your tax assessment as "zu versteuerndes Einkommen", minus your capital income.
- **Joint assessment** and **church tax rate**.

Limits of the estimate:

- Trade Republic's tax report and your tax assessment are binding. The loss pots are simulated from the exports and can differ, for example when your history starts after your first trade.
- All ETFs count as equity funds, 30 % of their income is tax free. Saveback, stock perks, and bonuses are not included. Foreign withholding tax is counted as withheld tax.
- Crypto follows the rules for private sales: tax free after one year, and tax free within a year while all such gains stay below 1,000 €.
- The income tax tariff is known up to 2026. Later years use the newest known tariff.

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
| Overview | Personal overview, the overview across all accounts if you are the only person, the key numbers of each account, and the cash flow forecast for the next 30 days |
| Income | Investment income, salary, and other income |
| Spending | Card spending and bank spending by group, category, merchant, and year |
| Running costs | Fixed costs from the bank account, and energy and water costs with annual bill forecast, contracts, and devices |
| Business | Net, VAT, and profit for a business account. Only shown when that option is on |
| Portfolio | Value, return, holdings with dividends, and allocation |
| Dividends | Calendar, yields, payback, comparison, and benchmarks |
| Taxes | Tax tips, unused allowance, sell and buy back, loss pots, and crypto holding periods |
| Bonds | Bonds held to maturity |
| Charts | Depot history, money in and out, bank balance |
| Data | Sync status, files, and warnings |

Every tab uses Finance Insights cards: key figures, charts, tables, and the cash flow forecast. The integration ships and loads them itself, including their fonts, so there is nothing extra to install. apexcharts-card is no longer needed.

### Theme

**Build dashboard** uses the Finance Insights theme by default, so the page, the header, and the cards match in light and dark mode. The action saves the theme as `themes/finance_insights.yaml` in your config folder and reloads themes.

- Home Assistant loads that folder only with `themes: !include_dir_merge_named themes` under `frontend:` in `configuration.yaml`. New installations have this line. Without it, a repair issue shows what to add.
- To keep your own theme, run the action once with **Use the Finance Insights theme** switched off. The choice is remembered.
- The file is overwritten on updates. To change colors, copy it under another name.

Overviews with several people get their own tab. Tabs without content are left out. An account without data, for example a bank account without a CSV export yet, shows a short note instead of its cards.

**Customizing**: change the dashboard as you like. When accounts change, the integration updates only the tabs you haven't touched:

- Tabs you changed stay as they are.
- Tabs you added yourself are kept.
- Tabs you deleted don't come back.

To get the original tabs back, run the action again with **Restore generated tabs** switched on. Your own tabs are kept.

After an update with a new dashboard design, tabs you changed keep their old look. Switch on **Restore generated tabs** once to get the new design on them.

## Business account

For a self-employed person with a separate business account. Switch on **Business account** under **Settings > Devices & services > Finance Insights > Configure**. Nothing changes for any other account.

It adds revenue and expenses net, VAT collected and input VAT, the VAT due per month and per quarter, the profit for the year, and a reserve for income tax. **Kleinunternehmer (§19 UStG)** turns VAT off completely: net equals gross.

### Where the VAT rate comes from

A bank booking has no VAT rate, so yours come from the `vat` column in `categories.csv` in the account folder:

```
pattern,category,vat
HOSTING.*,IT and hosting,19
FAHRKARTE,Travel,7
VERSICHERUNG,Insurance,0
RECHNUNG,Revenue,19
```

A booking no rule matches is not guessed. It is counted under **Without a VAT rate**, with the payees listed, so you can see exactly what is still missing a rule. Set a default rate in the options only if you know that it fits.

### What these figures are not

- **They are estimates from your own rules, not a tax calculation.** Check every number before it goes anywhere near a VAT return.
- **The date is the day the money moved.** That matches Ist-Versteuerung under §20 UStG. On Soll-Versteuerung, where VAT is owed by invoice date, these figures sit in the wrong period.
- **Only for an account used for the business alone.** Private spending on the same account counts as a business expense and makes the profit wrong.
- **Private withdrawals** are left out only while your private account is set up here too, because that is what lets the integration recognise a transfer between your own accounts.
- There is no invoicing, no receivables, and no EÜR or DATEV export.

## History before the integration was installed

Charts read Home Assistant statistics, which begin when the integration starts recording. Your exports reach further back. **Finance Insights: Backfill history** rebuilds the days in between from the exports and writes them as statistics:

| Statistic | Content |
|:--|:--|
| `finance_insights:<account>_broker_cash` | Cash at the broker, per day |
| `finance_insights:<account>_contributions` | Money paid in, minus withdrawals and card spending |
| `finance_insights:<account>_invested_cost` | Holdings at cost |
| `finance_insights:<account>_bank_balance` | Bank balance, per day |

Run it once after an import, or again after adding older exports. Writing the same day twice replaces it, so repeated runs are safe.

The net worth chart draws the money paid in as a second line, so the long history is visible next to the short one.

What is not backfilled is what your holdings were worth on a past day. Exports record the price you paid per trade, not a price per day, so any earlier value would be a guess. Holdings appear at cost instead, in their own series.

## Several people in one Home Assistant

1. Add one Trade Republic entry per account, each with its own name and folder, for example `Trade Republic Anna` in `trade_republic_anna`. Entity IDs follow the name: `sensor.trade_republic_anna_net_worth`. The first account with the default name keeps `sensor.trade_republic_*`.
2. Every account belongs to the user who added it. Change it under **Configure > Owner**, and share it under **Also visible to**.
3. Add overviews under **Overview across all accounts** with a name and **People**: one per person, and one for a couple or household. An overview without people includes all accounts.
4. Build the dashboard as described in [Dashboard](#dashboard).

Transfers are matched only between accounts of the same owner.

> **Not a security boundary**: Home Assistant has no per-user permissions for entities. Hidden views only tidy up the dashboard. Every user can still read all sensors, for example through the history or the API, and administrators can see stored PINs. Use it within a household that trusts each other.

Child savings accounts (Frühstart-Rente) are not supported yet: pytr can't read them ([pytr issue #228](https://github.com/pytr-org/pytr/issues/228)).

## Privacy

All calculations run locally. These are the only connections the integration makes, and each one is off until you switch it on:

| Connection | Switched on by | What is sent |
|:--|:--|:--|
| Your bank's FinTS server | FinTS in the bank account | Login name, PIN, product ID |
| Trade Republic | pytr in the Trade Republic account | Phone number, PIN |
| Yahoo Finance | **Yahoo as a fallback** in the options | The ISINs and ticker symbols you hold |
| eodhd, Alpha Vantage, or Finnhub | **Dividend data** in the options | The same, plus your API key |
| European Central Bank | **Benchmarks** in the options | Nothing about you: exchange rates and index series |

With all of them off, the integration reads your CSV exports and nothing leaves your network. It also installs no third-party package: pytr and python-fints are installed only when you switch those features on, and the manifest requires nothing on its own.

Yahoo and benchmarks were on by default before version 0.10.0. Turn them back on under **Settings > Devices & services > Finance Insights > Configure** if you want dividend data and comparisons.

### Your credentials, and what you are responsible for

**Read this part.** This integration holds the keys to your bank account. The risk is real, it does not go away by reading the code, and keeping your installation safe is your job, not this integration's.

By default the FinTS PIN, the product ID, and the Trade Republic PIN are stored the way every Home Assistant integration stores credentials: in the config entry, unencrypted, in `.storage/core.config_entries`. Encrypting them there would change nothing, because the integration has to read them again after every restart without asking you, so the key would have to sit on the same disk. Anything the integration can decrypt on its own, someone with the same files can decrypt too.

So the honest statement is: **anyone who can read your Home Assistant files can read your banking PIN.** That includes a backup on a NAS, a snapshot in cloud storage, a stolen SD card, another integration you installed, and anyone you hand a `.storage` file to.

**Do not store the PIN.** Under **Settings > Devices & services > Finance Insights > Configure**, switch on **Do not store the PIN**. The PIN then lives in memory only and never reaches the disk. After every restart the account asks for it again through the usual notification, and until you enter it that account does not sync. Everything else, including the CSV import, keeps working. This is the only way to keep a PIN off the disk in a service that reconnects on its own, and the restart cost is the price of it.

What else is on you:

- **Encrypt your backups.** Home Assistant backups contain `.storage`. An unencrypted backup is your banking PIN in a file.
- **Use read-only banking access if your bank offers it.** FinTS with a PIN and a TAN can authorize transfers, not only read them. A separate banking user with read-only rights bounds the worst case instead of trying to prevent it.
- **Never attach `.storage` files or unredacted logs to a bug report.** Use **Download diagnostics** on the integration page instead. It reports which data exists, how much of it, and what failed, with no credentials, no account numbers, and no amounts.
- **Skip pytr if you can.** The CSV import needs no Trade Republic credentials and installs eleven fewer packages.
- **Watch what else you install.** Any integration in your Home Assistant runs with the same access to the same files. This one is only as safe as the least careful thing next to it.
- **Keep Home Assistant updated and off the open internet.** A dashboard reachable from the internet without a reverse proxy, strong authentication, and updates is the most likely way this goes wrong.

### The FinTS product ID

Every user registers their own product ID, free of charge, with the Deutsche Kreditwirtschaft. This integration ships none, and that is deliberate.

The number identifies one product. The Deutsche Kreditwirtschaft confirmed on request that users of a product may use that product's number, but asked that it not be published in freely accessible source code: a number found in use by third parties can be blocked completely, and that would lock out every legitimate user of the product it belongs to. Asking each user for their own number keeps that risk with one account instead of all of them.

**If you fork this integration or build something from it, register your own number.** Do not reuse one you found in a repository.

`scripts/check_secrets.py` runs in CI and fails the build if anything shaped like a product ID, a valid IBAN, or a private key is committed here.

### The supply chain

The integration itself has no dependencies. The manifest requires nothing, so a setup that uses only CSV exports installs no third-party code at all.

Two features install packages, and only when you switch them on:

| Feature | Package | Packages added |
|:--|:--|:--|
| FinTS | `fints` | 9 |
| pytr | `pytr` | 7 |

Every one of them is pinned to an exact version, the dependencies of the dependencies included. A pinned version cannot be moved to other code, so a new release of any of those packages reaches you only when a release here changes the list. `scripts/check_pins.py` runs in CI and fails if pip would install anything that is not on the list. The packages Home Assistant already ships are deliberately not pinned, because its own constraints decide those.

What this does not cover:

- A release that was already malicious when the version was pinned. Pinning freezes the code, it does not review it.
- HACS downloads releases from GitHub unsigned. A compromised maintainer account would reach you. The workflows here are pinned to commit SHAs so a moved tag cannot change the build, but that is the build, not the account.
- Five of the nine FinTS packages (`sepaxml`, `lxml`, `xmlschema`, `elementpath`, `text-unidecode`) exist only for sending SEPA transfers, which this integration never does. They are imported at the top of `fints/client.py`, so they cannot be skipped without a change upstream.

No project can promise this away, including this one. Read the release notes before updating.

Every release note carries the SHA-256 of `finance_insights.zip`, which is the archive HACS installs. To check what you got: `sha256sum finance_insights.zip`.

Found something? `SECURITY.md` says how to report it privately.

### Other notes

- Do not share your CSV exports when reporting issues. Anonymize the rows that show the problem.
- Booking events end up in the recorder database like all Home Assistant events, including payee and purpose. Exclude `finance_insights_transaction` in the recorder settings if you do not want that.

## Development

```console
$ python -m venv .venv && . .venv/bin/activate
$ pip install -r requirements_test.txt
$ pytest
```

`tests/sample.csv` and `tests/sparkasse_sample.csv` are synthetic data.

## Support

If Finance Insights saves you time, you can support its development with a [coffee](https://buymeacoffee.com/robinlabs).

## Credits

Bank codes and names come from the bank code file of the Deutsche Bundesbank, taken from [schwifty](https://github.com/mdomke/schwifty) (MIT).

## License

[MIT](LICENSE). This project is not financial advice.
