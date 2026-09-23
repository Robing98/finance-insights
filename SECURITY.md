# Security

This integration holds the credentials to a bank account. Reports about it are welcome and taken seriously.

## Reporting a vulnerability

Use **Report a vulnerability** under the Security tab of this repository. That channel is private and reaches the maintainer only.

Please do not open a public issue for anything that could expose credentials or account data, and do not paste a real product ID, IBAN, or PIN into a report. A description of the mechanism is enough.

This is a single-maintainer project. Expect a first reply within a week. If a fix is needed, it ships as a normal release with the advisory published afterwards.

## What counts as a vulnerability here

- A way for anything other than the user's own Home Assistant to reach the stored credentials, the FinTS session, or the bank data.
- Credentials or account data leaking into logs, diagnostics, events, or the dashboard.
- A dependency in the pinned lists with a known vulnerability that this integration can trigger.
- A way to make the integration contact a host it was not configured for.

## What does not count

These are documented properties, not defects. The README explains each one.

- Home Assistant stores credentials unencrypted in `.storage`. That is Home Assistant's model. Switch on **Do not store the PIN** if you want the PIN kept in memory only.
- Anyone with read access to the Home Assistant files can read the bookings. Encrypt your backups.
- FinTS access with a PIN and a TAN can authorize transfers. Use a read-only banking access if your bank offers one.
- Exports, the FinTS cache, and the recorder database hold your bookings in plain text in the config folder.

## Supported versions

The latest release. Fixes are not backported.

## What this project does to reduce the risk

- No dependencies at all unless FinTS or pytr is switched on, and every package those pull in is pinned to an exact version. `scripts/check_pins.py` fails the build if anything unpinned appears.
- `scripts/check_secrets.py` fails the build if a FinTS product ID, a valid IBAN, or a private key is committed.
- GitHub Actions are pinned to commit SHAs, and workflows request read-only permissions except the one that publishes a release.
- Diagnostics contain no credentials, no account numbers, and no amounts.
- Each user registers their own FinTS product ID. None is shipped.
