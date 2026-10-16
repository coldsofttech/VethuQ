# Licence requests

Some add-ons need a licence. You ask for one from VethuQ itself, and the request is a **public issue**
in this repository, made from one of the forms in `.github/ISSUE_TEMPLATE`. Read this first: it says
what is in a request, what must never be in one, and how a licence reaches you.

## How to ask

```sh
vethuq licence request --addon docx --addon doc          # a new licence (or --bundle office)
vethuq licence request --type top-up --wallet local      # more credits
vethuq licence request --type rebind                     # run on the NEW device: move a licence
```

In the interactive shell it is **licence > request**; in the desktop app it is **Add-ons > Licences >
Request a licence**. Each shows exactly what will be in the issue, says it is public, and only then
gives you the link (`--open` opens the browser after asking). No GitHub sign-in or token is needed to
prepare a request; you need a GitHub account to submit the issue. `vethuq licence code` prints just the
request code, for the forms or for an admin.

## What a request contains

The issue holds only:

| Field | What it is |
|---|---|
| Request code | `VQREQ1.…`: an **anonymous hash of the device**, your **numeric GitHub id** (only if you asked for it: `--github`), the **numeric id of your runner repository's owner** (if you have one), and the VethuQ version. Not your name, login, e-mail address, computer name or any path. |
| Add-ons or bundle | ids such as `docx` or `office` |
| Wallet | for a top-up: `local` |
| Note | optional, short (200 characters), public |

Looking up your GitHub id (`--github`, `--runner-owner NAME`) is the only time VethuQ contacts GitHub
for a request, and only when you ask. The id is kept on your computer so a GitHub-bound licence can be
checked when you install it.

## What must never be in a request

Do **not** put in the issue, the note or a screenshot: a licence key or token, a GitHub or other access
token, your master key, an e-mail address or other contact details, file names or paths, or anything from
your documents. The forms say so, VethuQ builds the request from the fields above only, and a test checks
that nothing else can reach the link.

## How a licence is delivered

A licence key is **never posted in the issue**, even though it is bound to your device. The maintainer
sends it to you privately and records on the issue only that it was sent. Install it with
`vethuq licence install KEY` (or `--file acme.vqlic`, or **Add-ons > Licences**): one key unlocks every
add-on it lists.

A licence is issued by a person, not automatically, so a reply takes as long as it takes. A licence is
bound to the device it was issued for; **re-bind** requests move it, and each licence can be re-bound a
limited number of times.
