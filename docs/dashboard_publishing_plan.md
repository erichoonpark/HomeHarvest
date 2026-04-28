# Secure Dashboard Publishing (GitHub Pages)

This repo deploys the dashboard through GitHub Actions and GitHub Pages.

## Build + deploy workflow

- Build script: `scripts/build_dashboard_publish.sh`
- GitHub workflow: `.github/workflows/deploy_dashboard_pages.yml`
- Publish folder: `publish/`

## How deployment works

1. Push changes to `master` (or run the workflow manually).
2. GitHub Actions builds `publish/index.html`, `_headers`, and `robots.txt`.
3. The workflow uploads `publish/` as an artifact and deploys it to GitHub Pages.

## Local commands

Build locally:

```bash
make dashboard-publish
```

GitHub deploy trigger helper:

```bash
make dashboard-deploy-github
```

## GitHub setup required

1. Repository Settings -> Pages:
   - Source: **GitHub Actions**
2. Actions permissions:
   - Keep default permissions plus workflow-level `pages: write` and `id-token: write` (already in workflow).

## Notes

- Cloudflare deployment is no longer required for dashboard publishing.
- Existing Cloudflare resources can be removed once you confirm GitHub Pages serves the dashboard correctly.
