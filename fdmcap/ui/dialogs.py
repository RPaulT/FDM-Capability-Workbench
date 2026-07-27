"""Eingabe-, Hilfe- und Einstellungsdialoge der Tkinter-Oberfläche."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Mapping

from ..config import (
    BED_POSITIONS,
    FEATURES,
    SEAM_STRATEGIES,
    STUDY_TYPES,
    TEMPLATES,
    reference_features_for_settings,
    template_key_from_label,
)
from ..models import MeasurementRecord, ProjectSettings


def _parse_float(text: str, field_label: str) -> float | None:
    value = text.strip()
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"'{field_label}' enthält keinen gültigen Zahlenwert.") from exc


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *, height=520, width=820):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, width=width, height=height)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas, padding=(8, 4, 14, 8))
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.content.bind("<Configure>", self._update_region)
        self.canvas.bind("<Configure>", self._resize_content)
        self.canvas.bind_all("<MouseWheel>", self._mousewheel)

    def _update_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_content(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def _mousewheel(self, event):
        if self.winfo_ismapped():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class MeasurementDialog(tk.Toplevel):
    """Vorlagenabhängige Eingabe einer oder mehrerer Messzeilen."""

    def __init__(
        self,
        parent,
        *,
        record: MeasurementRecord | None = None,
        defaults: Mapping[str, str] | None = None,
        settings: ProjectSettings | None = None,
    ):
        super().__init__(parent)
        self.title("Messung bearbeiten" if record else "Messung hinzufügen")
        self.geometry("940x760")
        self.minsize(820, 620)
        self.transient(parent)
        self.grab_set()
        self.result: MeasurementRecord | None = None
        self.saved_records: list[MeasurementRecord] = []
        self.record = record
        self.settings = settings or ProjectSettings()
        defaults = dict(defaults or {})

        template_key = record.template_key if record else defaults.get("template_key", "reference")
        template = TEMPLATES.get(template_key, TEMPLATES["reference"])
        self.template_label_var = tk.StringVar(value=template.label)
        self.study_type_var = tk.StringVar(value=record.study_type if record else defaults.get("study_type", template.default_study_type))
        self.configuration_var = tk.StringVar(value=record.configuration if record else defaults.get("configuration", ""))
        self.material_var = tk.StringVar(value=record.material if record else defaults.get("material", "PLA"))
        self.batch_var = tk.StringVar(value=record.batch if record else defaults.get("batch", "1"))
        self.position_var = tk.StringVar(value=record.bed_position if record else defaults.get("bed_position", "Mitte"))
        self.specimen_var = tk.StringVar(value=record.specimen_id if record else defaults.get("specimen_id", "1"))
        self.note_var = tk.StringVar(value=record.note if record else "")
        self.value_vars: dict[str, tk.StringVar] = {}

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text="Messzeile erfassen",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Zuerst die Zuordnung festlegen, anschließend die zugehörigen Messwerte eintragen. "
                "Mit 'Speichern & weiter' wird die aktuelle Zeile übernommen und das Formular für die nächste Untersuchungsobjekt-Nr. vorbereitet."
            ),
            foreground="#555",
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(2, 10))

        self.scroll = ScrollableFrame(outer, height=600, width=900)
        self.scroll.pack(fill="both", expand=True)
        self.content = self.scroll.content
        self.content.columnconfigure(0, weight=1)

        assignment = ttk.LabelFrame(self.content, text="Zuordnung", padding=10)
        assignment.grid(row=0, column=0, sticky="ew")
        for col in range(3):
            assignment.columnconfigure(col, weight=1, uniform="assign")
        self._combo(assignment, 0, 0, "Untersuchungsobjekt", self.template_label_var, [t.label for t in TEMPLATES.values()], self._template_changed)
        self._combo(assignment, 0, 1, "Prüfstufe", self.study_type_var, STUDY_TYPES)
        self._entry(assignment, 0, 2, "Konfiguration / Profil", self.configuration_var)
        self._entry(assignment, 2, 0, "Material", self.material_var)
        self._entry(assignment, 2, 1, "Batch", self.batch_var)
        self._combo(assignment, 2, 2, "Druckbettposition", self.position_var, BED_POSITIONS)
        self._entry(assignment, 4, 0, "Untersuchungsobjekt-Nr.", self.specimen_var)
        self._entry(assignment, 4, 1, "Notiz", self.note_var, colspan=2)

        value_box = ttk.LabelFrame(self.content, text="Messwerte", padding=10)
        value_box.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        value_box.columnconfigure(0, weight=1)
        self.feature_frame = ttk.Frame(value_box)
        self.feature_frame.grid(row=0, column=0, sticky="ew")
        self.feature_frame.columnconfigure((0, 1, 2), weight=1, uniform="features")
        self.description_var = tk.StringVar()
        ttk.Label(
            value_box,
            textvariable=self.description_var,
            foreground="#555",
            wraplength=840,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(10, 0))
        self._build_feature_fields(template_key)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).pack(side="right")
        if record is None:
            ttk.Button(buttons, text="Speichern & schließen", command=self._save_and_close).pack(side="right", padx=(0, 8))
            ttk.Button(buttons, text="Speichern & weiter", command=self._save_and_continue).pack(side="right", padx=(0, 8))
        else:
            ttk.Button(buttons, text="Speichern & schließen", command=self._save_and_close).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._save_and_close())

    def _entry(self, parent, row, column, label, variable, *, colspan=1):
        ttk.Label(parent, text=label).grid(row=row, column=column, columnspan=colspan, sticky="w", padx=(0, 10))
        ttk.Entry(parent, textvariable=variable).grid(row=row + 1, column=column, columnspan=colspan, sticky="ew", padx=(0, 12), pady=(2, 7))

    def _combo(self, parent, row, column, label, variable, values, callback=None):
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 10))
        combo = ttk.Combobox(parent, textvariable=variable, values=list(values), state="readonly")
        combo.grid(row=row + 1, column=column, sticky="ew", padx=(0, 12), pady=(2, 7))
        if callback:
            combo.bind("<<ComboboxSelected>>", callback)

    def _template_changed(self, _event=None):
        key = template_key_from_label(self.template_label_var.get())
        template = TEMPLATES[key]
        self.study_type_var.set(template.default_study_type)
        self._build_feature_fields(key)

    def _build_feature_fields(self, template_key: str):
        old_values = {key: var.get() for key, var in self.value_vars.items()}
        if self.record:
            old_values.update({key: str(value).replace(".", ",") for key, value in self.record.values.items()})
        for child in self.feature_frame.winfo_children():
            child.destroy()
        self.value_vars = {}
        template = TEMPLATES.get(template_key, TEMPLATES["reference"])
        self.description_var.set(template.description)
        feature_keys = template.features
        if template_key == "reference":
            feature_keys = reference_features_for_settings(
                self.settings.seam_position,
                self.settings.measure_seam_separately,
            )
        for index, feature_key in enumerate(feature_keys):
            spec = FEATURES[feature_key]
            row = (index // 3) * 2
            col = index % 3
            label = spec.label + (" *" if spec.capability else "")
            ttk.Label(self.feature_frame, text=label).grid(row=row, column=col, sticky="w", padx=(0, 10), pady=(1, 0))
            var = tk.StringVar(value=old_values.get(feature_key, ""))
            self.value_vars[feature_key] = var
            ttk.Entry(self.feature_frame, textvariable=var).grid(row=row + 1, column=col, sticky="ew", padx=(0, 12), pady=(2, 6))
        self.scroll._update_region()

    def _collect_record(self) -> MeasurementRecord:
        specimen = self.specimen_var.get().strip()
        if not specimen:
            raise ValueError("Die Untersuchungsobjekt-Nr. fehlt.")
        values = {}
        for key, var in self.value_vars.items():
            parsed = _parse_float(var.get(), FEATURES[key].label)
            if parsed is not None:
                values[key] = parsed
        if not values:
            raise ValueError("Mindestens ein Messwert muss eingegeben werden.")
        template_key = template_key_from_label(self.template_label_var.get())
        return MeasurementRecord(
            record_id=self.record.record_id if self.record else MeasurementRecord().record_id,
            study_type=self.study_type_var.get().strip(),
            template_key=template_key,
            configuration=self.configuration_var.get().strip(),
            material=self.material_var.get().strip(),
            batch=self.batch_var.get().strip(),
            bed_position=self.position_var.get().strip(),
            specimen_id=specimen,
            values=values,
            note=self.note_var.get().strip(),
        )

    def _increment_specimen_id(self):
        raw = self.specimen_var.get().strip()
        try:
            self.specimen_var.set(str(int(raw) + 1))
        except ValueError:
            self.specimen_var.set(raw)

    def _clear_measurement_values(self):
        for var in self.value_vars.values():
            var.set("")

    def _save_and_continue(self):
        try:
            record = self._collect_record()
        except ValueError as exc:
            messagebox.showerror("Eingabefehler", str(exc), parent=self)
            return
        self.saved_records.append(record)
        self._increment_specimen_id()
        self._clear_measurement_values()
        first_entry = next(iter(self.value_vars.values()), None)
        if first_entry is not None:
            self.after(10, lambda: self.focus_force())
        self.description_var.set(self.description_var.get() + "")

    def _save_and_close(self):
        try:
            record = self._collect_record()
        except ValueError as exc:
            messagebox.showerror("Eingabefehler", str(exc), parent=self)
            return
        if self.record is None:
            self.saved_records.append(record)
            self.result = None
        else:
            self.result = record
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, settings: ProjectSettings):
        super().__init__(parent)
        self.title("Projekteinstellungen")
        self.geometry("700x710")
        self.minsize(600, 540)
        self.transient(parent)
        self.grab_set()
        self.result: ProjectSettings | None = None
        self._original = settings
        self.vars = {
            key: tk.StringVar(value=str(value))
            for key, value in settings.to_dict().items()
            if key != "measure_seam_separately"
        }
        self.vars["confidence_level"].set(f"{settings.confidence_level * 100:g}")
        self.measure_seam_var = tk.BooleanVar(value=bool(settings.measure_seam_separately))

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        scroll = ScrollableFrame(outer, height=585, width=660)
        scroll.pack(fill="both", expand=True)
        content = scroll.content
        content.columnconfigure(1, weight=1)

        row = 0

        def heading(title):
            nonlocal row
            ttk.Label(content, text=title, font=("Segoe UI", 12, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(8 if row else 0, 7)
            )
            row += 1

        def entry(key, label):
            nonlocal row
            ttk.Label(content, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            ttk.Entry(content, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=3)
            row += 1

        heading("Projekt und Messsystem")
        for key, label in (
            ("project_name", "Projektname"), ("printer", "Drucker"), ("nozzle_diameter_mm", "Düse [mm]"),
            ("slicer", "Slicer"), ("slicer_profile", "Slicerprofil"), ("measurement_tool", "Messmittel"),
            ("operator", "Prüfperson"),
        ):
            entry(key, label)

        heading("Bewertungslogik")
        for key, label in (
            ("resolution_mm", "Ableseschritt Maßmessung r [mm]"),
            ("mass_resolution_g", "Ableseschritt Waage [g]"),
            ("tolerance_half_width_mm", "Halbe Bewertungsbreite [mm]"),
            ("capability_orientation", "Orientierungsgrenze Cₘ/Cₘₖ"),
            ("alpha", "Signifikanzniveau α (Normalitätstests)"),
            ("confidence_level", "Konfidenzniveau [%]"),
            ("bootstrap_repetitions", "Bootstrap-Wiederholungen B"),
            ("bootstrap_seed", "Zufallsstartwert"),
        ):
            entry(key, label)

        heading("Standardisierte Randbedingungen")
        entry("preheat_minutes", "Bettvorwärmung [min]")
        entry("cooling_hours", "Abkühlzeit [h]")
        ttk.Label(content, text="Z-Naht-Strategie").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        seam_combo = ttk.Combobox(
            content,
            textvariable=self.vars["seam_position"],
            values=SEAM_STRATEGIES,
            state="readonly",
        )
        seam_combo.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1
        ttk.Label(content, text="Naht zusätzlich messen").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        ttk.Checkbutton(
            content,
            text="Separate 45°-Messrichtung durch die Naht in der Referenzeingabe anzeigen",
            variable=self.measure_seam_var,
        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1
        entry("filament_state", "Filament / Rolle / Lagerzustand")
        entry("notes", "Weitere Hinweise")

        ttk.Label(
            content,
            text=(
                "Empfehlung für neue Versuche: Z-Naht zwischen X und Y positionieren. Dann können beide regulären "
                "Zylinderdurchmesser nahtfrei erfasst werden. Eine separate Nahtmessung ist optional und nur deskriptiv."
            ),
            foreground="#555",
            wraplength=620,
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 4))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Speichern", command=self._save).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())

    def _save(self):
        try:
            data = {key: var.get().strip() for key, var in self.vars.items()}
            data["measure_seam_separately"] = bool(self.measure_seam_var.get())
            for key in ("resolution_mm", "mass_resolution_g", "tolerance_half_width_mm", "capability_orientation", "alpha"):
                data[key] = float(data[key].replace(",", "."))
            data["confidence_level"] = float(data["confidence_level"].replace(",", ".")) / 100.0
            for key in ("bootstrap_repetitions", "bootstrap_seed", "preheat_minutes", "cooling_hours"):
                data[key] = int(data[key])
            if data["resolution_mm"] <= 0 or data["mass_resolution_g"] <= 0 or data["tolerance_half_width_mm"] <= 0:
                raise ValueError("Ableseschritte und Bewertungsbreite müssen positiv sein.")
            if not 0 < data["alpha"] < 1:
                raise ValueError("α muss zwischen 0 und 1 liegen.")
            if not 0 < data["confidence_level"] < 1:
                raise ValueError("Das Konfidenzniveau muss zwischen 0 und 100 % liegen, z. B. 95.")
            if data["bootstrap_repetitions"] < 1:
                raise ValueError("B muss mindestens 1 betragen.")
            if data["seam_position"] not in SEAM_STRATEGIES:
                raise ValueError("Bitte eine gültige Z-Naht-Strategie auswählen.")
        except ValueError as exc:
            messagebox.showerror("Eingabefehler", str(exc), parent=self)
            return
        self.result = ProjectSettings.from_dict(data)
        self.destroy()


class MethodWindow(tk.Toplevel):
    def __init__(self, parent, settings: ProjectSettings):
        super().__init__(parent)
        self.title("Prüfablauf und Messstrategie")
        self.geometry("840x640")
        self.transient(parent)
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        text = tk.Text(outer, wrap="word", padx=12, pady=12, font=("Segoe UI", 10))
        scroll = ttk.Scrollbar(outer, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        if settings.seam_position == "entlang Y; X nahtfrei, Y über Naht":
            cylinder_sequence = "Zylinder X nahtfrei, Zylinder Y über Naht (nur deskriptiv)"
        else:
            cylinder_sequence = "Zylinder X nahtfrei, Zylinder Y nahtfrei"
            if settings.measure_seam_separately:
                cylinder_sequence += ", zusätzliche 45°-Messung über Naht (nur deskriptiv)"
        content = f"""MODULARER PRÜFABLAUF

1. Basisprüfung
Referenzprüfkörper an der festgelegten Referenzposition. Arbeitsinterner Zielumfang: n = 25 je dokumentierter Drucker-Prozess-Konfiguration.

2. Bauraumprüfung
Derselbe Referenzprüfkörper auf dem festgelegten 3×3-Raster. Die globale Streuung enthält Positions-, Batch- und kurzfristige Wiederholanteile und ist nicht direkt mit der Basisprüfung gleichzusetzen.

3. Geometriespezifische Zusatzprüfung
Außenmaß- und Zylinderstapel, Innenkonturen, Tiefen, Spalte und Dünnwände werden getrennt bewertet. Zusatz- und Grenzstrukturmerkmale dürfen nicht pauschal auf andere Geometrien übertragen werden.

4. Wiederholung nach wesentlichen Änderungen
Nach Änderungen an Material, Filamentrolle, Düse, Slicerprofil oder anderen wesentlichen Bestandteilen der Konfiguration empfiehlt sich aus Übersichtsgründen ein neues Projekt mit mindestens einer erneuten Basisprüfung. Die frühere Prüfstufe \"Neubewertung\" wird daher nicht mehr aktiv vorgeschlagen.

STANDARDISIERTE RANDBEDINGUNGEN
• Druckbettvorwärmung: {settings.preheat_minutes} min ab Einschalten der Bettbeheizung
• Messung nach mindestens {settings.cooling_hours} h bei Raumtemperatur
• Ableseschritt: {settings.resolution_mm:.3f} mm
• Z-Naht: {settings.seam_position}
• Materialart, Hersteller, Produkt, Farbe, Filamentrolle und Lagerzustand innerhalb einer Serie konstant halten
• Messreihenfolge am Referenzprüfkörper: X, Y, Z, 45°-Maß 1, 45°-Maß 2, {cylinder_sequence}; anschließend einmalige Wägung

BEWERTUNGSREGELN
• Cₘ/Cₘₖ nur bei s > 0
• s = 0 bedeutet: Streuung mit dem Messmittel nicht weiter auflösbar
• Orientierungsgrenze: {settings.capability_orientation:.2f}
• Konfidenzniveau: {settings.confidence_level * 100:.0f} %; Konfidenzintervalle werden ergänzend, aber nicht als eigener Fähigkeitsindex verwendet
• Bewertungsbereich: Nennmaß ± {settings.tolerance_half_width_mm:.2f} mm
• kᵣ = s/r dient nur als deskriptive Interpretationshilfe
• Bootstrap nur bei positiver Streuung und mindestens drei Ablesestufen
• Kein einzelner Gesamtwert beschreibt die Fähigkeit des gesamten Druckers
"""
        text.insert("1.0", content)
        text.configure(state="disabled")


class HelpWindow(tk.Toplevel):
    """Kompakte, allgemein verständliche Bedienhilfe zum Programm."""

    def __init__(self, parent, settings: ProjectSettings):
        super().__init__(parent)
        self.title("Programmhilfe")
        self.geometry("900x680")
        self.minsize(720, 540)
        self.transient(parent)

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="FDM-Capability-Workbench – Programmhilfe", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Diese kurze Anleitung beschreibt den üblichen Arbeitsablauf vom Anlegen eines Projekts bis zur Auswertung.",
            foreground="#555",
            wraplength=850,
            justify="left",
        ).pack(anchor="w", pady=(3, 10))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        text = tk.Text(body, wrap="word", padx=14, pady=14, font=("Segoe UI", 10))
        scroll = ttk.Scrollbar(body, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        content = f"""1. Projekt vorbereiten

Lege für jede klar abgegrenzte Drucker-Prozess-Konfiguration ein eigenes Projekt an. Dazu gehören beispielsweise der Drucker, die Düse, das Material, das Slicerprofil und der dokumentierte Filamentzustand. Die grundlegenden Angaben und Bewertungsparameter werden über „Projekteinstellungen“ in der oberen Menüleiste hinterlegt.

Nach wesentlichen Änderungen – etwa einer anderen Düse, einem neuen Material oder einem deutlich veränderten Slicerprofil – ist ein neues Projekt in der Regel übersichtlicher als das Vermischen alter und neuer Messreihen.

2. Untersuchungsobjekte auswählen

Über „Untersuchungsobjekte“ in der oberen Menüleiste öffnest du die Bibliothek der im Verfahren vorgesehenen Untersuchungsobjekte. Dort findest du den jeweiligen Zweck, die enthaltenen Merkmale und die im Programm verfügbaren STL- beziehungsweise STEP-Dateien. Die Dateien können anschließend für den Slicer oder zur weiteren CAD-Bearbeitung verwendet werden.

3. Messwerte erfassen

Mit „Messung hinzufügen“ öffnest du das Eingabefenster. Wähle zuerst das Untersuchungsobjekt sowie Prüfstufe, Konfiguration, Material, Batch und Druckbettposition aus. Danach trägst du die tatsächlich gemessenen Werte in die dafür vorgesehenen Felder ein. Nicht gemessene Merkmale können leer bleiben.

Für eine fortlaufende Messserie eignet sich „Speichern & weiter“. Die aktuelle Messzeile wird übernommen, die Untersuchungsobjekt-Nr. wird automatisch um eins erhöht und die Messwertfelder werden geleert. Alle Zuordnungsangaben bleiben erhalten. Mit „Speichern & schließen“ wird die aktuelle Messung gespeichert und das Fenster geschlossen.

4. Messdaten verwalten

Im Hauptfenster kannst du Messzeilen filtern, auswählen, bearbeiten oder löschen. Rechts werden die vollständigen Angaben und Messwerte der ausgewählten Zeile angezeigt. Über den CSV-Import und -Export lassen sich Messdaten außerdem mit Tabellenprogrammen austauschen.

5. Auswertung öffnen

Die Schaltfläche „Auswerten“ öffnet die merkmalbezogene Auswertung. Dort wird der gewünschte Prüfumfang über Prüfstufe, Untersuchungsobjekt, Material, Konfiguration und – bei der Bauraumprüfung – über Ansicht, Position oder Batch festgelegt. Die Registerkarten führen anschließend von der kompakten Interpretation über die Kennwerte bis zu Verteilungsdiagnostik, Gruppenvergleich und Diagrammen.

6. Bericht erstellen

Über „Bericht zusammenstellen“ wählst du gezielt aus, welche Inhalte exportiert werden sollen. So kann der Bericht auf den jeweiligen Zweck zugeschnitten werden, ohne alle verfügbaren Tabellen und Diagnoseinformationen übernehmen zu müssen.

Aktuelle Projekteinstellungen

• Ableseschritt der Maßmessung: {settings.resolution_mm:.3f} mm
• Bewertungsbereich: Nennmaß ± {settings.tolerance_half_width_mm:.2f} mm
• Orientierungsgrenze für Cₘ und Cₘₖ: {settings.capability_orientation:.2f}
• Konfidenzniveau: {settings.confidence_level * 100:.0f} %

"""
        text.insert("1.0", content)
        text.configure(state="disabled")

        ttk.Button(outer, text="Schließen", command=self.destroy).pack(anchor="e", pady=(10, 0))
