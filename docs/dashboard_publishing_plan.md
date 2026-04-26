# Dashboard Publishing Plan (Partner Access)

## Recommendation (best balance of simplicity + privacy)

Use **Cloudflare Pages** to host the generated `coc_dashboard.html` as a static site, then protect it with **Cloudflare Access** (one-time PIN email login) so only you and your partner can view it.

### Why this is the best fit for this project

- Your dashboard output is already a static HTML artifact (`examples/zips/coc_dashboard.html`), so no backend hosting is required.
- You can share a URL instead of manually sending files.
- Access policies let you allow only specific email addresses.
- It scales from "just two viewers" today to more people later without changing architecture.

## Implementation steps

1. **Generate dashboard HTML**
   - Run the existing generator and output to a publish folder.
   - Example:
     ```bash
     python examples/coc_dashboard.py --input examples/zips/coc_scorecard.xlsx --output publish/index.html
     ```

2. **Create a lightweight publish directory**
   - Keep only static artifacts required for viewing:
     - `publish/index.html`
     - optional assets (images, css, js)

3. **Deploy to Cloudflare Pages**
   - Create a Pages project connected to this repo (or a separate lightweight repo).
   - Build command: `exit 0` (static deploy).
   - Output directory: `publish`.

4. **Restrict access with Cloudflare Access**
   - Add the Pages domain as a protected web application.
   - Configure one-time PIN authentication.
   - Add an Allow policy for only these emails:
     - your email
     - partner's email

5. **Share the protected URL**
   - Your partner logs in with email and one-time code.
   - No VPN or GitHub account required.

## Operational workflow

- Update dashboard data as needed.
- Regenerate `publish/index.html`.
- Push commit; Cloudflare Pages auto-redeploys.
- Partner always uses the same URL.

## Alternative options and trade-offs

- **GitHub Pages (public)**
  - Easiest setup, but URL is publicly accessible unless you are on plans/features that support private/internal visibility.

- **Send HTML file directly (email/Drive/Dropbox)**
  - Fastest for one-off sharing.
  - Manual and error-prone for recurring updates.

- **Streamlit Cloud / Render / Railway**
  - Useful if dashboard becomes interactive with server-side computation.
  - More moving parts than needed for current static HTML output.

## Suggested next enhancement (optional)

Add a small script/Make target that regenerates `publish/index.html` in one command (for repeatable updates), e.g.:

```bash
make dashboard-publish
```

This keeps publish updates simple and consistent.
