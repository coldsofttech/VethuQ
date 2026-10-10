# Update check

VethuQ tells you when a newer version exists, and which features need one, using the signed
policy ([policy-client.md](policy-client.md)). The policy is the **only** source: there is no
fallback to PyPI or GitHub Releases, so we control when an update is announced (publish the new
`latest` once the release is downloadable) and everything the check reads is signature-verified.

## What it reads

The policy's `versions` entry for your distribution (compared with the `vethuq` package version on pip, and with the installer's version on desktop - `scripts/dev/release.py --desktop` stamps it into the build, because the packages inside the app carry their own versions): `desktop` for the Windows installer build,
`pip` for the `vethuq` package, each with `latest`, `minimum_supported` and an optional
`release_notes_url`. Versions are compared as PEP 440 (the policy's `1.2.0-rc.1` spelling reads
as `1.2.0rc1`); a value that can't be compared means "no information" and nothing is shown.

| Installed version | Result |
|---|---|
| at or above `latest` | up to date, nothing shown |
| below `latest`, at or above `minimum_supported` | update available |
| below `minimum_supported` | below the minimum: reported, never snoozed or skipped |
| no signed policy yet (the built-in baseline), offline, or an unparseable version | unknown, nothing shown |

**Local work is never blocked.** Below the minimum, indexing, search and your data keep working;
only features that need a newer client are held back, each with a clear message (see
[Features that need a newer version](#features-that-need-a-newer-version)).

## When it runs

- The CLI and the desktop app already refresh the policy in the background at startup, at most
  about once a day, with a short timeout. The update check reads the saved policy, so it adds no
  request of its own and never delays or fails a command; any failure is silent.
- `vethuq updates check` and `client.updates.check()` refresh the policy on request;
  `vethuq updates status` and `client.updates.status()` use the saved policy only.
- Nothing is fetched on `import vethuq` or `Vethuq()`.
- The background service and its workers never prompt and never update themselves.
  `vethuq background-service status` shows when an update is available.

## Settings

`vethuq settings updates check set on|notify-only|off` (`client.settings.updates.check`, and
Settings > Updates in the desktop app):

| Value | CLI | Desktop app | Python |
|---|---|---|---|
| `on` (default) | one-line notice after a command | dialog at startup with Later / Skip this version | `UpdateResult.offer_install` is true |
| `notify-only` | one-line notice after a command | message in the status bar, no dialog | `offer_install` is false |
| `off` | nothing | nothing | `UpdateStatus.DISABLED`, no request |

Set the environment variable **`VETHUQ_UPDATE_CHECK=off`** (also `0`, `false`, `no`, `disable`) to
switch the check off whatever the setting says, for CI and locked-down machines. It wins over the
setting; the setting and `vethuq updates status` both say when it is in force.

Two choices are remembered in your settings:

- **Snooze** ("remind me later"): `vethuq settings updates snooze set [DAYS]` hides the notice
  for DAYS days (default 1); `snooze clear` shows it again.
- **Skip this version**: `vethuq settings updates skip set VERSION` stops announcing that
  version only; a newer one is announced again; `skip clear` undoes it.

The CLI notice is one line after a command's output, only when output goes to a terminal. It
never prompts, and never appears when output is piped, with `--json`, `--help`, or after
`vethuq updates ...`.

## Features that need a newer version

The policy's `features` section can carry a `min_client` and a `message` per feature (schema:
`vethuq-policy` `docs/schema-v1.md`). `client.updates.feature(name, default)` returns a
`FeatureAccess`:

- `allowed` — whether the feature is available to this version;
- `requires_update` — it is unavailable only because this VethuQ is too old;
- `message` — the policy's message, or a generic one naming the version needed.

`default` is what the feature does when the policy doesn't cover it. An older client keeps
`default` (so nothing already working is switched off); a feature whose default is off and that
the policy enables for newer clients comes back `allowed=False, requires_update=True`.
A flag with `enabled: false` is the remote kill switch and applies to every client at or above
its `min_client`.

## Privacy

The check reads the policy file from its host (GitHub Pages, with mirrors). That request
exposes your IP address to the host. It identifies itself only as `VethuQ-policy/1` (the policy
client's protocol, not the app); **your VethuQ version is not sent** - the comparison happens on
your machine. There is no telemetry: nothing else is sent, GitHub Pages gives us no access logs,
and the check can be turned off completely (`off` or `VETHUQ_UPDATE_CHECK=off`).

## Not yet

Installing an update from the app (download, verify, stop the service, install, restart) and
`vethuq update` with per-install-type upgrade steps are tracked separately; today the check only
tells you.

## Code map

`vethuq_core.updates` (`UpdateChecker`, `UpdateResult`, `FeatureGate`, `Versions`,
`Distribution`), `vethuq_core.settings.UpdateSettings`, `vethuq_cli.updates`,
`vethuq_ui.update_plan` / `update_prompt`, and the `client.updates` and
`client.settings.updates` API in `vethuq`.
