# Releasing and versions

Every part of VethuQ that ships on its own has its own version, taken from git tags by
`hatch-vcs`. A fix in the UI does not make a new core, and a new add-on does not make a new app.

| Tag | Releases | Version of | Workflow |
|---|---|---|---|
| `vX.Y.Z` / `vX.Y.Z-dev.N` | the `vethuq` pip package | `vethuq` (what `pip install vethuq` gives) | `release.yml` (PyPI for stable tags) |
| `desktop-vX.Y.Z` / `-dev.N` | the Windows installer | the desktop app, as the policy's `versions.desktop` | `release-desktop.yml` |
| `core-vX.Y.Z` / `-dev.N` | `vethuq-core` | the engine | none: the tag *is* the release |
| `cli-vX.Y.Z` / `-dev.N` | `vethuq-cli` | the CLI | none |
| `ui-vX.Y.Z` / `-dev.N` | `vethuq-ui` | the desktop UI | none |

`vethuq-core`, `vethuq-cli` and `vethuq-ui` are never published on their own: the pip package
vendors core and CLI (`packages/vethuq/scripts/merge_sources.py`), and the installer bundles all
three. Their tags exist so each has a real version that the update check can compare with the
policy's `components` section ([updates.md](updates.md)).

## How a version is worked out

Each package asks git for the nearest tag with *its own* prefix (`git describe --match
'core-v*'`, and so on), so the other tags never disturb it:

- on the tag itself: `1.4.2`;
- N commits after `core-v1.4.2`: `1.4.3.dev<N>+g<hash>` (a development build);
- `core-v1.5.0-dev.1` gives `1.5.0.dev1`; a prerelease tag sorts before its release;
- no tag of its own yet: `0.1.dev<N>+g<hash>`.

Check a package's version with `python -m hatchling version` from its folder
(`packages/vethuq-core`, ...). The shallow clone CI uses by default is not enough: workflows that
need versions fetch the full history (`fetch-depth: 0`).

## Cutting a component release

1. Merge the change to `main` (or the `dev/v*` branch you are releasing from).
2. Tag it: `git tag core-v1.4.2 && git push origin core-v1.4.2` (same for `cli-v` and `ui-v`).
3. When the release should be announced to users, add or update the component in the signed
   policy: `components.vethuq-core.latest` (and `minimum_supported` if older versions must update).
   Publish the new `latest` only once the release is downloadable. Do not publish a `-dev.N` version.

An app release (`vX.Y.Z`, `desktop-vX.Y.Z`) takes whatever core, CLI and UI are on the commit it is
tagged from; it does not need new component tags.

## Rules for tags

- A tag must be reachable from the commit being built (tag the branch you release from).
- Tags are `<prefix>-vX.Y.Z` or `<prefix>-vX.Y.Z-dev.N` only. Anything else is ignored by the
  component it is not meant for and fails the package it is meant for, which is the point.
- The `vethuq` package matches only `v*` tags, so component and `desktop-v*` tags never change the
  pip version.
