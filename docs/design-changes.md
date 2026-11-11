# Gold Volt — Design Changes from the Feature List

Nov 10, 2026. This file applies on top of *Gold Volt — Final System and Software Design* (Nov 9, 2026). Where the two disagree, this file wins. Section numbers such as B4 refer to that document, and F0–F11 refer to the owner's feature list.

"Owner" means the admin account and "salesman" means a non-admin account.

## Decisions

| Topic | Decision |
| --- | --- |
| Gold differences | Calculated separately per origin, in fine grams. Balances in different origins never cancel out. |
| Money differences | Calculated separately from gold, in dinars. |
| Sales to clients | The client must always give gold, or gold plus money. Never money alone. |
| Supplier purchases | Gold and money stay as separate balances, with no price per gram. |
| Gold price | There is no gold price anywhere in the app, so daily buy and sell prices are removed. |
| Façon | Entered on every operation, per gram, per origin and category. |
| Salesman picking a client | Partial search returning names and phones only. |
| CSV import | Rows are added beside current data, tagged as loaded, and count in balances and stock. |

## 1. Settlement (F2, F3, F4 — replaces B4 formulas)

The fine weight of each line stays the same:

```latex
p = \frac{w \times f}{1000}
```

For each origin *o*, the gold difference is:

```latex
\Delta G_o = \sum p_{\text{given},o} - \sum p_{\text{received},o}
```

Façon is calculated per origin and category *k*, and only the total is rounded, to whole dinars, half away from zero:

```latex
F = \operatorname{round}\left(\sum_k \varphi_k \times W_k\right)
```

The money difference is:

```latex
\Delta M = F + M_{\text{given}} - M_{\text{received}}
```

A positive value means the party owes the shop. A negative value means the shop owes the party. Each non-zero difference becomes its own ledger entry.

**Worked example** (example values only). The client gives raw gold from origin A and takes rings from origin B.

| Step | Calculation | Result |
| --- | --- | --- |
| Received, origin A | 200.000 g × 999.9 ⁄ 1000 | Shop owes client 199.980 g of A |
| Given, origin B | 250.000 g × 750 ⁄ 1000 | Client owes shop 187.500 g of B |
| Façon | 250.000 × 900 | 225,000 DA, printed as "Total manufacture price" |
| Money | 225,000 − 200,000 cash received | Client owes shop 25,000 DA |

If the raw gold had also been origin B, the single gold entry would be 187.500 − 199.980 = −12.480 g of B, meaning the shop owes the client.

**Rules.**

- A sale is refused unless at least one gold line is received from the client.
- One façon rate is entered per origin and category in an operation. Whoever posts the operation enters it. The owner-only override in the design's confirmation list is removed.
- Façon applies to ready gold given in a sale. It does not apply to gold handed over as a debt payment.

**Supplier purchases** use the same formulas. No gold is valued in dinars, so a purchase paid in cash records two balances. For example, receiving 100.000 g at 999.9 of origin A and paying 1,000,000 DA records:

- the shop owes the supplier 99.990 g of A;
- the supplier owes the shop 1,000,000 DA.

These balances appear in debt totals and debt alerts like any other. They close only through debt payment entries.

**Removed by this decision.**

- The `pricing` app and the `daily_price` table. Section B2 now has nine apps.
- B5 step 3, which refused posting until the day's prices were set.
- "See today's prices" and "Set prices and façon" in B8, and the "Daily prices" screen in B10.
- "Value at today's price" in the stock report (B12), which now shows weight and pieces.

**Changes to reports (B12).** Sales statistics use fine grams and façon instead of a dinar transaction size. Debt aging is shown in dinars and, separately, in grams per origin. Payment reliability covers money and each gold origin separately.

## 2. Data model changes (B3)

| Table or column | Change |
| --- | --- |
| `party_ledger_entry` ★ | One row per asset. `asset` is `money` or `gold`. `origin_id` is required for gold and must be empty for money. A CHECK constraint enforces this. |
| Balances | Sum grouped by party, asset and origin. |
| `transaction_line` ★ | Adds `facon_rate` for ready gold given. |
| `transaction` ★ | Adds `operation_at` (editable by the user) and `recorded_at` (server time, never editable). |
| All ★ tables | Add `public_id` (UUID) and `import_batch_id` (empty unless loaded). |
| `import_batch` | New: file hash, date, author, row counts, source install ID. |
| `imported_audit_event` | New, append-only: activity-log rows that arrived through import. |
| `audit_head` | New: a single row holding the chain head. See below. |
| `totp_backup_code` | New: 10 per owner enrolment, stored hashed, single use. |
| `password_reset_token` | New: one active per owner, stored hashed. |

**Corrections to the design.**

- Fine weight becomes `NUMERIC(18,7)`. Gross weight has 3 decimals and fineness has 1, so the exact product divided by 1000 needs 7. The design's 4 decimals would round gold debts, and these are now long-lived balances.
- PostgreSQL requires UPDATE permission for `SELECT … FOR UPDATE`. The app role has no UPDATE on `audit_event`, so it cannot lock the chain's last row as B9 describes. It locks the `audit_head` row instead.
- The app role needs DELETE on `category` only, for F8.

## 3. Operations and date (F1)

- Every operation requires a party, and records the author automatically.
- `operation_at` defaults to the current moment, and both roles can change it.
- `recorded_at` always holds the real server time. The clock check (A8) uses this value only.
- The activity-log entry for an operation is stamped with the real date and time. Nobody can edit it, whatever date was entered on the operation.
- Statements and reports sort by `operation_at`. A receipt shows both times when they differ.
- Any changed date is written to the activity log with both values.
- Stock sufficiency is checked in the order operations are recorded, whatever date was entered.

## 4. Debt payments (F6 — extends B6)

A payment entry records direction (to the shop or from the shop) and asset.

- **Money:** amount in dinars. The cash drawer and the party's money balance change.
- **Gold received:** origin, purity and weight. Stock goes up and that origin's balance changes.
- **Gold given:** origin, purity, category, weight and pieces, all required. Stock goes down and that origin's balance changes.

Partial payments are allowed. A payment larger than the debt is allowed after a warning, and leaves a balance in the other direction.

## 5. Filters and party folder (F5, F7 — extends B12)

- **Stock:** origin, category, purity, kind, and pieces per category.
- **Debts:** owed to me or owed by me, money or gold, origin, client or supplier.
- **Movements:** user, client, supplier, date range, origin, category.
- **Party folder (clients and suppliers):** every operation with full detail. Filters cover date range, money amount, origin and category. The filtered result prints on A4.

All of these are owner-only.

## 6. Category deletion (F8 — refines B3)

A category can be deleted only when no `stock_item` row points to it, even one with zero stock, because history refers to that row. A database foreign key enforces this. A used category can still be disabled. Each deletion goes in the activity log.

## 7. Owner recovery (F9 — replaces B7 "Forgotten password" for the owner)

- **Backup codes:** 10 single-use codes, created when TOTP is first set up. A code can replace the authenticator at login, and the app then requires setting up TOTP again, which issues 10 new codes and cancels the old ones.
- **Password reset token:** created at owner signup. It resets the password only, so TOTP or a backup code is still needed to log in. After each reset, a new token is issued and the old one stops working.
- **Display:** a full-screen page in large monospace text, with Copy and Download as `.txt` buttons, and a confirmation before leaving. Codes and tokens are stored hashed and shown only once.
- **Risk handled in the app:** the Windows account is shared, so a `.txt` file saved on this PC is readable by the salesman. Saving uses the native dialog, and warns strongly if the destination is the C: drive.
- The installer's "owner recovery code" (A7) is removed, because these replace it. The printed recovery sheet keeps the BitLocker key, backup passphrase and PostgreSQL password.
- The salesman has no TOTP, and the owner resets the salesman's password, as already designed.

## 8. Salesman access (F10 — replaces the salesman column in B8 and B10)

| Action | Salesman |
| --- | --- |
| Post a sale, purchase or debt payment | Yes |
| Search parties | Names and phones only |
| Add a new client or supplier | Name and phone only, both required, with no later editing. Refused if the phone number already belongs to a party, and that party is offered instead. |
| Lists of origins, categories and purities | Labels only |
| Receipt of the operation just posted | Yes, once, showing this operation's differences only |
| Running balances, including on receipts | No |
| Stock levels | No. Too little stock gives "Not enough stock" with no quantity. |
| List, reprint or void transactions | No. The owner voids. |
| Dashboard, reports, activity log, folders, settings, backup, export, import | No |

The permission-matrix test (B13) must enforce this table.

## 9. CSV export and import (F11 — new)

**Export.** One owner-only button, with re-confirmation of identity. It saves one ZIP holding one CSV per table, a `files/` folder for uploaded ID scans, and a manifest.

- Everything is included, activity log too, except login accounts, password hashes, TOTP data, tokens and secrets. Author names stay as plain text on each row.
- CSV files are UTF-8 with BOM so Excel shows Arabic correctly, and decimals use a dot.
- Text cells that begin with `=`, `+`, `-` or `@` are escaped so Excel cannot run them as formulas.
- **This file is not encrypted.** It must not stay on the daily USB stick, because A9's "Lost USB stick" protection covers `.gvbak` backups only. The export screen says so.

**Import.** Owner-only, with re-confirmation of identity. It runs as follows.

1. An automatic backup is made first.
2. Every row is validated, and every transaction is recalculated from its lines. CSV files can be edited by hand, so they are never trusted.
3. A preview shows what will be added.
4. Everything is saved in one database transaction, or nothing is.

Further rules:

- Importing the same file twice is refused. Rows whose `public_id` already exists are skipped, so overlapping exports do not count twice.
- Parties with a matching phone number link to the existing party. Origins, categories and purities link by name or fineness.
- Loaded operations keep their original number as a label and use no new receipt numbers. They show a "loaded" tag everywhere.
- The import is refused if any stock item would end below zero.
- Loaded activity-log rows go to `imported_audit_event`, so the real chain stays valid. The real log gets one entry for the import.

## 10. Activity log (F0 — extends B9)

**Also recorded:** page opens, prints and reprints, exports and imports, category creation and deletion, logout and idle lock, TOTP setup, backup-code use and reset-token use. Live preview refreshes are not recorded.

**Failed logins** are written in their own committed transaction, so a rollback cannot lose them.

**Not deletable.**

- A database trigger rejects UPDATE, DELETE and TRUNCATE on `audit_event` for every role, including the migration role.
- A restore (A6) would otherwise wipe entries made after the backup. Before the switch, entries after the backup's head hash are copied into the restored database and the chain is verified. If the live chain does not continue from that hash, those entries go to `imported_audit_event` instead, flagged in red.
- A9 still applies: nothing can stop the Windows administrator account. The hash chain and off-PC copies reveal such edits afterwards.

## 11. Desktop window (extends A4)

The window's native actions grow from three to six. The new ones are saving recovery codes as `.txt`, saving the CSV export, and opening a CSV import.

## 12. Tests (extends B13)

The invariant "every printed total equals gold value plus façon" becomes "every printed money difference equals façon plus money given minus money received". New invariants:

- Each origin's gold balance equals the sum of its entries.
- A sale without gold received is always refused.
- Export then import into an empty database gives identical balances, and a second import changes nothing.
- The chain stays valid across a restore.

## 13. Build notes

- Two libraries were added to B1: WhiteNoise serves the local CSS, scripts and fonts, because Waitress does not, and segno draws the authenticator QR code without a network.
- A salesman's receipt opens once, right after posting, so printing must happen on that screen.
- Opening stock and ready gold from a workshop are entered through "Adjust stock" until the workshop flow below is decided.

## Open items

- [ ] **Ready gold entering stock.** Neither the design nor the feature list says how raw gold becomes rings and chains, for example gold sent to a workshop and returned as finished pieces. Until this is decided, the owner uses "Adjust stock".

- [ ] **Closing offsetting balances.** A party can owe gold of one origin while being owed gold of another, and a supplier paid in cash owes money while being owed gold. Nothing cancels these. Decide whether the owner needs a logged, admin-only "settlement" entry that closes such balances against each other.
- [ ] **Salesman voiding.** Section 8 lets only the owner void an operation. Not yet confirmed.
