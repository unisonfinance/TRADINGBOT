"""
Auto-deploy Firestore Security Rules via Firebase Rules REST API.
Called automatically by web/app.py on startup.

ONE-TIME SETUP (only do this once):
  1. Go to https://console.firebase.google.com
  2. Click the gear icon → Project Settings → Service Accounts tab
  3. Click "Generate new private key" → save as service_account.json
     in the project root folder (next to .env)
  4. Add to .env:  FIREBASE_PROJECT_ID=trading-bot-f3bd5
                   SERVICE_ACCOUNT_PATH=service_account.json
After that, rules deploy automatically every time the server starts.
"""

import json
import os
import sys
import requests

# ─── Firestore Security Rules ─────────────────────────────────────
# Users can only read/write their own data.
FIRESTORE_RULES = """rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // Every user can only access their own sub-collections
    match /users/{userId}/{document=**} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }

    // Top-level user profile document
    match /users/{userId} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }

  }
}
"""

BASE_URL = "https://firebaserules.googleapis.com/v1"


def _get_access_token(service_account_path: str) -> str:
    """Get a short-lived OAuth2 Bearer token from the service account."""
    try:
        from google.oauth2 import service_account as sa
        from google.auth.transport.requests import Request as GoogleRequest

        creds = sa.Credentials.from_service_account_file(
            service_account_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        creds.refresh(GoogleRequest())
        return creds.token
    except ImportError:
        raise RuntimeError(
            "google-auth not installed. Run: pip install google-auth"
        )


def _create_ruleset(project_id: str, token: str) -> str:
    """Create a new ruleset and return its resource name."""
    url = f"{BASE_URL}/projects/{project_id}/rulesets"
    payload = {
        "source": {
            "files": [{"name": "firestore.rules", "content": FIRESTORE_RULES}]
        }
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["name"]  # e.g. "projects/trading-bot-f3bd5/rulesets/abc123"


def _update_release(project_id: str, ruleset_name: str, token: str) -> None:
    """Point the cloud.firestore release at the new ruleset."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    release_resource_name = f"projects/{project_id}/releases/cloud.firestore"

    release_body = {
        "name": release_resource_name,
        "rulesetName": ruleset_name,
    }

    # Check if the release already exists
    get_resp = requests.get(
        f"{BASE_URL}/{release_resource_name}",
        headers=headers,
        timeout=15,
    )

    if get_resp.status_code == 200:
        # Update existing release — PATCH with field mask in body
        resp = requests.patch(
            f"{BASE_URL}/{release_resource_name}",
            headers=headers,
            json={"release": release_body, "updateMask": "rulesetName"},
            timeout=15,
        )
    else:
        # Create new release
        resp = requests.post(
            f"{BASE_URL}/projects/{project_id}/releases",
            headers=headers,
            json=release_body,
            timeout=15,
        )

    if not resp.ok:
        raise RuntimeError(f"{resp.status_code} {resp.text}")
    resp.raise_for_status()


def deploy_rules(project_id: str = None, service_account_path: str = None) -> dict:
    """
    Deploy Firestore security rules.
    Returns {"success": True} or {"success": False, "error": "..."}.
    """
    # Fall back to environment / .env file
    if not project_id:
        project_id = os.environ.get("FIREBASE_PROJECT_ID", "trading-bot-f3bd5")

    if not service_account_path:
        service_account_path = os.environ.get(
            "SERVICE_ACCOUNT_PATH",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "service_account.json"),
        )

    if not os.path.exists(service_account_path):
        return {
            "success": False,
            "error": (
                f"Service account key not found at: {service_account_path}\n"
                "Download it once from Firebase Console → Project Settings → Service Accounts → Generate new private key\n"
                "Save as service_account.json in the project root."
            ),
        }

    try:
        token = _get_access_token(service_account_path)
        ruleset_name = _create_ruleset(project_id, token)
        _update_release(project_id, ruleset_name, token)
        return {"success": True, "ruleset": ruleset_name}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    result = deploy_rules()
    if result["success"]:
        print(f"✓ Firestore rules deployed: {result['ruleset']}")
    else:
        print(f"✗ Failed: {result['error']}")
