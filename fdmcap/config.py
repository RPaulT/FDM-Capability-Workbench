from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

APP_TITLE = "FDM-Capability-Workbench"
PROGRAM_VERSION = "1.5.0"

DEFAULT_RESOLUTION_MM = 0.02
DEFAULT_TOLERANCE_HALF_WIDTH_MM = 0.20
DEFAULT_CAPABILITY_ORIENTATION = 1.67
DEFAULT_ALPHA = 0.05
DEFAULT_CONFIDENCE_LEVEL = 0.95
DEFAULT_BOOTSTRAP_REPETITIONS = 10_000
DEFAULT_BOOTSTRAP_SEED = 20_260_716
DEFAULT_BASIS_TARGET_N = 25
NORMATIVE_REFERENCE_N = 30

STUDY_TYPES: Tuple[str, ...] = (
    "Basisprüfung",
    "Bauraumprüfung",
    "Geometriespezifische Zusatzprüfung",
)

# "Neubewertung" wird für ältere Datensätze weiterhin unterstützt, wird aber
# nicht mehr als reguläre neue Prüfstufe vorgeschlagen. In der Praxis ist eine
# erneute Untersuchung nach einer wesentlichen Konfigurationsänderung meist als
# eigenes Projekt übersichtlicher.
LEGACY_STUDY_TYPES: Tuple[str, ...] = ("Neubewertung",)

BED_POSITIONS: Tuple[str, ...] = (
    "hinten links",
    "hinten Mitte",
    "hinten rechts",
    "Mitte links",
    "Mitte",
    "Mitte rechts",
    "vorne links",
    "vorne Mitte",
    "vorne rechts",
)



def normalize_bed_position(value: str) -> str:
    """Normalisiert Groß-/Kleinschreibung und häufige Schreibvarianten der 3×3-Positionen."""
    raw = " ".join(str(value or "").strip().replace("_", " ").replace("-", " ").split())
    if not raw:
        return ""
    aliases = {
        "hinten links": "hinten links",
        "hinten mitte": "hinten Mitte",
        "hinten rechts": "hinten rechts",
        "mitte links": "Mitte links",
        "mitte": "Mitte",
        "mitte rechts": "Mitte rechts",
        "vorne links": "vorne links",
        "vorne mitte": "vorne Mitte",
        "vorne rechts": "vorne rechts",
        "center": "Mitte",
        "centre": "Mitte",
        "middle": "Mitte",
        "back left": "hinten links",
        "back center": "hinten Mitte",
        "back centre": "hinten Mitte",
        "back right": "hinten rechts",
        "middle left": "Mitte links",
        "middle right": "Mitte rechts",
        "front left": "vorne links",
        "front center": "vorne Mitte",
        "front centre": "vorne Mitte",
        "front right": "vorne rechts",
    }
    return aliases.get(raw.casefold(), raw)


BED_POSITION_GRID = {
    "hinten links": (0, 0),
    "hinten Mitte": (0, 1),
    "hinten rechts": (0, 2),
    "Mitte links": (1, 0),
    "Mitte": (1, 1),
    "Mitte rechts": (1, 2),
    "vorne links": (2, 0),
    "vorne Mitte": (2, 1),
    "vorne rechts": (2, 2),
}

SEAM_BETWEEN_AXES = "zwischen X und Y (45°); X/Y nahtfrei"
SEAM_ALONG_Y = "entlang Y; X nahtfrei, Y über Naht"
SEAM_CUSTOM = "benutzerdefiniert / separat dokumentiert"
SEAM_STRATEGIES: Tuple[str, ...] = (SEAM_BETWEEN_AXES, SEAM_ALONG_Y, SEAM_CUSTOM)

ROLE_MAIN = "Hauptmerkmal"
ROLE_ADDITIONAL = "Zusatzmerkmal"
ROLE_BOUNDARY = "Grenzstrukturmerkmal"
ROLE_INDICATOR = "Plausibilitätsindikator"

GAP_WIDTHS: Tuple[int, ...] = (1, 2, 3, 4, 5, 10)
COMBINED_WEB_WIDTH_TEXTS: Tuple[str, ...] = ("0_4", "0_5", "0_6", "0_7", "0_8", "0_9", "1_0")
STANDALONE_WEB_WIDTH_TEXTS: Tuple[str, ...] = (
    "0_4", "0_5", "0_6", "0_7", "0_8", "0_9", "1_0", "1_1", "1_2"
)


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    label: str
    nominal: float | None
    unit: str = "mm"
    role: str = ROLE_MAIN
    capability: bool = True
    geometry_class: str = ""
    measurement_note: str = ""


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    label: str
    default_study_type: str
    features: Tuple[str, ...]
    target_n: int | None
    description: str


def _feature(
    key: str,
    label: str,
    nominal: float | None,
    *,
    role: str = ROLE_MAIN,
    capability: bool = True,
    geometry_class: str,
    measurement_note: str = "",
    unit: str = "mm",
) -> FeatureSpec:
    return FeatureSpec(
        key=key,
        label=label,
        nominal=nominal,
        unit=unit,
        role=role,
        capability=capability,
        geometry_class=geometry_class,
        measurement_note=measurement_note,
    )


FEATURES: Dict[str, FeatureSpec] = {
    "x_outer": _feature(
        "x_outer", "X-Außenmaß", 20.0,
        geometry_class="Lineares Außenmaß",
        measurement_note="Achsparalleles Zweipunktmaß in der mittleren Messzone.",
    ),
    "y_outer": _feature(
        "y_outer", "Y-Außenmaß", 20.0,
        geometry_class="Lineares Außenmaß",
        measurement_note="Achsparalleles Zweipunktmaß in der mittleren Messzone.",
    ),
    "z_height": _feature(
        "z_height", "Z-Höhe", 20.0,
        geometry_class="Höhenmaß",
        measurement_note="Messung zwischen den definierten parallelen Auflageflächen.",
    ),
    "diag_1": _feature(
        "diag_1", "45°-Maß 1", 20.0,
        geometry_class="Diagonales XY-Maß",
        measurement_note="Zweipunktmaß am ersten Paar gegenüberliegender Achteckflächen.",
    ),
    "diag_2": _feature(
        "diag_2", "45°-Maß 2", 20.0,
        geometry_class="Diagonales XY-Maß",
        measurement_note="Zweipunktmaß am zweiten Paar gegenüberliegender Achteckflächen.",
    ),
    "cylinder_x_free": _feature(
        "cylinder_x_free", "Zylinder außen, X nahtfrei", 20.0,
        geometry_class="Zylindrisches Außenmerkmal",
        measurement_note="Gerichtetes Zweipunktmaß in X-Richtung außerhalb des Z-Nahtbereichs.",
    ),
    "cylinder_y_free": _feature(
        "cylinder_y_free", "Zylinder außen, Y nahtfrei", 20.0,
        geometry_class="Zylindrisches Außenmerkmal",
        measurement_note=(
            "Gerichtetes Zweipunktmaß in Y-Richtung außerhalb des Z-Nahtbereichs. "
            "Voraussetzung ist eine Z-Naht zwischen den regulären X-/Y-Messrichtungen."
        ),
    ),
    "cylinder_seam_45": _feature(
        "cylinder_seam_45", "Zylinder außen, über Naht (45°)", 20.0,
        role=ROLE_ADDITIONAL,
        capability=False,
        geometry_class="Nahtbeeinflusstes Zylindermerkmal",
        measurement_note=(
            "Optionale zusätzliche Messrichtung durch den lokalen Z-Nahtbereich. "
            "Sie wird nur deskriptiv ausgewertet."
        ),
    ),
    # Abwärtskompatibilität zu den in der Bachelorarbeit bereits erfassten Reihen.
    "cylinder_y_seam": _feature(
        "cylinder_y_seam", "Zylinder außen, über Naht (Y)", 20.0,
        role=ROLE_ADDITIONAL,
        capability=False,
        geometry_class="Nahtbeeinflusstes Zylindermerkmal",
        measurement_note="Historische Messstrategie: gerichtetes Zweipunktmaß in Y-Richtung durch die Z-Naht; nur deskriptiv.",
    ),
    "mass_g": _feature(
        "mass_g", "Untersuchungsobjektmasse", None,
        unit="g",
        role=ROLE_INDICATOR,
        capability=False,
        geometry_class="Plausibilitätsindikator",
        measurement_note="Einmalige Wägung nach dem Abkühlen; kein geometrisches Fähigkeitsmerkmal.",
    ),
}


def _register_stack_features() -> None:
    for size in (10, 20, 30, 40):
        for axis in ("x", "y"):
            key = f"outer_{size}_{axis}"
            FEATURES[key] = _feature(
                key,
                f"Außenmaß {size} mm ({axis.upper()})",
                float(size),
                role=ROLE_ADDITIONAL,
                capability=True,
                geometry_class="Größenbezogenes lineares Außenmaßprofil",
                measurement_note="Zusatzprüfung am verbundenen Außenmaßstapel; vertikale Lage und Stapelgeometrie mitbeachten.",
            )
        for direction, label in (("free", "nahtfrei"), ("seam", "über Naht")):
            key = f"cylinder_{size}_{direction}"
            FEATURES[key] = _feature(
                key,
                f"Zylinder {size} mm ({label})",
                float(size),
                role=ROLE_ADDITIONAL,
                capability=(direction == "free"),
                geometry_class="Größenbezogenes Zylinderprofil",
                measurement_note=(
                    "Gerichtetes Zweipunktmaß am verbundenen Zylinderstapel."
                    if direction == "free"
                    else "Nahtbeeinflusstes gerichtetes Zweipunktmaß; nur deskriptiv."
                ),
            )

    for shape, shape_label in (("circle", "kreisförmig"), ("square", "quadratisch")):
        for size in (10, 15, 20):
            for axis in ("x", "y"):
                key = f"inner_{shape}_{size}_{axis}"
                FEATURES[key] = _feature(
                    key,
                    f"Innenkontur {shape_label} {size} mm ({axis.upper()})",
                    float(size),
                    role=ROLE_ADDITIONAL,
                    capability=True,
                    geometry_class=(
                        "Kreisförmige Innenkontur" if shape == "circle" else "Quadratische Innenkontur"
                    ),
                    measurement_note="Geometriespezifische Zusatzprüfung an der Referenzposition.",
                )

    for depth in range(1, 16):
        key = f"depth_{depth}"
        FEATURES[key] = _feature(
            key,
            f"Tiefe {depth} mm",
            float(depth),
            role=ROLE_ADDITIONAL,
            capability=True,
            geometry_class="Tiefenmerkmal",
            measurement_note="Tiefenmaß gegen gemeinsame Referenzfläche; verbundene Stufengeometrie.",
        )

    for gap in GAP_WIDTHS:
        for axis in ("x", "y"):
            key = f"gap_{gap}_{axis}"
            FEATURES[key] = _feature(
                key,
                f"Spalt {gap} mm ({axis.upper()})",
                float(gap),
                role=ROLE_ADDITIONAL,
                capability=False,
                geometry_class="Spaltmerkmal",
                measurement_note=(
                    "Geometriespezifisches Zusatzmerkmal des kombinierten Spalt-/Dünnwandobjekts; "
                    "keine reguläre Cₘ-/Cₘₖ-Bewertung."
                ),
            )

    # Dünnwandmerkmale des neuen kombinierten Untersuchungsobjekts. Sie werden in beiden
    # Richtungen geführt und bewusst von der historischen, eigenständigen Stegreihe getrennt.
    for width_text in COMBINED_WEB_WIDTH_TEXTS:
        width = float(width_text.replace("_", "."))
        for axis in ("x", "y"):
            key = f"combined_web_{width_text}_{axis}"
            FEATURES[key] = _feature(
                key,
                f"Dünnwand {width:.1f} mm ({axis.upper()})",
                width,
                role=ROLE_BOUNDARY,
                capability=False,
                geometry_class="Dünnwand-Grenzstruktur",
                measurement_note=(
                    "Richtungsbezogene Umsetzbarkeitsprüfung am kombinierten Spalt-/Dünnwandobjekt; "
                    "keine reguläre Cₘ-/Cₘₖ-Bewertung."
                ),
            )

    # Das eigenständige Dünnwanduntersuchungsobjekt bleibt vollständig erhalten.
    for width_text in STANDALONE_WEB_WIDTH_TEXTS:
        width = float(width_text.replace("_", "."))
        key = f"web_{width_text}"
        FEATURES[key] = _feature(
            key,
            f"Dünnwand {width:.1f} mm",
            width,
            role=ROLE_BOUNDARY,
            capability=False,
            geometry_class="Dünnwand-Grenzstruktur",
            measurement_note="Umsetzbarkeitsprüfung im Bereich diskreter Werkzeugpfadentscheidungen.",
        )


_register_stack_features()

REFERENCE_FEATURES_ALL = (
    "x_outer",
    "y_outer",
    "z_height",
    "diag_1",
    "diag_2",
    "cylinder_x_free",
    "cylinder_y_free",
    "cylinder_seam_45",
    "cylinder_y_seam",
    "mass_g",
)


def reference_features_for_settings(
    seam_position: str,
    measure_seam_separately: bool = False,
) -> Tuple[str, ...]:
    """Liefert die in der Eingabe sichtbaren Referenzmerkmale passend zur Nahtstrategie."""
    core = ["x_outer", "y_outer", "z_height", "diag_1", "diag_2", "cylinder_x_free"]
    if seam_position == SEAM_ALONG_Y:
        core.append("cylinder_y_seam")
    else:
        # Standard und benutzerdefinierte Position: beide regulären Richtungen nahtfrei erfassen.
        core.append("cylinder_y_free")
        if measure_seam_separately:
            core.append("cylinder_seam_45")
    core.append("mass_g")
    return tuple(core)


TEMPLATES: Dict[str, TemplateSpec] = {
    "reference": TemplateSpec(
        key="reference",
        label="Referenzuntersuchungsobjekt",
        default_study_type="Basisprüfung",
        features=REFERENCE_FEATURES_ALL,
        target_n=DEFAULT_BASIS_TARGET_N,
        description=(
            "Referenzuntersuchungsobjekt mit X-/Y-Außenmaß, Z-Höhe, zwei 45°-Maßen, "
            "zylindrischen Außenmerkmalen und Masse. Die sichtbaren Zylinderfelder "
            "werden an die gewählte Z-Naht-Strategie angepasst."
        ),
    ),
    "outer_stack": TemplateSpec(
        key="outer_stack",
        label="Außenmaßstapel",
        default_study_type="Geometriespezifische Zusatzprüfung",
        features=tuple(f"outer_{size}_{axis}" for size in (10, 20, 30, 40) for axis in ("x", "y")),
        target_n=10,
        description="Größenbezogenes Profil linearer Außenmaße; keine isolierte Skalierungsprüfung.",
    ),
    "cylinder_stack": TemplateSpec(
        key="cylinder_stack",
        label="Zylinderstapel",
        default_study_type="Geometriespezifische Zusatzprüfung",
        features=tuple(
            f"cylinder_{size}_{direction}"
            for size in (10, 20, 30, 40)
            for direction in ("free", "seam")
        ),
        target_n=10,
        description="Größenbezogenes Zylinderprofil mit nahtfreier und optional nahtbeeinflusster Messrichtung.",
    ),
    "inner_circle": TemplateSpec(
        key="inner_circle",
        label="Innenkonturuntersuchungsobjekt – Kreis",
        default_study_type="Geometriespezifische Zusatzprüfung",
        features=tuple(
            f"inner_circle_{size}_{axis}"
            for size in (10, 15, 20)
            for axis in ("x", "y")
        ),
        target_n=10,
        description=(
            "Kreisförmige Innenkonturen mit getrennten X- und Y-Messrichtungen. "
            "Die Kreisprüfung wird unabhängig von der quadratischen Innenkonturprüfung erfasst und ausgewertet."
        ),
    ),
    "inner_square": TemplateSpec(
        key="inner_square",
        label="Innenkonturuntersuchungsobjekt – Quadrat",
        default_study_type="Geometriespezifische Zusatzprüfung",
        features=tuple(
            f"inner_square_{size}_{axis}"
            for size in (10, 15, 20)
            for axis in ("x", "y")
        ),
        target_n=10,
        description=(
            "Quadratische Innenkonturen mit getrennten X- und Y-Messrichtungen. "
            "Die Quadratprüfung wird unabhängig von der kreisförmigen Innenkonturprüfung erfasst und ausgewertet."
        ),
    ),
    "depth_steps": TemplateSpec(
        key="depth_steps",
        label="Stufenuntersuchungsobjekt",
        default_study_type="Geometriespezifische Zusatzprüfung",
        features=tuple(f"depth_{depth}" for depth in range(1, 16)),
        target_n=10,
        description="Tiefenmerkmale gegen eine gemeinsame Referenzfläche.",
    ),
    "gaps": TemplateSpec(
        key="gaps",
        label="Spalt- und Dünnwanduntersuchungsobjekt",
        default_study_type="Geometriespezifische Zusatzprüfung",
        features=(
            tuple(f"gap_{gap}_{axis}" for gap in GAP_WIDTHS for axis in ("x", "y"))
            + tuple(
                f"combined_web_{width_text}_{axis}"
                for width_text in COMBINED_WEB_WIDTH_TEXTS
                for axis in ("x", "y")
            )
        ),
        target_n=10,
        description=(
            "Kombiniertes Untersuchungsobjekt mit Spalten von 1/2/3/4/5/10 mm und "
            "Dünnwänden von 0,4 bis 1,0 mm, jeweils getrennt in X- und Y-Richtung. "
            "Spalte sind Zusatzmerkmale; Dünnwände werden als Grenzstrukturen eingeordnet."
        ),
    ),
    "webs": TemplateSpec(
        key="webs",
        label="Dünnwanduntersuchungsobjekt",
        default_study_type="Geometriespezifische Zusatzprüfung",
        features=tuple(f"web_{x}" for x in STANDALONE_WEB_WIDTH_TEXTS),
        target_n=5,
        description=(
            "Eigenständiges Dünnwanduntersuchungsobjekt. "
            "Es bleibt für die dokumentierte Grenzstrukturreihe von 0,4 bis 1,2 mm erhalten."
        ),
    ),
}


def template_labels() -> Tuple[str, ...]:
    return tuple(spec.label for spec in TEMPLATES.values())


def template_key_from_label(label: str) -> str:
    for key, spec in TEMPLATES.items():
        if spec.label == label:
            return key
    # Abwärtskompatibilität zu Bezeichnungen aus früheren 1.5.0-Ständen.
    legacy_labels = {
        "Außenmaßstapel 10–40 mm": "outer_stack",
        "Zylinderstapel 10–40 mm": "cylinder_stack",
        "Innenkonturen": "inner_circle",
        "Innenkonturen 10/15/20 mm": "inner_circle",
        "Kreisförmige Innenkonturen": "inner_circle",
        "Quadratische Innenkonturen": "inner_square",
        "Stufenuntersuchungsobjekt 1–15 mm": "depth_steps",
        "Steguntersuchungsobjekt 0,4–1,2 mm (Bestand)": "webs",
    }
    return legacy_labels.get(label, "reference")


def all_feature_keys() -> Iterable[str]:
    return FEATURES.keys()
