import pytest
from pydantic import ValidationError

from coding_books.simplified_v4.models import (
    ComparisonCoding,
    ComparisonFields,
    DifferentiationCoding,
    DifferentiationFields,
    ExpressedCertainty,
    NuanceCoding,
    NuanceFields,
    NuanceRelationType,
    PerspectiveType,
)
from coding_books.simplified_v4.validation import completion_issues


def test_every_manual_field_can_be_saved_empty() -> None:
    assert DifferentiationFields().model_dump(mode="json") == {
        "thing_being_considered": None,
        "perspectives": [],
        "perspective_types": [],
        "coder_note": None,
    }
    assert ComparisonFields().model_dump(mode="json") == {
        "text_passage": None,
        "thing_a": None,
        "thing_b": None,
        "relation": None,
        "comparison_basis": None,
        "coder_note": None,
    }
    assert NuanceFields().model_dump(mode="json") == {
        "relation_type": None,
        "influence_or_action_x": None,
        "outcome_or_goal_y": None,
        "x_y_connection": None,
        "expressed_certainty": None,
        "limitation": None,
        "coder_note": None,
    }


def test_manual_text_fields_strip_outer_whitespace_including_lists() -> None:
    fields = DifferentiationFields(
        thing_being_considered="  ledelse  ",
        perspectives=["  medarbejderne ", " borgerne  "],
        coder_note="  uklar reference  ",
    )
    assert fields.thing_being_considered == "ledelse"
    assert fields.perspectives == ["medarbejderne", "borgerne"]
    assert fields.coder_note == "uklar reference"


def test_new_models_reject_unknown_legacy_fields() -> None:
    with pytest.raises(ValidationError):
        DifferentiationFields.model_validate(
            {
                "thing_being_considered": "topic",
                "why_is_it_important_extract": "legacy field",
            }
        )


def test_completeness_is_warning_only_and_not_pydantic_validation() -> None:
    empty = DifferentiationCoding()
    assert len(completion_issues(empty)) == 2

    complete = DifferentiationCoding(
        fields=DifferentiationFields(
            thing_being_considered="organisationen",
            perspectives=["ledelsen", "medarbejderne"],
            perspective_types=[PerspectiveType.ACTORS_ROLES],
        )
    )
    assert completion_issues(complete) == []


def test_nuance_certainty_is_conditional_but_remains_losslessly_optional() -> None:
    expected_effect = NuanceCoding(
        fields=NuanceFields(
            relation_type=NuanceRelationType.EXPECTED_EFFECT,
            influence_or_action_x="indsatsen",
            outcome_or_goal_y="bedre kvalitet",
            x_y_connection="kan føre til",
        )
    )
    assert completion_issues(expected_effect) == ["Udtrykt sikkerhed mangler."]

    ambition = NuanceCoding(
        fields=NuanceFields(
            relation_type=NuanceRelationType.AMBITION_INTENTION,
            influence_or_action_x="indsatsen",
            outcome_or_goal_y="bedre kvalitet",
            x_y_connection="for at opnå",
            expressed_certainty=ExpressedCertainty.QUALIFIED,
        )
    )
    assert completion_issues(ambition) == []


def test_comparison_can_be_saved_one_field_at_a_time() -> None:
    coding = ComparisonCoding(fields=ComparisonFields(thing_a="før"))
    assert coding.fields.thing_a == "før"
    assert "Ting B mangler." in completion_issues(coding)
