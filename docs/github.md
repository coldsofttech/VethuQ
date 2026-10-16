# Running OCR in your own GitHub account

The GitHub tier (the `vethuq-addon-github` add-on) sends the pages that need OCR to a repository
you own. A GitHub Actions job reads them with VethuQ's worker image and the result comes back.
Pages with a text layer never leave your computer. How it is built is in `github/README.md`; this
page is for the person using it.

## Set it up

1. Make a fine-grained token limited to the runner repository: *Contents*, *Actions*, *Secrets* and
   *Workflows* (read and write). To let VethuQ create the repository (or delete it later), add
   *Administration*; otherwise create an empty repository and use `--adopt`.
2. `vethuq github setup --token ...` (or set `VETHUQ_GITHUB_TOKEN`; save it with
   `vethuq github token remember ...`). The runner is private unless you pass `--public`.
3. `vethuq index run --tier github` (or `--tier hybrid`: small pages stay local).

`vethuq github status` shows the repository, what GitHub says about it, the workflow version and
this month's minutes.

## Public or private

| | Private repository | Public repository |
|---|---|---|
| Credits a day (GitHub wallet) | 20 | 200 |
| GitHub minutes | 2,000 a month free (a private runner stops at the cap) | not capped |
| Visible to others | nothing | job sizes, timing, the repository's name |
| Content | encrypted | encrypted |

Everything is encrypted whichever you choose (AES-256-GCM, a key per job from your master key). A
private runner that becomes public stops getting jobs until you agree again
(`vethuq github confirm-public`) or make it private.

## What leaves your computer, and what stays

```
your computer                      your runner repository                 GitHub's runner
pages that need OCR  --encrypt-->  release asset job-<id>  --workflow-->  worker image (no network)
        ^                                                                        |
        +-- decrypt, import, delete <-- artifact vethuq-result-<id> (1 day) <----+
```

- Only a job id and the asset's name are plain. File names, paths and text are inside the encrypted
  payload. The worker's logs hold none of them.
- After each job VethuQ deletes the release, its tag and the result artifact; leftovers of a job
  that died are removed by `vethuq github cleanup`.
- The master key never leaves your data folder except as the repository's secret; VethuQ never
  prints or logs it. `vethuq github key export FILE` writes it to a file for another computer.
- Metrics sharing (off unless you opt in) is separate and never includes job content.

## Minutes and credits

Credits are work, not time. GitHub bills the job in whole minutes: `vethuq github minutes` shows
the month so far, warns at 50% and 80% of the 2,000 a private repository gets, and stops sending
at the cap. `--pages N` estimates a job from the pace of earlier jobs (the pace differs by up to 3x
between runners; the CPU models seen are kept with their pace).

## Troubleshooting (`vethuq github doctor`, `--fix` repairs what it can)

| It says | What it means | What to do |
|---|---|---|
| The repository is gone | deleted or renamed | `setup` again |
| The runner workflow is missing / isn't VethuQ's / was changed | someone edited or removed it | `doctor --fix` rewrites it |
| The master key secret is missing | deleted in the repository settings | `doctor --fix` sets it again |
| The master key is missing on this computer | the key file was removed | `key import FILE` from a backup; without it past results can't be read |
| The master key isn't the one set up | another key was imported or rotated elsewhere | `key import` the right one, or `setup` again |
| The repository is public | sizes and timing are visible | make it private, or accept it |
| Leftover job releases and results | a job died | `cleanup` |
| Minutes nearly or fully used | the month's allowance | use the local tier, or wait for next month |
| The tier is switched off here | `github disable` was run | `github enable` |

Key rotation: `vethuq github key rotate` makes a new key and sets the secret. Results of jobs
already sent can still be read (the old key is kept; drop it with `GitHub(client).forget_previous_key()`
once they are done). A job that had not started fails and its pages are sent again, so rotate when
`vethuq index status` shows no open remote jobs.

## What a worker refuses (result codes)

| Code | Meaning |
|---|---|
| `bad_key`, `bad_payload`, `bad_manifest`, `bad_result` | the job can't be read or doesn't fit protocol v1 |
| `too_many_pages`, `too_large` | a job is at most 200 pages and 200 MB, whatever the manifest says |
| `bad_profile` | the manifest names a model profile (other than `fast`, `advanced`) the worker lacks |
| `owner_mismatch` | a licence in the job lists GitHub owners, and the repository's owner isn't one of them |
| `models_unverified` | the downloaded models don't match the image's lock |
| `language_unavailable`, `missing_image`, `ocr_failed` | one page failed; the others are read (`partial`) |

Licences and caps come from the encrypted manifest, never from the workflow, so editing the workflow
lifts nothing. A licence that lists owner ids is held to the owner of the repository the job runs
in (a user or an organisation; membership of an organisation is not verified). The daily credit
totals are counted by your computer's wallet, not by the worker.
