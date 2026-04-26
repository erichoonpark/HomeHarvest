# Secure Dashboard Publishing (Partner-Only)

This repo now includes scripts so you can publish the dashboard as a static site with security headers and then deploy it to Cloudflare Pages.

## What was added

- `scripts/build_dashboard_publish.sh`: builds `publish/index.html` from your scorecard and adds:
  - `publish/_headers` (security headers)
  - `publish/robots.txt` (`Disallow: /`)
- `scripts/deploy_cloudflare_pages.sh`: deploys `publish/` to Cloudflare Pages with `wrangler`.
- `Makefile` shortcuts:
  - `make dashboard-publish`
  - `make dashboard-deploy-secure`

## 1) Build the secure static bundle

```bash
make dashboard-publish
```

Optional custom input/output:

```bash
./scripts/build_dashboard_publish.sh examples/zips/coc_scorecard.xlsx publish
```

## 2) Deploy to Cloudflare Pages

Set required environment variables:

```bash
export CLOUDFLARE_API_TOKEN="<token-with-pages-edit>"
export CLOUDFLARE_ACCOUNT_ID="<account-id>"
export CLOUDFLARE_PAGES_PROJECT="homeharvest-dashboard"
```

Deploy:

```bash
make dashboard-deploy-secure
```

## 3) Enforce partner-only security (required)

In **Cloudflare Zero Trust → Access → Applications**, protect your Pages URL and set:

- **Login method**: One-time PIN (email)
- **Allow policy**: only
  - your email
  - your partner's email
- **Default action**: deny

This turns the dashboard into a private link requiring email verification.

## 4) Update workflow

Whenever data changes:

```bash
make dashboard-publish
make dashboard-deploy-secure
```

Same URL, updated dashboard, still protected by Access policy.

## Notes

- The scripts cannot create your Access policy automatically because that depends on your account identity setup.
- Do not share the unprotected `*.pages.dev` URL before Access is active.
