from __future__ import annotations

from coding_books.simplified_v4.models import (
    ExpressedCertainty,
    NuanceRelationType,
    PerspectiveType,
)


CODE_TYPE_LABELS = {
    "differentiation": "Differentiation",
    "comparison": "Comparison",
    "nuance": "Nuance",
}

FIELD_LABELS = {
    "thing_being_considered": "Fokusemne / thing being considered",
    "perspectives": "Perspektiver",
    "perspective_types": "Perspektiv-type",
    "text_passage": "Tekststykke",
    "thing_a": "Ting A",
    "thing_b": "Ting B",
    "relation": "Relation",
    "comparison_basis": "Sammenligningsgrundlag",
    "relation_type": "Relationstype",
    "influence_or_action_x": "Påvirkning eller handling (X)",
    "outcome_or_goal_y": "Udfald eller mål (Y)",
    "x_y_connection": "X–Y-forbindelse",
    "expressed_certainty": "Udtrykt sikkerhed",
    "limitation": "Afgrænsning",
    "coder_note": "Kodernote",
}

PERSPECTIVE_TYPE_LABELS = {
    PerspectiveType.ACTORS_ROLES: "Aktører/roller",
    PerspectiveType.CONSIDERATIONS: "Hensyn",
    PerspectiveType.GOALS: "Mål",
    PerspectiveType.CONDITIONS_CIRCUMSTANCES: "Vilkår",
    PerspectiveType.INTERPRETATIONS: "Fortolkninger",
    PerspectiveType.CONSEQUENCES: "Konsekvenser",
    PerspectiveType.COURSES_OF_ACTION: "Handlemuligheder",
}

NUANCE_RELATION_TYPE_LABELS = {
    NuanceRelationType.PROBLEM_EXPLANATION: "Problemforklaring",
    NuanceRelationType.EXPECTED_EFFECT: "Forventet virkning",
    NuanceRelationType.AMBITION_INTENTION: "Ambition/intention",
}

EXPRESSED_CERTAINTY_LABELS = {
    ExpressedCertainty.ASSERTED: "Hævdet",
    ExpressedCertainty.QUALIFIED: "Forbeholden",
}
