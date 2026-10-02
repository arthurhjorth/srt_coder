from __future__ import annotations

import asyncio
import csv
from io import StringIO
import json

import pytest

from coding_books.simplified_v5.models import (
    ComparisonCoding,
    ComparisonFields,
    DifferentiationCoding,
    DifferentiationFields,
    NuanceCoding,
    NuanceFields,
    Perspective,
)
from domain.simplified_agreement_service_v5 import (
    AgreementRules,
    build_agreement_report,
    field_has_agreement,
    report_as_csv,
    report_as_json,
)
from tests.test_simplified_v5_agreement import _entry, _source, _span
from ui.pages.agreement_v5 import _field_rows, _field_status, _render_entry


@pytest.mark.parametrize(
    "coding,path",
    [
        (DifferentiationCoding(), "differentiation.thing_being_considered"),
        (ComparisonCoding(), "comparison.thing_a"),
        (NuanceCoding(), "nuance.x_y_connection"),
    ],
)
def test_one_partial_overlap_is_enough_for_a_multi_span_field(coding, path) -> None:
    left = _source(
        [_entry("left", coding, {path: [_span(0, 5), _span(20, 25)]})], "left", 0
    )
    right = _source(
        [_entry("right", coding, {path: [_span(2, 7), _span(40, 45)]})], "right", 1
    )
    pair = build_agreement_report([left, right]).pair_agreements[0]

    assert len(pair.field_matches) == 1
    assert pair.field_agreement.true_positives == 1
    assert pair.field_agreement.false_positives == 0
    assert pair.field_agreement.false_negatives == 0
    assert pair.field_agreement.f1 == 1.0
    assert _field_status(left, left.codings[0], path, pair) == "match"
    assert _field_status(right, right.codings[0], path, pair) == "match"
    # The original per-span diagnostic remains distinct in exported reports.
    assert pair.f1 == 0.5
    assert len(pair.object_alignments) == 1


def test_extra_spans_do_not_inflate_field_counts_or_require_matching_boundaries() -> None:
    path = "nuance.x_y_connection"
    left = _source(
        [_entry("left", NuanceCoding(), {path: [_span(0, 5), _span(10, 15), _span(20, 25)]})],
        "left",
        0,
    )
    right = _source(
        [_entry("right", NuanceCoding(), {path: [_span(1, 4)]})], "right", 1
    )
    partial = build_agreement_report([left, right]).pair_agreements[0]
    exact = build_agreement_report(
        [left, right], AgreementRules(span_mode="exact")
    ).pair_agreements[0]
    assert partial.field_agreement.true_positives == 1
    assert partial.field_agreement.f1 == 1.0
    assert exact.field_agreement.true_positives == 0


def test_nonoverlapping_span_collections_disagree() -> None:
    path = "nuance.x_y_connection"
    left = _source(
        [_entry("left", NuanceCoding(), {path: [_span(0, 5), _span(10, 15)]})], "left", 0
    )
    right = _source(
        [_entry("right", NuanceCoding(), {path: [_span(20, 25), _span(30, 35)]})], "right", 1
    )
    pair = build_agreement_report([left, right]).pair_agreements[0]
    assert pair.field_agreement.true_positives == 0
    assert pair.field_agreement.false_positives == 1
    assert pair.field_agreement.false_negatives == 1
    assert _field_status(left, left.codings[0], path, pair) == "mismatch"


def test_field_coloring_and_score_only_use_the_displayed_object_pair() -> None:
    left = _source(
        [
            _entry("a1", ComparisonCoding(), {
                "comparison.thing_a": [_span(0, 5)],
                "comparison.relation": [_span(20, 25)],
            }),
            _entry("a2", ComparisonCoding(), {
                "comparison.thing_a": [_span(100, 105)],
                "comparison.relation": [_span(40, 45)],
            }),
        ], "left", 0,
    )
    right = _source(
        [
            _entry("b1", ComparisonCoding(), {
                "comparison.thing_a": [_span(0, 5)],
                "comparison.relation": [_span(40, 45)],
            }),
            _entry("b2", ComparisonCoding(), {
                "comparison.thing_a": [_span(100, 105)],
                "comparison.relation": [_span(20, 25)],
            }),
        ], "right", 1,
    )
    pair = build_agreement_report([left, right]).pair_agreements[0]
    assert {(item.left_coding_id, item.right_coding_id) for item in pair.object_alignments} == {
        ("a1", "b1"), ("a2", "b2")
    }
    assert pair.field_agreement.f1 == 0.5
    for source in (left, right):
        for entry in source.codings:
            assert _field_status(source, entry, "comparison.thing_a", pair) == "match"
            assert _field_status(source, entry, "comparison.relation", pair) == "mismatch"
    assert not field_has_agreement(
        pair, source_index=2, coding_id="a1", field_path="comparison.thing_a"
    )


def test_reordered_perspectives_are_counted_once_as_fields() -> None:
    left = _source([_entry("left", DifferentiationCoding(fields=DifferentiationFields(
        perspectives=[Perspective(text="staff"), Perspective(text="leaders")]
    )), {
        "differentiation.perspectives[0].text": [_span(0, 5), _span(30, 35)],
        "differentiation.perspectives[1].text": [_span(10, 15)],
    })], "left", 0)
    right = _source([_entry("right", DifferentiationCoding(fields=DifferentiationFields(
        perspectives=[Perspective(text="leaders"), Perspective(text="staff")]
    )), {
        "differentiation.perspectives[0].text": [_span(10, 15)],
        "differentiation.perspectives[1].text": [_span(1, 4)],
    })], "right", 1)
    pair = build_agreement_report([left, right]).pair_agreements[0]
    assert pair.field_agreement.true_positives == 2
    assert pair.field_agreement.f1 == 1.0
    assert pair.parent_code_summaries[0].matched_perspective_pairs == 2


def test_rewrites_and_their_possible_span_paths_are_neutral_and_not_scored() -> None:
    left = _source([_entry("left", NuanceCoding(fields=NuanceFields(
        x_y_connection_rewritten=True, x_y_connection_rewrite="More training reduces mistakes"
    )), {
        "nuance.outcome_or_goal_y": [_span(0, 5)],
        "nuance.x_y_connection_rewrite": [_span(30, 35)],
        "nuance.x_y_connection_rewritten": [_span(40, 45)],
    })], "left", 0)
    right = _source([_entry("right", NuanceCoding(fields=NuanceFields(
        x_y_connection_rewritten=False, x_y_connection_rewrite="A different interpretation"
    )), {"nuance.outcome_or_goal_y": [_span(0, 5)]})], "right", 1)
    pair = build_agreement_report([left, right]).pair_agreements[0]
    assert len(left.annotations) == 1
    assert pair.field_agreement.f1 == 1.0
    assert pair.f1 == 1.0
    assert pair.categorical_total == 0
    rewrite_rows = [
        row for row in _field_rows(left.codings[0])
        if row[0] in {"nuance.x_y_connection_rewrite", "nuance.x_y_connection_rewritten"}
    ]
    assert len(rewrite_rows) == 2
    assert all(row[3] for row in rewrite_rows)


def test_downloads_distinguish_field_agreement_from_span_diagnostics() -> None:
    path = "nuance.x_y_connection"
    left = _source([_entry("left", NuanceCoding(), {
        path: [_span(0, 5), _span(20, 25)]
    })], "left", 0)
    right = _source([_entry("right", NuanceCoding(), {
        path: [_span(1, 4)]
    })], "right", 1)
    report = build_agreement_report([left, right])
    payload = json.loads(report_as_json(report))
    assert payload["pairs"][0]["field_agreement"]["f1"] == 1.0
    assert len(payload["pairs"][0]["field_matches"]) == 1
    assert "Each field counts once" in payload["metric_definitions"]["field_agreement"]
    row = next(csv.DictReader(StringIO(report_as_csv(report).lstrip("\ufeff"))))
    assert row["field_true_positives"] == "1"
    assert row["field_f1"] == "1.000000"


def test_comparison_card_lists_each_span_and_keeps_comments_with_their_span(tmp_path, monkeypatch) -> None:
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation

    monkeypatch.setattr(Storage, "path", tmp_path / "sessions")

    span = _span(0, 5, text="first passage").model_copy(update={"comment": "first comment"})
    left = _source([_entry("left", ComparisonCoding(fields=ComparisonFields(
        thing_a="first passage\nsecond passage"
    )), {"comparison.thing_a": [span, _span(20, 25, text="second passage")]})], "left", 0)
    right = _source([_entry("right", ComparisonCoding(), {
        "comparison.thing_a": [_span(1, 4)]
    })], "right", 1)
    pair = build_agreement_report([left, right]).pair_agreements[0]

    async def scenario() -> None:
        async with user_simulation(root=lambda: _render_entry(left, left.codings[0], pair)) as user:
            await user.open("/")
            items = [item for item in user.current_layout.descendants() if item.tag == "li"]
            assert len(items) == 2
            first_labels = [getattr(item, "text", None) for item in items[0].descendants()]
            second_labels = [getattr(item, "text", None) for item in items[1].descendants()]
            assert "first passage" in first_labels
            assert "Comment: first comment" in first_labels
            assert "second passage" in second_labels
            assert "Comment: first comment" not in second_labels

    asyncio.run(scenario())
