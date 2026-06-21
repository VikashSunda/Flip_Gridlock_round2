"""External integration readiness helpers.

The hackathon demo can run without third-party credentials, but the UI should
be explicit about whether a live provider is connected or a deterministic
offline fallback is being used.
"""

import os
from typing import Optional

from dotenv import load_dotenv


def _present(value: Optional[str]) -> bool:
    return bool(value and value.strip() and "your_" not in value.lower())


def get_integration_status() -> dict:
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

    gemini_key = os.getenv("GEMINI_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    mappls_client_id = os.getenv("MAPMYINDIA_CLIENT_ID") or os.getenv("MAPPLS_CLIENT_ID")
    mappls_client_secret = os.getenv("MAPMYINDIA_CLIENT_SECRET") or os.getenv("MAPPLS_CLIENT_SECRET")
    mappls_api_key = os.getenv("MAPMYINDIA_API_KEY") or os.getenv("MAPPLS_API_KEY")

    mappls_ready = _present(mappls_client_id) and _present(mappls_client_secret)

    return {
        "gemini": {
            "status": "connected" if _present(gemini_key) else "fallback",
            "model": gemini_model,
            "fallback": "deterministic command synthesis",
        },
        "mapmyindia": {
            "status": "connected" if mappls_ready else "offline_fallback",
            "credential_type": "oauth_client" if mappls_ready else "missing_client_credentials",
            "has_api_key": _present(mappls_api_key),
            "fallback": "local Bengaluru proximity graph + haversine distances",
            "needed_env": [
                "MAPMYINDIA_CLIENT_ID",
                "MAPMYINDIA_CLIENT_SECRET",
            ],
        },
    }
