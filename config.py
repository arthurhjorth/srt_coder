from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INTERVIEW_DATA_DIR = BASE_DIR / "interview_data"
CODED_DATA_DIR = BASE_DIR / "coded_data"
EXPORTS_DIR = CODED_DATA_DIR / "exports"
USERS_JSON = CODED_DATA_DIR / "users.json"
ANALYSES_JSON = CODED_DATA_DIR / "analyses.json"
CODINGS_JSON = CODED_DATA_DIR / "codings.json"

APP_TITLE = "SRT Coder"
APP_HOST = os.getenv("SRT_CODER_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("SRT_CODER_PORT", "8085"))
STORAGE_SECRET = os.getenv(
    "SRT_CODER_STORAGE_SECRET",
    "srt-coder-dev-secret-change-me",
)
