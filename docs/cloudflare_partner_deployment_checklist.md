# Cloudflare Partner-Only Deployment Checklist

Use this checklist to publish the dashboard and lock it down so only you + your partner can access it.

## A) One-time setup

1. **Install prerequisites**
   - Python environment with project deps.
   - `openpyxl` (required for reading `.xlsx` input).
   - Node.js 18+ (for `npx wrangler`).

2. **Create Cloudflare Pages project**
   - Cloudflare Dashboard → Workers & Pages → Create application → Pages.
   - Create project named (example) `homeharvest-dashboard`.

3. **Create API token**
   - Cloudflare Dashboard → My Profile → API Tokens.
   - Create token with permissions sufficient for Pages deploy (account-scoped Pages edit/deploy).
   - Copy token value.

4. **Get Cloudflare account ID**
   - Cloudflare Dashboard sidebar (or account overview page).
   - Copy Account ID.

## B) Each deployment

1. **Export credentials in your shell**

```bash
export CLOUDFLARE_API_TOKEN="<token-with-pages-edit>"
export CLOUDFLARE_ACCOUNT_ID="<account-id>"
export CLOUDFLARE_PAGES_PROJECT="homeharvest-dashboard"
```

2. **Build dashboard artifact + security files**

```bash
make dashboard-publish
```

Expected output:
- `publish/index.html`
- `publish/_headers`
- `publish/robots.txt`

3. **Deploy to Pages**

```bash
make dashboard-deploy-secure
```

4. **Verify deployment URL loads**
   - Confirm the site loads over HTTPS.
   - Do **not** share URL yet if Access policy is not active.

## C) Security lock-down (required)

1. **Enable Cloudflare Access app for your Pages URL**
   - Cloudflare Zero Trust → Access → Applications → Add application.
   - App type: Self-hosted.
   - Domain: your Pages domain (custom domain recommended).

2. **Authentication settings**
   - Login method: **One-time PIN**.
   - Session duration: set an expiration you’re comfortable with (e.g., 24h).

3. **Allow policy**
   - Include only these email addresses:
     - your email
     - partner email

4. **Deny by default**
   - Ensure no broad allow rule exists (`*@domain.com`, `Everyone`, etc.).

5. **Validate access controls**
   - Test with your email (should allow).
   - Test with partner email (should allow).
   - Test with a third email (should deny).

## D) Safety verification

- Check response headers include:
  - `Content-Security-Policy`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
- Confirm `robots.txt` returns `Disallow: /`.
- Confirm Access challenge appears before dashboard content.

## E) Ongoing update routine

When your scorecard changes:

```bash
make dashboard-publish
make dashboard-deploy-secure
```

Reuse the same protected URL.
