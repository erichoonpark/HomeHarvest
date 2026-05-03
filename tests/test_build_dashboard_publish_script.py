from __future__ import annotations

from pathlib import Path


def test_publish_script_csp_allows_firebase_runtime_dependencies():
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "build_dashboard_publish.sh"
    text = script.read_text(encoding="utf-8")

    assert "Content-Security-Policy:" in text
    assert "script-src 'self' 'unsafe-inline' https://www.gstatic.com" in text
    assert "https://identitytoolkit.googleapis.com" in text
    assert "https://securetoken.googleapis.com" in text
    assert "https://firestore.googleapis.com" in text
    assert "wss://firestore.googleapis.com" in text
