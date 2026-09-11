from __future__ import annotations

import json

from coding_books.simplified_v5.models import (
    ComparisonCoding,
    ComparisonFields,
    DifferentiationCoding,
    DifferentiationFields,
    NuanceCoding,
    NuanceFields,
    Perspective,
    SimplifiedCodingEntry,
    TranscriptSpan,
)
from coding_books.simplified_v4.models import (
    NuanceCoding as V4NuanceCoding,
    NuanceFields as V4NuanceFields,
    NuanceRelationType as V4NuanceRelationType,
    SimplifiedCodingEntry as V4Entry,
    TranscriptSpan as V4TranscriptSpan,
)
from core_models import Analysis
from domain.simplified_agreement_service_v5 import (
    AgreementRules,
    build_agreement_report,
    load_agreement_export,
    matched_annotation_keys,
    report_as_csv,
    report_as_json,
)


def _span(start: int, end: int, *, text: str = "text", segment: str = "seg-00001"):
    return TranscriptSpan(
        start_segment_id=segment,
        start_char_offset=start,
        end_segment_id=segment,
        end_char_offset=end,
        selected_text=text,
    )


def _entry(coding_id: str, coding, spans: dict[str, list[TranscriptSpan]]):
    return SimplifiedCodingEntry(
        coding_id=coding_id,
        analysis_id=f"analysis-{coding_id}",
        interview_file="test.srt",
        coding=coding,
        field_spans=spans,
        created_by="coder",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _payload(entries, owner: str):
    return {
        "export_format_version": 1,
        "coding_book_version": 5,
        "analyses": [
            Analysis(
                analysis_id=entries[0].analysis_id,
                owner_username=owner,
                interview_file="test.srt",
                name=owner,
            ).model_dump(mode="json")
        ],
        "codings": [entry.model_dump(mode="json") for entry in entries],
        "users": [],
    }


def _source(entries, owner: str, index: int):
    return load_agreement_export(
        json.dumps(_payload(entries, owner)),
        source_name=f"{owner}.json",
        source_index=index,
        content_hash=f"hash-{index}",
    )


def test_maximum_cardinality_matching_fixes_greedy_undercount() -> None:
    left = _source(
        [
            _entry(
                "left-only-b1",
                NuanceCoding(fields=NuanceFields(x_y_connection="one")),
                {"nuance.x_y_connection": [_span(0, 3)]},
            ),
            _entry(
                "left-flexible",
                NuanceCoding(fields=NuanceFields(x_y_connection="wide")),
                {"nuance.x_y_connection": [_span(0, 7)]},
            ),
        ],
        "left",
        0,
    )
    right = _source(
        [
            _entry(
                "right-second",
                NuanceCoding(fields=NuanceFields(x_y_connection="second")),
                {"nuance.x_y_connection": [_span(4, 7)]},
            ),
            _entry(
                "right-first",
                NuanceCoding(fields=NuanceFields(x_y_connection="first")),
                {"nuance.x_y_connection": [_span(0, 3)]},
            ),
        ],
        "right",
        1,
    )
    pair = build_agreement_report([left, right]).pair_agreements[0]
    assert pair.true_positives == 2
    assert pair.f1 == 1.0


def test_span_comments_do_not_change_agreement_or_annotation_totals() -> None:
    left = _source(
        [
            _entry(
                "comment",
                NuanceCoding(fields=NuanceFields(x_y_connection="reason")),
                {
                    "nuance.x_y_connection": [
                        _span(0, 4).model_copy(update={"comment": "left explanation"})
                    ],
                    "nuance.coder_note": [_span(5, 7)],
                },
            )
        ],
        "left",
        0,
    )
    right = _source(
        [
            _entry(
                "comment-right",
                NuanceCoding(fields=NuanceFields(x_y_connection="reason")),
                {
                    "nuance.x_y_connection": [
                        _span(0, 4).model_copy(update={"comment": "different explanation"})
                    ]
                },
            )
        ],
        "right",
        1,
    )
    assert len(left.annotations) == 1
    pair = build_agreement_report([left, right]).pair_agreements[0]
    assert pair.true_positives == 1
    assert pair.f1 == 1.0


def test_matching_status_is_annotation_specific_not_global_by_field_name() -> None:
    left = _source(
        [
            _entry(
                "left-match",
                NuanceCoding(fields=NuanceFields(x_y_connection="match")),
                {"nuance.x_y_connection": [_span(0, 3)]},
            ),
            _entry(
                "left-unmatched",
                NuanceCoding(fields=NuanceFields(x_y_connection="unique")),
                {"nuance.x_y_connection": [_span(20, 23)]},
            ),
        ],
        "left",
        0,
    )
    right = _source(
        [
            _entry(
                "right-match",
                NuanceCoding(fields=NuanceFields(x_y_connection="match")),
                {"nuance.x_y_connection": [_span(1, 4)]},
            )
        ],
        "right",
        1,
    )
    pair = build_agreement_report([left, right]).pair_agreements[0]
    matched = matched_annotation_keys(pair)
    left_by_id = {annotation.coding_id: annotation for annotation in left.annotations}
    assert left_by_id["left-match"].key in matched
    assert left_by_id["left-unmatched"].key not in matched


def test_categorical_agreement_is_separate_for_aligned_objects() -> None:
    left_coding = DifferentiationCoding(
        fields=DifferentiationFields(
            perspectives=[Perspective(text="staff", perspective_types=["actors_roles"])]
        )
    )
    right_coding = DifferentiationCoding(
        fields=DifferentiationFields(
            perspectives=[Perspective(text="staff", perspective_types=["goals"])]
        )
    )
    left = _source(
        [_entry("left", left_coding, {"differentiation.perspectives[0].text": [_span(0, 5)]})],
        "left",
        0,
    )
    right = _source(
        [_entry("right", right_coding, {"differentiation.perspectives[0].text": [_span(0, 5)]})],
        "right",
        1,
    )
    pair = build_agreement_report([left, right]).pair_agreements[0]
    assert pair.f1 == 1.0
    assert pair.categorical_total == 1
    assert pair.categorical_matches == 0
    assert pair.categorical_agreement == 0.0


def test_parent_code_summary_and_review_items_cover_every_object_once() -> None:
    left = _source(
        [
            _entry(
                "left-diff",
                DifferentiationCoding(
                    fields=DifferentiationFields(thing_being_considered="focus")
                ),
                {
                    "differentiation.thing_being_considered": [
                        _span(0, 8, segment="seg-00001")
                    ]
                },
            ),
            _entry(
                "left-comparison-primary",
                ComparisonCoding(fields=ComparisonFields(thing_a="first thing")),
                {"comparison.thing_a": [_span(0, 8, segment="seg-00002")]},
            ),
            _entry(
                "left-nuance-only",
                NuanceCoding(fields=NuanceFields(outcome_or_goal_y="left outcome")),
                {"nuance.outcome_or_goal_y": [_span(0, 8, segment="seg-00003")]},
            ),
            _entry(
                "left-comparison-partial",
                ComparisonCoding(fields=ComparisonFields(relation="more than")),
                {"comparison.relation": [_span(0, 8, segment="seg-00004")]},
            ),
        ],
        "left",
        0,
    )
    right = _source(
        [
            _entry(
                "right-diff",
                DifferentiationCoding(
                    fields=DifferentiationFields(thing_being_considered="same focus")
                ),
                {
                    "differentiation.thing_being_considered": [
                        _span(3, 10, segment="seg-00001")
                    ]
                },
            ),
            _entry(
                "right-comparison-primary",
                ComparisonCoding(fields=ComparisonFields(thing_b="first thing")),
                {"comparison.thing_b": [_span(2, 9, segment="seg-00002")]},
            ),
            _entry(
                "right-comparison-partial",
                ComparisonCoding(fields=ComparisonFields(comparison_basis="degree")),
                {"comparison.comparison_basis": [_span(2, 6, segment="seg-00004")]},
            ),
            _entry(
                "right-nuance-only",
                NuanceCoding(fields=NuanceFields(outcome_or_goal_y="right outcome")),
                {"nuance.outcome_or_goal_y": [_span(0, 8, segment="seg-00009")]},
            ),
        ],
        "right",
        1,
    )

    pair = build_agreement_report([left, right]).pair_agreements[0]
    summaries = {item.object_type: item for item in pair.parent_code_summaries}

    differentiation = summaries["differentiation"]
    assert differentiation.left_identified == 1
    assert differentiation.right_identified == 1
    assert differentiation.overlap == 1
    assert differentiation.primary_field_overlap == 1
    assert differentiation.partial_only == 0
    assert differentiation.no_overlap_left == 0
    assert differentiation.no_overlap_right == 0

    comparison = summaries["comparison"]
    assert comparison.left_identified == 2
    assert comparison.right_identified == 2
    assert comparison.overlap == 2
    assert comparison.primary_field_overlap == 1
    assert comparison.partial_only == 1
    assert comparison.no_overlap_left == 0
    assert comparison.no_overlap_right == 0

    nuance = summaries["nuance"]
    assert nuance.left_identified == 1
    assert nuance.right_identified == 1
    assert nuance.overlap == 0
    assert nuance.primary_field_overlap == 0
    assert nuance.partial_only == 0
    assert nuance.no_overlap_left == 1
    assert nuance.no_overlap_right == 1

    for summary in pair.parent_code_summaries:
        assert summary.overlap == summary.primary_field_overlap + summary.partial_only
        assert summary.left_identified == summary.overlap + summary.no_overlap_left
        assert summary.right_identified == summary.overlap + summary.no_overlap_right

    assert [item.start_segment_id for item in pair.object_review_items] == [
        "seg-00001",
        "seg-00002",
        "seg-00003",
        "seg-00004",
        "seg-00009",
    ]
    assert [item.agreement_status for item in pair.object_review_items] == [
        "primary_field_overlap",
        "primary_field_overlap",
        "no_overlap",
        "partial_only",
        "no_overlap",
    ]
    assert pair.object_review_items[2].left_coding_id == "left-nuance-only"
    assert pair.object_review_items[2].right_coding_id is None
    assert pair.object_review_items[4].left_coding_id is None
    assert pair.object_review_items[4].right_coding_id == "right-nuance-only"


def test_report_downloads_contain_pairwise_results() -> None:
    left = _source(
        [_entry("left", NuanceCoding(), {"nuance.x_y_connection": [_span(0, 2)]})],
        "left",
        0,
    )
    right = _source(
        [_entry("right", NuanceCoding(), {"nuance.x_y_connection": [_span(0, 2)]})],
        "right",
        1,
    )
    report = build_agreement_report([left, right], AgreementRules(span_mode="exact"))
    payload = json.loads(report_as_json(report))
    assert payload["pairs"][0]["true_positives"] == 1
    assert payload["pairs"][0]["parent_code_summaries"][2] == {
        "object_type": "nuance",
        "left_identified": 1,
        "right_identified": 1,
        "overlap": 1,
        "primary_field_overlap": 0,
        "partial_only": 1,
        "no_overlap_left": 0,
        "no_overlap_right": 0,
    }
    assert payload["pairs"][0]["object_review_items"][0]["agreement_status"] == (
        "partial_only"
    )
    csv_text = report_as_csv(report)
    assert csv_text.startswith("\ufeffleft_source,right_source")
    assert "1.000000" in csv_text
    assert "nuance_primary_field_overlap" in csv_text


def test_v4_agreement_upload_is_migrated_in_memory() -> None:
    entry = V4Entry(
        coding_id="old-ambition",
        analysis_id="analysis-old",
        interview_file="test.srt",
        coding=V4NuanceCoding(
            fields=V4NuanceFields(
                relation_type=V4NuanceRelationType.AMBITION_INTENTION,
                x_y_connection="will lead to",
            )
        ),
        field_spans={
            "nuance.x_y_connection": [
                V4TranscriptSpan(
                    start_segment_id="seg-00001",
                    start_char_offset=0,
                    end_segment_id="seg-00001",
                    end_char_offset=4,
                    selected_text="text",
                )
            ]
        },
        created_by="old-coder",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    payload = {
        "export_format_version": 1,
        "coding_book_version": 4,
        "analyses": [
            Analysis(
                analysis_id="analysis-old",
                owner_username="old-coder",
                interview_file="test.srt",
            ).model_dump(mode="json")
        ],
        "codings": [entry.model_dump(mode="json")],
        "users": [],
    }
    source = load_agreement_export(
        json.dumps(payload), source_name="old.json", source_index=0
    )
    assert source.codings[0].coding.fields.relation_type.value == "expected_effect"
