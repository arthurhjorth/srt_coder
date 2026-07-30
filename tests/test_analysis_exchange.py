from __future__ import annotations

from models import Analysis, CodingEntry, User
from domain import analysis_exchange_service


def test_import_skips_analysis_when_transcript_missing() -> None:
    payload = {
        "analyses": [
            {
                "analysis_id": "a-src",
                "owner_username": "alice",
                "interview_file": "missing.srt",
                "name": "Run 1",
            }
        ],
        "codings": [
            {
                "coding_id": "c-src",
                "analysis_id": "a-src",
                "object_type": "comparison",
            }
        ],
        "users": [
            {
                "username": "alice",
                "password_hash": "pbkdf2_sha256$1$aa$bb",
                "is_active": True,
            }
        ],
    }

    saved = {"users": None, "analyses": None, "codings": None}

    orig_list_users = analysis_exchange_service.list_users
    orig_list_analyses = analysis_exchange_service.list_analyses
    orig_list_codings = analysis_exchange_service.list_codings
    orig_save_users = analysis_exchange_service.save_users
    orig_save_analyses = analysis_exchange_service.save_analyses
    orig_save_codings = analysis_exchange_service.save_codings
    orig_list_files = analysis_exchange_service.list_interview_files

    analysis_exchange_service.list_users = lambda: []
    analysis_exchange_service.list_analyses = lambda: []
    analysis_exchange_service.list_codings = lambda: []
    analysis_exchange_service.list_interview_files = lambda: ["existing.srt"]
    analysis_exchange_service.save_users = lambda xs: saved.__setitem__("users", xs)
    analysis_exchange_service.save_analyses = lambda xs: saved.__setitem__("analyses", xs)
    analysis_exchange_service.save_codings = lambda xs: saved.__setitem__("codings", xs)
    try:
        report = analysis_exchange_service.import_analyses_from_payload(payload)
    finally:
        analysis_exchange_service.list_users = orig_list_users
        analysis_exchange_service.list_analyses = orig_list_analyses
        analysis_exchange_service.list_codings = orig_list_codings
        analysis_exchange_service.save_users = orig_save_users
        analysis_exchange_service.save_analyses = orig_save_analyses
        analysis_exchange_service.save_codings = orig_save_codings
        analysis_exchange_service.list_interview_files = orig_list_files

    assert report["imported_analyses"] == 0
    assert report["skipped_missing_transcript"] == 1
    assert report["imported_codings"] == 0


def test_import_recreates_ids_and_matches_existing_by_name() -> None:
    payload = {
        "analyses": [
            {
                "analysis_id": "a-src",
                "owner_username": "alice",
                "interview_file": "file.srt",
                "name": "Run 1",
            }
        ],
        "codings": [
            {
                "coding_id": "c-src",
                "analysis_id": "a-src",
                "object_type": "comparison",
                "created_by": "alice",
            }
        ],
        "users": [
            {
                "username": "alice",
                "password_hash": "pbkdf2_sha256$1$aa$bb",
                "is_active": True,
            }
        ],
    }

    existing_user = User(username="alice", password_hash="hash", is_active=True)
    existing_analysis = Analysis(
        analysis_id="existing",
        owner_username="alice",
        interview_file="file.srt",
        name="Existing Name",
    )

    saved = {"users": None, "analyses": None, "codings": None}

    orig_list_users = analysis_exchange_service.list_users
    orig_list_analyses = analysis_exchange_service.list_analyses
    orig_list_codings = analysis_exchange_service.list_codings
    orig_save_users = analysis_exchange_service.save_users
    orig_save_analyses = analysis_exchange_service.save_analyses
    orig_save_codings = analysis_exchange_service.save_codings
    orig_list_files = analysis_exchange_service.list_interview_files

    analysis_exchange_service.list_users = lambda: [existing_user]
    analysis_exchange_service.list_analyses = lambda: [existing_analysis]
    analysis_exchange_service.list_codings = lambda: []
    analysis_exchange_service.list_interview_files = lambda: ["file.srt"]
    analysis_exchange_service.save_users = lambda xs: saved.__setitem__("users", xs)
    analysis_exchange_service.save_analyses = lambda xs: saved.__setitem__("analyses", xs)
    analysis_exchange_service.save_codings = lambda xs: saved.__setitem__("codings", xs)
    try:
        report = analysis_exchange_service.import_analyses_from_payload(payload)
    finally:
        analysis_exchange_service.list_users = orig_list_users
        analysis_exchange_service.list_analyses = orig_list_analyses
        analysis_exchange_service.list_codings = orig_list_codings
        analysis_exchange_service.save_users = orig_save_users
        analysis_exchange_service.save_analyses = orig_save_analyses
        analysis_exchange_service.save_codings = orig_save_codings
        analysis_exchange_service.list_interview_files = orig_list_files

    assert report["imported_analyses"] == 1
    assert report["imported_users"] == 0
    assert report["imported_codings"] == 1
    assert saved["analyses"] is not None
    imported = [a for a in saved["analyses"] if a.name == "Run 1"]
    assert len(imported) == 1
    assert imported[0].analysis_id != "a-src"
    assert saved["codings"] is not None
    imported_coding = saved["codings"][0]
    assert imported_coding.coding_id != "c-src"
    assert imported_coding.analysis_id == imported[0].analysis_id


def test_import_migrates_legacy_differentiation_before_model_validation() -> None:
    old_field = "why_is_this_a_thing_or_how_did_it_happen_extract"
    target_field = "why_is_it_important_extract"
    payload = {
        "export_version": "1",
        "analyses": [
            {
                "analysis_id": "legacy-analysis",
                "owner_username": "alice",
                "interview_file": "file.srt",
                "name": "Legacy run",
            }
        ],
        "codings": [
            {
                "coding_id": "legacy-coding",
                "analysis_id": "legacy-analysis",
                "interview_file": "file.srt",
                "object_type": "differentiation",
                "created_by": "alice",
                "differentiation": {
                    target_field: "target text",
                    old_field: "legacy text",
                },
                "field_spans": {
                    f"differentiation.{old_field}": [
                        {
                            "start_segment_id": "seg-00001",
                            "start_char_offset": 0,
                            "end_segment_id": "seg-00001",
                            "end_char_offset": 4,
                            "selected_text": "legacy",
                        }
                    ]
                },
            }
        ],
        "users": [{"username": "alice", "is_active": False}],
    }
    saved = {"codings": None}
    originals = {
        "list_users": analysis_exchange_service.list_users,
        "list_analyses": analysis_exchange_service.list_analyses,
        "list_codings": analysis_exchange_service.list_codings,
        "save_users": analysis_exchange_service.save_users,
        "save_analyses": analysis_exchange_service.save_analyses,
        "save_codings": analysis_exchange_service.save_codings,
        "list_interview_files": analysis_exchange_service.list_interview_files,
    }
    analysis_exchange_service.list_users = lambda: []
    analysis_exchange_service.list_analyses = lambda: []
    analysis_exchange_service.list_codings = lambda: []
    analysis_exchange_service.save_users = lambda _items: None
    analysis_exchange_service.save_analyses = lambda _items: None
    analysis_exchange_service.save_codings = lambda items: saved.__setitem__("codings", items)
    analysis_exchange_service.list_interview_files = lambda: ["file.srt"]
    try:
        report = analysis_exchange_service.import_analyses_from_payload(payload)
    finally:
        for name, value in originals.items():
            setattr(analysis_exchange_service, name, value)

    assert report["imported_codings"] == 1
    imported = saved["codings"][0]
    assert imported.differentiation is not None
    assert imported.differentiation.why_is_it_important_extract == "target text\nlegacy text"
    assert f"differentiation.{old_field}" not in imported.field_spans
    assert f"differentiation.{target_field}" in imported.field_spans
