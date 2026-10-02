from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


CODING_BOOK_VERSION = 5
CodeType = Literal["differentiation", "comparison", "nuance"]


class CodingBookModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PerspectiveType(str, Enum):
    ACTORS_ROLES = "actors_roles"
    CONSIDERATIONS = "considerations"
    GOALS = "goals"
    CONDITIONS_CIRCUMSTANCES = "conditions_circumstances"
    INTERPRETATIONS = "interpretations"
    CONSEQUENCES = "consequences"
    COURSES_OF_ACTION = "courses_of_action"


class NuanceRelationType(str, Enum):
    PROBLEM_EXPLANATION = "problem_explanation"
    EXPECTED_EFFECT = "expected_effect"


class ExpressedCertainty(str, Enum):
    ASSERTED = "asserted"
    QUALIFIED = "qualified"


class Perspective(CodingBookModel):
    text: str | None = Field(
        default=None,
        description="A concrete, non-redundant perspective on the shared focus topic.",
    )
    perspective_types: list[PerspectiveType] = Field(default_factory=list)
    perspective_types_comment: str | None = None


class DifferentiationFields(CodingBookModel):
    thing_being_considered: str | None = Field(
        default=None,
        description="The single topic to which all perspectives relate.",
    )
    perspectives: list[Perspective] = Field(default_factory=list)
    coder_note: str | None = None


class ComparisonFields(CodingBookModel):
    text_passage: str | None = None
    thing_a: str | None = None
    thing_b: str | None = None
    relation: str | None = None
    comparison_basis: str | None = None
    coder_note: str | None = None


class NuanceFields(CodingBookModel):
    relation_type: NuanceRelationType | None = None
    relation_type_comment: str | None = None
    influence_or_action_x: str | None = None
    outcome_or_goal_y: str | None = None
    x_y_connection: str | None = None
    x_y_connection_rewritten: bool | None = Field(
        default=None,
        description="Whether the coder has rewritten the X–Y connection in their own words.",
    )
    x_y_connection_rewrite: str | None = Field(
        default=None,
        description="The coder's rewritten X–Y connection, separate from transcript evidence.",
    )
    x_y_connection_rewrite_comment: str | None = Field(
        default=None,
        description="Optional coder comment on the rewritten X–Y connection.",
    )
    expressed_certainty: ExpressedCertainty | None = None
    expressed_certainty_comment: str | None = None
    limitation: str | None = None
    coder_note: str | None = None


class DifferentiationCoding(CodingBookModel):
    code_type: Literal["differentiation"] = "differentiation"
    fields: DifferentiationFields = Field(default_factory=DifferentiationFields)


class ComparisonCoding(CodingBookModel):
    code_type: Literal["comparison"] = "comparison"
    fields: ComparisonFields = Field(default_factory=ComparisonFields)


class NuanceCoding(CodingBookModel):
    code_type: Literal["nuance"] = "nuance"
    fields: NuanceFields = Field(default_factory=NuanceFields)


SimplifiedCoding = Annotated[
    DifferentiationCoding | ComparisonCoding | NuanceCoding,
    Field(discriminator="code_type"),
]


class TranscriptSpan(CodingBookModel):
    start_segment_id: str
    start_char_offset: int
    end_segment_id: str
    end_char_offset: int
    selected_text: str
    comment: str | None = Field(
        default=None,
        description="Optional coder comment attached specifically to this transcript span.",
    )


class MigrationMetadata(CodingBookModel):
    source_coding_book_version: int | None = None
    legacy_differentiation_perspective_types: list[PerspectiveType] = Field(
        default_factory=list
    )
    legacy_field_spans: dict[str, list[TranscriptSpan]] = Field(default_factory=dict)


class SimplifiedCodingEntry(CodingBookModel):
    coding_book_version: Literal[5] = CODING_BOOK_VERSION
    coding_id: str
    analysis_id: str
    interview_file: str
    coding: SimplifiedCoding
    field_spans: dict[str, list[TranscriptSpan]] = Field(default_factory=dict)
    migration_metadata: MigrationMetadata | None = None
    created_by: str
    created_at: str
    updated_at: str

    @property
    def object_type(self) -> CodeType:
        return self.coding.code_type
