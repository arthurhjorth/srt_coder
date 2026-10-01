from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from io import StringIO
from itertools import combinations
import json
import re
from typing import Any, Literal

from coding_books.simplified_v5.models import (
    CODING_BOOK_VERSION,
    DifferentiationCoding,
    NuanceCoding,
    SimplifiedCodingEntry,
)
from core_models import Analysis
from domain.simplified_analysis_exchange_service_v5 import EXPORT_FORMAT_VERSION
from domain.simplified_schema_migration import migrate_export_payload


SpanMode = Literal["exact", "partial"]
FieldMode = Literal["exact", "normalized", "ignore"]
AgreementStatus = Literal["primary_field_overlap", "partial_only", "no_overlap"]

PARENT_CODE_ORDER = ("differentiation", "comparison", "nuance")
PRIMARY_FIELD_PATHS = {
    "differentiation": {"differentiation.thing_being_considered"},
    "comparison": {"comparison.thing_a", "comparison.thing_b"},
    "nuance": {"nuance.outcome_or_goal_y"},
}


@dataclass(frozen=True)
class AgreementRules:
    span_mode: SpanMode = "partial"
    field_mode: FieldMode = "normalized"
    require_same_object_type: bool = True


@dataclass(frozen=True)
class TranscriptSpan:
    start_segment_id: str
    start_char_offset: int
    end_segment_id: str
    end_char_offset: int
    selected_text: str = ""

    @property
    def range_label(self) -> str:
        return (
            f"{self.start_segment_id}:{self.start_char_offset}-"
            f"{self.end_segment_id}:{self.end_char_offset}"
        )


@dataclass(frozen=True)
class NormalizedAnnotation:
    annotation_id: int
    source_index: int
    source_label: str
    source_name: str
    analysis_id: str
    analysis_name: str
    interview_file: str
    coding_id: str
    object_type: str
    field_path: str
    normalized_field_path: str
    span: TranscriptSpan

    @property
    def key(self) -> tuple:
        return (
            self.source_index,
            self.coding_id,
            self.field_path,
            self.span.start_segment_id,
            self.span.start_char_offset,
            self.span.end_segment_id,
            self.span.end_char_offset,
            self.annotation_id,
        )


@dataclass(frozen=True)
class AnnotationMatch:
    left: NormalizedAnnotation
    right: NormalizedAnnotation
    quality: float


@dataclass(frozen=True)
class AgreementSource:
    source_index: int
    source_name: str
    content_hash: str
    label: str
    analyses: list[Analysis]
    codings: list[SimplifiedCodingEntry]
    annotations: list[NormalizedAnnotation]
    warnings: list[str]


@dataclass(frozen=True)
class ObjectAlignment:
    left_coding_id: str
    right_coding_id: str
    object_type: str
    matched_span_count: int
    primary_field_matched_span_count: int
    primary_field_overlap: bool
    total_overlap_quality: float


@dataclass(frozen=True)
class PerspectiveAlignment:
    left_coding_id: str
    right_coding_id: str
    left_perspective_index: int
    right_perspective_index: int
    matched_span_count: int
    total_overlap_quality: float


@dataclass(frozen=True)
class ParentCodeAgreementSummary:
    object_type: str
    left_identified: int
    right_identified: int
    overlap: int
    primary_field_overlap: int
    matched_perspective_pairs: int | None
    partial_only: int
    no_overlap_left: int
    no_overlap_right: int


@dataclass(frozen=True)
class ObjectReviewItem:
    object_type: str
    agreement_status: AgreementStatus
    left_coding_id: str | None
    right_coding_id: str | None
    interview_file: str
    start_segment_id: str | None
    start_char_offset: int | None


@dataclass(frozen=True)
class CategoricalComparison:
    left_coding_id: str
    right_coding_id: str
    field_path: str
    left_value: Any
    right_value: Any
    agrees: bool
    included_in_score: bool


@dataclass(frozen=True)
class PairAgreement:
    left_source_index: int
    right_source_index: int
    left_label: str
    right_label: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    annotation_matches: list[AnnotationMatch]
    object_alignments: list[ObjectAlignment]
    perspective_alignments: list[PerspectiveAlignment]
    parent_code_summaries: list[ParentCodeAgreementSummary]
    object_review_items: list[ObjectReviewItem]
    unmatched_left_coding_ids: list[str]
    unmatched_right_coding_ids: list[str]
    categorical_comparisons: list[CategoricalComparison]

    @property
    def categorical_total(self) -> int:
        return sum(item.included_in_score for item in self.categorical_comparisons)

    @property
    def categorical_matches(self) -> int:
        return sum(
            item.agrees
            for item in self.categorical_comparisons
            if item.included_in_score
        )

    @property
    def categorical_agreement(self) -> float | None:
        if not self.categorical_total:
            return None
        return self.categorical_matches / self.categorical_total


@dataclass(frozen=True)
class AgreementCluster:
    cluster_id: int
    annotations: list[NormalizedAnnotation]
    present_source_indices: set[int]
    missing_source_indices: set[int]


@dataclass(frozen=True)
class AgreementReport:
    sources: list[AgreementSource]
    rules: AgreementRules
    total_annotations: int
    clusters: list[AgreementCluster]
    full_agreement_clusters: int
    pair_agreements: list[PairAgreement]


def agreement_field_path_is_ignored(field_path: str) -> bool:
    final_name = re.split(r"\.|\]", field_path)[-1]
    return (
        final_name in {"coder_note", "perspective_types"}
        or final_name.endswith("_comment")
    )


def normalize_field_path(field_path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", field_path)


def load_agreement_export(
    raw_text: str,
    *,
    source_name: str,
    source_index: int,
    content_hash: str = "",
) -> AgreementSource:
    try:
        raw_payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    payload = migrate_export_payload(raw_payload)
    if payload.get("export_format_version") != EXPORT_FORMAT_VERSION:
        raise ValueError("Unsupported simplified coding export format")
    if payload.get("coding_book_version") != CODING_BOOK_VERSION:
        raise ValueError("Agreement comparison accepts coding book v4 or v5 exports only")
    analyses_raw = payload.get("analyses")
    codings_raw = payload.get("codings") or []
    if not isinstance(analyses_raw, list) or not analyses_raw:
        raise ValueError("Agreement input must contain at least one analysis")
    if not isinstance(codings_raw, list):
        raise ValueError("codings must be a list")
    analyses = [Analysis.model_validate(raw) for raw in analyses_raw]
    codings = [SimplifiedCodingEntry.model_validate(raw) for raw in codings_raw]
    analysis_by_id = {analysis.analysis_id: analysis for analysis in analyses if analysis.analysis_id}
    label = _source_label(source_name, analyses, codings)
    warnings: list[str] = []
    annotations: list[NormalizedAnnotation] = []
    for coding in codings:
        analysis = analysis_by_id.get(coding.analysis_id) or analyses[0]
        included_for_coding = 0
        for field_path, spans in coding.field_spans.items():
            if agreement_field_path_is_ignored(field_path):
                continue
            for raw_span in spans:
                span = TranscriptSpan(
                    start_segment_id=raw_span.start_segment_id,
                    start_char_offset=raw_span.start_char_offset,
                    end_segment_id=raw_span.end_segment_id,
                    end_char_offset=raw_span.end_char_offset,
                    selected_text=raw_span.selected_text,
                )
                annotations.append(
                    NormalizedAnnotation(
                        annotation_id=len(annotations),
                        source_index=source_index,
                        source_label=label,
                        source_name=source_name,
                        analysis_id=coding.analysis_id,
                        analysis_name=analysis.name or "",
                        interview_file=coding.interview_file or analysis.interview_file or "",
                        coding_id=coding.coding_id,
                        object_type=coding.object_type,
                        field_path=str(field_path),
                        normalized_field_path=normalize_field_path(str(field_path)),
                        span=span,
                    )
                )
                included_for_coding += 1
        if not included_for_coding:
            warnings.append(
                f"Coding {coding.coding_id} has no agreement-eligible transcript spans."
            )
    return AgreementSource(
        source_index=source_index,
        source_name=source_name,
        content_hash=content_hash,
        label=label,
        analyses=analyses,
        codings=codings,
        annotations=annotations,
        warnings=warnings,
    )


def build_agreement_report(
    sources: list[AgreementSource], rules: AgreementRules | None = None
) -> AgreementReport:
    rules = rules or AgreementRules()
    ordered_sources = sorted(sources, key=lambda source: source.source_index)
    annotations = [item for source in ordered_sources for item in source.annotations]
    clusters = _cluster_annotations(annotations, ordered_sources, rules)
    pairs = [_build_pair(left, right, rules) for left, right in combinations(ordered_sources, 2)]
    return AgreementReport(
        sources=ordered_sources,
        rules=rules,
        total_annotations=len(annotations),
        clusters=clusters,
        full_agreement_clusters=sum(
            1
            for cluster in clusters
            if ordered_sources
            and len(cluster.present_source_indices) == len(ordered_sources)
        ),
        pair_agreements=pairs,
    )


def annotations_match(
    left: NormalizedAnnotation,
    right: NormalizedAnnotation,
    rules: AgreementRules,
) -> bool:
    if left.source_index == right.source_index:
        return False
    if left.interview_file and right.interview_file and left.interview_file != right.interview_file:
        return False
    if rules.require_same_object_type and left.object_type != right.object_type:
        return False
    if rules.field_mode == "exact" and left.field_path != right.field_path:
        return False
    if rules.field_mode == "normalized" and left.normalized_field_path != right.normalized_field_path:
        return False
    if rules.span_mode == "exact":
        return _ordered_span_points(left.span) == _ordered_span_points(right.span)
    return spans_overlap(left.span, right.span)


def spans_overlap(left: TranscriptSpan, right: TranscriptSpan) -> bool:
    left_start, left_end = _ordered_span_points(left)
    right_start, right_end = _ordered_span_points(right)
    return left_start < right_end and right_start < left_end


def _annotation_matches(
    left: list[NormalizedAnnotation],
    right: list[NormalizedAnnotation],
    rules: AgreementRules,
) -> list[AnnotationMatch]:
    candidates: list[tuple[int, int, int]] = []
    qualities: dict[tuple[int, int], float] = {}
    for left_index, left_annotation in enumerate(left):
        for right_index, right_annotation in enumerate(right):
            if not annotations_match(left_annotation, right_annotation, rules):
                continue
            quality = _overlap_quality(left_annotation.span, right_annotation.span)
            qualities[(left_index, right_index)] = quality
            candidates.append((left_index, right_index, int(round(quality * 1_000_000))))
    pairs = _weighted_maximum_cardinality_matching(len(left), len(right), candidates)
    return [
        AnnotationMatch(
            left=left[left_index],
            right=right[right_index],
            quality=qualities[(left_index, right_index)],
        )
        for left_index, right_index in pairs
    ]


def _weighted_maximum_cardinality_matching(
    left_count: int,
    right_count: int,
    candidates: list[tuple[int, int, int]],
) -> list[tuple[int, int]]:
    """Return a deterministic max-cardinality, then max-weight bipartite matching."""
    if not candidates or not left_count or not right_count:
        return []
    source = 0
    left_offset = 1
    right_offset = left_offset + left_count
    sink = right_offset + right_count
    node_count = sink + 1
    graph: list[list[list[int]]] = [[] for _ in range(node_count)]

    def add_edge(start: int, end: int, capacity: int, cost: int) -> int:
        forward_index = len(graph[start])
        graph[start].append([end, len(graph[end]), capacity, cost])
        graph[end].append([start, forward_index, 0, -cost])
        return forward_index

    for index in range(left_count):
        add_edge(source, left_offset + index, 1, 0)
    for index in range(right_count):
        add_edge(right_offset + index, sink, 1, 0)

    max_flow = min(left_count, right_count)
    edge_count = max(1, left_count * right_count)
    tie_scale = (max_flow + 1) * (edge_count + 1)
    tracked: dict[tuple[int, int], tuple[int, int]] = {}
    for left_index, right_index, weight in sorted(candidates):
        tie_rank = left_index * right_count + right_index
        start = left_offset + left_index
        edge_index = add_edge(
            start,
            right_offset + right_index,
            1,
            -(weight * tie_scale) + tie_rank,
        )
        tracked[(left_index, right_index)] = (start, edge_index)

    infinity = 10**30
    while True:
        distances = [infinity] * node_count
        previous: list[tuple[int, int] | None] = [None] * node_count
        distances[source] = 0
        for _ in range(node_count - 1):
            changed = False
            for start, edges in enumerate(graph):
                if distances[start] == infinity:
                    continue
                for edge_index, edge in enumerate(edges):
                    end, _reverse, capacity, cost = edge
                    if capacity <= 0:
                        continue
                    candidate_distance = distances[start] + cost
                    if candidate_distance < distances[end]:
                        distances[end] = candidate_distance
                        previous[end] = (start, edge_index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            start, edge_index = previous[node] or (-1, -1)
            if start < 0:
                raise RuntimeError("Invalid matching path")
            edge = graph[start][edge_index]
            edge[2] -= 1
            graph[node][edge[1]][2] += 1
            node = start

    matched = [
        pair
        for pair, (start, edge_index) in tracked.items()
        if graph[start][edge_index][2] == 0
    ]
    return sorted(matched)


def _build_pair(
    left: AgreementSource,
    right: AgreementSource,
    rules: AgreementRules,
) -> PairAgreement:
    matches = _annotation_matches(left.annotations, right.annotations, rules)
    true_positives = len(matches)
    false_positives = len(left.annotations) - true_positives
    false_negatives = len(right.annotations) - true_positives
    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )
    alignments = _align_objects(left, right, rules)
    perspective_alignments = _align_perspectives(left, right, alignments, rules)
    aligned_left = {item.left_coding_id for item in alignments}
    aligned_right = {item.right_coding_id for item in alignments}
    unmatched_left_coding_ids = [
        entry.coding_id for entry in left.codings if entry.coding_id not in aligned_left
    ]
    unmatched_right_coding_ids = [
        entry.coding_id for entry in right.codings if entry.coding_id not in aligned_right
    ]
    return PairAgreement(
        left_source_index=left.source_index,
        right_source_index=right.source_index,
        left_label=f"{left.label} ({left.source_name})",
        right_label=f"{right.label} ({right.source_name})",
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=(2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
        annotation_matches=matches,
        object_alignments=alignments,
        perspective_alignments=perspective_alignments,
        parent_code_summaries=_parent_code_summaries(
            left,
            right,
            alignments,
            perspective_alignments,
        ),
        object_review_items=_object_review_items(
            left,
            right,
            alignments,
            unmatched_left_coding_ids,
            unmatched_right_coding_ids,
        ),
        unmatched_left_coding_ids=unmatched_left_coding_ids,
        unmatched_right_coding_ids=unmatched_right_coding_ids,
        categorical_comparisons=_categorical_comparisons(
            left,
            right,
            alignments,
            perspective_alignments,
        ),
    )


def _align_objects(
    left: AgreementSource,
    right: AgreementSource,
    rules: AgreementRules,
) -> list[ObjectAlignment]:
    annotations_left = _annotations_by_coding(left.annotations)
    annotations_right = _annotations_by_coding(right.annotations)
    object_rules = AgreementRules(
        span_mode=rules.span_mode,
        field_mode="ignore",
        require_same_object_type=True,
    )
    candidates: list[tuple[int, int, int]] = []
    details: dict[tuple[int, int], tuple[int, int, float]] = {}
    for left_index, left_entry in enumerate(left.codings):
        for right_index, right_entry in enumerate(right.codings):
            if left_entry.object_type != right_entry.object_type:
                continue
            matches = _annotation_matches(
                annotations_left.get(left_entry.coding_id, []),
                annotations_right.get(right_entry.coding_id, []),
                object_rules,
            )
            if not matches:
                continue
            primary_paths = PRIMARY_FIELD_PATHS.get(left_entry.object_type, set())
            primary_matches = _annotation_matches(
                [
                    annotation
                    for annotation in annotations_left.get(left_entry.coding_id, [])
                    if annotation.field_path in primary_paths
                ],
                [
                    annotation
                    for annotation in annotations_right.get(right_entry.coding_id, [])
                    if annotation.field_path in primary_paths
                ],
                object_rules,
            )
            quality = sum(match.quality for match in matches)
            weight = (
                len(primary_matches) * 1_000_000_000
                + len(matches) * 1_000_000
                + int(round(quality * 1_000))
            )
            candidates.append((left_index, right_index, weight))
            details[(left_index, right_index)] = (
                len(matches),
                len(primary_matches),
                quality,
            )
    pairs = _weighted_maximum_cardinality_matching(
        len(left.codings), len(right.codings), candidates
    )
    return [
        ObjectAlignment(
            left_coding_id=left.codings[left_index].coding_id,
            right_coding_id=right.codings[right_index].coding_id,
            object_type=(
                left.codings[left_index].object_type
                if left.codings[left_index].object_type
                == right.codings[right_index].object_type
                else f"{left.codings[left_index].object_type}/{right.codings[right_index].object_type}"
            ),
            matched_span_count=details[(left_index, right_index)][0],
            primary_field_matched_span_count=details[(left_index, right_index)][1],
            primary_field_overlap=details[(left_index, right_index)][1] > 0,
            total_overlap_quality=details[(left_index, right_index)][2],
        )
        for left_index, right_index in pairs
    ]


def _align_perspectives(
    left: AgreementSource,
    right: AgreementSource,
    object_alignments: list[ObjectAlignment],
    rules: AgreementRules,
) -> list[PerspectiveAlignment]:
    annotations_left = _annotations_by_coding(left.annotations)
    annotations_right = _annotations_by_coding(right.annotations)
    perspective_rules = AgreementRules(
        span_mode=rules.span_mode,
        field_mode="ignore",
        require_same_object_type=True,
    )
    aligned: list[PerspectiveAlignment] = []
    for object_alignment in object_alignments:
        if object_alignment.object_type != "differentiation":
            continue
        left_groups = _perspective_annotations_by_index(
            annotations_left.get(object_alignment.left_coding_id, [])
        )
        right_groups = _perspective_annotations_by_index(
            annotations_right.get(object_alignment.right_coding_id, [])
        )
        left_indices = sorted(left_groups)
        right_indices = sorted(right_groups)
        candidates: list[tuple[int, int, int]] = []
        details: dict[tuple[int, int], tuple[int, float]] = {}
        for left_position, left_index in enumerate(left_indices):
            for right_position, right_index in enumerate(right_indices):
                matches = _annotation_matches(
                    left_groups[left_index],
                    right_groups[right_index],
                    perspective_rules,
                )
                if not matches:
                    continue
                quality = sum(match.quality for match in matches)
                weight = len(matches) * 1_000_000 + int(round(quality * 1_000))
                candidates.append((left_position, right_position, weight))
                details[(left_position, right_position)] = (len(matches), quality)
        pairs = _weighted_maximum_cardinality_matching(
            len(left_indices),
            len(right_indices),
            candidates,
        )
        for left_position, right_position in pairs:
            matched_span_count, quality = details[(left_position, right_position)]
            aligned.append(
                PerspectiveAlignment(
                    left_coding_id=object_alignment.left_coding_id,
                    right_coding_id=object_alignment.right_coding_id,
                    left_perspective_index=left_indices[left_position],
                    right_perspective_index=right_indices[right_position],
                    matched_span_count=matched_span_count,
                    total_overlap_quality=quality,
                )
            )
    return aligned


def _parent_code_summaries(
    left: AgreementSource,
    right: AgreementSource,
    alignments: list[ObjectAlignment],
    perspective_alignments: list[PerspectiveAlignment],
) -> list[ParentCodeAgreementSummary]:
    summaries: list[ParentCodeAgreementSummary] = []
    for object_type in PARENT_CODE_ORDER:
        left_count = sum(entry.object_type == object_type for entry in left.codings)
        right_count = sum(entry.object_type == object_type for entry in right.codings)
        aligned = [item for item in alignments if item.object_type == object_type]
        primary_count = sum(item.primary_field_overlap for item in aligned)
        overlap_count = len(aligned)
        summaries.append(
            ParentCodeAgreementSummary(
                object_type=object_type,
                left_identified=left_count,
                right_identified=right_count,
                overlap=overlap_count,
                primary_field_overlap=primary_count,
                matched_perspective_pairs=(
                    len(perspective_alignments)
                    if object_type == "differentiation"
                    else None
                ),
                partial_only=overlap_count - primary_count,
                no_overlap_left=left_count - overlap_count,
                no_overlap_right=right_count - overlap_count,
            )
        )
    return summaries


def _object_review_items(
    left: AgreementSource,
    right: AgreementSource,
    alignments: list[ObjectAlignment],
    unmatched_left_coding_ids: list[str],
    unmatched_right_coding_ids: list[str],
) -> list[ObjectReviewItem]:
    left_annotations = _annotations_by_coding(left.annotations)
    right_annotations = _annotations_by_coding(right.annotations)
    left_entries = {entry.coding_id: entry for entry in left.codings}
    right_entries = {entry.coding_id: entry for entry in right.codings}
    items: list[tuple[tuple[Any, ...], ObjectReviewItem]] = []

    for stable_index, alignment in enumerate(alignments):
        annotations = (
            left_annotations.get(alignment.left_coding_id, [])
            + right_annotations.get(alignment.right_coding_id, [])
        )
        earliest = _earliest_annotation(annotations)
        item = ObjectReviewItem(
            object_type=alignment.object_type,
            agreement_status=(
                "primary_field_overlap"
                if alignment.primary_field_overlap
                else "partial_only"
            ),
            left_coding_id=alignment.left_coding_id,
            right_coding_id=alignment.right_coding_id,
            interview_file=earliest.interview_file if earliest else "",
            start_segment_id=earliest.span.start_segment_id if earliest else None,
            start_char_offset=earliest.span.start_char_offset if earliest else None,
        )
        items.append((_review_item_order_key(item, 0, stable_index), item))

    for side_rank, (source, entries, annotations_by_id, coding_ids) in enumerate(
        (
            (left, left_entries, left_annotations, unmatched_left_coding_ids),
            (right, right_entries, right_annotations, unmatched_right_coding_ids),
        ),
        start=1,
    ):
        for stable_index, coding_id in enumerate(coding_ids):
            entry = entries[coding_id]
            earliest = _earliest_annotation(annotations_by_id.get(coding_id, []))
            item = ObjectReviewItem(
                object_type=entry.object_type,
                agreement_status="no_overlap",
                left_coding_id=coding_id if source.source_index == left.source_index else None,
                right_coding_id=coding_id if source.source_index == right.source_index else None,
                interview_file=(
                    earliest.interview_file
                    if earliest
                    else entry.interview_file
                ),
                start_segment_id=earliest.span.start_segment_id if earliest else None,
                start_char_offset=earliest.span.start_char_offset if earliest else None,
            )
            items.append(
                (_review_item_order_key(item, side_rank, stable_index), item)
            )

    return [item for _key, item in sorted(items, key=lambda pair: pair[0])]


def _earliest_annotation(
    annotations: list[NormalizedAnnotation],
) -> NormalizedAnnotation | None:
    if not annotations:
        return None
    return min(
        annotations,
        key=lambda annotation: (
            annotation.interview_file,
            _ordered_span_points(annotation.span)[0],
            annotation.key,
        ),
    )


def _review_item_order_key(
    item: ObjectReviewItem,
    side_rank: int,
    stable_index: int,
) -> tuple[Any, ...]:
    if item.start_segment_id is None or item.start_char_offset is None:
        position: tuple[Any, ...] = (1, 0, "", 0)
    else:
        point = _span_point(item.start_segment_id, item.start_char_offset)
        position = (0, *point)
    return (
        item.interview_file,
        position,
        side_rank,
        stable_index,
        item.left_coding_id or "",
        item.right_coding_id or "",
    )


def _categorical_comparisons(
    left: AgreementSource,
    right: AgreementSource,
    alignments: list[ObjectAlignment],
    perspective_alignments: list[PerspectiveAlignment],
) -> list[CategoricalComparison]:
    left_entries = {entry.coding_id: entry for entry in left.codings}
    right_entries = {entry.coding_id: entry for entry in right.codings}
    comparisons: list[CategoricalComparison] = []
    for alignment in alignments:
        left_entry = left_entries[alignment.left_coding_id]
        right_entry = right_entries[alignment.right_coding_id]
        if isinstance(left_entry.coding, NuanceCoding) and isinstance(
            right_entry.coding, NuanceCoding
        ):
            for name in ("relation_type", "expressed_certainty"):
                left_value = getattr(left_entry.coding.fields, name)
                right_value = getattr(right_entry.coding.fields, name)
                left_value = left_value.value if left_value is not None else None
                right_value = right_value.value if right_value is not None else None
                if left_value is None and right_value is None:
                    continue
                comparisons.append(
                    CategoricalComparison(
                        left_coding_id=left_entry.coding_id,
                        right_coding_id=right_entry.coding_id,
                        field_path=f"nuance.{name}",
                        left_value=left_value,
                        right_value=right_value,
                        agrees=left_value == right_value,
                        included_in_score=True,
                    )
                )
        if isinstance(left_entry.coding, DifferentiationCoding) and isinstance(
            right_entry.coding, DifferentiationCoding
        ):
            perspective_pairs = [
                item
                for item in perspective_alignments
                if item.left_coding_id == left_entry.coding_id
                and item.right_coding_id == right_entry.coding_id
            ]
            for perspective_alignment in perspective_pairs:
                left_index = perspective_alignment.left_perspective_index
                right_index = perspective_alignment.right_perspective_index
                if left_index >= len(left_entry.coding.fields.perspectives) or right_index >= len(
                    right_entry.coding.fields.perspectives
                ):
                    continue
                left_values = sorted(
                    item.value
                    for item in left_entry.coding.fields.perspectives[
                        left_index
                    ].perspective_types
                )
                right_values = sorted(
                    item.value
                    for item in right_entry.coding.fields.perspectives[
                        right_index
                    ].perspective_types
                )
                if not left_values and not right_values:
                    continue
                comparisons.append(
                    CategoricalComparison(
                        left_coding_id=left_entry.coding_id,
                        right_coding_id=right_entry.coding_id,
                        field_path=(
                            f"differentiation.perspectives[{left_index}:{right_index}]"
                            ".perspective_types"
                        ),
                        left_value=left_values,
                        right_value=right_values,
                        agrees=left_values == right_values,
                        included_in_score=False,
                    )
                )
    return comparisons


def _perspective_text_index(path: str) -> int | None:
    match = re.fullmatch(r"differentiation\.perspectives\[(\d+)\]\.text", path)
    return int(match.group(1)) if match else None


def _perspective_annotations_by_index(
    annotations: list[NormalizedAnnotation],
) -> dict[int, list[NormalizedAnnotation]]:
    grouped: dict[int, list[NormalizedAnnotation]] = {}
    for annotation in annotations:
        index = _perspective_text_index(annotation.field_path)
        if index is not None:
            grouped.setdefault(index, []).append(annotation)
    return grouped


def _annotations_by_coding(
    annotations: list[NormalizedAnnotation],
) -> dict[str, list[NormalizedAnnotation]]:
    grouped: dict[str, list[NormalizedAnnotation]] = {}
    for annotation in annotations:
        grouped.setdefault(annotation.coding_id, []).append(annotation)
    return grouped


def _cluster_annotations(
    annotations: list[NormalizedAnnotation],
    sources: list[AgreementSource],
    rules: AgreementRules,
) -> list[AgreementCluster]:
    if not annotations:
        return []
    parents = list(range(len(annotations)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parents[right_root] = left_root

    for left_index, right_index in combinations(range(len(annotations)), 2):
        if annotations_match(annotations[left_index], annotations[right_index], rules):
            union(left_index, right_index)
    grouped: dict[int, list[NormalizedAnnotation]] = {}
    for index, annotation in enumerate(annotations):
        grouped.setdefault(find(index), []).append(annotation)
    all_sources = {source.source_index for source in sources}
    clusters = []
    for cluster_id, group in enumerate(grouped.values(), start=1):
        present = {annotation.source_index for annotation in group}
        clusters.append(
            AgreementCluster(
                cluster_id=cluster_id,
                annotations=sorted(group, key=lambda item: item.key),
                present_source_indices=present,
                missing_source_indices=all_sources - present,
            )
        )
    return sorted(
        clusters,
        key=lambda item: (
            -len(item.present_source_indices),
            item.annotations[0].interview_file,
            item.annotations[0].span.range_label,
        ),
    )


def matched_annotation_keys(pair: PairAgreement) -> set[tuple]:
    return {
        annotation.key
        for match in pair.annotation_matches
        for annotation in (match.left, match.right)
    }


def report_as_json(report: AgreementReport) -> str:
    payload = {
        "coding_book_version": CODING_BOOK_VERSION,
        "rules": asdict(report.rules),
        "sources": [
            {
                "source_index": source.source_index,
                "source_name": source.source_name,
                "label": source.label,
                "content_hash": source.content_hash,
            }
            for source in report.sources
        ],
        "total_annotations": report.total_annotations,
        "full_agreement_clusters": report.full_agreement_clusters,
        "pairs": [_pair_as_dict(pair) for pair in report.pair_agreements],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def report_as_csv(report: AgreementReport) -> str:
    output = StringIO()
    parent_metric_names = (
        "left_identified",
        "right_identified",
        "overlap",
        "primary_field_overlap",
        "matched_perspective_pairs",
        "partial_only",
        "no_overlap_left",
        "no_overlap_right",
    )
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "left_source",
            "right_source",
            "true_positives",
            "false_positives",
            "false_negatives",
            "precision",
            "recall",
            "f1",
            "categorical_matches",
            "categorical_total",
            "categorical_agreement",
            "aligned_objects",
            "unmatched_left_objects",
            "unmatched_right_objects",
        ]
        + [
            f"{object_type}_{metric}"
            for object_type in PARENT_CODE_ORDER
            for metric in parent_metric_names
        ],
    )
    writer.writeheader()
    for pair in report.pair_agreements:
        row = {
            "left_source": pair.left_label,
            "right_source": pair.right_label,
            "true_positives": pair.true_positives,
            "false_positives": pair.false_positives,
            "false_negatives": pair.false_negatives,
            "precision": f"{pair.precision:.6f}",
            "recall": f"{pair.recall:.6f}",
            "f1": f"{pair.f1:.6f}",
            "categorical_matches": pair.categorical_matches,
            "categorical_total": pair.categorical_total,
            "categorical_agreement": (
                ""
                if pair.categorical_agreement is None
                else f"{pair.categorical_agreement:.6f}"
            ),
            "aligned_objects": len(pair.object_alignments),
            "unmatched_left_objects": len(pair.unmatched_left_coding_ids),
            "unmatched_right_objects": len(pair.unmatched_right_coding_ids),
        }
        for summary in pair.parent_code_summaries:
            for metric in parent_metric_names:
                row[f"{summary.object_type}_{metric}"] = getattr(summary, metric)
        writer.writerow(row)
    return "\ufeff" + output.getvalue()


def _pair_as_dict(pair: PairAgreement) -> dict[str, Any]:
    return {
        "left_source_index": pair.left_source_index,
        "right_source_index": pair.right_source_index,
        "left_label": pair.left_label,
        "right_label": pair.right_label,
        "true_positives": pair.true_positives,
        "false_positives": pair.false_positives,
        "false_negatives": pair.false_negatives,
        "precision": pair.precision,
        "recall": pair.recall,
        "f1": pair.f1,
        "categorical_matches": pair.categorical_matches,
        "categorical_total": pair.categorical_total,
        "categorical_agreement": pair.categorical_agreement,
        "parent_code_summaries": [
            asdict(item) for item in pair.parent_code_summaries
        ],
        "object_alignments": [asdict(item) for item in pair.object_alignments],
        "perspective_alignments": [
            asdict(item) for item in pair.perspective_alignments
        ],
        "object_review_items": [asdict(item) for item in pair.object_review_items],
        "unmatched_left_coding_ids": pair.unmatched_left_coding_ids,
        "unmatched_right_coding_ids": pair.unmatched_right_coding_ids,
        "categorical_comparisons": [asdict(item) for item in pair.categorical_comparisons],
        "annotation_matches": [
            {
                "left": match.left.key,
                "right": match.right.key,
                "quality": match.quality,
            }
            for match in pair.annotation_matches
        ],
    }


def _source_label(
    source_name: str,
    analyses: list[Analysis],
    codings: list[SimplifiedCodingEntry],
) -> str:
    for analysis in analyses:
        if analysis.owner_username:
            return analysis.owner_username
    for coding in codings:
        if coding.created_by:
            return coding.created_by
    return source_name


def _ordered_span_points(
    span: TranscriptSpan,
) -> tuple[tuple[int, str, int], tuple[int, str, int]]:
    start = _span_point(span.start_segment_id, span.start_char_offset)
    end = _span_point(span.end_segment_id, span.end_char_offset)
    return (start, end) if start <= end else (end, start)


def _span_point(segment_id: str, char_offset: int) -> tuple[int, str, int]:
    match = re.search(r"(\d+)$", segment_id)
    if match:
        return (int(match.group(1)), "", char_offset)
    return (0, segment_id, char_offset)


def _overlap_quality(left: TranscriptSpan, right: TranscriptSpan) -> float:
    left_start, left_end = _ordered_span_points(left)
    right_start, right_end = _ordered_span_points(right)
    if left_start == right_start and left_end == right_end:
        return 1.0
    if not spans_overlap(left, right):
        return 0.0
    if left_start[0] == left_end[0] == right_start[0] == right_end[0]:
        overlap = min(left_end[2], right_end[2]) - max(left_start[2], right_start[2])
        union = max(left_end[2], right_end[2]) - min(left_start[2], right_start[2])
        return overlap / union if union else 0.0
    return 0.5
