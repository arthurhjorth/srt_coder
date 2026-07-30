from __future__ import annotations

from dataclasses import dataclass
import json
import re
from itertools import combinations
from typing import Any, Literal

from models import Analysis, CodingEntry
from domain.differentiation_migration import migrate_export_payload


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
            f"{self.start_segment_id}:{self.start_char_offset}"
            f"-{self.end_segment_id}:{self.end_char_offset}"
        )


@dataclass(frozen=True)
class AgreementSource:
    source_index: int
    source_name: str
    label: str
    analyses: list[Analysis]
    codings: list[CodingEntry]
    annotations: list["NormalizedAnnotation"]
    warnings: list[str]


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
    root_object_key: str
    embedded_parent_path: str | None
    normalized_embedded_parent_path: str | None
    span: TranscriptSpan


@dataclass(frozen=True)
class AnnotationMatch:
    left: NormalizedAnnotation
    right: NormalizedAnnotation
    quality: float


@dataclass(frozen=True)
class GraphDiagnostics:
    root_splits: int
    root_merges: int
    embedded_splits: int
    embedded_merges: int
    warnings: list[str]

    @property
    def total_issues(self) -> int:
        return self.root_splits + self.root_merges + self.embedded_splits + self.embedded_merges


@dataclass(frozen=True)
class AgreementCluster:
    cluster_id: int
    annotations: list[NormalizedAnnotation]
    present_source_indices: set[int]
    missing_source_indices: set[int]

    @property
    def object_types(self) -> list[str]:
        return sorted({a.object_type for a in self.annotations if a.object_type})

    @property
    def field_paths(self) -> list[str]:
        return sorted({a.normalized_field_path for a in self.annotations if a.normalized_field_path})


@dataclass(frozen=True)
class PairAgreement:
    left_label: str
    right_label: str
    overlap_clusters: int
    union_clusters: int
    score: float
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    graph_diagnostics: GraphDiagnostics
    annotation_matches: list[AnnotationMatch]


@dataclass(frozen=True)
class AgreementReport:
    sources: list[AgreementSource]
    rules: AgreementRules
    total_annotations: int
    clusters: list[AgreementCluster]
    full_agreement_clusters: int
    pair_agreements: list[PairAgreement]


def load_agreement_export(raw_text: str, *, source_name: str, source_index: int) -> AgreementSource:
    """Parse an exported analysis bundle for read-only agreement comparison."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Agreement input must be a JSON object")

    payload = migrate_export_payload(payload)

    analyses_raw = payload.get("analyses")
    if analyses_raw is None and payload.get("analysis") is not None:
        analyses_raw = [payload.get("analysis")]
    if not isinstance(analyses_raw, list) or not analyses_raw:
        raise ValueError("Agreement input must contain at least one analysis")

    codings_raw = payload.get("codings") or []
    if not isinstance(codings_raw, list):
        raise ValueError("codings must be a list")

    analyses = [Analysis.model_validate(raw) for raw in analyses_raw]
    codings = [CodingEntry.model_validate(raw) for raw in codings_raw]
    analysis_by_id = {a.analysis_id: a for a in analyses if a.analysis_id}

    label = _source_label(source_name, analyses, codings)
    warnings: list[str] = []
    annotations: list[NormalizedAnnotation] = []

    for coding in codings:
        analysis = analysis_by_id.get(coding.analysis_id or "") or analyses[0]
        field_spans = coding.field_spans or {}
        if not field_spans:
            warnings.append(f"Coding {coding.coding_id or '(no id)'} has no field spans.")
            continue
        if not isinstance(field_spans, dict):
            warnings.append(f"Coding {coding.coding_id or '(no id)'} has invalid field spans.")
            continue

        for field_path, raw_spans in field_spans.items():
            if not isinstance(raw_spans, list):
                warnings.append(f"Field {field_path} has invalid span data.")
                continue
            for raw_span in raw_spans:
                span = _parse_span(raw_span)
                if span is None:
                    warnings.append(f"Field {field_path} has a span without complete offsets.")
                    continue
                annotations.append(
                    NormalizedAnnotation(
                        annotation_id=len(annotations),
                        source_index=source_index,
                        source_label=label,
                        source_name=source_name,
                        analysis_id=coding.analysis_id or "",
                        analysis_name=analysis.name or "",
                        interview_file=coding.interview_file or analysis.interview_file or "",
                        coding_id=coding.coding_id or "",
                        object_type=coding.object_type or "",
                        field_path=str(field_path),
                        normalized_field_path=normalize_field_path(str(field_path)),
                        root_object_key=_root_object_key(coding, len(annotations)),
                        embedded_parent_path=extract_embedded_parent_path(str(field_path)),
                        normalized_embedded_parent_path=(
                            normalize_field_path(parent_path)
                            if (parent_path := extract_embedded_parent_path(str(field_path))) is not None
                            else None
                        ),
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
    clusters = _cluster_annotations(annotations, sources=sources, rules=rules)
    pair_agreements = _pair_agreements(clusters, sources, rules)
    full_agreement_clusters = sum(
        1 for cluster in clusters if len(cluster.present_source_indices) == len(sources)
    )
    return AgreementReport(
        sources=sources,
        rules=rules,
        total_annotations=len(annotations),
        clusters=clusters,
        full_agreement_clusters=full_agreement_clusters,
        pair_agreements=pair_agreements,
    )


def normalize_field_path(field_path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", field_path)


def extract_embedded_parent_path(field_path: str) -> str | None:
    match = re.search(r"^(.*\[\d+\])\.[^.]+$", field_path)
    if not match:
        return None
    return match.group(1)


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
        return left.span == right.span
    return spans_overlap(left.span, right.span)


def spans_overlap(left: TranscriptSpan, right: TranscriptSpan) -> bool:
    left_start = _span_point(left.start_segment_id, left.start_char_offset)
    left_end = _span_point(left.end_segment_id, left.end_char_offset)
    right_start = _span_point(right.start_segment_id, right.start_char_offset)
    right_end = _span_point(right.end_segment_id, right.end_char_offset)

    if left_start > left_end:
        left_start, left_end = left_end, left_start
    if right_start > right_end:
        right_start, right_end = right_end, right_start

    return left_start < right_end and right_start < left_end


def _cluster_annotations(
    annotations: list[NormalizedAnnotation],
    *,
    sources: list[AgreementSource],
    rules: AgreementRules,
) -> list[AgreementCluster]:
    if not annotations:
        return []

    parent = list(range(len(annotations)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, right_index in combinations(range(len(annotations)), 2):
        if annotations_match(annotations[left_index], annotations[right_index], rules):
            union(left_index, right_index)

    grouped: dict[int, list[NormalizedAnnotation]] = {}
    for index, annotation in enumerate(annotations):
        grouped.setdefault(find(index), []).append(annotation)

    all_source_indices = {source.source_index for source in sources}
    clusters: list[AgreementCluster] = []
    for cluster_id, group in enumerate(grouped.values(), start=1):
        present = {annotation.source_index for annotation in group}
        clusters.append(
            AgreementCluster(
                cluster_id=cluster_id,
                annotations=sorted(group, key=lambda a: (a.source_index, a.field_path, a.span.range_label)),
                present_source_indices=present,
                missing_source_indices=all_source_indices - present,
            )
        )

    return sorted(
        clusters,
        key=lambda c: (
            -len(c.present_source_indices),
            c.annotations[0].interview_file if c.annotations else "",
            c.annotations[0].span.range_label if c.annotations else "",
            c.annotations[0].normalized_field_path if c.annotations else "",
        ),
    )


def _pair_agreements(
    clusters: list[AgreementCluster],
    sources: list[AgreementSource],
    rules: AgreementRules,
) -> list[PairAgreement]:
    by_index = {source.source_index: f"{source.label} ({source.source_name})" for source in sources}
    sources_by_index = {source.source_index: source for source in sources}
    reports: list[PairAgreement] = []
    for left, right in combinations([source.source_index for source in sources], 2):
        overlap = sum(
            1 for cluster in clusters if left in cluster.present_source_indices and right in cluster.present_source_indices
        )
        union = sum(
            1 for cluster in clusters if left in cluster.present_source_indices or right in cluster.present_source_indices
        )
        f1_counts = _pairwise_f1_counts(
            sources_by_index[left].annotations,
            sources_by_index[right].annotations,
            rules,
        )
        graph_diagnostics = _graph_diagnostics(
            f1_counts["matches"],
            left_label=by_index.get(left, str(left)),
            right_label=by_index.get(right, str(right)),
        )
        reports.append(
            PairAgreement(
                left_label=by_index.get(left, str(left)),
                right_label=by_index.get(right, str(right)),
                overlap_clusters=overlap,
                union_clusters=union,
                score=(overlap / union) if union else 0.0,
                true_positives=f1_counts["tp"],
                false_positives=f1_counts["fp"],
                false_negatives=f1_counts["fn"],
                precision=f1_counts["precision"],
                recall=f1_counts["recall"],
                f1=f1_counts["f1"],
                graph_diagnostics=graph_diagnostics,
                annotation_matches=f1_counts["matches"],
            )
        )
    return reports


def _pairwise_f1_counts(
    left_annotations: list[NormalizedAnnotation],
    right_annotations: list[NormalizedAnnotation],
    rules: AgreementRules,
) -> dict[str, float | int | list[AnnotationMatch]]:
    matches = _pairwise_annotation_matches(left_annotations, right_annotations, rules)
    true_positives = len(matches)
    false_positives = len(left_annotations) - true_positives
    false_negatives = len(right_annotations) - true_positives
    precision = true_positives / (true_positives + false_positives) if true_positives + false_positives else 0.0
    recall = true_positives / (true_positives + false_negatives) if true_positives + false_negatives else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": true_positives,
        "fp": false_positives,
        "fn": false_negatives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "matches": matches,
    }


def _pairwise_annotation_matches(
    left_annotations: list[NormalizedAnnotation],
    right_annotations: list[NormalizedAnnotation],
    rules: AgreementRules,
) -> list[AnnotationMatch]:
    candidates: list[tuple[float, int, int]] = []
    for left_index, left in enumerate(left_annotations):
        for right_index, right in enumerate(right_annotations):
            if annotations_match(left, right, rules):
                candidates.append((_match_quality(left, right, rules), left_index, right_index))

    candidates.sort(reverse=True)
    matched_left: set[int] = set()
    matched_right: set[int] = set()
    matches: list[AnnotationMatch] = []
    for quality, left_index, right_index in candidates:
        if left_index in matched_left or right_index in matched_right:
            continue
        matched_left.add(left_index)
        matched_right.add(right_index)
        matches.append(
            AnnotationMatch(
                left=left_annotations[left_index],
                right=right_annotations[right_index],
                quality=quality,
            )
        )
    return matches


def _graph_diagnostics(
    matches: list[AnnotationMatch],
    *,
    left_label: str,
    right_label: str,
) -> GraphDiagnostics:
    root_left_to_right: dict[str, set[str]] = {}
    root_right_to_left: dict[str, set[str]] = {}
    embedded_left_to_right: dict[str, set[str]] = {}
    embedded_right_to_left: dict[str, set[str]] = {}

    for match in matches:
        _add_link(root_left_to_right, match.left.root_object_key, match.right.root_object_key)
        _add_link(root_right_to_left, match.right.root_object_key, match.left.root_object_key)

        left_embedded = _embedded_object_key(match.left)
        right_embedded = _embedded_object_key(match.right)
        if left_embedded and right_embedded:
            _add_link(embedded_left_to_right, left_embedded, right_embedded)
            _add_link(embedded_right_to_left, right_embedded, left_embedded)

    root_splits = sum(1 for targets in root_left_to_right.values() if len(targets) > 1)
    root_merges = sum(1 for targets in root_right_to_left.values() if len(targets) > 1)
    embedded_splits = sum(1 for targets in embedded_left_to_right.values() if len(targets) > 1)
    embedded_merges = sum(1 for targets in embedded_right_to_left.values() if len(targets) > 1)

    warnings: list[str] = []
    warnings.extend(
        _connection_warnings(
            root_left_to_right,
            f"{left_label} root object",
            f"{right_label} root objects",
            "split",
        )
    )
    warnings.extend(
        _connection_warnings(
            root_right_to_left,
            f"{right_label} root object",
            f"{left_label} root objects",
            "merge",
        )
    )
    warnings.extend(
        _connection_warnings(
            embedded_left_to_right,
            f"{left_label} embedded object",
            f"{right_label} embedded objects",
            "embedded split",
        )
    )
    warnings.extend(
        _connection_warnings(
            embedded_right_to_left,
            f"{right_label} embedded object",
            f"{left_label} embedded objects",
            "embedded merge",
        )
    )

    return GraphDiagnostics(
        root_splits=root_splits,
        root_merges=root_merges,
        embedded_splits=embedded_splits,
        embedded_merges=embedded_merges,
        warnings=warnings,
    )


def _add_link(links: dict[str, set[str]], left: str, right: str) -> None:
    if not left or not right:
        return
    links.setdefault(left, set()).add(right)


def _connection_warnings(
    links: dict[str, set[str]],
    left_name: str,
    right_name: str,
    label: str,
) -> list[str]:
    warnings = []
    for left, targets in sorted(links.items()):
        if len(targets) <= 1:
            continue
        warnings.append(f"{label}: {left_name} {left} maps to {len(targets)} {right_name}.")
    return warnings


def _match_quality(
    left: NormalizedAnnotation,
    right: NormalizedAnnotation,
    rules: AgreementRules,
) -> float:
    if rules.span_mode == "exact":
        return 1.0
    return _span_overlap_ratio(left.span, right.span)


def _span_overlap_ratio(left: TranscriptSpan, right: TranscriptSpan) -> float:
    left_start = _span_point(left.start_segment_id, left.start_char_offset)
    left_end = _span_point(left.end_segment_id, left.end_char_offset)
    right_start = _span_point(right.start_segment_id, right.start_char_offset)
    right_end = _span_point(right.end_segment_id, right.end_char_offset)

    if left_start > left_end:
        left_start, left_end = left_end, left_start
    if right_start > right_end:
        right_start, right_end = right_end, right_start

    overlap_start = max(left_start, right_start)
    overlap_end = min(left_end, right_end)
    if overlap_start >= overlap_end:
        return 0.0

    overlap = _point_distance(overlap_start, overlap_end)
    union = _point_distance(min(left_start, right_start), max(left_end, right_end))
    return (overlap / union) if union else 0.0


def _point_distance(left: tuple[int, str, int], right: tuple[int, str, int]) -> int:
    if left[1] or right[1]:
        if left[0] == right[0] and left[1] == right[1]:
            return max(0, right[2] - left[2])
        return 1
    return max(0, ((right[0] - left[0]) * 1_000_000) + right[2] - left[2])


def _source_label(source_name: str, analyses: list[Analysis], codings: list[CodingEntry]) -> str:
    for analysis in analyses:
        if analysis.owner_username:
            return analysis.owner_username
    for coding in codings:
        if coding.created_by:
            return coding.created_by
    return source_name


def _root_object_key(coding: CodingEntry, fallback_index: int) -> str:
    if coding.coding_id:
        return coding.coding_id
    return f"{coding.object_type or 'coding'}:{fallback_index}"


def _embedded_object_key(annotation: NormalizedAnnotation) -> str | None:
    if annotation.embedded_parent_path is None:
        return None
    return f"{annotation.root_object_key}:{annotation.embedded_parent_path}"


def _parse_span(raw_span: Any) -> TranscriptSpan | None:
    if not isinstance(raw_span, dict):
        return None
    start_segment_id = raw_span.get("start_segment_id")
    end_segment_id = raw_span.get("end_segment_id")
    start_char_offset = raw_span.get("start_char_offset")
    end_char_offset = raw_span.get("end_char_offset")
    if not start_segment_id or not end_segment_id:
        return None
    if start_char_offset is None or end_char_offset is None:
        return None
    try:
        start_offset = int(start_char_offset)
        end_offset = int(end_char_offset)
    except (TypeError, ValueError):
        return None
    return TranscriptSpan(
        start_segment_id=str(start_segment_id),
        start_char_offset=start_offset,
        end_segment_id=str(end_segment_id),
        end_char_offset=end_offset,
        selected_text=str(raw_span.get("selected_text") or ""),
    )


def _span_point(segment_id: str, char_offset: int) -> tuple[int, str, int]:
    match = re.search(r"(\d+)$", segment_id)
    if match:
        return (int(match.group(1)), "", char_offset)
    return (0, segment_id, char_offset)
