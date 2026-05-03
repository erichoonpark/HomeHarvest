# Secure Dashboard Publishing (Firebase Hosting)

This repo deploys the dashboard through GitHub Actions and Firebase Hosting.

## Artifact roles

- Runtime dashboard output: `examples/zips/coc_dashboard.html`
- Canonical deploy artifact: `publish/index.html` (deployed to Firebase Hosting)
- Optional compatibility mirror: root `index.html` (synced from `publish/index.html` when needed)

## Build + deploy workflow

- Build script: `scripts/build_dashboard_publish.sh`
- GitHub workflow: `.github/workflows/deploy_dashboard_firebase.yml`
- Publish folder: `publish/`

## Local prerequisites

Poetry is required for local dashboard build commands in this repo.

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
# restart terminal (or source your shell rc)
pipx install poetry
poetry --version
poetry install --no-interaction --no-ansi
```

## How deployment works

1. Push changes to `master` (or run the workflow manually).
2. GitHub Actions builds `publish/index.html`, `_headers`, and `robots.txt`.
3. The workflow deploys `publish/` to Firebase Hosting.

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

1. Add repository secrets:
   - `FIREBASE_SERVICE_ACCOUNT_HOMEHARVEST`
2. Configure Firebase Auth Email Link authorized domains for local + hosted URLs.

## Notes

- GitHub Pages and Cloudflare deployment paths are optional during transition only.
- Root `index.html` should be treated as an optional mirror only; `publish/index.html` remains source of truth for deployment.
