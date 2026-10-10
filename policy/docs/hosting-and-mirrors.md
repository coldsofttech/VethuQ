# Hosting, URL list and moving hosts

## How clients fetch the policy

The client embeds an **ordered URL list** for `policy.json` and tries each URL in turn:

| # | Role | URL |
|---|------|-----|
| 1 | Primary (GitHub Pages) | `https://coldsofttech.github.io/vethuq/policy/v1/policy.json` |
| 2 | Mirror (jsDelivr) | `https://cdn.jsdelivr.net/gh/coldsofttech/vethuq@main/policy/v1/policy.json` |
| 3 | Mirror (raw) | `https://raw.githubusercontent.com/coldsofttech/vethuq/main/policy/v1/policy.json` |
| optional | Custom domain, placed first | e.g. `https://policy.<our-domain>/v1/policy.json` |

Rules for clients:

- **Trust comes from the signature, not the host.** Every response is verified against the embedded
  public key whatever URL it came from, so a mirror cannot forge a policy.
- Use the first URL that returns a valid, verified envelope; fall through on network errors, non-200
  responses, or verification failure.
- Mirrors can be stale (jsDelivr caches branch refs). The `sequence` rule (never accept a lower
  sequence than the last accepted) stops a stale mirror from rolling a client back.
- A failed fetch never breaks the app: the client keeps the last verified policy.

## Moving hosting without a client release

The URL list is compiled into released clients, so a move without a release only works through a URL
that is **already in the list and that we control**. Two supported ways:

1. **Custom domain (recommended).** Ship the first client release with a custom domain we own as
   URL #1. To move (for example to Cloudflare Pages), publish the same `/v1/` files on the new host
   and repoint the domain's DNS. Clients need no update.
2. **Mirror fallthrough.** If we only use the GitHub URLs, moving off GitHub Pages leaves the
   jsDelivr and raw mirrors serving whatever is still in this repo; those keep working as long as
   the repo is kept up to date. This is a fallback, not a migration path.

Procedure to move a host (with a custom domain):

1. Deploy the contents of `policy/` on `main` to the new host; keep the path layout (`/policy/v1/policy.json`) and
   `Content-Type: application/json`.
2. Verify the new host serves the current signed file (compare bytes with the repo).
3. Lower the domain's DNS TTL, repoint it, then confirm clients still verify against the new host.
4. Keep this repo (and its mirrors) updated until old clients are no longer in use.

A later, additive schema field could let a signed policy extend the client's URL list. It is **not**
part of schema v1; adding one would be an additive change within the major.

## `/v1/` stays available

Breaking schema changes go to `/v2/`. Never remove or repurpose `/v1/`, because old clients keep
fetching it.

## Where it is published from

The policy lives in the `policy/` folder of the VethuQ repository. The `policy-pages` workflow publishes
only that folder to GitHub Pages (the rest of the repository is not served), so a file's path in the
repository is also its path on the site: `policy/v1/policy.json` is served at `/policy/v1/policy.json`.
The jsDelivr and raw mirrors serve the same path straight from the repository. The older
`vethuq-policy` repository is retired; no released client used its URLs.
