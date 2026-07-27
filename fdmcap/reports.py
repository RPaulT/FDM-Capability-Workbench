"""Berichtsausgabe."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Iterable, Sequence

from .analysis import WARNING_TEXTS, analyze_feature, analyze_records, feature_keys_present, feature_spec, prioritized_findings, scope_summary_text
from .config import BED_POSITIONS, NORMATIVE_REFERENCE_N, TEMPLATES
from .models import CapabilityResult, DistributionResult, MeasurementRecord, ProjectSettings
from .spatial import analyze_spatial_feature



@dataclass(frozen=True)
class ReportOptions:
    include_scope: bool = True
    include_summary: bool = True
    include_findings: bool = True
    include_core: bool = True
    include_confidence: bool = True
    include_ppm: bool = True
    include_warnings: bool = True
    include_distributions: bool = True
    include_spatial: bool = True
    include_batch_comparison: bool = True
    include_method: bool = True
    include_raw_data: bool = False


def _options(value=None) -> ReportOptions:
    if value is None:
        return ReportOptions()
    return ReportOptions(**{field: bool(getattr(value, field, getattr(ReportOptions(), field))) for field in ReportOptions.__dataclass_fields__})

def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}".replace(".", ",")


def _fmt_p(value: float | None) -> str:
    if value is None:
        return "–"
    if value < 0.001:
        return "< 0,001"
    return _fmt(value, 3)


def _fmt_ppm(value: float | None) -> str:
    if value is None:
        return "–"
    if 0 < value < 0.01:
        return "< 0,01"
    if value >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    if value >= 10:
        return _fmt(value, 1)
    return _fmt(value, 2)


def scope_rows(records: Sequence[MeasurementRecord], settings: ProjectSettings) -> list[tuple[str, str]]:
    if not records:
        return []
    configurations = sorted({r.configuration or "nicht angegeben" for r in records})
    materials = sorted({r.material or "nicht angegeben" for r in records})
    study_types = sorted({r.study_type for r in records})
    templates = sorted({TEMPLATES.get(r.template_key, None).label if r.template_key in TEMPLATES else r.template_key for r in records})
    batches = sorted({r.batch or "–" for r in records}, key=lambda x: (not str(x).isdigit(), int(x) if str(x).isdigit() else str(x)))
    present_positions = {r.bed_position or "–" for r in records}
    positions = [position for position in BED_POSITIONS if position in present_positions]
    positions.extend(sorted(present_positions.difference(positions)))
    return [
        ("Projekt", settings.project_name),
        ("Prüfumfang", ", ".join(study_types)),
        ("Untersuchungsobjekt", ", ".join(templates)),
        ("Konfiguration", ", ".join(configurations)),
        ("Material", ", ".join(materials)),
        ("Messzeilen", str(len(records))),
        ("Batches", ", ".join(batches)),
        ("Druckbettpositionen", ", ".join(positions)),
        ("Bewertungsbereich", f"Nennmaß ± {_fmt(settings.tolerance_half_width_mm, 2)} mm"),
        ("Ableseschritt Maßmessung r", f"{_fmt(settings.resolution_mm, 3)} mm"),
        ("Ableseschritt Waage", f"{_fmt(settings.mass_resolution_g, 3)} g"),
        ("Orientierungsgrenze", f"Cₘ/Cₘₖ = {_fmt(settings.capability_orientation, 2)}"),
        ("Konfidenzniveau", f"{settings.confidence_level * 100:.0f} %"),
        ("Z-Naht-Strategie", settings.seam_position),
    ]


def compact_result_rows(results: Sequence[CapabilityResult]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in results:
        rows.append([
            item.label,
            item.role,
            str(item.n),
            _fmt(item.mean),
            _fmt(item.deviation),
            _fmt(item.stdev),
            _fmt(item.span),
            _fmt(item.cm, 2),
            _fmt(item.cmk, 2),
            _fmt_ppm(item.observed_ppm_total),
            _fmt_ppm(item.expected_ppm_total),
            str(item.unique_levels),
            _fmt(item.k_r, 2),
            item.status,
        ])
    return rows



def confidence_rows(results: Sequence[CapabilityResult]) -> list[list[str]]:
    """Tabellenzeilen für Lage-, Streuungs- und Fähigkeitsintervalle."""
    rows: list[list[str]] = []
    for item in results:
        if item.cmk is None or item.cmk_ci_lower is None:
            continue
        rows.append([
            item.label,
            str(item.n),
            f"{_fmt(item.mean_ci_lower)} … {_fmt(item.mean_ci_upper)}",
            f"{_fmt(item.stdev_ci_lower)} … {_fmt(item.stdev_ci_upper)}",
            _fmt(item.cml, 2),
            _fmt(item.cmu, 2),
            item.limiting_side or "–",
            _fmt(item.cm, 2),
            f"{_fmt(item.cm_ci_lower, 2)} … {_fmt(item.cm_ci_upper, 2)}",
            _fmt(item.cm_lower_confidence_bound, 2),
            _fmt(item.cmk, 2),
            f"{_fmt(item.cmk_ci_lower, 2)} … {_fmt(item.cmk_ci_upper, 2)}",
            _fmt(item.cmk_lower_confidence_bound, 2),
            item.confidence_status,
        ])
    return rows


def ppm_rows(results: Sequence[CapabilityResult]) -> list[list[str]]:
    """Beobachtete Anteile inklusive exaktem Binomialintervall sowie Modell-ppm."""
    rows: list[list[str]] = []
    for item in results:
        if item.lower_limit is None or item.upper_limit is None:
            continue
        rows.append([
            item.label,
            _fmt(item.lower_limit),
            _fmt(item.upper_limit),
            "–" if item.observed_below_count is None else str(item.observed_below_count),
            "–" if item.observed_above_count is None else str(item.observed_above_count),
            _fmt_ppm(item.observed_ppm_below),
            _fmt_ppm(item.observed_ppm_above),
            _fmt_ppm(item.observed_ppm_total),
            f"{_fmt_ppm(item.observed_ppm_total_ci_lower)} … {_fmt_ppm(item.observed_ppm_total_ci_upper)}",
            _fmt_ppm(item.observed_ppm_total_upper_bound),
            _fmt_ppm(item.expected_ppm_below),
            _fmt_ppm(item.expected_ppm_above),
            _fmt_ppm(item.expected_ppm_total),
            item.status,
        ])
    return rows


def spatial_overview_rows(records: Sequence[MeasurementRecord], settings: ProjectSettings) -> list[list[str]]:
    if {r.study_type for r in records} != {"Bauraumprüfung"}:
        return []
    rows: list[list[str]] = []
    for key in feature_keys_present(records):
        spec = feature_spec(key)
        if spec.unit != "mm":
            continue
        item = analyze_spatial_feature(records, key, settings)
        global_result = item.global_result
        rows.append([
            spec.label,
            str(global_result.n) if global_result else "–",
            _fmt(global_result.mean if global_result else None),
            _fmt(global_result.stdev if global_result else None),
            _fmt(global_result.cmk if global_result else None, 2),
            _fmt(global_result.cmk_lower_confidence_bound if global_result else None, 2),
            _fmt(item.position_mean_span),
            item.minimum_position or "–",
            item.maximum_position or "–",
            str(item.complete_batches),
            _fmt_p(item.friedman_p),
            _fmt(item.kendall_w, 3),
            item.status,
        ])
    return rows


def position_detail_rows(records: Sequence[MeasurementRecord], settings: ProjectSettings) -> list[list[str]]:
    if {r.study_type for r in records} != {"Bauraumprüfung"}:
        return []
    rows: list[list[str]] = []
    for key in feature_keys_present(records):
        spec = feature_spec(key)
        if spec.unit != "mm":
            continue
        item = analyze_spatial_feature(records, key, settings)
        for position, result in item.position_results:
            rows.append([
                spec.label, position, str(result.n), _fmt(result.mean), _fmt(result.deviation),
                _fmt(result.stdev), _fmt(result.span), _fmt(result.cm, 2), _fmt(result.cmk, 2),
                _fmt(result.cmk_lower_confidence_bound, 2), result.confidence_status, result.status,
            ])
    return rows


def batch_detail_rows(records: Sequence[MeasurementRecord], settings: ProjectSettings) -> list[list[str]]:
    if {r.study_type for r in records} != {"Bauraumprüfung"}:
        return []
    rows: list[list[str]] = []
    batches = sorted({str(r.batch) for r in records}, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x))
    for key in feature_keys_present(records):
        spec = feature_spec(key)
        if spec.unit != "mm":
            continue
        for batch in batches:
            subset = [r for r in records if str(r.batch) == batch]
            result = analyze_feature(subset, key, settings)
            if result is None:
                continue
            rows.append([
                spec.label, batch, str(result.n), _fmt(result.mean), _fmt(result.deviation),
                _fmt(result.stdev), _fmt(result.span), _fmt(result.cm, 2), _fmt(result.cmk, 2),
                _fmt(result.cmk_lower_confidence_bound, 2), result.confidence_status, result.status,
            ])
    return rows


def raw_record_rows(records: Sequence[MeasurementRecord]) -> list[list[str]]:
    rows: list[list[str]] = []
    for record in records:
        values = "; ".join(f"{feature_spec(key).label}={_fmt(value)}" for key, value in record.values.items())
        rows.append([
            record.study_type, TEMPLATES.get(record.template_key).label if record.template_key in TEMPLATES else record.template_key,
            record.configuration, record.material, record.batch, record.bed_position, record.specimen_id, values, record.note,
        ])
    return rows

def warning_rows(results: Sequence[CapabilityResult]) -> list[tuple[str, str]]:
    """Fasst gleiche Hinweise zusammen, statt sie für jedes Merkmal zu wiederholen."""
    labels_by_code: dict[str, list[str]] = {}
    for item in results:
        for code in item.warning_codes:
            labels_by_code.setdefault(code, [])
            if item.label not in labels_by_code[code]:
                labels_by_code[code].append(item.label)
    scope_codes = {
        "N_LT_30", "N_LT_TARGET", "GLOBAL_BED", "MIXED_SCOPE",
        "MISSING_CONFIGURATION", "MISSING_MATERIAL", "BASIS_NOT_REFERENCE_POSITION", "SEAM_STRATEGY_MISMATCH",
    }
    rows: list[tuple[str, str]] = []
    for code, labels in labels_by_code.items():
        text = WARNING_TEXTS.get(code)
        if not text:
            continue
        affected = "Prüfumfang" if code in scope_codes else ", ".join(labels)
        rows.append((affected, text))
    return rows


def _method_note(settings: ProjectSettings) -> str:
    return (
        "Cₘ und Cₘₖ werden nur bei s > 0 ausgewiesen. Identische Ablesewerte gelten nicht als "
        "Nachweis unendlich hoher Fähigkeit. Die Kennwerte sind merkmal-, positions- und "
        "konfigurationsbezogene Vergleichsgrößen; sie stellen keinen normkonformen industriellen "
        f"Fähigkeitsnachweis dar. Für reguläre Maschinenleistungsstudien dient n ≥ {NORMATIVE_REFERENCE_N} "
        "nur als normative Referenz. Beobachtete ppm sind auf eine Million skalierte Stichprobenanteile. "
        "Normalmodellbasierte ppm werden nur ergänzend ausgewiesen und setzen einen stabilen Zustand sowie "
        "eine plausible Verteilungsannahme voraus. Konfidenzintervalle für Cₘ basieren auf der Chi-Quadrat-Verteilung, "
        "für Cₘₖ wird eine Bissell-/Delta-Approximation verwendet. Die einseitige untere Konfidenzgrenze ist für eine "
        "Einordnung der Stichprobenunsicherheit gegenüber der Orientierungsgrenze hilfreich, ersetzt aber keinen normkonformen Freigabenachweis. "
        "Beobachtete ppm erhalten ein exaktes Clopper-Pearson-Intervall."
    )


def generate_text_report(
    records: Sequence[MeasurementRecord],
    settings: ProjectSettings,
    *,
    distributions: Sequence[DistributionResult] = (),
    options=None,
) -> str:
    opts = _options(options)
    results = analyze_records(records, settings)
    lines = [
        "FDM-Capability-Workbench",
        "=" * 72,
        f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
    ]
    if opts.include_scope:
        lines.extend(["", "Prüfumfang und Metadaten", "-" * 72])
        lines.extend(f"{label}: {value}" for label, value in scope_rows(records, settings))
    if opts.include_summary:
        lines.extend(["", "Kurzbewertung", "-" * 72, scope_summary_text(records, settings, results=results, distributions=distributions)])
    if opts.include_findings:
        lines.extend(["", "Priorisierte Befunde und nächste Schritte", "-" * 72])
        for level, area, finding, step in prioritized_findings(records, settings, results=results, distributions=distributions):
            lines.append(f"[{level.upper()}] {area}: {finding}")
            lines.append(f"  Nächster Schritt: {step}")
    if opts.include_core:
        lines.extend(["", "Kernkennwerte", "-" * 72])
        lines.append("Merkmal;Rolle;n;Mittelwert;Abweichung;s;R;Cm;Cmk;ppm_beob_gesamt;ppm_Modell_gesamt;Stufen;k_r;Einordnung")
        lines.extend(";".join(row) for row in compact_result_rows(results))
    if opts.include_confidence:
        rows = confidence_rows(results)
        if rows:
            lines.extend(["", "Konfidenzintervalle der Fähigkeitskennwerte", "-" * 72])
            lines.append("Merkmal;n;KI_Mittelwert;KI_s;Cm_USG;Cm_OSG;limitierende_Seite;Cm;KI_Cm;Cm_untere_Konfidenzgrenze;Cmk;KI_Cmk;Cmk_untere_Konfidenzgrenze;Einordnung")
            lines.extend(";".join(row) for row in rows)
    if opts.include_ppm:
        rows = ppm_rows(results)
        if rows:
            lines.extend(["", "ppm / Grenzüberschreitungsanteile", "-" * 72])
            lines.append("Merkmal;USG_UGW;OSG_OGW;n_unter;n_ober;ppm_beob_unter;ppm_beob_ober;ppm_beob_gesamt;KI_ppm_beob_gesamt;obere_Konfidenzgrenze_ppm;ppm_Modell_unter;ppm_Modell_ober;ppm_Modell_gesamt;Einordnung")
            lines.extend(";".join(row) for row in rows)
            lines.append("Hinweis: Beobachtete ppm sind Stichprobenanteile. Das exakte Clopper-Pearson-Intervall und die einseitige obere Konfidenzgrenze zeigen die Unsicherheit kleiner Stichproben; Modell-ppm sind eine ergänzende Normalmodellrechnung und keine exakte Ausschussprognose.")
    warnings = warning_rows(results)
    if opts.include_warnings and warnings:
        lines.extend(["", "Interpretationshinweise", "-" * 72])
        lines.extend(f"{label}: {warning}" for label, warning in warnings)
    if opts.include_distributions and distributions:
        lines.extend(["", "Verteilungsdiagnostik (ergänzend)", "-" * 72])
        lines.append("Merkmal;USG_UGW;OSG_OGW;n;Stufen;k_r;SW-p;JB-p;p_boot;Status")
        by_key = {r.feature_key: r for r in results}
        for dist in distributions:
            cap = by_key.get(dist.feature_key)
            label = cap.label if cap else dist.feature_key
            lines.append(";".join([label, _fmt(cap.lower_limit if cap else None), _fmt(cap.upper_limit if cap else None), str(dist.n), str(dist.unique_levels), _fmt(dist.k_r, 2), _fmt_p(dist.shapiro_p), _fmt_p(dist.jarque_bera_p), _fmt_p(dist.bootstrap_p), dist.status]))
            lines.append(f"  {dist.note}")
    if opts.include_spatial:
        spatial_rows = spatial_overview_rows(records, settings)
        if spatial_rows:
            lines.extend(["", "Bauraumdiagnose – Gesamt und Positionsabhängigkeit", "-" * 72])
            lines.append("Merkmal;n_global;Mittel_global;s_global;Cmk_global;Cmk_untere_Konfidenzgrenze;Spanne_Positionsmittel;Min_Position;Max_Position;vollst_Batches;Friedman_p;Kendall_W;Status")
            lines.extend(";".join(row) for row in spatial_rows)
            lines.extend(["", "Positionskennwerte", "-" * 72])
            lines.append("Merkmal;Position;n;Mittel;Delta;s;R;Cm;Cmk;Cmk_untere_Konfidenzgrenze;Konfidenz_Einordnung;Einordnung")
            lines.extend(";".join(row) for row in position_detail_rows(records, settings))
    if opts.include_batch_comparison:
        batch_rows = batch_detail_rows(records, settings)
        if batch_rows:
            lines.extend(["", "Batchvergleich", "-" * 72])
            lines.append("Merkmal;Batch;n;Mittel;Delta;s;R;Cm;Cmk;Cmk_untere_Konfidenzgrenze;Konfidenz_Einordnung;Einordnung")
            lines.extend(";".join(row) for row in batch_rows)
    if opts.include_raw_data:
        lines.extend(["", "Rohdatenanhang", "-" * 72])
        lines.append("Prüfstufe;Untersuchungsobjekt;Konfiguration;Material;Batch;Position;Nr.;Messwerte;Notiz")
        lines.extend(";".join(row) for row in raw_record_rows(records))
    if opts.include_method:
        lines.extend(["", "Methodische Einordnung", "-" * 72, _method_note(settings)])
    return "\n".join(lines)


def _html_table(headers: Sequence[str], rows: Iterable[Sequence[str]], class_name: str = "") -> str:
    cls = f' class="{class_name}"' if class_name else ""
    out = [f"<table{cls}><thead><tr>"]
    out.extend(f"<th>{escape(str(h))}</th>" for h in headers)
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        out.extend(f"<td>{escape(str(value))}</td>" for value in row)
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def generate_html_report(
    records: Sequence[MeasurementRecord],
    settings: ProjectSettings,
    *,
    distributions: Sequence[DistributionResult] = (),
    options=None,
) -> str:
    opts = _options(options)
    results = analyze_records(records, settings)
    sections: list[str] = []
    if opts.include_scope:
        sections.append("<h2>Prüfumfang und Metadaten</h2>" + _html_table(["Angabe", "Wert"], scope_rows(records, settings), "kv"))
    if opts.include_summary:
        sections.append("<h2>Kurzbewertung</h2><div class=\"note\">" + escape(scope_summary_text(records, settings, results=results, distributions=distributions)) + "</div>")
    if opts.include_findings:
        sections.append("<h2>Priorisierte Befunde und nächste Schritte</h2>" + _html_table(["Stufe", "Bereich", "Befund", "Nächster Schritt"], prioritized_findings(records, settings, results=results, distributions=distributions)))
    if opts.include_core:
        sections.append("<h2>Kernkennwerte</h2>" + _html_table(
            ["Merkmal", "Rolle", "n", "Mittel", "Δ", "s", "R", "Cₘ", "Cₘₖ", "ppm beob. ges.", "ppm Modell ges.", "Stufen", "kᵣ", "Einordnung"],
            compact_result_rows(results),
        ))
    if opts.include_confidence:
        rows = confidence_rows(results)
        if rows:
            sections.append("<h2>Konfidenzintervalle der Fähigkeitskennwerte</h2>" + _html_table(
                ["Merkmal", "n", "KI x̄", "KI s", "Cₘ,USG", "Cₘ,OSG", "limitierend", "Cₘ", "KI Cₘ", "einseitige untere Konfidenzgrenze Cₘ", "Cₘₖ", "KI Cₘₖ", "einseitige untere Konfidenzgrenze Cₘₖ", "Einordnung"], rows
            ))
    if opts.include_ppm:
        rows = ppm_rows(results)
        if rows:
            sections.append(
                "<h2>ppm / Grenzüberschreitungsanteile</h2>"
                + _html_table(
                    ["Merkmal", "USG / UGW", "OSG / OGW", "n < USG", "n > OSG", "beob. ppm < USG", "beob. ppm > OSG", "beob. ppm gesamt", "KI beob. gesamt", "obere Konfidenzgrenze", "Modell-ppm < USG", "Modell-ppm > OSG", "Modell-ppm gesamt", "Einordnung"],
                    rows,
                )
                + '<div class="note">Beobachtete ppm sind auf eine Million skalierte Stichprobenanteile. Das exakte Clopper-Pearson-Intervall und die einseitige obere Konfidenzgrenze zeigen die Unsicherheit kleiner Stichproben. Modell-ppm beruhen auf einer Normalverteilung mit x̄ und s und sind nur ergänzend zu interpretieren.</div>'
            )
    warnings = warning_rows(results)
    if opts.include_warnings and warnings:
        sections.append("<h2>Interpretationshinweise</h2>" + _html_table(["Merkmal / Umfang", "Hinweis"], warnings, "kv"))
    if opts.include_distributions and distributions:
        by_key = {r.feature_key: r for r in results}
        rows = [[
            by_key.get(item.feature_key).label if item.feature_key in by_key else item.feature_key,
            _fmt(by_key.get(item.feature_key).lower_limit if item.feature_key in by_key else None),
            _fmt(by_key.get(item.feature_key).upper_limit if item.feature_key in by_key else None),
            item.n, item.unique_levels, _fmt(item.k_r, 2), _fmt_p(item.shapiro_p), _fmt_p(item.jarque_bera_p),
            _fmt_p(item.bootstrap_p), item.status, item.note,
        ] for item in distributions]
        sections.append("<h2>Verteilungsdiagnostik <small>(ergänzend)</small></h2>" + _html_table(
            ["Merkmal", "USG / UGW", "OSG / OGW", "n", "Stufen", "kᵣ", "SW-p", "JB-p", "p_boot", "Status", "Hinweis"], rows
        ))
    if opts.include_spatial:
        rows = spatial_overview_rows(records, settings)
        if rows:
            sections.append("<h2>Bauraumdiagnose – globale und positionsbezogene Auswertung</h2>" + _html_table(
                ["Merkmal", "n global", "Mittel global", "s global", "Cₘₖ global", "Cₘₖ: einseitige untere Konfidenzgrenze", "Spanne Positionsmittel", "Min-Position", "Max-Position", "vollst. Batches", "Friedman p", "Kendall W", "Einordnung"], rows
            ))
            sections.append("<h3>Positionskennwerte</h3>" + _html_table(
                ["Merkmal", "Position", "n", "Mittel", "Δ", "s", "R", "Cₘ", "Cₘₖ", "Cₘₖ: einseitige untere Konfidenzgrenze", "Konfidenz-Einordnung", "Einordnung"], position_detail_rows(records, settings)
            ))
    if opts.include_batch_comparison:
        rows = batch_detail_rows(records, settings)
        if rows:
            sections.append("<h2>Batchvergleich</h2>" + _html_table(
                ["Merkmal", "Batch", "n", "Mittel", "Δ", "s", "R", "Cₘ", "Cₘₖ", "Cₘₖ: einseitige untere Konfidenzgrenze", "Konfidenz-Einordnung", "Einordnung"], rows
            ))
    if opts.include_raw_data:
        sections.append("<h2>Rohdatenanhang</h2>" + _html_table(
            ["Prüfstufe", "Untersuchungsobjekt", "Konfiguration", "Material", "Batch", "Position", "Nr.", "Messwerte", "Notiz"], raw_record_rows(records)
        ))
    if opts.include_method:
        sections.append("<h2>Methodische Einordnung</h2><div class=\"note\">" + escape(_method_note(settings)) + "</div>")

    css = """
    @page { size: A4 landscape; margin: 12mm; }
    body { font-family: Arial, sans-serif; margin: 24px; color: #222; line-height: 1.35; }
    h1 { margin-bottom: 3px; } h2 { margin-top: 24px; font-size: 18px; border-bottom: 1px solid #aaa; padding-bottom: 4px; }
    h3 { margin-top: 18px; } small { font-size: 70%; font-weight: normal; }
    .meta { color: #555; margin-bottom: 18px; }
    table { border-collapse: collapse; width: 100%; margin: 8px 0 14px; font-size: 11px; }
    th, td { border: 1px solid #ccc; padding: 5px 6px; vertical-align: top; }
    th { background: #eceff3; text-align: left; position: sticky; top: 0; }
    table.kv th, table.kv td:first-child { width: 220px; font-weight: bold; background: #f7f7f7; }
    .note { background: #f5f6f8; border-left: 4px solid #777; padding: 10px 12px; }
    """
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{escape(settings.project_name)}</title>
<style>{css}</style></head><body><h1>FDM-Capability-Workbench</h1>
<div class="meta">Erstellt am {datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')}</div>
{''.join(sections)}</body></html>"""


def save_text_report(path: str | Path, records: Sequence[MeasurementRecord], settings: ProjectSettings, *, distributions=(), options=None) -> None:
    Path(path).write_text(generate_text_report(records, settings, distributions=distributions, options=options), encoding="utf-8")


def save_html_report(path: str | Path, records: Sequence[MeasurementRecord], settings: ProjectSettings, *, distributions=(), options=None) -> None:
    Path(path).write_text(generate_html_report(records, settings, distributions=distributions, options=options), encoding="utf-8")


def save_pdf_report(path: str | Path, records: Sequence[MeasurementRecord], settings: ProjectSettings, *, distributions=(), options=None) -> None:
    """Erzeugt einen kompakten PDF-Bericht; reportlab ist eine optionale Abhängigkeit."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover - optionale Abhängigkeit
        raise RuntimeError("Für den PDF-Export wird reportlab benötigt: py -m pip install reportlab") from exc

    opts = _options(options)
    results = analyze_records(records, settings)
    doc = SimpleDocTemplate(
        str(path), pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=6 * mm, bottomMargin=6 * mm,
    )
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=6.7, leading=7.8)
    small_bold = ParagraphStyle("small_bold", parent=small, fontName="Helvetica-Bold")
    heading = ParagraphStyle("heading", parent=styles["Heading2"], fontSize=11, leading=13, spaceBefore=4, spaceAfter=3)
    def pdf_markup(value) -> str:
        text = escape(str(value))
        replacements = (
            ("Cₘₖ", "C<sub>mk</sub>"),
            ("Cₘ", "C<sub>m</sub>"),
            ("kᵣ", "k<sub>r</sub>"),
            ("μ̂", "mu_hat"),
            ("σ̂", "sigma_hat"),
            ("Δ", "Delta"),
            ("≥", "&gt;="),
            ("≤", "&lt;="),
        )
        for source, target in replacements:
            text = text.replace(source, target)
        return text

    story = [Paragraph("FDM-Capability-Workbench", styles["Title"]), Spacer(1, 2 * mm)]

    def table(data, widths=None):
        prepared = [[Paragraph(pdf_markup(v), small_bold if r == 0 else small) for v in row] for r, row in enumerate(data)]
        obj = Table(prepared, colWidths=widths, repeatRows=1, hAlign="LEFT")
        obj.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECEFF3")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return obj

    if opts.include_scope:
        story.append(Paragraph("Prüfumfang und Metadaten", heading))
        story.append(table([["Angabe", "Wert"]] + [[k, v] for k, v in scope_rows(records, settings)], [46 * mm, 225 * mm]))
    if opts.include_summary:
        story.append(Paragraph("Kurzbewertung", heading))
        story.append(Paragraph(pdf_markup(scope_summary_text(records, settings, results=results, distributions=distributions)), small))
    if opts.include_findings:
        story.append(Paragraph("Priorisierte Befunde und nächste Schritte", heading))
        finding_data = [["Stufe", "Bereich", "Befund", "Nächster Schritt"]] + [list(row) for row in prioritized_findings(records, settings, results=results, distributions=distributions)]
        story.append(table(finding_data, [18*mm, 36*mm, 96*mm, 121*mm]))
    if opts.include_core:
        story.append(Paragraph("Kernkennwerte", heading))
        headers = ["Merkmal", "Rolle", "n", "Mittel", "Δ", "s", "R", "Cₘ", "Cₘₖ", "ppm beob.", "ppm Modell", "Stufen", "kᵣ", "Einordnung"]
        story.append(table([headers] + compact_result_rows(results), [36*mm, 24*mm, 7*mm, 13*mm, 12*mm, 11*mm, 11*mm, 10*mm, 11*mm, 15*mm, 15*mm, 9*mm, 9*mm, 48*mm]))
    if opts.include_confidence:
        rows = confidence_rows(results)
        if rows:
            story.append(Paragraph("Konfidenzintervalle der Fähigkeitskennwerte", heading))
            headers = ["Merkmal", "n", "KI x_bar", "KI s", "Cm USG", "Cm OSG", "Limit", "Cm", "KI Cm", "UG Cm", "Cmk", "KI Cmk", "UG Cmk", "Einordnung"]
            story.append(table([headers] + rows))
    if opts.include_ppm:
        rows = ppm_rows(results)
        if rows:
            story.append(Paragraph("ppm / Grenzüberschreitungsanteile", heading))
            headers = ["Merkmal", "USG", "OSG", "n<", "n>", "beob.<", "beob.>", "beob.ges.", "KI beob.", "obere KG", "Modell<", "Modell>", "Modell ges.", "Einordnung"]
            story.append(table([headers] + rows))
            story.append(Paragraph("Beobachtete ppm sind auf eine Million skalierte Stichprobenanteile; das Clopper-Pearson-Intervall zeigt ihre Stichprobenunsicherheit. Modell-ppm beruhen auf einer Normalverteilung mit x_bar und s und sind nur ergänzend zu interpretieren.", small))
    warnings = warning_rows(results)
    if opts.include_warnings and warnings:
        story.append(Paragraph("Interpretationshinweise", heading))
        story.append(table([["Merkmal", "Hinweis"]] + [[a, b] for a, b in warnings], [55*mm, 216*mm]))
    if opts.include_distributions and distributions:
        by_key = {r.feature_key: r for r in results}
        dist_rows = [["Merkmal", "USG", "OSG", "n", "Stufen", "kᵣ", "SW-p", "JB-p", "p_boot", "Status"]]
        for item in distributions:
            cap = by_key.get(item.feature_key)
            dist_rows.append([cap.label if cap else item.feature_key, _fmt(cap.lower_limit if cap else None), _fmt(cap.upper_limit if cap else None), str(item.n), str(item.unique_levels), _fmt(item.k_r, 2), _fmt_p(item.shapiro_p), _fmt_p(item.jarque_bera_p), _fmt_p(item.bootstrap_p), item.status])
        story.append(Paragraph("Verteilungsdiagnostik (ergänzend)", heading))
        story.append(table(dist_rows))
    if opts.include_spatial:
        rows = spatial_overview_rows(records, settings)
        if rows:
            story.append(Paragraph("Bauraumdiagnose – globale und positionsbezogene Auswertung", heading))
            headers = ["Merkmal", "n", "Mittel", "s", "Cmk", "Cmk: einseitige untere Konfidenzgrenze", "Spanne Pos.-Mittel", "Min", "Max", "Batches", "Friedman p", "W", "Einordnung"]
            story.append(table([headers] + rows))
            story.append(Paragraph("Positionskennwerte", heading))
            story.append(table([["Merkmal", "Position", "n", "Mittel", "Delta", "s", "R", "Cm", "Cmk", "Cmk: einseitige untere Konfidenzgrenze", "Konfidenz-Einordnung", "Einordnung"]] + position_detail_rows(records, settings)))
    if opts.include_batch_comparison:
        rows = batch_detail_rows(records, settings)
        if rows:
            story.append(Paragraph("Batchvergleich", heading))
            story.append(table([["Merkmal", "Batch", "n", "Mittel", "Delta", "s", "R", "Cm", "Cmk", "Cmk: einseitige untere Konfidenzgrenze", "Konfidenz-Einordnung", "Einordnung"]] + rows))
    if opts.include_raw_data:
        story.append(Paragraph("Rohdatenanhang", heading))
        story.append(table([["Prüfstufe", "Untersuchungsobjekt", "Konfiguration", "Material", "Batch", "Position", "Nr.", "Messwerte", "Notiz"]] + raw_record_rows(records)))
    if opts.include_method:
        story.append(Paragraph("Methodische Einordnung", heading))
        story.append(Paragraph(pdf_markup(_method_note(settings)), small))
    doc.build(story)
