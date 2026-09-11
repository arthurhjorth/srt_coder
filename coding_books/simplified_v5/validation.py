from __future__ import annotations

from coding_books.simplified_v5.models import (
    ComparisonCoding,
    DifferentiationCoding,
    NuanceCoding,
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
        populated = [row for row in coding.fields.perspectives if _has_text(row.text)]
        if len(populated) < 2:
            issues.append("Der skal normalt være mindst to perspektiver.")
        return issues

    if isinstance(coding, ComparisonCoding):
        issues = []
        for name, label in (
            ("text_passage", "Tekststykke"),
            ("thing_a", "Ting A"),
            ("thing_b", "Ting B"),
            ("relation", "Relation"),
        ):
            if not _has_text(getattr(coding.fields, name)):
                issues.append(f"{label} mangler.")
        return issues

    if isinstance(coding, NuanceCoding):
        issues = []
        if coding.fields.relation_type is None:
            issues.append("Relationstype mangler.")
        for name, label in (
            ("influence_or_action_x", "Påvirkning eller handling (X)"),
            ("outcome_or_goal_y", "Udfald eller mål (Y)"),
            ("x_y_connection", "X–Y-forbindelse"),
        ):
            if not _has_text(getattr(coding.fields, name)):
                issues.append(f"{label} mangler.")
        if coding.fields.expressed_certainty is None:
            issues.append("Udtrykt sikkerhed mangler.")
        return issues

    return ["Ukendt kodetype."]
