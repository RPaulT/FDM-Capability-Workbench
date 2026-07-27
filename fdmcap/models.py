"""Datenmodelle."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, Mapping
from uuid import uuid4

from .config import (
    DEFAULT_ALPHA,
    DEFAULT_BOOTSTRAP_REPETITIONS,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_CAPABILITY_ORIENTATION,
    DEFAULT_CONFIDENCE_LEVEL,
    DEFAULT_RESOLUTION_MM,
    DEFAULT_TOLERANCE_HALF_WIDTH_MM,
    SEAM_ALONG_Y,
    normalize_bed_position,
)


@dataclass
class ProjectSettings:
    project_name: str = "FDM-Capability-Workbench – Maschinenfähigkeitsuntersuchung"
    printer: str = ""
    nozzle_diameter_mm: str = "0.4"
    slicer: str = ""
    slicer_profile: str = ""
    measurement_tool: str = "Uhrmessschieber"
    operator: str = ""
    resolution_mm: float = DEFAULT_RESOLUTION_MM
    mass_resolution_g: float = 0.001
    tolerance_half_width_mm: float = DEFAULT_TOLERANCE_HALF_WIDTH_MM
    capability_orientation: float = DEFAULT_CAPABILITY_ORIENTATION
    alpha: float = DEFAULT_ALPHA
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL
    bootstrap_repetitions: int = DEFAULT_BOOTSTRAP_REPETITIONS
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED
    preheat_minutes: int = 15
    cooling_hours: int = 6
    seam_position: str = "zwischen X und Y (45°); X/Y nahtfrei"
    measure_seam_separately: bool = False
    filament_state: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectSettings":
        allowed = {field_.name for field_ in cls.__dataclass_fields__.values()}
        clean = {key: value for key, value in data.items() if key in allowed}
        legacy_seam = str(clean.get("seam_position", ""))
        if legacy_seam in {"entlang der Y-Messrichtung", "entlang Y"}:
            clean["seam_position"] = SEAM_ALONG_Y
        if isinstance(clean.get("measure_seam_separately"), str):
            clean["measure_seam_separately"] = clean["measure_seam_separately"].strip().lower() in {"1", "true", "ja", "yes"}
        return cls(**clean)


@dataclass
class MeasurementRecord:
    record_id: str = field(default_factory=lambda: uuid4().hex)
    study_type: str = "Basisprüfung"
    template_key: str = "reference"
    configuration: str = ""
    material: str = "PLA"
    batch: str = "1"
    bed_position: str = "Mitte"
    specimen_id: str = "1"
    values: Dict[str, float] = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        self.bed_position = normalize_bed_position(self.bed_position)
        self.study_type = str(self.study_type or "").strip() or "Basisprüfung"
        self.template_key = str(self.template_key or "").strip() or "reference"
        self.configuration = str(self.configuration or "").strip()
        self.material = str(self.material or "").strip()
        self.batch = str(self.batch or "").strip()
        self.specimen_id = str(self.specimen_id or "").strip()

    def copy_with_new_id(self) -> "MeasurementRecord":
        return MeasurementRecord(
            study_type=self.study_type,
            template_key=self.template_key,
            configuration=self.configuration,
            material=self.material,
            batch=self.batch,
            bed_position=self.bed_position,
            specimen_id=self.specimen_id,
            values=dict(self.values),
            note=self.note,
        )

    def group_key(self) -> tuple[str, str, str, str]:
        return self.configuration, self.material, self.study_type, self.template_key

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "study_type": self.study_type,
            "template_key": self.template_key,
            "configuration": self.configuration,
            "material": self.material,
            "batch": self.batch,
            "bed_position": self.bed_position,
            "specimen_id": self.specimen_id,
            "values": dict(self.values),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MeasurementRecord":
        values_raw = data.get("values", {}) or {}
        values = {
            str(key): float(value)
            for key, value in values_raw.items()
            if value not in (None, "")
        }
        return cls(
            record_id=str(data.get("record_id") or uuid4().hex),
            study_type=str(data.get("study_type") or "Basisprüfung"),
            template_key=str(data.get("template_key") or "reference"),
            configuration=str(data.get("configuration") or ""),
            material=str(data.get("material") or ""),
            batch=str(data.get("batch") or ""),
            bed_position=str(data.get("bed_position") or ""),
            specimen_id=str(data.get("specimen_id") or ""),
            values=values,
            note=str(data.get("note") or ""),
        )


@dataclass
class ProjectData:
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    records: list[MeasurementRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": "fdmcap-project-v1",
            "settings": self.settings.to_dict(),
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProjectData":
        records: list[MeasurementRecord] = []
        for item in data.get("records", []):
            raw = dict(item)
            if str(raw.get("template_key") or "") != "inner_contours":
                records.append(MeasurementRecord.from_dict(raw))
                continue

            # Migration früherer 1.5.0-Projekte: Kreis- und Quadratmerkmale waren
            # zeitweise in einer gemeinsamen Messzeile gespeichert. Die fertige
            # Fassung führt beide Prüfungen getrennt.
            values = dict(raw.get("values", {}) or {})
            circle_values = {key: value for key, value in values.items() if str(key).startswith("inner_circle_")}
            square_values = {key: value for key, value in values.items() if str(key).startswith("inner_square_")}
            for template_key, separated_values in (
                ("inner_circle", circle_values),
                ("inner_square", square_values),
            ):
                if not separated_values:
                    continue
                migrated = dict(raw)
                migrated["record_id"] = uuid4().hex
                migrated["template_key"] = template_key
                migrated["values"] = separated_values
                records.append(MeasurementRecord.from_dict(migrated))

            # Unbekannte Altwerte nicht stillschweigend verwerfen.
            if not circle_values and not square_values:
                raw["template_key"] = "inner_circle"
                records.append(MeasurementRecord.from_dict(raw))

        return cls(
            settings=ProjectSettings.from_dict(data.get("settings", {})),
            records=records,
        )


@dataclass
class CapabilityResult:
    feature_key: str
    label: str
    role: str
    geometry_class: str
    unit: str
    nominal: float | None
    lower_limit: float | None
    upper_limit: float | None
    n: int
    mean: float
    deviation: float | None
    stdev: float
    span: float
    minimum: float
    maximum: float
    unique_levels: int
    k_r: float | None
    cm: float | None
    cmk: float | None
    cml: float | None
    cmu: float | None
    limiting_side: str | None
    mean_ci_lower: float | None
    mean_ci_upper: float | None
    stdev_ci_lower: float | None
    stdev_ci_upper: float | None
    cm_ci_lower: float | None
    cm_ci_upper: float | None
    cm_lower_confidence_bound: float | None
    cmk_ci_lower: float | None
    cmk_ci_upper: float | None
    cmk_lower_confidence_bound: float | None
    confidence_level: float
    confidence_status: str
    observed_below_count: int | None
    observed_above_count: int | None
    observed_ppm_below: float | None
    observed_ppm_above: float | None
    observed_ppm_total: float | None
    expected_ppm_below: float | None
    expected_ppm_above: float | None
    expected_ppm_total: float | None
    observed_ppm_total_ci_lower: float | None
    observed_ppm_total_ci_upper: float | None
    observed_ppm_total_upper_bound: float | None
    status: str
    warning_codes: tuple[str, ...] = ()
    warning_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DistributionResult:
    feature_key: str
    n: int
    unique_levels: int
    k_r: float | None
    shapiro_statistic: float | None
    shapiro_p: float | None
    jarque_bera_statistic: float | None
    jarque_bera_p: float | None
    bootstrap_q: float | None
    bootstrap_p: float | None
    fitted_mu: float | None
    fitted_sigma: float | None
    bootstrap_repetitions: int
    failed_fits: int
    bootstrap_q_values: tuple[float, ...]
    status: str
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def values_for_feature(records: Iterable[MeasurementRecord], feature_key: str) -> list[float]:
    values: list[float] = []
    for record in records:
        value = record.values.get(feature_key)
        if value is not None:
            values.append(float(value))
    return values
