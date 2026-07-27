from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

import numpy as np
from scipy.stats import friedmanchisquare

from .analysis import analyze_feature, feature_spec
from .config import BED_POSITIONS, normalize_bed_position
from .models import CapabilityResult, MeasurementRecord, ProjectSettings


@dataclass(frozen=True)
class SpatialAnalysisResult:
    feature_key: str
    global_result: CapabilityResult | None
    position_results: tuple[tuple[str, CapabilityResult], ...]
    position_mean_span: float | None
    minimum_position: str | None
    maximum_position: str | None
    complete_batches: int
    position_count: int
    friedman_statistic: float | None
    friedman_p: float | None
    kendall_w: float | None
    status: str
    note: str


def _batch_position_matrix(
    records: Sequence[MeasurementRecord],
    feature_key: str,
    positions: Sequence[str],
) -> tuple[list[str], np.ndarray]:
    grouped: dict[tuple[str, str], list[float]] = {}
    batches: set[str] = set()
    for record in records:
        value = record.values.get(feature_key)
        if value is None:
            continue
        position = normalize_bed_position(record.bed_position)
        if position not in positions:
            continue
        batch = str(record.batch or "").strip()
        batches.add(batch)
        grouped.setdefault((batch, position), []).append(float(value))

    complete_batches: list[str] = []
    rows: list[list[float]] = []
    for batch in sorted(batches, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x)):
        if all((batch, position) in grouped for position in positions):
            complete_batches.append(batch)
            rows.append([float(np.mean(grouped[(batch, position)])) for position in positions])
    if not rows:
        return complete_batches, np.empty((0, len(positions)), dtype=float)
    return complete_batches, np.asarray(rows, dtype=float)


def analyze_spatial_feature(
    records: Sequence[MeasurementRecord],
    feature_key: str,
    settings: ProjectSettings,
) -> SpatialAnalysisResult:
    base = [record for record in records if record.study_type == "Bauraumprüfung"]
    global_result = analyze_feature(base, feature_key, settings)

    position_rows: list[tuple[str, CapabilityResult]] = []
    for position in BED_POSITIONS:
        subset = [record for record in base if normalize_bed_position(record.bed_position) == position]
        result = analyze_feature(subset, feature_key, settings)
        if result is not None:
            position_rows.append((position, result))

    means = [(position, result.mean) for position, result in position_rows]
    if means:
        min_position, min_mean = min(means, key=lambda item: item[1])
        max_position, max_mean = max(means, key=lambda item: item[1])
        mean_span = max_mean - min_mean
    else:
        min_position = max_position = None
        mean_span = None

    positions = [position for position, _ in position_rows]
    complete_batches, matrix = _batch_position_matrix(base, feature_key, positions)
    friedman_stat = friedman_p = kendall_w = None
    if matrix.shape[0] >= 2 and matrix.shape[1] >= 3:
        try:
            test = friedmanchisquare(*(matrix[:, index] for index in range(matrix.shape[1])))
            if isfinite(float(test.statistic)) and isfinite(float(test.pvalue)):
                friedman_stat = float(test.statistic)
                friedman_p = float(test.pvalue)
                kendall_w = friedman_stat / (matrix.shape[0] * (matrix.shape[1] - 1))
        except ValueError:
            pass

    if not position_rows:
        status = "nicht beurteilbar"
        note = "Für das Merkmal liegen keine positionsbezogenen Messwerte vor."
    elif len(position_rows) < 3:
        status = "nur eingeschränkt beurteilbar"
        note = "Es liegen weniger als drei auswertbare Druckbettpositionen vor."
    elif friedman_p is None:
        status = "blockweiser Test nicht möglich"
        note = (
            "Für eine blockweise Positionsprüfung fehlen mindestens zwei vollständige Batches mit Werten an allen "
            "ausgewerteten Positionen. Die Positionsmittelwerte bleiben deskriptiv vergleichbar."
        )
    elif friedman_p < settings.alpha:
        status = "positionsbezogene Unterschiede auffällig"
        note = (
            "Der ergänzende Friedman-Test zeigt über die vollständigen Druckbatches einen auffälligen systematischen "
            "Rangunterschied zwischen den Positionen. Wegen der festen Werkzeugpfadreihenfolge beschreibt dies einen "
            "positionsbezogenen Gesamteffekt und keinen isolierten kausalen Positionseffekt."
        )
    else:
        status = "kein hinreichender statistischer Hinweis"
        note = (
            "Der ergänzende Friedman-Test liefert keinen hinreichenden Hinweis auf einen systematischen Rangunterschied "
            "zwischen den Positionen. Das bestätigt keine Positionsunabhängigkeit; Positionsmittelwerte, Heatmap und "
            "praktische Größenordnung der Unterschiede sind weiterhin gemeinsam zu beurteilen."
        )

    return SpatialAnalysisResult(
        feature_key=feature_key,
        global_result=global_result,
        position_results=tuple(position_rows),
        position_mean_span=mean_span,
        minimum_position=min_position,
        maximum_position=max_position,
        complete_batches=len(complete_batches),
        position_count=len(position_rows),
        friedman_statistic=friedman_stat,
        friedman_p=friedman_p,
        kendall_w=kendall_w,
        status=status,
        note=note,
    )


def spatial_summary_text(result: SpatialAnalysisResult, settings: ProjectSettings) -> str:
    spec = feature_spec(result.feature_key)
    parts = [f"Merkmal: {spec.label}."]
    if result.global_result is not None:
        parts.append(
            f"Global über alle Positionen und Batches: n = {result.global_result.n}, "
            f"Mittelwert = {result.global_result.mean:.3f} {result.global_result.unit}, "
            f"s = {result.global_result.stdev:.3f} {result.global_result.unit}, "
            f"Cₘₖ = {result.global_result.cmk:.2f}." if result.global_result.cmk is not None else
            f"Global über alle Positionen und Batches: n = {result.global_result.n}, "
            f"Mittelwert = {result.global_result.mean:.3f} {result.global_result.unit}, "
            f"s = {result.global_result.stdev:.3f} {result.global_result.unit}; Cₘ/Cₘₖ nicht definiert oder nicht vorgesehen."
        )
    if result.position_mean_span is not None:
        parts.append(
            f"Die Spanne der Positionsmittelwerte beträgt {result.position_mean_span:.3f} {spec.unit}; "
            f"kleinstes Positionsmittel: {result.minimum_position}, größtes: {result.maximum_position}."
        )
    if result.friedman_p is not None:
        p_text = "< 0,0001" if result.friedman_p < 0.0001 else f"{result.friedman_p:.4f}".replace(".", ",")
        parts.append(
            f"Blockweise Positionsprüfung: {result.complete_batches} vollständige Batches, "
            f"Friedman p = {p_text}, Kendall W = {result.kendall_w:.3f}."
        )
    parts.append(result.note)
    return " ".join(parts)
