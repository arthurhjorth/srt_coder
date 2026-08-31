from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


CODING_BOOK_VERSION = 4
CodeType = Literal["differentiation", "comparison", "nuance"]


class CodingBookModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


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
    AMBITION_INTENTION = "ambition_intention"


class ExpressedCertainty(str, Enum):
    ASSERTED = "asserted"
    QUALIFIED = "qualified"


class DifferentiationFields(CodingBookModel):
    thing_being_considered: str | None = Field(
        default=None,
        description=(
            "The interviewee's own words for the single topic to which all "
            "perspectives relate."
        ),
    )
    perspectives: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete, non-redundant perspectives explicitly connected to the "
            "same focus topic; a complete coding normally contains at least two."
        ),
    )
    perspective_types: list[PerspectiveType] = Field(
        default_factory=list,
        description="Optional classifications of the perspectives.",
    )
    coder_note: str | None = Field(
        default=None,
        description="Optional note about references, transcription errors, or coding boundaries.",
    )


class ComparisonFields(CodingBookModel):
    text_passage: str | None = Field(
        default=None,
        description="The smallest passage containing thing A, thing B, and their comparison.",
    )
    thing_a: str | None = Field(
        default=None,
        description="The interviewee's own words for the first compared referent.",
    )
    thing_b: str | None = Field(
        default=None,
        description="The interviewee's own words for the explicit comparison target.",
    )
    relation: str | None = Field(
        default=None,
        description="The interviewee's wording that places thing A relative to thing B.",
    )
    comparison_basis: str | None = Field(
        default=None,
        description="Optional property or question on which thing A and thing B are compared.",
    )
    coder_note: str | None = Field(
        default=None,
        description="Optional note about references, transcription errors, or coding boundaries.",
    )


class NuanceFields(CodingBookModel):
    relation_type: NuanceRelationType | None = Field(
        default=None,
        description="Problem explanation, expected effect, or ambition/intention.",
    )
    influence_or_action_x: str | None = Field(
        default=None,
        description="The cause, condition, action, or plan connected to Y.",
    )
    outcome_or_goal_y: str | None = Field(
        default=None,
        description="The state, change, effect, or goal connected to X.",
    )
    x_y_connection: str | None = Field(
        default=None,
        description="The interviewee's wording or grammatical construction connecting X and Y.",
    )
    expressed_certainty: ExpressedCertainty | None = Field(
        default=None,
        description=(
            "Asserted or qualified; relevant only to problem explanations and expected effects."
        ),
    )
    limitation: str | None = Field(
        default=None,
        description="Optional respondent-given condition limiting when the relation applies.",
    )
    coder_note: str | None = Field(
        default=None,
        description="Optional note about references, transcription errors, or coding boundaries.",
    )


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


class SimplifiedCodingEntry(CodingBookModel):
    coding_book_version: Literal[4] = CODING_BOOK_VERSION
    coding_id: str
    analysis_id: str
    interview_file: str
    coding: SimplifiedCoding
    field_spans: dict[str, list[TranscriptSpan]] = Field(default_factory=dict)
    created_by: str
    created_at: str
    updated_at: str

    @property
    def object_type(self) -> CodeType:
        return self.coding.code_type
