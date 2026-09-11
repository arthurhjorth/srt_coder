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
