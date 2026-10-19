# The device folder

Licences and the credit ledger belong to the **computer**, not to one account. They are kept in a
folder that every OS account on the computer and the background service share, so:

- a second account does not get a second free allowance (the daily and one-off credits are one
  ledger for the whole computer);
- a licence installed once works for every account, and for the service, whatever account it runs as;
- restoring or resetting a database does not hand out credits again: the ledger is not in it.

## Where it is

| Scope | Folder | When |
|---|---|---|
| `device` | `%PROGRAMDATA%\VethuQ` (Windows), `/Users/Shared/VethuQ` (macOS), `/var/lib/vethuq` (Linux) | a database in an account's standard data folder, when this folder can be used |
| `custom` | the folder `VETHUQ_DEVICE_HOME` names | the variable is set (use it to share a folder on Linux without `/var/lib` rights) |
| `user` | `device/` in the account's own data folder | the shared folder can't be created or written (for example a `pip install` without the rights): nothing is shared |
| `database` | `device/` next to the database | a database anywhere else (a test, a copy, `--db` of a custom folder): it is self-contained |

A database counts as "in the standard data folder" when it sits in the data folder this account
resolves (`VETHUQ_HOME`, the saved location, or the platform default), or in a folder named `VethuQ`,
which is where the installed background service is pointed (`--db`). `vethuq settings location show`
prints the folder and who shares it; `vethuq.paths.Paths.device_dir()` and `device_scope()` give them
to programs. When the shared folder can't be used, VethuQ logs a warning once and falls back to
`user`: it never stops working for lack of it.

## What is in it

One SQLite file, `device.db`:

- the credit ledger, attached to every database connection as the `device` schema
  (`device.credit_grants`, `device.credit_ledger`), kept with a rollback journal rather than WAL so
  accounts with different rights can all use it;
- the licence tokens, one per add-on (`licences` table), read with plain `sqlite3` so a licence can
  be read while the user's database is opening or damaged. A licence an older version left in the
  user's database is still read until it is replaced or removed.

Spending is recorded against a source by its id; removing the source (`purge`) deletes those rows
from the ledger, because a foreign key can't reach into the other database. Everything else about
sources, documents and pages stays in the user's own database.

### Locking

A transaction that writes to both databases takes the two write locks in one fixed order (user's
database, then device) at its first write, with a no-op `DELETE ... WHERE 0`. Two transactions that
took them in opposite orders would otherwise deadlock, and SQLite reports that at once as `database is
locked` instead of waiting for the busy timeout. The ledger is small and written in short
transactions, so the cost is that writers queue.

## Permissions

- **Windows:** the installer (an all-users install) creates `%PROGRAMDATA%\VethuQ` with modify
  rights for the Users group and never removes it, so uninstalling and reinstalling does not reset
  the allowance. A per-user install can't, so VethuQ creates it on first use when the account may
  (granting Users modify access with `icacls`, best effort), and otherwise falls back to `user`.
- **Linux and macOS:** a folder VethuQ creates is world-writable with the sticky bit (like `/tmp`),
  and the database file is `0666`, so any account can use it but not delete another's files. A
  folder that already exists keeps its permissions.

## Uninstalling

An ordinary uninstall never removes the device folder, so uninstalling and reinstalling keeps the
licences and the credit ledger (and does not hand out a fresh allowance). Everything below is done
by the command line's uninstaller (`Uninstall VethuQ CLI`, or `unins000.exe`):

| What | Default uninstall | "Remove all VethuQ data" |
|---|---|---|
| Programs, `lib\` and installed add-ons (`add-ons\`) | removed | removed |
| Background service | stopped and removed | stopped and removed |
| Device folder (licences, credit ledger) | kept | removed |
| This account's data folder: database, settings, logs, add-on data | kept | removed |
| OCR models (`models\` in the data folder) | kept | removed |
| Another account's data folder, a data folder moved with `VETHUQ_HOME` or `vethuq settings location set` | kept | kept: remove it by hand |

"Remove all VethuQ data" is a question in the uninstaller, answered No unless chosen, with a warning
that it deletes licences and credit history. A silent uninstall never asks: add `/REMOVEDATA=1`
(`VethuQ-CLI-Setup` leaves `unins000.exe` in the install folder:
`unins000.exe /VERYSILENT /REMOVEDATA=1`). Removing the device folder needs the rights it was
created with: a per-user uninstall that cannot delete it says so, and the folder can be deleted as
an administrator. The other installers' uninstallers (desktop app, interactive CLI, worker,
background service) remove only their own program and have no such choice.

## What it is not

It is a **deterrent, not a lock**. The folder is writable by every local account, so a user with the
rights to change it can edit the ledger, and an administrator can delete it. It stops the casual ways
of getting a second allowance (a second account, a reinstall, a restored or reset database), not a
determined local user. A protected, service-owned ledger remains a later option (#188).

- A **VM clone** has the same device folder and so the same ledger; a licence bound to the device
  hash is for the original machine's id, as before.
- A user who points `VETHUQ_DEVICE_HOME` at their own folder gets a ledger of their own: the variable
  is for setting up sharing, not a boundary.
- After restoring an older copy of the user's database, ledger rows for sources whose ids were reused
  may show against the wrong source in per-source usage. The balance is unaffected.
