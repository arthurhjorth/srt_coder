from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ComparatorDetail(BaseModel):
    comparator: Optional[str] = None
    comparator_comment: Optional[str] = None

    adjective: Optional[str] = None
    adjective_comment: Optional[str] = None

    dimensions_or_examples: Optional[list[str]] = None
    dimensions_or_examples_comment: Optional[str] = None


class Comparison(BaseModel):
    comparand: Optional[str] = None
    comparand_comment: Optional[str] = None

    comparators: Optional[list[ComparatorDetail]] = None


class Perspective(BaseModel):
    what_is_this_perspective_extract: Optional[str] = None
    what_is_this_perspective_extract_comment: Optional[str] = None

    why_is_it_relevant_to_take_this_perspective_extract: Optional[str] = None
    why_is_it_relevant_to_take_this_perspective_extract_comment: Optional[str] = None

    how_does_this_particular_perspective_add_complexity_or_difficulty_to_the_thing_being_considered_extract: Optional[str] = None
    how_does_this_particular_perspective_add_complexity_or_difficulty_to_the_thing_being_considered_extract_comment: Optional[str] = None

    what_are_the_implications_extract: Optional[str] = None
    what_are_the_implications_extract_comment: Optional[str] = None


class Differentiation(BaseModel):
    thing_being_considered_extract: Optional[str] = None
    thing_being_considered_extract_comment: Optional[str] = None

    context_why_is_this_thing_being_considered_or_talked_about_extract: Optional[str] = None
    context_why_is_this_thing_being_considered_or_talked_about_extract_comment: Optional[str] = None

    why_is_it_important_extract: Optional[str] = None
    why_is_it_important_extract_comment: Optional[str] = None

    why_is_this_a_thing_or_how_did_it_happen_extract: Optional[str] = None
    why_is_this_a_thing_or_how_did_it_happen_extract_comment: Optional[str] = None

    perspectives_extract: Optional[list[Perspective]] = None

    why_is_it_important_to_take_different_perspectives_extract: Optional[str] = None
    why_is_it_important_to_take_different_perspectives_extract_comment: Optional[str] = None

    what_is_wrong_with_taking_a_unitary_perspective_extract: Optional[str] = None
    what_is_wrong_with_taking_a_unitary_perspective_extract_comment: Optional[str] = None


class ConditionAntecedentReason(BaseModel):
    description_an_event_or_state_that_contributes_or_contributed_towards_increasing_the_likelihood_of_the_outcome_or_towards_explaining_why_it_happened_extract: Optional[str] = None
    description_an_event_or_state_that_contributes_or_contributed_towards_increasing_the_likelihood_of_the_outcome_or_towards_explaining_why_it_happened_extract_comment: Optional[str] = None

    direction_of_impact_increase_or_decrease_the_likelihood_extract: Optional[str] = None
    direction_of_impact_increase_or_decrease_the_likelihood_extract_comment: Optional[str] = None

    reasoning_of_impact_in_what_ways_would_this_contribute_towards_the_likelihood_of_the_outcome_extract: Optional[str] = None
    reasoning_of_impact_in_what_ways_would_this_contribute_towards_the_likelihood_of_the_outcome_extract_comment: Optional[str] = None

    certitude_about_impact_how_likely_is_this_condition_to_impact_the_likelihood_of_the_outcome_extract: Optional[str] = None
    certitude_about_impact_how_likely_is_this_condition_to_impact_the_likelihood_of_the_outcome_extract_comment: Optional[str] = None

    epistemic_stance_extract: Optional[str] = None
    epistemic_stance_extract_comment: Optional[str] = None


class Nuance(BaseModel):
    outcome_something_that_can_happen_or_has_happened_event_something_that_can_be_or_is_the_case_state_extract: Optional[str] = None
    outcome_something_that_can_happen_or_has_happened_event_something_that_can_be_or_is_the_case_state_extract_comment: Optional[str] = None

    certitude_about_outcome_or_epistemic_modality_does_the_person_say_that_this_will_happen_or_could_it_happen_or_might_it_happen_extract: Optional[str] = None
    certitude_about_outcome_or_epistemic_modality_does_the_person_say_that_this_will_happen_or_could_it_happen_or_might_it_happen_extract_comment: Optional[str] = None

    epistemic_stance_extract: Optional[str] = None
    epistemic_stance_extract_comment: Optional[str] = None

    negation_or_not_extract: Optional[str] = None
    negation_or_not_extract_comment: Optional[str] = None

    stance_does_the_person_want_this_or_does_the_person_not_want_this_extract: Optional[str] = None
    stance_does_the_person_want_this_or_does_the_person_not_want_this_extract_comment: Optional[str] = None

    condition_antecedent_reason_extract: Optional[str] = None
    condition_antecedent_reason_extract_comment: Optional[str] = None

    condition_antecedent_reason: Optional[list[ConditionAntecedentReason]] = None

    sufficiency_does_person_state_that_these_are_sufficient_conditions_extract: Optional[str] = None
    sufficiency_does_person_state_that_these_are_sufficient_conditions_extract_comment: Optional[str] = None


class User(BaseModel):
    username: Optional[str] = None
    username_comment: Optional[str] = None

    password_hash: Optional[str] = None
    password_hash_comment: Optional[str] = None

    role: Optional[str] = None
    role_comment: Optional[str] = None

    is_active: Optional[bool] = None
    is_active_comment: Optional[str] = None

    created_at: Optional[str] = None
    created_at_comment: Optional[str] = None

    updated_at: Optional[str] = None
    updated_at_comment: Optional[str] = None


class Analysis(BaseModel):
    analysis_id: Optional[str] = None
    analysis_id_comment: Optional[str] = None

    owner_username: Optional[str] = None
    owner_username_comment: Optional[str] = None

    interview_file: Optional[str] = None
    interview_file_comment: Optional[str] = None

    name: Optional[str] = None
    name_comment: Optional[str] = None

    description: Optional[str] = None
    description_comment: Optional[str] = None

    created_at: Optional[str] = None
    created_at_comment: Optional[str] = None

    updated_at: Optional[str] = None
    updated_at_comment: Optional[str] = None


class CodingEntry(BaseModel):
    coding_id: Optional[str] = None
    coding_id_comment: Optional[str] = None

    analysis_id: Optional[str] = None
    analysis_id_comment: Optional[str] = None

    object_type: Optional[str] = None
    object_type_comment: Optional[str] = None

    interview_file: Optional[str] = None
    interview_file_comment: Optional[str] = None

    segment_id: Optional[str] = None
    segment_id_comment: Optional[str] = None

    segment_index: Optional[int] = None
    segment_index_comment: Optional[str] = None

    segment_start_ms: Optional[int] = None
    segment_start_ms_comment: Optional[str] = None

    segment_end_ms: Optional[int] = None
    segment_end_ms_comment: Optional[str] = None

    start_segment_id: Optional[str] = None
    start_segment_id_comment: Optional[str] = None

    start_char_offset: Optional[int] = None
    start_char_offset_comment: Optional[str] = None

    end_segment_id: Optional[str] = None
    end_segment_id_comment: Optional[str] = None

    end_char_offset: Optional[int] = None
    end_char_offset_comment: Optional[str] = None

    speaker: Optional[str] = None
    speaker_comment: Optional[str] = None

    quote_text: Optional[str] = None
    quote_text_comment: Optional[str] = None

    selected_text: Optional[str] = None
    selected_text_comment: Optional[str] = None

    note: Optional[str] = None
    note_comment: Optional[str] = None

    comparison: Optional[Comparison] = None
    comparison_comment: Optional[str] = None

    differentiation: Optional[Differentiation] = None
    differentiation_comment: Optional[str] = None

    nuance: Optional[Nuance] = None
    nuance_comment: Optional[str] = None

    field_spans: Optional[dict[str, list[dict]]] = None
    field_spans_comment: Optional[str] = None

    created_by: Optional[str] = None
    created_by_comment: Optional[str] = None

    created_at: Optional[str] = None
    created_at_comment: Optional[str] = None

    updated_at: Optional[str] = None
    updated_at_comment: Optional[str] = None
