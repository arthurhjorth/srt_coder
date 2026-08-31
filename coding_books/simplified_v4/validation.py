from __future__ import annotations

from coding_books.simplified_v4.models import (
    ComparisonCoding,
    DifferentiationCoding,
    NuanceCoding,
    NuanceRelationType,
    SimplifiedCoding,
)


def _has_text(value: str | None) -> bool:
    return bool((value or "").strip())


def completion_issues(coding: SimplifiedCoding) -> list[str]:
    """Return non-blocking coding-manual completeness warnings."""
    if isinstance(coding, DifferentiationCoding):
        issues: list[str] = []
        if not _has_text(coding.fields.thing_being_considered):
            issues.append("Fokusemne mangler.")
        populated = [value for value in coding.fields.perspectives if _has_text(value)]
        if len(populated) < 2:
            issues.append("Der skal normalt være mindst to perspektiver.")
        return issues

    if isinstance(coding, ComparisonCoding):
        issues = []
        if not _has_text(coding.fields.text_passage):
            issues.append("Tekststykke mangler.")
        if not _has_text(coding.fields.thing_a):
            issues.append("Ting A mangler.")
        if not _has_text(coding.fields.thing_b):
            issues.append("Ting B mangler.")
        if not _has_text(coding.fields.relation):
            issues.append("Relation mangler.")
        return issues

    if isinstance(coding, NuanceCoding):
        issues = []
        if coding.fields.relation_type is None:
            issues.append("Relationstype mangler.")
        if not _has_text(coding.fields.influence_or_action_x):
            issues.append("Påvirkning eller handling (X) mangler.")
        if not _has_text(coding.fields.outcome_or_goal_y):
            issues.append("Udfald eller mål (Y) mangler.")
        if not _has_text(coding.fields.x_y_connection):
            issues.append("X–Y-forbindelse mangler.")
        if (
            coding.fields.relation_type
            in {
                NuanceRelationType.PROBLEM_EXPLANATION,
                NuanceRelationType.EXPECTED_EFFECT,
            }
            and coding.fields.expressed_certainty is None
        ):
            issues.append("Udtrykt sikkerhed mangler.")
        return issues

    return ["Ukendt kodetype."]
