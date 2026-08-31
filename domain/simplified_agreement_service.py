from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import json
import re
from typing import Literal

from coding_books.simplified_v4.models import CODING_BOOK_VERSION, SimplifiedCodingEntry
from core_models import Analysis
from domain.simplified_analysis_exchange_service import EXPORT_FORMAT_VERSION


SpanMode = Literal["exact", "partial"]
FieldMode = Literal["exact", "normalized", "ignore"]


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


@dataclass(frozen=True)
class AgreementSource:
    source_index: int
    source_name: str
    label: str
    analyses: list[Analysis]
    codings: list[SimplifiedCodingEntry]
    annotations: list[NormalizedAnnotation]
    warnings: list[str]


@dataclass(frozen=True)
class AgreementCluster:
    cluster_id: int
    annotations: list[NormalizedAnnotation]
    present_source_indices: set[int]
    missing_source_indices: set[int]

    @property
    def field_paths(self) -> list[str]:
        return sorted({annotation.normalized_field_path for annotation in self.annotations})


@dataclass(frozen=True)
class PairAgreement:
    left_label: str
    right_label: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class AgreementReport:
    sources: list[AgreementSource]
    rules: AgreementRules
    total_annotations: int
    clusters: list[AgreementCluster]
    full_agreement_clusters: int
    pair_agreements: list[PairAgreement]


def load_agreement_export(
    raw_text: str,
    *,
    source_name: str,
    source_index: int,
) -> AgreementSource:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Agreement input must be a JSON object")
    if payload.get("export_format_version") != EXPORT_FORMAT_VERSION:
        raise ValueError("Unsupported simplified coding export format")
    if payload.get("coding_book_version") != CODING_BOOK_VERSION:
        raise ValueError(
            "Agreement comparison accepts coding book v4 exports only; the uploaded file was not changed."
        )

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
        if not coding.field_spans:
            warnings.append(f"Coding {coding.coding_id} has no transcript spans.")
            continue
        for field_path, spans in coding.field_spans.items():
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

    return AgreementSource(
        source_index=source_index,
        source_name=source_name,
        label=label,
        analyses=analyses,
        codings=codings,
        annotations=annotations,
        warnings=warnings,
    )


def build_agreement_report(
    sources: list[AgreementSource],
    rules: AgreementRules | None = None,
) -> AgreementReport:
    rules = rules or AgreementRules()
    annotations = [annotation for source in sources for annotation in source.annotations]
    clusters = _cluster_annotations(annotations, sources, rules)
    full_agreement_clusters = sum(
        1
        for cluster in clusters
        if sources and len(cluster.present_source_indices) == len(sources)
    )
    return AgreementReport(
        sources=sources,
        rules=rules,
        total_annotations=len(annotations),
        clusters=clusters,
        full_agreement_clusters=full_agreement_clusters,
        pair_agreements=_pair_agreements(sources, rules),
    )


def normalize_field_path(field_path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", field_path)


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

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left_index, right_index in combinations(range(len(annotations)), 2):
        if annotations_match(annotations[left_index], annotations[right_index], rules):
            union(left_index, right_index)

    grouped: dict[int, list[NormalizedAnnotation]] = {}
    for index, annotation in enumerate(annotations):
        grouped.setdefault(find(index), []).append(annotation)

    all_source_indices = {source.source_index for source in sources}
    clusters = []
    for cluster_id, group in enumerate(grouped.values(), start=1):
        present = {annotation.source_index for annotation in group}
        clusters.append(
            AgreementCluster(
                cluster_id=cluster_id,
                annotations=sorted(
                    group,
                    key=lambda annotation: (
                        annotation.source_index,
                        annotation.normalized_field_path,
                        annotation.span.range_label,
                    ),
                ),
                present_source_indices=present,
                missing_source_indices=all_source_indices - present,
            )
        )
    return sorted(
        clusters,
        key=lambda cluster: (
            -len(cluster.present_source_indices),
            cluster.annotations[0].interview_file,
            cluster.annotations[0].span.range_label,
            cluster.annotations[0].normalized_field_path,
        ),
    )


def _pair_agreements(
    sources: list[AgreementSource],
    rules: AgreementRules,
) -> list[PairAgreement]:
    reports = []
    for left, right in combinations(sources, 2):
        matches = _best_matches(left.annotations, right.annotations, rules)
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
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        reports.append(
            PairAgreement(
                left_label=f"{left.label} ({left.source_name})",
                right_label=f"{right.label} ({right.source_name})",
                true_positives=true_positives,
                false_positives=false_positives,
                false_negatives=false_negatives,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
    return reports


def _best_matches(
    left_annotations: list[NormalizedAnnotation],
    right_annotations: list[NormalizedAnnotation],
    rules: AgreementRules,
) -> list[tuple[int, int]]:
    candidates: list[tuple[float, int, int]] = []
    for left_index, left in enumerate(left_annotations):
        for right_index, right in enumerate(right_annotations):
            if annotations_match(left, right, rules):
                candidates.append((_overlap_quality(left.span, right.span), left_index, right_index))
    candidates.sort(reverse=True)
    used_left: set[int] = set()
    used_right: set[int] = set()
    matches = []
    for _quality, left_index, right_index in candidates:
        if left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        matches.append((left_index, right_index))
    return matches


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
