import pytest
from pydantic import ValidationError

from coding_books.simplified_v5.models import (
    ComparisonCoding,
    DifferentiationCoding,
    DifferentiationFields,
    NuanceCoding,
    NuanceFields,
    Perspective,
    PerspectiveType,
    TranscriptSpan,
)
from coding_books.simplified_v5.validation import completion_issues


def test_all_v5_coding_types_can_be_saved_empty() -> None:
    assert ComparisonCoding().fields.text_passage is None
    assert DifferentiationCoding().fields.perspectives == []
    assert NuanceCoding().fields.relation_type is None


def test_perspective_owns_types_and_dropdown_comment_and_strips_whitespace() -> None:
    coding = DifferentiationCoding(
        fields=DifferentiationFields(
            thing_being_considered="  emnet  ",
            perspectives=[
                Perspective(
                    text="  medarbejderne  ",
                    perspective_types=[PerspectiveType.ACTORS_ROLES],
                    perspective_types_comment="  type note  ",
                )
            ],
        )
    )
    row = coding.fields.perspectives[0]
    assert coding.fields.thing_being_considered == "emnet"
    assert row.text == "medarbejderne"
    assert row.perspective_types == [PerspectiveType.ACTORS_ROLES]
    assert row.perspective_types_comment == "type note"


def test_dropdowns_have_adjacent_comments() -> None:
    fields = NuanceFields.model_fields
    for name in ("relation_type", "expressed_certainty"):
        assert f"{name}_comment" in fields


def test_each_transcript_span_owns_its_optional_comment() -> None:
    span = TranscriptSpan(
        start_segment_id="seg-00001",
        start_char_offset=0,
        end_segment_id="seg-00001",
        end_char_offset=4,
        selected_text=" text ",
        comment="  why this was coded  ",
    )
    assert span.selected_text == "text"
    assert span.comment == "why this was coded"


def test_v5_rejects_ambition_intention() -> None:
    with pytest.raises(ValidationError):
        NuanceCoding.model_validate(
            {
                "code_type": "nuance",
                "fields": {"relation_type": "ambition_intention"},
            }
        )


def test_nuance_rewrite_is_optional_and_trims_outer_whitespace() -> None:
    legacy = NuanceFields.model_validate({"x_y_connection": "original wording"})
    assert legacy.x_y_connection_rewritten is None
    assert legacy.x_y_connection_rewrite is None
    assert legacy.x_y_connection_rewrite_comment is None
    rewritten = NuanceFields(
        x_y_connection_rewritten=True,
        x_y_connection_rewrite="  More training reduces mistakes.  ",
        x_y_connection_rewrite_comment="  The connection is implicit.  ",
    )
    assert rewritten.x_y_connection_rewrite == "More training reduces mistakes."
    assert rewritten.x_y_connection_rewrite_comment == "The connection is implicit."


@pytest.mark.parametrize("comment", [None, "", "  ", "A coder explanation"])
def test_rewrite_comment_is_optional_and_does_not_affect_completeness(comment) -> None:
    fields = NuanceFields(
        relation_type="expected_effect",
        influence_or_action_x="training",
        outcome_or_goal_y="fewer mistakes",
        expressed_certainty="qualified",
        x_y_connection_rewritten=True,
        x_y_connection_rewrite="Training may reduce mistakes.",
        x_y_connection_rewrite_comment=comment,
    )
    assert completion_issues(NuanceCoding(fields=fields)) == []


def test_saved_rewrite_can_satisfy_connection_completeness() -> None:
    fields = NuanceFields(
        relation_type="expected_effect",
        influence_or_action_x="training",
        outcome_or_goal_y="fewer mistakes",
        expressed_certainty="qualified",
        x_y_connection_rewritten=True,
        x_y_connection_rewrite="Training may reduce mistakes.",
    )
    assert completion_issues(NuanceCoding(fields=fields)) == []
    # A retained but unchecked rewrite does not act as active coding content.
    fields.x_y_connection_rewritten = False
    assert "X–Y-forbindelse mangler." in completion_issues(NuanceCoding(fields=fields))
    fields.x_y_connection_rewritten = True
    fields.x_y_connection_rewrite = " "
    issues = completion_issues(NuanceCoding(fields=fields))
    assert "X–Y-forbindelse mangler." in issues
    assert "Omskrevet X–Y-forbindelse mangler." in issues
