# Changelog

All notable changes to Finance Insights. The newest release comes first.

This file is the source of the release notes on GitHub and in HACS, so each version needs a section
before it can be released.

## 0.15.0

### Fixed

- The cash flow chart counted a transfer from a bank account to a depot as spending, and then
  counted what that money later paid for as spending again. The same euro was charged twice, which
  invented a raid on your savings that never happened and made the chart disagree with the
  **Saved (12 months)** figure next to it. A transfer between your own accounts is now never a use
  of its own; it only splits the surplus, to show how much of what was left over went to the depot.

### Added

- The cash flow chart has **3M / 6M / 12M** buttons. An account younger than a year drowns in a
  twelve-month window: a salary that started three months ago is compared against a year of
  spending, which reads as a deficit that says nothing about where you stand now.
- Card spending on a broker account is split into the same groups as bank spending instead of
  sitting in one lump. The broker groups by merchant type and the bank by its own categories, so
  the household view now maps the two onto one set of names.

### Changed

- Every figure the dashboard shows in more than one place is now checked against the others by the
  test suite, so two cards can no longer disagree about the same number.

## 0.14.0

### Changed

- The Income and Spending tabs are built the same way. Both now open with key figures and then
  show the same three views: per month, where it came from or went over twelve months, and the
  detail tables. Until now Spending had the breakdowns and no key figures, and Income had the key
  figures and no breakdowns, so you could see a year of spending at a glance but not a year of
  income.

### Added

- A cash flow chart on the Overview tab: every income kind on the left, everything it paid for on
  the right, over the last twelve months. Both sides carry the same total, so nothing appears or
  disappears in the middle. A year that spent more than it earned shows the difference as an extra
  source rather than as a negative flow.
- Bank accounts: income per month split by kind, where the money came from over twelve months, and
  the largest payers.
- Trade Republic: where the investment income came from over twelve months, by kind and by
  position.

## 0.13.0

### Added

- Events on your holdings. A feed of dividends announced, raised, cut, or overdue, and of corporate
  actions your broker books, such as splits, swaps, and spin-offs. It is built from the dividend
  provider you already configured and from your own bookings, so it sends no request of its own and
  no holding leaves your system.
- Portfolio checks. Nine measurements of the account's shape: the largest position and the five
  largest, cash that is not invested, positions without a price, prices from an old trade, dividend
  income from one payer, dividend income in a foreign currency, and the order fees of the last twelve
  months. Each check states the figure it measured and the threshold it was compared with.
- Four sensors: **Holding events**, **Next ex-dividend date**, **Portfolio checks**, and
  **Largest position**.
- The event `finance_insights_holding_event`, and a blueprint that filters by the kind of event.
- Two cards on the Portfolio tab, in English and German.

### Notes

The checks describe your portfolio. They do not rate it, do not compare your positions against each
other, and never suggest that you buy or sell anything. There is no headline feed, because fetching
news per position would mean sending your holdings to a third party on every refresh.

## 0.12.0

### Changed

- Income and spending are measured over a rolling 30 days instead of the calendar month. A salary
  paid at the end of the month no longer reads as 0 EUR and -100 percent for most of the month.
- The savings rate was replaced by what you saved over the last twelve months, with the rate as a
  secondary figure.

### Fixed

- Twelve-month averages divide by the months your export actually covers, not always by twelve. A
  three-month history no longer looks like a year of low spending.
- Dividend growth drops a first year that holds only part of a payment cycle. Growing from one
  payment to four was reported as growth.
- Year-over-year dividend growth stays empty until the window before it is a full year of payments.

## 0.11.0

### Added

- Business account. Switch a bank account to a business account under **Configure** to get net
  revenue, VAT collected and paid, VAT due per month and per quarter, profit, and a tax reserve, on a
  dashboard tab of its own.
- VAT rates come from a rules file in the account's folder, and small businesses under section 19
  UStG are supported.

## 0.10.1

### Fixed

- The setup form keeps everything you typed when a step fails. The PIN is the one exception and is
  never put back into a form.
- The test suite and the pin check run without python-fints installed.

## 0.10.0

### Added

- A redesigned dashboard with its own cards and theme.
- Bank search by name, bank code, or IBAN, which fills in the FinTS server address for you.
- The daily history from your exports is written into the statistics, so the charts reach back to
  before you installed the integration.

### Changed

- The cards register as a Lovelace resource and announce themselves again after a restart. Each card
  registers on its own, so one that fails cannot hide the others.
- The time range buttons on a chart offer only the ranges the history covers.
- Credentials are kept out of the integration's files where possible, and a failed FinTS login
  reports the bank's own reason instead of a generic failure.
- Every dependency is pinned to an exact version, and the repository checks itself for committed
  credentials and for pins that drifted.

## 0.7.1

### Fixed

- The demo sample data ships with the integration.

## 0.7.0

### Added

- Demo mode, events for automations, and the cash flow forecast.

## 0.5.1

### Changed

- The dashboard tabs are ordered money flow first, then investments, and an account without data
  shows a note instead of empty cards.

## 0.5.0

### Added

- Dividends and running costs, and a dashboard per person.

## 0.4.0

### Added

- Dividend analysis with external dividend data, and benchmarks from the ECB.

## 0.3.1

### Fixed

- Lovelace is declared as an after dependency, so the dashboard is built at startup.

## 0.3.0

### Added

- Several people in one Home Assistant, with owners, overview accounts, and a generated dashboard.

## 0.2.0

### Added

- Bank accounts, through a CSV-CAMT export or FinTS, with rules for credits that offset spending.

### Changed

- Renamed from Trade Republic Insights to Finance Insights.

## 0.1.0

### Added

- Initial release as Trade Republic Insights.
