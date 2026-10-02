from __future__ import annotations

import asyncio
import json
import re

from nicegui import ui
from nicegui.storage import Storage
from nicegui.testing.user_simulation import user_simulation

from coding_books.simplified_v5.models import NuanceCoding, NuanceFields
from core_models import Analysis
from domain import simplified_coding_service_v5 as service
from domain.transcript_service import TranscriptDocument
from storage import simplified_coding_repo_v5 as repo
from tests.test_simplified_v5_agreement import _entry, _payload, _span
from ui.pages import agreement_v5, analysis_v5


def test_nuance_rewrite_toggle_save_reload_and_completeness(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Storage, "path", tmp_path / "sessions")
    monkeypatch.setattr(repo, "SIMPLIFIED_CODINGS_JSON", tmp_path / "codings_simplified.json")
    entry = _entry("nuance", NuanceCoding(fields=NuanceFields(
        relation_type="expected_effect", influence_or_action_x="training",
        outcome_or_goal_y="fewer mistakes", expressed_certainty="qualified",
    )), {"nuance.outcome_or_goal_y": [_span(0, 5)]})
    repo.save_codings([entry])
    analysis = Analysis(analysis_id=entry.analysis_id, interview_file=entry.interview_file)
    monkeypatch.setattr(analysis_v5, "get_analysis", lambda _: analysis)
    monkeypatch.setattr(analysis_v5, "require_auth_or_redirect", lambda: True)
    monkeypatch.setattr(analysis_v5, "current_username", lambda: "coder")
    monkeypatch.setattr(analysis_v5, "top_nav", lambda: None)
    monkeypatch.setattr(analysis_v5, "set_selected_analysis_id", lambda _: None)
    monkeypatch.setattr(analysis_v5, "set_selected_interview_file", lambda _: None)
    monkeypatch.setattr(analysis_v5, "load_transcript", lambda _: TranscriptDocument(
        source_file=entry.interview_file, segments=[], speakers=[]
    ))
    rewrite_marker = "x-y-connection-rewrite"
    comment_marker = "x-y-connection-rewrite-comment"

    async def scenario() -> None:
        async with user_simulation(root=lambda: analysis_v5.render_analysis_page(entry.analysis_id)) as user:
            user.javascript_rules[re.compile(r"(?s).*__srt_selection_revision.*")] = lambda _: {
                "revision": 0, "payload": None,
            }
            await user.open("/")
            await user.should_not_see(kind=ui.textarea, marker=rewrite_marker)
            await user.should_not_see(kind=ui.textarea, marker=comment_marker)
            user.find(kind=ui.checkbox, content="Omskrevet X–Y-forbindelse?").click()
            await user.should_see(kind=ui.textarea, marker=rewrite_marker)
            await user.should_see(kind=ui.textarea, marker=comment_marker)
            user.find(kind=ui.textarea, marker=rewrite_marker).type(
                "  More training may reduce mistakes.  "
            ).trigger("blur")
            await user.should_see("Recommended fields complete.")
            user.find(kind=ui.textarea, marker=comment_marker).type(
                "  The causal connection is implicit here.  "
            ).trigger("blur")
            loaded = repo.list_codings()[0]
            assert loaded.coding.fields.x_y_connection_rewritten is True
            assert loaded.coding.fields.x_y_connection_rewrite == "More training may reduce mistakes."
            assert loaded.coding.fields.x_y_connection_rewrite_comment == "The causal connection is implicit here."
            assert loaded.coding.fields.x_y_connection is None
            assert loaded.field_spans == entry.field_spans

            # Refresh from disk, then uncheck without deleting the rewrite or comment.
            await user.open("/")
            await user.should_see("More training may reduce mistakes.")
            await user.should_see("The causal connection is implicit here.")
            user.find(kind=ui.checkbox, content="Omskrevet X–Y-forbindelse?").click()
            await user.should_not_see(kind=ui.textarea, marker=rewrite_marker)
            await user.should_not_see(kind=ui.textarea, marker=comment_marker)
            await user.should_see("X–Y-forbindelse mangler.")
            loaded = repo.list_codings()[0]
            assert loaded.coding.fields.x_y_connection_rewritten is False
            assert loaded.coding.fields.x_y_connection_rewrite == "More training may reduce mistakes."
            assert loaded.coding.fields.x_y_connection_rewrite_comment == "The causal connection is implicit here."

            # Empty comments remain valid, and clearing one preserves the rewrite and evidence.
            user.find(kind=ui.checkbox, content="Omskrevet X–Y-forbindelse?").click()
            await user.should_see(kind=ui.textarea, marker=comment_marker)
            next(iter(user.find(kind=ui.textarea, marker=comment_marker).elements)).set_value("  ")
            user.find(kind=ui.textarea, marker=comment_marker).trigger("blur")
            await user.should_see("Recommended fields complete.")
            loaded = repo.list_codings()[0]
            assert loaded.coding.fields.x_y_connection_rewrite_comment is None
            assert loaded.coding.fields.x_y_connection_rewrite == "More training may reduce mistakes."
            assert loaded.field_spans == entry.field_spans

    asyncio.run(scenario())


def test_agreement_upload_shows_field_score_bullets_and_downloads(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Storage, "path", tmp_path / "sessions")
    monkeypatch.setattr(agreement_v5, "require_auth_or_redirect", lambda: True)
    monkeypatch.setattr(agreement_v5, "top_nav", lambda: None)
    left = _entry("left", NuanceCoding(fields=NuanceFields(
        x_y_connection_rewritten=True, x_y_connection_rewrite="Training reduces mistakes.",
        x_y_connection_rewrite_comment="The causal connection is implicit here.",
    )), {"nuance.x_y_connection": [
        _span(0, 5, text="first passage"), _span(20, 25, text="extra passage")
    ]})
    right = _entry("right", NuanceCoding(), {
        "nuance.x_y_connection": [_span(1, 4, text="shared passage")]
    })

    async def scenario() -> None:
        async with user_simulation(root=agreement_v5.render_agreement_page) as user:
            await user.open("/")
            upload = next(iter(user.find(ui.upload).elements))
            response = await user.http_client.post(upload.props["url"], files=[
                ("left", ("left.json", json.dumps(_payload([left], "left")), "application/json")),
                ("right", ("right.json", json.dumps(_payload([right], "right")), "application/json")),
            ])
            assert response.status_code == 200
            await user.should_see("Field agreement F1 100.0%")
            await user.should_see("extra passage")
            await user.should_see("Training reduces mistakes.")
            await user.should_see("The causal connection is implicit here.")
            items = [item for item in user.current_layout.descendants() if item.tag == "li"]
            assert len(items) == 3
            user.find("Download JSON").click()
            download = await user.download.next()
            payload = download.json()
            assert payload["pairs"][0]["field_agreement"]["f1"] == 1.0
            user.find("Download CSV").click()
            download = await user.download.next()
            assert "field_f1" in download.text

    asyncio.run(scenario())
