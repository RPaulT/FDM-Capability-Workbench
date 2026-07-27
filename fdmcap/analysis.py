"""Auswertungs- und Warnlogik."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence

from .config import (
    FEATURES,
    NORMATIVE_REFERENCE_N,
    ROLE_ADDITIONAL,
    ROLE_BOUNDARY,
    ROLE_INDICATOR,
    ROLE_MAIN,
    SEAM_ALONG_Y,
    SEAM_BETWEEN_AXES,
    TEMPLATES,
    FeatureSpec,
)
from .models import CapabilityResult, DistributionResult, MeasurementRecord, ProjectSettings, values_for_feature
from .statistics import (
    capability_confidence_intervals,
    capability_indices,
    descriptive,
    normality_tests,
    ppm_performance,
    quantized_normal_bootstrap,
)


WARNING_TEXTS = {
    "N_LT_30": "Stichprobenumfang unter 30: praxisnahe Vergleichsbewertung, kein normkonformer Fähigkeitsnachweis.",
    "S_ZERO": "Nur identische Ablesewerte: Die tatsächliche Streuung ist mit dem Messmittel nicht weiter auflösbar.",
    "FEW_LEVELS": "Weniger als drei unterschiedliche Ablesestufen: Die Verteilungsform ist nicht hinreichend beurteilbar.",
    "RESOLUTION_DOMINANT": "Die beobachtete Streuung liegt unter einem Ableseschritt (k_r < 1); Kennwerte zurückhaltend interpretieren.",
    "NON_CAPABILITY_ROLE": "Dieses Merkmal wird gemäß Messstrategie nur deskriptiv ausgewertet.",
    "ADDITIONAL_PROFILE": "Geometriespezifisches Zusatzmerkmal: Kennwerte sind orientierend und nicht auf andere Größen oder Geometrien übertragbar.",
    "BOUNDARY_FEATURE": "Grenzstrukturmerkmal: Fertig- und Messbarkeit stehen vor einer regulären Fähigkeitsbewertung.",
    "MASS_INDICATOR": "Die Masse ist nur ein Plausibilitätsindikator und kein geometrisches Fähigkeitsmerkmal.",
    "GLOBAL_BED": "Globale Bauraumstreuung überlagert Positions-, Batch- und kurzfristige Wiederholanteile.",
    "MIXED_SCOPE": "Die Auswahl enthält unterschiedliche Konfigurationen oder Prüfstufen; Ergebnisse nicht als eine einzige Fähigkeitsaussage interpretieren.",
    "MISSING_CONFIGURATION": "Die Drucker-Prozess-Konfiguration ist nicht benannt; der Geltungsbereich der Fähigkeitsaussage bleibt unvollständig dokumentiert.",
    "MISSING_MATERIAL": "Das Material ist nicht angegeben; unterschiedliche Werkstoffe dürfen nicht gemeinsam bewertet werden.",
    "BASIS_NOT_REFERENCE_POSITION": "Die Basisprüfung enthält eine andere oder mehrere Druckbettpositionen; sie ist auf die festgelegte Referenzposition zu begrenzen.",
    "N_LT_TARGET": "Der arbeitsinterne Zielumfang der gewählten Prüfung wird unterschritten.",
    "SEAM_STRATEGY_MISMATCH": "Die vorhandenen Zylinderfelder passen nicht vollständig zur eingestellten Z-Naht-Strategie; Messrichtung und Nahtlage vor der Interpretation prüfen.",
}


def feature_keys_present(records: Iterable[MeasurementRecord]) -> list[str]:
    keys: set[str] = set()
    for record in records:
        keys.update(key for key, value in record.values.items() if value is not None)
    known = [key for key in FEATURES if key in keys]
    unknown = sorted(keys.difference(FEATURES))
    return known + unknown


def feature_spec(feature_key: str) -> FeatureSpec:
    if feature_key in FEATURES:
        return FEATURES[feature_key]
    return FeatureSpec(
        key=feature_key,
        label=feature_key,
        nominal=None,
        unit="",
        role=ROLE_ADDITIONAL,
        capability=False,
        geometry_class="Benutzerdefiniertes Zusatzmerkmal",
        measurement_note="Für benutzerdefinierte Merkmale ist die fachliche Einordnung zu prüfen.",
    )




def resolution_for_feature(feature_key: str, settings: ProjectSettings) -> float:
    """Liefert den passenden Ableseschritt für die Einheit des Merkmals."""
    spec = feature_spec(feature_key)
    if spec.unit == "g":
        return float(settings.mass_resolution_g)
    return float(settings.resolution_mm)

def scope_warning_codes(records: Sequence[MeasurementRecord], settings: ProjectSettings | None = None) -> tuple[str, ...]:
    configurations = {(record.configuration, record.material) for record in records}
    study_types = {record.study_type for record in records}
    codes: list[str] = []
    if len(configurations) > 1 or len(study_types) > 1:
        codes.append("MIXED_SCOPE")
    if any(not record.configuration.strip() for record in records):
        codes.append("MISSING_CONFIGURATION")
    if any(not record.material.strip() for record in records):
        codes.append("MISSING_MATERIAL")
    positions = {record.bed_position for record in records}
    if study_types == {"Bauraumprüfung"} and len(positions) > 1:
        codes.append("GLOBAL_BED")
    if study_types == {"Basisprüfung"} and positions != {"Mitte"}:
        codes.append("BASIS_NOT_REFERENCE_POSITION")
    if settings is not None:
        keys = feature_keys_present(records)
        if settings.seam_position == SEAM_BETWEEN_AXES and "cylinder_y_seam" in keys:
            codes.append("SEAM_STRATEGY_MISMATCH")
        if settings.seam_position == SEAM_ALONG_Y and "cylinder_y_free" in keys:
            codes.append("SEAM_STRATEGY_MISMATCH")
    return tuple(codes)


def _status_for_capability(
    spec: FeatureSpec,
    cm: float | None,
    cmk: float | None,
    stdev: float,
    orientation: float,
) -> str:
    if not spec.capability:
        if spec.role == ROLE_BOUNDARY:
            return "Grenzstruktur / deskriptiv"
        if spec.role == ROLE_INDICATOR:
            return "Plausibilitätsindikator"
        return "nur deskriptiv"
    if stdev <= 0 or cm is None or cmk is None:
        return "Streuung nicht auflösbar"
    if cmk < 0:
        return "Mittelwert außerhalb des Bewertungsbereichs"
    if cm >= orientation and cmk >= orientation:
        return "Orientierungsgrenze erreicht"
    if cm >= orientation and cmk < orientation:
        return "durch Mittelwertlage begrenzt"
    return "durch Streuung begrenzt"


def _confidence_status(
    spec: FeatureSpec,
    cmk: float | None,
    lower_bound: float | None,
    orientation: float,
    confidence_level: float,
) -> str:
    if not spec.capability:
        return "nicht anwendbar"
    if cmk is None or lower_bound is None:
        return "nicht berechenbar"
    percentage = confidence_level * 100.0
    if cmk < orientation:
        return "Punktschätzer unter Orientierungsgrenze"
    if lower_bound >= orientation:
        return f"einseitige untere {percentage:.0f}-%-Konfidenzgrenze erreicht die Orientierungsgrenze"
    return f"Punktschätzer erreicht; untere {percentage:.0f}-%-Konfidenzgrenze liegt darunter"


def analyze_feature(
    records: Sequence[MeasurementRecord],
    feature_key: str,
    settings: ProjectSettings,
) -> CapabilityResult | None:
    values = values_for_feature(records, feature_key)
    if not values:
        return None
    spec = feature_spec(feature_key)
    stats = descriptive(values)
    nominal = spec.nominal
    lower_limit = None
    upper_limit = None
    deviation = None
    cm = None
    cmk = None
    cml = None
    cmu = None
    limiting_side = None
    mean_ci_lower = None
    mean_ci_upper = None
    stdev_ci_lower = None
    stdev_ci_upper = None
    cm_ci_lower = None
    cm_ci_upper = None
    cm_lower_confidence_bound = None
    cmk_ci_lower = None
    cmk_ci_upper = None
    cmk_lower_confidence_bound = None
    confidence_status = "nicht anwendbar"
    observed_below_count = None
    observed_above_count = None
    observed_ppm_below = None
    observed_ppm_above = None
    observed_ppm_total = None
    expected_ppm_below = None
    expected_ppm_above = None
    expected_ppm_total = None
    observed_ppm_total_ci_lower = None
    observed_ppm_total_ci_upper = None
    observed_ppm_total_upper_bound = None
    if nominal is not None:
        lower_limit = nominal - settings.tolerance_half_width_mm
        upper_limit = nominal + settings.tolerance_half_width_mm
        deviation = stats.mean - nominal
        performance = ppm_performance(
            values,
            lower_limit,
            upper_limit,
            mean=stats.mean,
            stdev=stats.stdev,
            confidence_level=settings.confidence_level,
        )
        observed_below_count = performance.observed_below_count
        observed_above_count = performance.observed_above_count
        observed_ppm_below = performance.observed_ppm_below
        observed_ppm_above = performance.observed_ppm_above
        observed_ppm_total = performance.observed_ppm_total
        expected_ppm_below = performance.expected_ppm_below
        expected_ppm_above = performance.expected_ppm_above
        expected_ppm_total = performance.expected_ppm_total
        observed_ppm_total_ci_lower = performance.observed_total_ci_lower
        observed_ppm_total_ci_upper = performance.observed_total_ci_upper
        observed_ppm_total_upper_bound = performance.observed_total_upper_one_sided
        if spec.capability:
            cm, cmk = capability_indices(stats.mean, stats.stdev, lower_limit, upper_limit)
            intervals = capability_confidence_intervals(
                stats.mean, stats.stdev, stats.n, lower_limit, upper_limit,
                confidence_level=settings.confidence_level,
            )
            cml = intervals.cml
            cmu = intervals.cmu
            limiting_side = intervals.limiting_side
            mean_ci_lower = intervals.mean_lower
            mean_ci_upper = intervals.mean_upper
            stdev_ci_lower = intervals.stdev_lower
            stdev_ci_upper = intervals.stdev_upper
            cm_ci_lower = intervals.cm_lower
            cm_ci_upper = intervals.cm_upper
            cm_lower_confidence_bound = intervals.cm_lower_one_sided
            cmk_ci_lower = intervals.cmk_lower
            cmk_ci_upper = intervals.cmk_upper
            cmk_lower_confidence_bound = intervals.cmk_lower_one_sided
            confidence_status = _confidence_status(
                spec, cmk, cmk_lower_confidence_bound, settings.capability_orientation, settings.confidence_level
            )

    resolution = resolution_for_feature(feature_key, settings)
    k_r = stats.stdev / resolution if resolution > 0 else None
    warnings: list[str] = list(scope_warning_codes(records, settings))
    if stats.n < NORMATIVE_REFERENCE_N:
        warnings.append("N_LT_30")
    template_keys = {record.template_key for record in records}
    target_n = None
    if len(template_keys) == 1:
        template = TEMPLATES.get(next(iter(template_keys)))
        target_n = template.target_n if template else None
    if target_n is not None and stats.n < target_n:
        warnings.append("N_LT_TARGET")
    if stats.stdev <= 0:
        warnings.append("S_ZERO")
    if stats.unique_levels < 3:
        warnings.append("FEW_LEVELS")
    if k_r is not None and k_r < 1.0 and stats.stdev > 0:
        warnings.append("RESOLUTION_DOMINANT")
    if not spec.capability:
        warnings.append("NON_CAPABILITY_ROLE")
    if spec.role == ROLE_ADDITIONAL:
        warnings.append("ADDITIONAL_PROFILE")
    elif spec.role == ROLE_BOUNDARY:
        warnings.append("BOUNDARY_FEATURE")
    elif spec.role == ROLE_INDICATOR:
        warnings.append("MASS_INDICATOR")

    # Reihenfolge erhalten und Dopplungen vermeiden.
    warning_codes = tuple(dict.fromkeys(warnings))
    warning_parts = [WARNING_TEXTS[code] for code in warning_codes if code in WARNING_TEXTS]
    if "N_LT_TARGET" in warning_codes and target_n is not None:
        warning_parts.append(f"Aktuell n = {stats.n}, Zielumfang n = {target_n}.")
    warning_text = " ".join(warning_parts)
    return CapabilityResult(
        feature_key=feature_key,
        label=spec.label,
        role=spec.role,
        geometry_class=spec.geometry_class,
        unit=spec.unit,
        nominal=nominal,
        lower_limit=lower_limit,
        upper_limit=upper_limit,
        n=stats.n,
        mean=stats.mean,
        deviation=deviation,
        stdev=stats.stdev,
        span=stats.span,
        minimum=stats.minimum,
        maximum=stats.maximum,
        unique_levels=stats.unique_levels,
        k_r=k_r,
        cm=cm,
        cmk=cmk,
        cml=cml,
        cmu=cmu,
        limiting_side=limiting_side,
        mean_ci_lower=mean_ci_lower,
        mean_ci_upper=mean_ci_upper,
        stdev_ci_lower=stdev_ci_lower,
        stdev_ci_upper=stdev_ci_upper,
        cm_ci_lower=cm_ci_lower,
        cm_ci_upper=cm_ci_upper,
        cm_lower_confidence_bound=cm_lower_confidence_bound,
        cmk_ci_lower=cmk_ci_lower,
        cmk_ci_upper=cmk_ci_upper,
        cmk_lower_confidence_bound=cmk_lower_confidence_bound,
        confidence_level=settings.confidence_level,
        confidence_status=confidence_status,
        observed_below_count=observed_below_count,
        observed_above_count=observed_above_count,
        observed_ppm_below=observed_ppm_below,
        observed_ppm_above=observed_ppm_above,
        observed_ppm_total=observed_ppm_total,
        expected_ppm_below=expected_ppm_below,
        expected_ppm_above=expected_ppm_above,
        expected_ppm_total=expected_ppm_total,
        observed_ppm_total_ci_lower=observed_ppm_total_ci_lower,
        observed_ppm_total_ci_upper=observed_ppm_total_ci_upper,
        observed_ppm_total_upper_bound=observed_ppm_total_upper_bound,
        status=_status_for_capability(spec, cm, cmk, stats.stdev, settings.capability_orientation),
        warning_codes=warning_codes,
        warning_text=warning_text,
    )


def analyze_records(records: Sequence[MeasurementRecord], settings: ProjectSettings) -> list[CapabilityResult]:
    results: list[CapabilityResult] = []
    for key in feature_keys_present(records):
        result = analyze_feature(records, key, settings)
        if result is not None:
            results.append(result)
    return results


def distribution_analysis(
    records: Sequence[MeasurementRecord],
    feature_key: str,
    settings: ProjectSettings,
    *,
    run_bootstrap: bool = False,
    repetitions: int | None = None,
    progress=None,
) -> DistributionResult:
    values = values_for_feature(records, feature_key)
    if not values:
        raise ValueError("Für das ausgewählte Merkmal liegen keine Werte vor.")
    stats = descriptive(values)
    resolution = resolution_for_feature(feature_key, settings)
    k_r = stats.stdev / resolution if resolution > 0 else None
    sw_stat, sw_p, jb_stat, jb_p = normality_tests(values)

    if stats.stdev <= 0:
        return DistributionResult(
            feature_key=feature_key,
            n=stats.n,
            unique_levels=stats.unique_levels,
            k_r=k_r,
            shapiro_statistic=sw_stat,
            shapiro_p=sw_p,
            jarque_bera_statistic=jb_stat,
            jarque_bera_p=jb_p,
            bootstrap_q=None,
            bootstrap_p=None,
            fitted_mu=None,
            fitted_sigma=None,
            bootstrap_repetitions=0,
            failed_fits=0,
            bootstrap_q_values=(),
            status="nicht beurteilbar",
            note="s = 0; die Streuung ist mit dem verwendeten Messmittel nicht weiter auflösbar.",
        )
    if stats.unique_levels < 3:
        return DistributionResult(
            feature_key=feature_key,
            n=stats.n,
            unique_levels=stats.unique_levels,
            k_r=k_r,
            shapiro_statistic=sw_stat,
            shapiro_p=sw_p,
            jarque_bera_statistic=jb_stat,
            jarque_bera_p=jb_p,
            bootstrap_q=None,
            bootstrap_p=None,
            fitted_mu=None,
            fitted_sigma=None,
            bootstrap_repetitions=0,
            failed_fits=0,
            bootstrap_q_values=(),
            status="nicht hinreichend beurteilbar",
            note="Weniger als drei unterschiedliche Ablesestufen; kein Bootstrap-p-Wert.",
        )

    bootstrap_p = None
    bootstrap_q = None
    fitted_mu = None
    fitted_sigma = None
    failed = 0
    bootstrap_q_values: tuple[float, ...] = ()
    used_repetitions = 0
    if run_bootstrap:
        used_repetitions = int(repetitions or settings.bootstrap_repetitions)
        bootstrap_p, bootstrap_q, fit, failed, bootstrap_q_values = quantized_normal_bootstrap(
            values,
            resolution,
            repetitions=used_repetitions,
            seed=settings.bootstrap_seed,
            progress=progress,
        )
        fitted_mu = fit.mu
        fitted_sigma = fit.sigma

    if bootstrap_p is None:
        status = "klassische Zusatzdiagnostik berechnet"
        note = "Keine Bootstrap-Auswertung vorhanden; Shapiro-Wilk und Jarque-Bera nicht isoliert interpretieren."
    elif bootstrap_p < settings.alpha:
        status = "im quantisierten Normalmodell auffällig"
        note = "Die Stufenverteilung weicht auch unter Berücksichtigung des Ableseschritts auffällig ab."
    else:
        status = "im quantisierten Normalmodell nicht auffällig"
        note = "Kein signifikanter Hinweis gegen das angepasste quantisierte Normalmodell; keine Bestätigung der Normalverteilung."
    if k_r is not None and k_r < 1:
        note += " Die Messreihe ist stark auflösungsdominiert (k_r < 1)."

    return DistributionResult(
        feature_key=feature_key,
        n=stats.n,
        unique_levels=stats.unique_levels,
        k_r=k_r,
        shapiro_statistic=sw_stat,
        shapiro_p=sw_p,
        jarque_bera_statistic=jb_stat,
        jarque_bera_p=jb_p,
        bootstrap_q=bootstrap_q,
        bootstrap_p=bootstrap_p,
        fitted_mu=fitted_mu,
        fitted_sigma=fitted_sigma,
        bootstrap_repetitions=used_repetitions,
        failed_fits=failed,
        bootstrap_q_values=bootstrap_q_values,
        status=status,
        note=note,
    )


def group_records(
    records: Iterable[MeasurementRecord],
    attribute: str,
) -> dict[str, list[MeasurementRecord]]:
    grouped: dict[str, list[MeasurementRecord]] = defaultdict(list)
    for record in records:
        grouped[str(getattr(record, attribute, ""))].append(record)
    return dict(grouped)


def _fmt_de(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}".replace(".", ",")


def scope_summary_text(
    records: Sequence[MeasurementRecord],
    settings: ProjectSettings,
    *,
    results: Sequence[CapabilityResult] | None = None,
    distributions: Sequence[DistributionResult] = (),
) -> str:
    """Erzeugt eine verständliche Gesamtzusammenfassung ohne pauschalen Drucker-Gesamtwert."""
    if not records:
        return "Für den gewählten Prüfumfang liegen keine Messdaten vor."
    results = list(results or analyze_records(records, settings))
    regular = [item for item in results if feature_spec(item.feature_key).capability]
    defined = [item for item in regular if item.cmk is not None]
    reached = [item for item in defined if item.cm is not None and item.cm >= settings.capability_orientation and item.cmk >= settings.capability_orientation]
    limited = [item for item in defined if item not in reached]
    unresolved = [item for item in regular if item.cmk is None]

    parts = [
        f"Der gewählte Prüfumfang umfasst {len(records)} Untersuchungsobjektzeilen und {len(results)} ausgewertete Merkmale."
    ]
    if defined:
        worst = min(defined, key=lambda item: item.cmk if item.cmk is not None else float("inf"))
        parts.append(
            f"Von {len(defined)} regulär berechenbaren Fähigkeitsmerkmalen erreichen {len(reached)} die "
            f"arbeitsinterne Orientierungsgrenze von {settings.capability_orientation:.2f}; {len(limited)} liegen darunter."
        )
        parts.append(
            f"Begrenzendes Merkmal ist {worst.label} mit Cₘₖ = {_fmt_de(worst.cmk, 2)} "
            f"(Mittelwert {_fmt_de(worst.mean)} {worst.unit}, s = {_fmt_de(worst.stdev)} {worst.unit})."
        )
    if unresolved:
        parts.append(
            f"Bei {len(unresolved)} regulären Merkmal(en) ist Cₘ/Cₘₖ nicht definiert, weil die Streuung mit dem Messmittel nicht ausreichend aufgelöst wurde."
        )
    study_types = {record.study_type for record in records}
    positions = {record.bed_position for record in records}
    if study_types == {"Bauraumprüfung"} and len(positions) > 1:
        parts.append(
            "Die globale Bauraumauswertung enthält zusätzlich Positions- und Batcheffekte; die positionsbezogene Vergleichsansicht ist für die Ursachenlokalisierung entscheidend."
        )
    if any(result.role == ROLE_ADDITIONAL for result in results):
        parts.append(
            "Zusatzmerkmale beschreiben geometriespezifische Profile und dürfen nicht ungeprüft auf andere Größen oder Konturformen übertragen werden."
        )
    completed_distributions = [item for item in distributions if item.bootstrap_p is not None]
    if completed_distributions:
        conspicuous = [item for item in completed_distributions if item.bootstrap_p is not None and item.bootstrap_p < settings.alpha]
        parts.append(
            f"Der quantisierte Bootstrap wurde für {len(completed_distributions)} Merkmal(e) berechnet; "
            f"{len(conspicuous)} davon sind bei α = {settings.alpha:.2f} auffällig."
        )
    parts.append(
        "Die Aussage bleibt merkmal-, geometrie-, positions-, material- und konfigurationsbezogen; ein einzelner Gesamtwert für den Drucker wird bewusst nicht gebildet."
    )
    return " ".join(parts)


def prioritized_findings(
    records: Sequence[MeasurementRecord],
    settings: ProjectSettings,
    *,
    results: Sequence[CapabilityResult] | None = None,
    distributions: Sequence[DistributionResult] = (),
    limit: int = 10,
) -> list[tuple[str, str, str, str]]:
    """Liefert priorisierte Befunde als (Stufe, Bereich, Befund, nächster Schritt)."""
    results = list(results or analyze_records(records, settings))
    findings: list[tuple[int, str, str, str, str]] = []

    for result in results:
        spec = feature_spec(result.feature_key)
        if spec.capability and result.cmk is not None:
            if result.cmk < 0:
                findings.append((0, "kritisch", result.label,
                    f"Der Mittelwert liegt außerhalb des Bewertungsbereichs; Cₘₖ = {_fmt_de(result.cmk, 2)}.",
                    "Messstrategie und Datensatz prüfen, anschließend Maßlage der dokumentierten Konfiguration mit einer neuen Basisreihe verifizieren."))
            elif result.cmk < 1.0:
                mechanism = "Mittelwertlage" if result.cm is not None and result.cm >= settings.capability_orientation else "Streuung und/oder Mittelwertlage"
                findings.append((1, "kritisch", result.label,
                    f"Cₘₖ = {_fmt_de(result.cmk, 2)}; die Fähigkeit wird durch {mechanism} deutlich begrenzt.",
                    "Zuerst Messstrategie und Randbedingungen prüfen; danach gezielt Maßlage, thermischen Zustand, Materialförderung und mechanische Wiederholbarkeit untersuchen."))
            elif result.cmk < settings.capability_orientation:
                if result.cm is not None and result.cm >= settings.capability_orientation:
                    finding = f"Cₘ = {_fmt_de(result.cm, 2)} wäre ausreichend, Cₘₖ = {_fmt_de(result.cmk, 2)} bleibt wegen der Mittelwertlage darunter."
                    step = "Systematische Maßabweichung über eine Wiederholreihe bestätigen; erst danach geometriespezifische Slicer-Kompensation oder Parametrierung prüfen."
                else:
                    finding = f"Cₘ = {_fmt_de(result.cm, 2)}, Cₘₖ = {_fmt_de(result.cmk, 2)}; die beobachtete Streuung reicht für die Orientierungsgrenze nicht aus."
                    step = "Zeit-/Batchverlauf und Randbedingungen prüfen; Wiederholstreuung nicht durch Zusammenfassen unterschiedlicher Zustände künstlich erhöhen."
                findings.append((2, "auffällig", result.label, finding, step))
        if result.stdev <= 0:
            findings.append((2, "Hinweis", f"Messmittel – {result.label}",
                "Es wurden ausschließlich identische Ablesewerte beobachtet; Cₘ/Cₘₖ sind nicht definiert.",
                "Mit höher auflösendem oder geometriespezifischem Messmittel nachprüfen oder das Ergebnis ausdrücklich als nicht weiter auflösbar dokumentieren."))
        elif result.k_r is not None and result.k_r < 1.0:
            findings.append((3, "Hinweis", f"Messmittel – {result.label}",
                f"kᵣ = {_fmt_de(result.k_r, 2)}; die Streuung ist kleiner als ein Ableseschritt.",
                "Sehr hohe Fähigkeitswerte und Normalitätstests nur zurückhaltend interpretieren; Anzahl der Ablesestufen mit ausweisen."))
        if "N_LT_TARGET" in result.warning_codes:
            findings.append((4, "Hinweis", f"Versuchsumfang – {result.label}",
                f"Der arbeitsinterne Zielumfang wird unterschritten (aktuell n = {result.n}).",
                "Weitere unabhängig gefertigte Untersuchungsobjekt unter unverändertem Untersuchungszustand ergänzen."))

    if "SEAM_STRATEGY_MISMATCH" in scope_warning_codes(records, settings):
        findings.append((1, "kritisch", "Z-Naht und Messstrategie",
            "Die vorhandenen Zylinderfelder passen nicht vollständig zur eingestellten Nahtstrategie.",
            "Nahtlage im Slicer und tatsächliche Messrichtungen dokumentieren; die Projekteinstellung korrigieren und nahtbeeinflusste Werte nur deskriptiv behandeln."))

    distribution_map = {item.feature_key: item for item in distributions}
    for key, item in distribution_map.items():
        if item.bootstrap_p is not None and item.bootstrap_p < settings.alpha:
            findings.append((2, "auffällig", f"Verteilung – {feature_spec(key).label}",
                f"p_boot = {_fmt_de(item.bootstrap_p, 4)}; die quantisierte Stufenverteilung ist auffällig.",
                "Verlauf, Histogramm und Q-Q-Diagramm gemeinsam prüfen; keine modellbasierte ppm-Prognose als exakte Fehlerwahrscheinlichkeit verwenden."))
        elif item.failed_fits:
            findings.append((3, "Hinweis", f"Bootstrap – {feature_spec(key).label}",
                f"Bei {item.failed_fits} Bootstrap-Stichproben schlug die Parameterschätzung fehl.",
                "Konvergenz und Zahl unterschiedlicher Ablesestufen prüfen; Ergebnis nur als ergänzende Plausibilitätsgröße verwenden."))

    study_types = {record.study_type for record in records}
    positions = {record.bed_position for record in records}
    if study_types == {"Bauraumprüfung"} and len(positions) > 1:
        findings.append((2, "auffällig", "Bauraum – globale Auswertung",
            "Globale Streuung überlagert Positions-, Batch- und kurzfristige Wiederholanteile.",
            "Im Gruppenvergleich das begrenzende Merkmal positions- und anschließend batchbezogen untersuchen."))

    findings.sort(key=lambda item: (item[0], item[2]))
    # Gleiche Aussagen pro Merkmal/Bereich nur einmal ausgeben.
    unique: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for _priority, level, area, finding, step in findings:
        signature = (level, area, finding)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append((level, area, finding, step))
        if len(unique) >= limit:
            break
    if not unique:
        unique.append((
            "unauffällig",
            "Gewählter Prüfumfang",
            "Es wurde kein vorrangiger kritischer Befund aus den verfügbaren Kennwerten abgeleitet.",
            "Verlaufsgrafiken, Messstrategie und dokumentierte Randbedingungen dennoch prüfen; ein positives Ergebnis ist kein normkonformer Freigabenachweis.",
        ))
    return unique


def feature_interpretation_text(
    result: CapabilityResult,
    settings: ProjectSettings,
    distribution: DistributionResult | None = None,
) -> str:
    """Ausführliche, fachlich vorsichtige Interpretation eines ausgewählten Merkmals."""
    spec = feature_spec(result.feature_key)
    lines = [f"MERKMAL: {result.label}", f"Geometrieklasse: {result.geometry_class}", f"Rolle: {result.role}", ""]
    if result.nominal is not None:
        lines.extend([
            "LAGE UND STREUUNG",
            f"Mittelwert: {_fmt_de(result.mean)} {result.unit} bei Nennmaß {_fmt_de(result.nominal)} {result.unit}",
            f"Mittlere Abweichung: {_fmt_de(result.deviation)} {result.unit}",
            f"Stichprobenstandardabweichung: {_fmt_de(result.stdev)} {result.unit}",
            f"Spannweite: {_fmt_de(result.span)} {result.unit} (Min {_fmt_de(result.minimum)}, Max {_fmt_de(result.maximum)})",
            f"Bewertungsgrenzen: {_fmt_de(result.lower_limit)} bis {_fmt_de(result.upper_limit)} {result.unit}",
            "",
        ])
    else:
        lines.extend([
            "DESKRIPTIVE KENNWERTE",
            f"Mittelwert: {_fmt_de(result.mean)} {result.unit}",
            f"Stichprobenstandardabweichung: {_fmt_de(result.stdev)} {result.unit}",
            f"Spannweite: {_fmt_de(result.span)} {result.unit}",
            "",
        ])

    lines.append("FÄHIGKEITSEINORDNUNG")
    if not spec.capability:
        lines.append("Für dieses Merkmal wird gemäß Messstrategie keine reguläre Cₘ-/Cₘₖ-Bewertung verwendet.")
    elif result.cmk is None:
        lines.append("Cₘ und Cₘₖ sind nicht definiert, weil s = 0 oder die Streuung nicht berechenbar ist.")
    else:
        lines.append(f"Cₘ = {_fmt_de(result.cm, 2)}, Cₘₖ = {_fmt_de(result.cmk, 2)}; Einordnung: {result.status}.")
        lines.append(
            f"Seitenspezifisch: Cₘ,USG = {_fmt_de(result.cml, 2)}, Cₘ,OSG = {_fmt_de(result.cmu, 2)}; "
            f"limitierend ist {result.limiting_side or '–'}."
        )
        lines.append(
            f"Zweiseitiges {settings.confidence_level * 100:.0f}-%-KI: Cₘ "
            f"[{_fmt_de(result.cm_ci_lower, 2)}; {_fmt_de(result.cm_ci_upper, 2)}], Cₘₖ "
            f"[{_fmt_de(result.cmk_ci_lower, 2)}; {_fmt_de(result.cmk_ci_upper, 2)}]."
        )
        lines.append(
            f"Einseitige untere {settings.confidence_level * 100:.0f}-%-Konfidenzgrenze: "
            f"Cₘ = {_fmt_de(result.cm_lower_confidence_bound, 2)}, "
            f"Cₘₖ = {_fmt_de(result.cmk_lower_confidence_bound, 2)}. {result.confidence_status}."
        )
        lines.append(
            f"Unsicherheit von Lage und Streuung: x̄-KI [{_fmt_de(result.mean_ci_lower)}; {_fmt_de(result.mean_ci_upper)}] {result.unit}, "
            f"s-KI [{_fmt_de(result.stdev_ci_lower)}; {_fmt_de(result.stdev_ci_upper)}] {result.unit}."
        )
        if result.cm is not None and result.cm >= settings.capability_orientation and result.cmk < settings.capability_orientation:
            lines.append("Die potenzielle Streuungsfähigkeit wäre ausreichend; die Mittelwertlage ist der primäre begrenzende Faktor.")
        elif result.cm is not None and result.cm < settings.capability_orientation:
            lines.append("Bereits die beobachtete Streuung ist im Verhältnis zur Bewertungsbreite zu groß; eine reine Lagekorrektur würde die Orientierungsgrenze nicht sicher erreichen.")
        elif result.cmk >= settings.capability_orientation:
            lines.append("Die arbeitsinterne Orientierungsgrenze wird erreicht. Dies gilt ausschließlich für den gewählten Untersuchungsumfang.")
    lines.append("")

    if result.lower_limit is not None and result.upper_limit is not None:
        lines.extend([
            "GRENZÜBERSCHREITUNGSANTEILE (ppm)",
            f"Beobachtet: < USG/UGW {_fmt_de(result.observed_ppm_below, 1)} ppm, > OSG/OGW {_fmt_de(result.observed_ppm_above, 1)} ppm, gesamt {_fmt_de(result.observed_ppm_total, 1)} ppm.",
            f"Exaktes {settings.confidence_level * 100:.0f}-%-KI des beobachteten Gesamtanteils: "
            f"[{_fmt_de(result.observed_ppm_total_ci_lower, 1)}; {_fmt_de(result.observed_ppm_total_ci_upper, 1)}] ppm; "
            f"einseitige obere {settings.confidence_level * 100:.0f}-%-Grenze: {_fmt_de(result.observed_ppm_total_upper_bound, 1)} ppm.",
            f"Normalmodell (x̄, s): < USG/UGW {_fmt_de(result.expected_ppm_below, 2)} ppm, > OSG/OGW {_fmt_de(result.expected_ppm_above, 2)} ppm, gesamt {_fmt_de(result.expected_ppm_total, 2)} ppm.",
            "Die beobachteten ppm sind lediglich der Stichprobenanteil auf eine Million skaliert. Das Clopper-Pearson-Intervall zeigt die Unsicherheit dieses Anteils. Die Modell-ppm setzen eine statistisch stabile und näherungsweise normalverteilte Merkmalsgröße voraus und sind weder eine beobachtete Ausschussquote noch eine exakte Zukunftsprognose.",
            "",
        ])

    lines.extend([
        "MESSMITTEL UND DISKRETISIERUNG",
        f"Unterschiedliche Ablesestufen: {result.unique_levels}; kᵣ = {_fmt_de(result.k_r, 2)} bei r = {_fmt_de(resolution_for_feature(result.feature_key, settings))} {result.unit}.",
    ])
    if result.stdev <= 0:
        lines.append("Die Streuung ist mit dem verwendeten Messmittel nicht weiter auflösbar; identische Ablesewerte sind kein Nachweis einer streuungsfreien Fertigung.")
    elif result.k_r is not None and result.k_r < 1:
        lines.append("Die Streuung liegt unter einem Ableseschritt. Sehr hohe Kennwerte und Formtests sind daher besonders vorsichtig zu interpretieren.")
    elif result.k_r is not None and result.k_r < 2:
        lines.append("Die Streuung wird nur durch wenige Ableseschritte abgebildet; die Diskretisierung bleibt relevant.")
    else:
        lines.append("Die beobachtete Streuung umfasst mehrere Ableseschritte; dennoch bleibt der Messanteil Bestandteil der beobachteten Variation.")
    lines.append("")

    lines.append("VERTEILUNGSDIAGNOSTIK")
    if distribution is None:
        lines.append("Für dieses Merkmal wurde in der aktuellen Sitzung noch kein quantisierter Bootstrap berechnet.")
    else:
        lines.append(
            f"Shapiro-Wilk p = {_fmt_de(distribution.shapiro_p, 4)}, Jarque-Bera p = {_fmt_de(distribution.jarque_bera_p, 4)}, "
            f"p_boot = {_fmt_de(distribution.bootstrap_p, 4)}."
        )
        lines.append(distribution.note)
    lines.append("")

    lines.extend(["MESSSTRATEGIE", spec.measurement_note or "Keine spezifische Messnotiz hinterlegt.", ""])
    lines.append("EMPFOHLENER NÄCHSTER SCHRITT")
    if result.role == ROLE_INDICATOR:
        lines.append("Masse nur gemeinsam mit Filamentzustand, Materialförderung und Konfigurationsänderungen als Plausibilitätsindikator betrachten.")
    elif result.role == ROLE_BOUNDARY:
        lines.append("Werkzeugpfad im Slicer kontrollieren und die tatsächliche Erzeugbarkeit der Grenzstruktur vor jeder quantitativen Bewertung verifizieren.")
    elif not spec.capability:
        lines.append("Das Merkmal deskriptiv mit vergleichbaren Reihen gegenüberstellen; keine reguläre Fähigkeitsfreigabe daraus ableiten.")
    elif result.cmk is None:
        lines.append("Höher auflösendes Messverfahren oder zusätzliche Messsystemprüfung erwägen; den Datensatz nicht als unendlich fähig interpretieren.")
    elif result.cmk < settings.capability_orientation:
        if result.cm is not None and result.cm >= settings.capability_orientation:
            lines.append("Systematische Maßlage durch eine unabhängige Wiederholreihe bestätigen und erst danach geometriespezifische Kompensation prüfen.")
        else:
            lines.append("Zeitverlauf, Batch-/Positionseinflüsse und standardisierte Randbedingungen prüfen; anschließend unter unverändertem Zustand wiederholen.")
    else:
        lines.append("Ergebnis durch eine dokumentierte Wiederholung beziehungsweise Bauraum- oder anwendungsbezogene Zusatzprüfung bestätigen, sofern die spätere Anwendung dies erfordert.")
    if result.warning_text:
        lines.extend(["", "ZUSÄTZLICHE WARNUNGEN", result.warning_text])
    return "\n".join(lines)


def group_comparison_rows(
    records: Sequence[MeasurementRecord],
    feature_key: str,
    settings: ProjectSettings,
    attribute: str,
) -> list[tuple[str, CapabilityResult]]:
    rows: list[tuple[str, CapabilityResult]] = []
    for label, group in sorted(group_records(records, attribute).items(), key=lambda item: item[0]):
        result = analyze_feature(group, feature_key, settings)
        if result is not None:
            rows.append((label or "nicht angegeben", result))
    return rows
