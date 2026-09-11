from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INTERVIEW_DATA_DIR = Path(
    os.getenv("SRT_CODER_INTERVIEW_DATA_DIR", str(BASE_DIR / "interview_data"))
).expanduser().resolve()
CODED_DATA_DIR = Path(
    os.getenv("SRT_CODER_CODED_DATA_DIR", str(BASE_DIR / "coded_data"))
).expanduser().resolve()
EXPORTS_DIR = CODED_DATA_DIR / "exports"
RUNTIME_DIR = Path(
    os.getenv("SRT_CODER_RUNTIME_DIR", str(BASE_DIR / ".runtime"))
).expanduser().resolve()
USERS_JSON = CODED_DATA_DIR / "users.json"
ANALYSES_JSON = CODED_DATA_DIR / "analyses.json"
CODINGS_JSON = CODED_DATA_DIR / "codings.json"
CODINGS_V4_JSON = CODED_DATA_DIR / "codings_v4.json"
EXPORTS_V4_DIR = CODED_DATA_DIR / "exports_v4"
SIMPLIFIED_CODINGS_JSON = CODED_DATA_DIR / "codings_simplified.json"
SIMPLIFIED_EXPORTS_DIR = CODED_DATA_DIR / "exports_simplified"

APP_TITLE = "SRT Coder"
APP_HOST = os.getenv("SRT_CODER_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("SRT_CODER_PORT", "8085"))
STORAGE_SECRET = os.getenv(
    "SRT_CODER_STORAGE_SECRET",
    "srt-coder-dev-secret-change-me",
)
