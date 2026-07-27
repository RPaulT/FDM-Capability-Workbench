from __future__ import annotations

from collections import defaultdict
from typing import Sequence

import numpy as np
from matplotlib.figure import Figure
from scipy.stats import norm, probplot
from matplotlib.colors import TwoSlopeNorm

from .analysis import analyze_feature, analyze_records, feature_spec
from .config import BED_POSITION_GRID, BED_POSITIONS, normalize_bed_position
from .models import DistributionResult, MeasurementRecord, ProjectSettings, values_for_feature


def _figure(title: str, figsize=(8.8, 5.2)) -> tuple[Figure, object]:
    figure = Figure(figsize=figsize, dpi=100)
    axis = figure.add_subplot(111)
    axis.set_title(title)
    axis.grid(True, alpha=0.25)
    return figure, axis


def chronological_figure(records: Sequence[MeasurementRecord], feature_key: str) -> Figure:
    spec = feature_spec(feature_key)
    values = values_for_feature(records, feature_key)
    fig, ax = _figure(f"Verlauf – {spec.label}")
    indices = np.arange(1, len(values) + 1)
    ax.plot(indices, values, marker="o", linewidth=1.2)
    if spec.nominal is not None:
        ax.axhline(spec.nominal, linestyle="--", linewidth=1.0, label="Nennmaß")
        ax.legend()
    ax.set_xlabel("Messreihenfolge")
    ax.set_ylabel(f"{spec.label} [{spec.unit}]")
    return fig


def _histogram_bins(values: np.ndarray, resolution: float, *, detail: bool) -> np.ndarray | int:
    """Wählt bei quantisierten Daten bevorzugt Ablesestufen als Klassen."""
    unique_values = np.unique(values)
    if unique_values.size <= 60 and resolution > 0:
        low = float(unique_values.min() - resolution / 2.0)
        high = float(unique_values.max() + resolution / 2.0)
        edges = np.arange(low, high + resolution * 0.51, resolution)
        if edges.size >= 2:
            return edges
    if detail:
        return min(max(int(np.sqrt(values.size)), 5), 24)
    return min(max(unique_values.size, 5), 24)


def _add_capability_histogram(
    ax,
    records: Sequence[MeasurementRecord],
    feature_key: str,
    settings: ProjectSettings,
    *,
    detail: bool = False,
    distribution: DistributionResult | None = None,
) -> None:
    """Zeichnet eine fachlich eindeutige Fähigkeitsdarstellung.

    Die natürliche Prozessbreite beträgt 6s und reicht von x̄-3s bis x̄+3s.
    Es werden bewusst keine Linien bei ±6s gezeichnet, da dies einer 12s-Breite
    entsprechen würde und für Cₘ/Cₘₖ irreführend wäre.
    """
    spec = feature_spec(feature_key)
    values = np.asarray(values_for_feature(records, feature_key), dtype=float)
    if values.size == 0:
        return

    resolution = settings.mass_resolution_g if spec.unit == "g" else settings.resolution_mm
    ax.hist(
        values,
        bins=_histogram_bins(values, resolution, detail=detail),
        density=True,
        alpha=0.55,
        edgecolor="black",
        label="Messwerte" if detail else "beobachtete Ablesestufen",
    )

    sample_mean = float(np.mean(values))
    sample_stdev = float(np.std(values, ddof=1)) if values.size >= 2 else 0.0
    fit_mu = distribution.fitted_mu if distribution and distribution.fitted_mu is not None else sample_mean
    fit_sigma = distribution.fitted_sigma if distribution and distribution.fitted_sigma is not None else sample_stdev

    lower = spec.nominal - settings.tolerance_half_width_mm if spec.nominal is not None else None
    upper = spec.nominal + settings.tolerance_half_width_mm if spec.nominal is not None else None
    process_low = sample_mean - 3.0 * sample_stdev if sample_stdev > 0 else None
    process_high = sample_mean + 3.0 * sample_stdev if sample_stdev > 0 else None

    x_candidates = [float(values.min()), float(values.max()), sample_mean]
    for candidate in (lower, upper, process_low, process_high, spec.nominal):
        if candidate is not None:
            x_candidates.append(float(candidate))
    margin = max((fit_sigma if fit_sigma and fit_sigma > 0 else resolution) * 1.5, resolution)
    if detail:
        x_min = float(values.min()) - margin
        x_max = float(values.max()) + margin
    else:
        x_min = min(x_candidates) - margin
        x_max = max(x_candidates) + margin
    x_grid = np.linspace(x_min, x_max, 700)

    if fit_sigma is not None and fit_sigma > 0:
        model_label = (
            "quantisiertes Normalmodell (μ̂, σ̂)"
            if distribution and distribution.fitted_mu is not None
            else "angepasste Normaldichte (x̄, s)"
        )
        density = norm.pdf(x_grid, fit_mu, fit_sigma)
        ax.plot(x_grid, density, linewidth=1.6, label=model_label)
        if not detail and lower is not None and upper is not None:
            lower_mask = x_grid < lower
            upper_mask = x_grid > upper
            ax.fill_between(x_grid[lower_mask], 0, density[lower_mask], alpha=0.14)
            ax.fill_between(x_grid[upper_mask], 0, density[upper_mask], alpha=0.14)

    ax.axvline(sample_mean, linewidth=1.3, label="Mittelwert x̄")
    if sample_stdev > 0:
        ax.axvspan(process_low, process_high, alpha=0.10, label="6s-Breite (x̄ ± 3s)")
        ax.axvline(process_low, linestyle="-.", linewidth=1.1, label="x̄ − 3s")
        ax.axvline(process_high, linestyle="-.", linewidth=1.1, label="x̄ + 3s")

    if spec.nominal is not None and not detail:
        ax.axvline(spec.nominal, linestyle=":", linewidth=1.3, label="Nennmaß")
        ax.axvline(lower, linestyle="--", linewidth=1.4, label="UGW")
        ax.axvline(upper, linestyle="--", linewidth=1.4, label="OGW")

    ax.set_xlim(x_min, x_max)
    if not detail:
        result = analyze_feature(records, feature_key, settings)
        if result is not None:
            lines = [f"n = {result.n}", f"x̄ = {result.mean:.3f} {result.unit}", f"s = {result.stdev:.3f} {result.unit}"]
            if result.cm is not None:
                lines.append(f"Cₘ = {result.cm:.2f}")
            if result.cmk is not None:
                lines.append(f"Cₘₖ = {result.cmk:.2f}")
            ax.text(
                0.015,
                0.97,
                "\n".join(lines),
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=8,
                bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.82},
            )

    ax.set_xlabel(f"{spec.label} [{spec.unit}]")
    ax.set_ylabel("Dichte")
    ax.legend(fontsize=8, ncols=2 if detail else 3, loc="best")


def histogram_figure(
    records: Sequence[MeasurementRecord],
    feature_key: str,
    settings: ProjectSettings,
    *,
    detail: bool = False,
) -> Figure:
    spec = feature_spec(feature_key)
    title = f"Histogramm (Detail) – {spec.label}" if detail else f"Fähigkeitshistogramm – {spec.label}"
    fig, ax = _figure(title)
    _add_capability_histogram(ax, records, feature_key, settings, detail=detail)
    return fig


def qq_figure(records: Sequence[MeasurementRecord], feature_key: str) -> Figure:
    spec = feature_spec(feature_key)
    values = np.asarray(values_for_feature(records, feature_key), dtype=float)
    fig, ax = _figure(f"Q-Q-Diagramm – {spec.label}")
    if values.size >= 2:
        (theoretical, ordered), (slope, intercept, _) = probplot(values, dist="norm")
        ax.scatter(theoretical, ordered, s=26)
        ax.plot(theoretical, slope * np.asarray(theoretical) + intercept, linestyle="--")
    ax.set_xlabel("Theoretische Normalquantile")
    ax.set_ylabel(f"Geordnete Messwerte [{spec.unit}]")
    return fig


def distribution_diagnostics_figure(
    records: Sequence[MeasurementRecord],
    feature_key: str,
    settings: ProjectSettings,
    distribution: DistributionResult | None = None,
) -> Figure:
    """Kombinierte Standarddiagnostik aus Capability-Histogramm, Q-Q- und Bootstrap-Plot."""
    spec = feature_spec(feature_key)
    values = np.asarray(values_for_feature(records, feature_key), dtype=float)
    figure = Figure(figsize=(11.8, 8.0), dpi=100)
    grid = figure.add_gridspec(2, 2, height_ratios=(1.12, 1.0), hspace=0.66, wspace=0.32)
    hist_ax = figure.add_subplot(grid[0, :])
    qq_ax = figure.add_subplot(grid[1, 0])
    boot_ax = figure.add_subplot(grid[1, 1])

    hist_ax.set_title(f"Verteilung, Bewertungsgrenzen und 6s-Breite – {spec.label}", pad=12)
    hist_ax.grid(True, alpha=0.25)
    _add_capability_histogram(
        hist_ax,
        records,
        feature_key,
        settings,
        detail=False,
        distribution=distribution,
    )

    qq_ax.set_title("Normal-Q-Q-Diagramm", pad=10)
    qq_ax.grid(True, alpha=0.25)
    if values.size >= 2:
        (theoretical, ordered), (slope, intercept, _) = probplot(values, dist="norm")
        qq_ax.scatter(theoretical, ordered, s=24)
        qq_ax.plot(theoretical, slope * np.asarray(theoretical) + intercept, linestyle="--")
    qq_ax.set_xlabel("Theoretische Normalquantile")
    qq_ax.set_ylabel(f"Geordnete Messwerte [{spec.unit}]")
    if distribution is not None:
        sw = "–" if distribution.shapiro_p is None else f"{distribution.shapiro_p:.4f}"
        jb = "–" if distribution.jarque_bera_p is None else f"{distribution.jarque_bera_p:.4f}"
        qq_ax.text(0.02, 0.98, f"SW-p = {sw}\nJB-p = {jb}", transform=qq_ax.transAxes, va="top", ha="left", fontsize=8,
                   bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.75})

    boot_ax.set_title("Parametrische Bootstrap-Verteilung von Q", pad=10)
    boot_ax.grid(True, alpha=0.25)
    q_values = np.asarray(distribution.bootstrap_q_values if distribution is not None else (), dtype=float)
    if q_values.size:
        bins = min(max(int(np.sqrt(q_values.size)), 20), 70)
        boot_ax.hist(q_values, bins=bins, alpha=0.62, edgecolor="black")
        if distribution.bootstrap_q is not None:
            boot_ax.axvline(distribution.bootstrap_q, linestyle="--", linewidth=1.6, label="Q beobachtet")
        p_text = "–" if distribution.bootstrap_p is None else f"{distribution.bootstrap_p:.4f}"
        boot_ax.text(0.98, 0.96, f"B = {distribution.bootstrap_repetitions}\np_boot = {p_text}", transform=boot_ax.transAxes,
                     va="top", ha="right", fontsize=8, bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.75})
        boot_ax.legend(fontsize=8)
    else:
        boot_ax.text(
            0.5, 0.5,
            "Für dieses Merkmal liegt keine Bootstrap-Auswertung vor.\n"
            "Starte die Berechnung über die Schaltfläche oberhalb der Diagramme.",
            ha="center", va="center", transform=boot_ax.transAxes, wrap=True,
        )
    boot_ax.set_xlabel("simulierte Prüfgröße Qᵦ")
    boot_ax.set_ylabel("Häufigkeit")
    figure.subplots_adjust(top=0.95, bottom=0.09, left=0.07, right=0.98)
    return figure


def mean_deviation_figure(records: Sequence[MeasurementRecord], settings: ProjectSettings) -> Figure:
    results = [r for r in analyze_records(records, settings) if r.deviation is not None]
    fig, ax = _figure("Mittlere Abweichungen der Merkmale", figsize=(9.4, 5.6))
    if not results:
        return fig
    labels = [r.label for r in results]
    deviations = [r.deviation for r in results]
    errors = [r.stdev for r in results]
    y = np.arange(len(labels))
    ax.barh(y, deviations, xerr=errors, alpha=0.7)
    ax.axvline(0.0, linewidth=1.0)
    ax.axvline(settings.tolerance_half_width_mm, linestyle=":", linewidth=1.0)
    ax.axvline(-settings.tolerance_half_width_mm, linestyle=":", linewidth=1.0)
    ax.set_yticks(y, labels)
    ax.set_xlabel("mittlere Abweichung ± s [mm]")
    fig.subplots_adjust(left=0.34)
    return fig


def capability_figure(records: Sequence[MeasurementRecord], settings: ProjectSettings) -> Figure:
    results = [r for r in analyze_records(records, settings) if r.cm is not None and r.cmk is not None]
    fig, ax = _figure("Cₘ-/Cₘₖ-Vergleich", figsize=(9.4, 5.6))
    if not results:
        return fig
    labels = [r.label for r in results]
    y = np.arange(len(labels))
    height = 0.36
    ax.barh(y - height / 2, [r.cm for r in results], height=height, label="Cₘ")
    ax.barh(y + height / 2, [r.cmk for r in results], height=height, label="Cₘₖ")
    ax.axvline(settings.capability_orientation, linestyle="--", linewidth=1.0, label="Orientierungsgrenze")
    ax.set_yticks(y, labels)
    ax.set_xlabel("Fähigkeitsindex")
    ax.legend()
    fig.subplots_adjust(left=0.34)
    return fig


def bed_heatmap_data(records: Sequence[MeasurementRecord], feature_key: str):
    """Liefert Matrix der Mittelwerte, Abweichungen und Stichprobenumfänge je Rasterposition."""
    spec = feature_spec(feature_key)
    groups: dict[str, list[float]] = defaultdict(list)
    for record in records:
        value = record.values.get(feature_key)
        if value is None:
            continue
        position = normalize_bed_position(record.bed_position)
        if position in BED_POSITION_GRID:
            groups[position].append(float(value))
    means = np.full((3, 3), np.nan)
    display = np.full((3, 3), np.nan)
    counts = np.zeros((3, 3), dtype=int)
    for position, vals in groups.items():
        row, col = BED_POSITION_GRID[position]
        mean = float(np.mean(vals))
        means[row, col] = mean
        display[row, col] = mean - spec.nominal if spec.nominal is not None else mean
        counts[row, col] = len(vals)
    return means, display, counts


def bed_heatmap_figure(records: Sequence[MeasurementRecord], feature_key: str, settings: ProjectSettings | None = None) -> Figure:
    spec = feature_spec(feature_key)
    means, matrix, counts = bed_heatmap_data(records, feature_key)
    fig, ax = _figure(f"Bauraum-Heatmap – {spec.label}", figsize=(7.8, 6.2))
    finite = matrix[np.isfinite(matrix)]
    if finite.size:
        limit = float(np.max(np.abs(finite)))
        if settings is not None and spec.nominal is not None:
            limit = max(limit, float(settings.tolerance_half_width_mm))
        limit = max(limit, 1e-9)
        norm_obj = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)
        image = ax.imshow(np.ma.masked_invalid(matrix), aspect="equal", cmap="coolwarm", norm=norm_obj)
        cbar_label = "mittlere Abweichung [mm]" if spec.nominal is not None else f"Mittelwert [{spec.unit}]"
        fig.colorbar(image, ax=ax, label=cbar_label)
    else:
        image = ax.imshow(np.ma.masked_invalid(matrix), aspect="equal")
    ax.set_xticks([0, 1, 2], ["links", "Mitte", "rechts"])
    ax.set_yticks([0, 1, 2], ["hinten", "Mitte", "vorne"])
    ax.set_xticks(np.arange(-.5, 3, 1), minor=True)
    ax.set_yticks(np.arange(-.5, 3, 1), minor=True)
    ax.grid(which="minor", linewidth=1.0)
    ax.tick_params(which="minor", bottom=False, left=False)
    for row in range(3):
        for col in range(3):
            if np.isfinite(matrix[row, col]):
                deviation_line = f"Δ={matrix[row, col]:.3f}" if spec.nominal is not None else f"x̄={matrix[row, col]:.3f}"
                mean_line = f"x̄={means[row, col]:.3f}" if spec.nominal is not None else ""
                label = "\n".join(part for part in (mean_line, deviation_line, f"n={counts[row, col]}") if part)
                ax.text(col, row, label, ha="center", va="center", fontsize=9)
            else:
                ax.text(col, row, "keine Daten", ha="center", va="center", fontsize=9, color="#666666")
    return fig


def position_profile_figure(records: Sequence[MeasurementRecord], feature_key: str, settings: ProjectSettings) -> Figure:
    spec = feature_spec(feature_key)
    means, matrix, counts = bed_heatmap_data(records, feature_key)
    labels, values, errors = [], [], []
    for position in BED_POSITIONS:
        subset = [float(r.values[feature_key]) for r in records if normalize_bed_position(r.bed_position) == position and feature_key in r.values]
        if subset:
            labels.append(position)
            values.append(float(np.mean(subset)) - spec.nominal if spec.nominal is not None else float(np.mean(subset)))
            errors.append(float(np.std(subset, ddof=1)) if len(subset) >= 2 else 0.0)
    fig, ax = _figure(f"Positionsprofil – {spec.label}", figsize=(9.6, 5.8))
    x = np.arange(len(labels))
    ax.errorbar(x, values, yerr=errors, marker="o", linestyle="-", capsize=3)
    ax.axhline(0.0, linewidth=1.0)
    if spec.nominal is not None:
        ax.axhline(settings.tolerance_half_width_mm, linestyle=":", linewidth=1.0)
        ax.axhline(-settings.tolerance_half_width_mm, linestyle=":", linewidth=1.0)
        ax.set_ylabel("mittlere Abweichung ± s [mm]")
    else:
        ax.set_ylabel(f"Mittelwert ± s [{spec.unit}]")
    ax.set_xticks(x, labels, rotation=35, ha="right")
    fig.subplots_adjust(bottom=0.25)
    return fig


def capability_confidence_figure(records: Sequence[MeasurementRecord], settings: ProjectSettings) -> Figure:
    """Intervallplot der Cₘ- und Cₘₖ-Punktschätzer mit zweiseitigen Konfidenzintervallen."""
    results = [
        item for item in analyze_records(records, settings)
        if item.cmk is not None and item.cmk_ci_lower is not None and item.cmk_ci_upper is not None
    ]
    fig, ax = _figure(
        f"Fähigkeitskennwerte mit {settings.confidence_level * 100:.0f}-%-Konfidenzintervallen",
        figsize=(9.8, 6.0),
    )
    if not results:
        ax.text(0.5, 0.5, "Keine berechenbaren Konfidenzintervalle.", ha="center", va="center", transform=ax.transAxes)
        return fig
    labels = [item.label for item in results]
    y = np.arange(len(results), dtype=float)
    offset = 0.13

    cm_values = np.array([item.cm for item in results], dtype=float)
    cm_low = np.array([item.cm_ci_lower for item in results], dtype=float)
    cm_high = np.array([item.cm_ci_upper for item in results], dtype=float)
    cmk_values = np.array([item.cmk for item in results], dtype=float)
    cmk_low = np.array([item.cmk_ci_lower for item in results], dtype=float)
    cmk_high = np.array([item.cmk_ci_upper for item in results], dtype=float)

    ax.errorbar(
        cm_values, y - offset,
        xerr=np.vstack((cm_values - cm_low, cm_high - cm_values)),
        fmt="o", capsize=3, label="Cₘ (zweiseitiges KI)",
    )
    ax.errorbar(
        cmk_values, y + offset,
        xerr=np.vstack((cmk_values - cmk_low, cmk_high - cmk_values)),
        fmt="s", capsize=3, label="Cₘₖ (zweiseitiges KI)",
    )
    cmk_lcb = np.array([item.cmk_lower_confidence_bound for item in results], dtype=float)
    ax.scatter(cmk_lcb, y + offset, marker="|", s=150, linewidths=1.8, label="einseitige untere Cₘₖ-Grenze")
    ax.axvline(settings.capability_orientation, linestyle="--", linewidth=1.3, label="Orientierungsgrenze")
    ax.set_yticks(y, labels)
    ax.set_xlabel("Fähigkeitskennwert")
    ax.set_ylabel("Merkmal")
    ax.legend(loc="best", fontsize=8)
    fig.subplots_adjust(left=0.34)
    return fig


def build_figure(kind: str, records: Sequence[MeasurementRecord], feature_key: str, settings: ProjectSettings) -> Figure:
    if kind == "Verlauf":
        return chronological_figure(records, feature_key)
    if kind in {"Histogramm", "Fähigkeitshistogramm"}:
        return histogram_figure(records, feature_key, settings, detail=False)
    if kind == "Histogramm (Detail)":
        return histogram_figure(records, feature_key, settings, detail=True)
    if kind == "Q-Q-Diagramm":
        return qq_figure(records, feature_key)
    if kind == "Bauraum-Heatmap":
        return bed_heatmap_figure(records, feature_key, settings)
    if kind == "Positionsprofil":
        return position_profile_figure(records, feature_key, settings)
    if kind == "Mittlere Abweichungen":
        return mean_deviation_figure(records, settings)
    if kind == "Cₘ/Cₘₖ":
        return capability_figure(records, settings)
    if kind == "Konfidenzintervalle Cₘ/Cₘₖ":
        return capability_confidence_figure(records, settings)
    raise ValueError(f"Unbekannte Diagrammart: {kind}")
