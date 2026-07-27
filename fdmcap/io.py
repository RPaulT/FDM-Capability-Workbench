from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Sequence

from .config import FEATURES, TEMPLATES
from .models import CapabilityResult, MeasurementRecord, ProjectData

META_COLUMNS = (
    "record_id",
    "study_type",
    "template_key",
    "configuration",
    "material",
    "batch",
    "bed_position",
    "specimen_id",
    "note",
)
FEATURE_PREFIX = "feature."


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"na", "n/a", "-", "–"}:
        return None
    return float(text.replace(",", "."))


def save_project(path: str | Path, project: ProjectData) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(project.to_dict(), handle, ensure_ascii=False, indent=2)


def load_project(path: str | Path) -> ProjectData:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return ProjectData.from_dict(data)


def _present_feature_keys(records: Iterable[MeasurementRecord]) -> list[str]:
    present: set[str] = set()
    for record in records:
        present.update(record.values)
    known = [key for key in FEATURES if key in present]
    return known + sorted(present.difference(FEATURES))


def save_measurements_csv(path: str | Path, records: Sequence[MeasurementRecord]) -> None:
    feature_keys = _present_feature_keys(records)
    fieldnames = list(META_COLUMNS) + [FEATURE_PREFIX + key for key in feature_keys]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for record in records:
            row = {
                "record_id": record.record_id,
                "study_type": record.study_type,
                "template_key": record.template_key,
                "configuration": record.configuration,
                "material": record.material,
                "batch": record.batch,
                "bed_position": record.bed_position,
                "specimen_id": record.specimen_id,
                "note": record.note,
            }
            for key in feature_keys:
                value = record.values.get(key)
                row[FEATURE_PREFIX + key] = "" if value is None else format(value, ".12g")
            writer.writerow(row)


def _load_new_format(rows: list[dict[str, str]], fieldnames: list[str]) -> list[MeasurementRecord]:
    feature_columns = [name for name in fieldnames if name.startswith(FEATURE_PREFIX)]
    records: list[MeasurementRecord] = []
    for row in rows:
        values = {}
        for column in feature_columns:
            value = _float_or_none(row.get(column))
            if value is not None:
                values[column[len(FEATURE_PREFIX):]] = value
        records.append(
            MeasurementRecord(
                record_id=str(row.get("record_id") or MeasurementRecord().record_id),
                study_type=str(row.get("study_type") or "Basisprüfung"),
                template_key=str(row.get("template_key") or "reference"),
                configuration=str(row.get("configuration") or ""),
                material=str(row.get("material") or ""),
                batch=str(row.get("batch") or ""),
                bed_position=str(row.get("bed_position") or ""),
                specimen_id=str(row.get("specimen_id") or ""),
                values=values,
                note=str(row.get("note") or ""),
            )
        )
    return records


def _map_old_test_type(value: str) -> tuple[str, str]:
    text = (value or "").strip().lower()
    if "bauraum" in text:
        return "Bauraumprüfung", "reference"
    if "45" in text:
        return "Basisprüfung", "reference"
    if "hohl" in text or "zylinder" in text:
        return "Geometriespezifische Zusatzprüfung", "cylinder_stack"
    return "Basisprüfung", "reference"


def _load_legacy_app(rows: list[dict[str, str]]) -> list[MeasurementRecord]:
    records: list[MeasurementRecord] = []
    for row in rows:
        study_type, template_key = _map_old_test_type(row.get("test_type", ""))
        is_45 = "45" in (row.get("test_type", "") + row.get("orientation", ""))
        values = {}
        x = _float_or_none(row.get("x_mm"))
        y = _float_or_none(row.get("y_mm"))
        z = _float_or_none(row.get("z_mm"))
        if is_45:
            if x is not None:
                values["diag_1"] = x
            if y is not None:
                values["diag_2"] = y
        else:
            if x is not None:
                values["x_outer"] = x
            if y is not None:
                values["y_outer"] = y
        if z is not None:
            values["z_height"] = z
        mappings = {
            "diag1_mm": "diag_1",
            "diag2_mm": "diag_2",
            "weight_g": "mass_g",
            "x_bottom_mm": "legacy_x_bottom",
            "x_top_mm": "legacy_x_top",
            "y_bottom_mm": "legacy_y_bottom",
            "y_top_mm": "legacy_y_top",
        }
        for source, target in mappings.items():
            parsed = _float_or_none(row.get(source))
            if parsed is not None:
                values[target] = parsed
        records.append(
            MeasurementRecord(
                study_type=study_type,
                template_key=template_key,
                configuration=str(row.get("profile") or row.get("test_id") or ""),
                material=str(row.get("material") or ""),
                batch=str(row.get("test_id") or row.get("print_job") or "1"),
                bed_position=str(row.get("bed_position") or "Mitte"),
                specimen_id=str(row.get("cube_id") or ""),
                values=values,
                note=str(row.get("note") or ""),
            )
        )
    return records


def _normalized_header_map(fieldnames: list[str]) -> dict[str, str]:
    return {name.strip().lower().replace("°", "grad"): name for name in fieldnames}


def _load_thesis_reference_table(rows: list[dict[str, str]], fieldnames: list[str]) -> list[MeasurementRecord]:
    header_map = _normalized_header_map(fieldnames)

    def source(*candidates: str) -> str | None:
        for candidate in candidates:
            key = candidate.lower().replace("°", "grad")
            if key in header_map:
                return header_map[key]
        return None

    columns = {
        "x_outer": source("x"),
        "y_outer": source("y"),
        "z_height": source("z"),
        "diag_1": source("ur -> ol", "ur→ol", "45grad-maß 1", "45°-maß 1"),
        "diag_2": source("ul -> or", "ul→or", "45grad-maß 2", "45°-maß 2"),
        "cylinder_x_free": source("zylinder x (ohne nat)", "zylinder x (ohne naht)", "zylinder außen, nahtfrei (x)"),
        "cylinder_y_seam": source("zylinder y (mit nat)", "zylinder y (mit naht)", "zylinder außen, über naht (y)"),
        "mass_g": source("g", "masse", "gewicht")
    }
    batch_col = source("batch")
    position_col = source("position", "druckbettposition")
    id_col = source("nr", "nummer", "specimen_id")
    records: list[MeasurementRecord] = []
    for row in rows:
        values = {}
        for target, column in columns.items():
            if column:
                value = _float_or_none(row.get(column))
                if value is not None:
                    values[target] = value
        study_type = "Bauraumprüfung" if batch_col or position_col else "Basisprüfung"
        records.append(
            MeasurementRecord(
                study_type=study_type,
                template_key="reference",
                configuration="",
                material="",
                batch=str(row.get(batch_col, "1") if batch_col else "1"),
                bed_position=str(row.get(position_col, "Mitte") if position_col else "Mitte"),
                specimen_id=str(row.get(id_col, "") if id_col else ""),
                values=values,
            )
        )
    return records


def load_measurements_csv(path: str | Path) -> tuple[list[MeasurementRecord], list[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        fieldnames = [str(name).strip() for name in (reader.fieldnames or [])]
        rows = [{str(k).strip(): (v or "").strip() for k, v in row.items()} for row in reader]

    if not fieldnames:
        raise ValueError("Die CSV-Datei enthält keine Kopfzeile.")
    warnings: list[str] = []
    if any(name.startswith(FEATURE_PREFIX) for name in fieldnames):
        records = _load_new_format(rows, fieldnames)
    elif {"cube_id", "x_mm", "y_mm", "z_mm"}.issubset(fieldnames):
        records = _load_legacy_app(rows)
        warnings.append("Altes Würfeltest-CSV-Format wurde in das neue Datenmodell überführt.")
    elif {"nr", "x", "y", "z"}.issubset({name.lower() for name in fieldnames}):
        records = _load_thesis_reference_table(rows, fieldnames)
        warnings.append("Tabellenformat der Bachelorarbeit wurde als Referenzprüfkörper-Datensatz importiert.")
    else:
        raise ValueError(
            "Unbekanntes CSV-Format. Erwartet werden feature.*-Spalten, das alte Würfeltestformat "
            "oder die Referenzprüfkörper-Spalten nr/x/y/z/ur -> ol/ul -> or/..."
        )
    return records, warnings


def save_analysis_csv(path: str | Path, results: Sequence[CapabilityResult]) -> None:
    fieldnames = (
        "feature_key",
        "merkmal",
        "rolle",
        "geometrieklasse",
        "n",
        "mittelwert",
        "mittlere_abweichung",
        "s",
        "R",
        "min",
        "max",
        "stufen",
        "k_r",
        "Cm",
        "Cm_KI_unter",
        "Cm_KI_ober",
        "Cm_untere_Konfidenzgrenze",
        "Cmk",
        "Cmk_KI_unter",
        "Cmk_KI_ober",
        "Cmk_untere_Konfidenzgrenze",
        "Cm_USG",
        "Cm_OSG",
        "limitierende_Seite",
        "KI_Mittelwert_unter",
        "KI_Mittelwert_ober",
        "KI_s_unter",
        "KI_s_ober",
        "Konfidenzniveau",
        "Konfidenz_Einordnung",
        "USG_UGW",
        "OSG_OGW",
        "beobachtet_n_unter",
        "beobachtet_n_ober",
        "beobachtet_ppm_unter",
        "beobachtet_ppm_ober",
        "beobachtet_ppm_gesamt",
        "beobachtet_ppm_gesamt_KI_unter",
        "beobachtet_ppm_gesamt_KI_ober",
        "beobachtet_ppm_gesamt_obere_Konfidenzgrenze",
        "modell_ppm_unter",
        "modell_ppm_ober",
        "modell_ppm_gesamt",
        "status",
        "warnhinweis",
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for result in results:
            writer.writerow({
                "feature_key": result.feature_key,
                "merkmal": result.label,
                "rolle": result.role,
                "geometrieklasse": result.geometry_class,
                "n": result.n,
                "mittelwert": result.mean,
                "mittlere_abweichung": "" if result.deviation is None else result.deviation,
                "s": result.stdev,
                "R": result.span,
                "min": result.minimum,
                "max": result.maximum,
                "stufen": result.unique_levels,
                "k_r": "" if result.k_r is None else result.k_r,
                "Cm": "" if result.cm is None else result.cm,
                "Cm_KI_unter": "" if result.cm_ci_lower is None else result.cm_ci_lower,
                "Cm_KI_ober": "" if result.cm_ci_upper is None else result.cm_ci_upper,
                "Cm_untere_Konfidenzgrenze": "" if result.cm_lower_confidence_bound is None else result.cm_lower_confidence_bound,
                "Cmk": "" if result.cmk is None else result.cmk,
                "Cmk_KI_unter": "" if result.cmk_ci_lower is None else result.cmk_ci_lower,
                "Cmk_KI_ober": "" if result.cmk_ci_upper is None else result.cmk_ci_upper,
                "Cmk_untere_Konfidenzgrenze": "" if result.cmk_lower_confidence_bound is None else result.cmk_lower_confidence_bound,
                "Cm_USG": "" if result.cml is None else result.cml,
                "Cm_OSG": "" if result.cmu is None else result.cmu,
                "limitierende_Seite": result.limiting_side or "",
                "KI_Mittelwert_unter": "" if result.mean_ci_lower is None else result.mean_ci_lower,
                "KI_Mittelwert_ober": "" if result.mean_ci_upper is None else result.mean_ci_upper,
                "KI_s_unter": "" if result.stdev_ci_lower is None else result.stdev_ci_lower,
                "KI_s_ober": "" if result.stdev_ci_upper is None else result.stdev_ci_upper,
                "Konfidenzniveau": result.confidence_level,
                "Konfidenz_Einordnung": result.confidence_status,
                "USG_UGW": "" if result.lower_limit is None else result.lower_limit,
                "OSG_OGW": "" if result.upper_limit is None else result.upper_limit,
                "beobachtet_n_unter": "" if result.observed_below_count is None else result.observed_below_count,
                "beobachtet_n_ober": "" if result.observed_above_count is None else result.observed_above_count,
                "beobachtet_ppm_unter": "" if result.observed_ppm_below is None else result.observed_ppm_below,
                "beobachtet_ppm_ober": "" if result.observed_ppm_above is None else result.observed_ppm_above,
                "beobachtet_ppm_gesamt": "" if result.observed_ppm_total is None else result.observed_ppm_total,
                "beobachtet_ppm_gesamt_KI_unter": "" if result.observed_ppm_total_ci_lower is None else result.observed_ppm_total_ci_lower,
                "beobachtet_ppm_gesamt_KI_ober": "" if result.observed_ppm_total_ci_upper is None else result.observed_ppm_total_ci_upper,
                "beobachtet_ppm_gesamt_obere_Konfidenzgrenze": "" if result.observed_ppm_total_upper_bound is None else result.observed_ppm_total_upper_bound,
                "modell_ppm_unter": "" if result.expected_ppm_below is None else result.expected_ppm_below,
                "modell_ppm_ober": "" if result.expected_ppm_above is None else result.expected_ppm_above,
                "modell_ppm_gesamt": "" if result.expected_ppm_total is None else result.expected_ppm_total,
                "status": result.status,
                "warnhinweis": result.warning_text,
            })
