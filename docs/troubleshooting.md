# Troubleshooting

## Uninstalling and reinstalling

- **I reinstalled and my licences and credits are still there.** That is intended: an ordinary
  uninstall keeps the device folder (licences and the credit ledger), the database, settings and
  downloaded OCR models, so a reinstall does not reset the credit allowance.
- **I want to start from nothing.** Uninstall with "Also remove all VethuQ data?" answered Yes, or
  silently: `unins000.exe /VERYSILENT /REMOVEDATA=1` in the install folder. This deletes licences and
  credit history, and this account's database, settings, logs, OCR models and add-on data. It cannot
  be undone. See [the device folder](device-folder.md#uninstalling) for what each choice removes.
- **Licences and credit history were not removed.** Removing the shared folder (`%PROGRAMDATA%\VethuQ`)
  needs the rights an all-users install has. After a per-user uninstall, delete the folder as an
  administrator. Other accounts' data folders, and a data folder moved elsewhere on purpose, are
  never removed by the uninstaller.
- **The background service is still listed.** Uninstalling the command line or the background service
  stops and removes it. If it is left (for example the uninstall was cancelled part way), run
  `sc stop VethuQBackground` and `sc delete VethuQBackground` from an administrator terminal.
