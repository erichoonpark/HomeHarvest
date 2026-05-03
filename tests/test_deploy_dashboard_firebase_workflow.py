from __future__ import annotations

from pathlib import Path

import yaml


def _workflow_text_and_yaml() -> tuple[str, dict]:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = repo_root / ".github" / "workflows" / "deploy_dashboard_firebase.yml"
    text = workflow.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return text, data


def test_deploy_workflow_has_concurrency_and_secret_preflight():
    text, workflow = _workflow_text_and_yaml()

    assert "concurrency:" in text
    assert workflow["concurrency"]["group"] == "deploy-dashboard-firebase-live"
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert "Validate Firebase deploy credentials" in text
    assert "Missing required secret FIREBASE_SERVICE_ACCOUNT_HOMEHARVEST" in text
    assert "must have type=service_account" in text
