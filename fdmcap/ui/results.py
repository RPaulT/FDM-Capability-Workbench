"""Ergebnisoberfläche."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Sequence

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from ..analysis import (
    analyze_records,
    distribution_analysis,
    feature_interpretation_text,
    feature_spec,
    group_comparison_rows,
    prioritized_findings,
    scope_summary_text,
)
from ..config import APP_TITLE, BED_POSITIONS, STUDY_TYPES, TEMPLATES
from ..io import save_analysis_csv
from ..models import CapabilityResult, DistributionResult, MeasurementRecord, ProjectData
from ..plotting import build_figure, capability_confidence_figure, distribution_diagnostics_figure
from ..reports import save_html_report, save_pdf_report, save_text_report
from ..spatial import analyze_spatial_feature, spatial_summary_text
from .report_dialog import ReportExportDialog


def _fmt(value: float | None, digits=3) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}".replace(".", ",")


def _fmt_p(value: float | None) -> str:
    if value is None:
        return "–"
    if value < 0.0001:
        return "< 0,0001"
    if value < 0.001:
        return "< 0,001"
    return _fmt(value, 4)


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


def _set_text(widget: tk.Text, text: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.configure(state="disabled")


class ResultWindow(tk.Toplevel):
    def __init__(self, parent, project: ProjectData):
        super().__init__(parent)
        self.title(f"{APP_TITLE} – Auswertung")
        self.geometry("1440x900")
        self.minsize(1120, 700)
        self.project = project
        self.base_groups = self._build_base_groups(project.records)
        self.distribution_cache: dict[tuple[str, str], DistributionResult] = {}
        self._selector_updating = False
        self.current_results: list[CapabilityResult] = []
        self.chart_canvas: FigureCanvasTkAgg | None = None
        self.distribution_canvas: FigureCanvasTkAgg | None = None
        self.confidence_canvas: FigureCanvasTkAgg | None = None
        self._bootstrap_running = False
        self._finding_details: dict[str, tuple[str, str, str, str]] = {}

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Merkmalbezogene Fähigkeitsauswertung", font=("Segoe UI", 19, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Interpretation, Fähigkeitskennwerte, Verteilungsdiagnostik und Gruppenvergleich",
            foreground="#555",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        selection = ttk.LabelFrame(outer, text="Auswertungsumfang", padding=8)
        selection.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        for column in range(4):
            selection.columnconfigure(column, weight=1, uniform="scope")

        self.study_var = tk.StringVar()
        self.template_var = tk.StringVar()
        self.material_var = tk.StringVar()
        self.configuration_var = tk.StringVar()
        self.analysis_mode_var = tk.StringVar()
        self.position_var = tk.StringVar()
        self.batch_var = tk.StringVar()
        self.scope_var = tk.StringVar()  # stabiler Schlüssel für Bootstrap-Cache

        ttk.Label(selection, text="Prüfstufe").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(selection, text="Untersuchungsobjekt").grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Label(selection, text="Material").grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Label(selection, text="Konfiguration").grid(row=0, column=3, sticky="w", padx=(0, 8))
        self.study_combo = ttk.Combobox(selection, textvariable=self.study_var, state="readonly")
        self.study_combo.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.template_combo = ttk.Combobox(selection, textvariable=self.template_var, state="readonly")
        self.template_combo.grid(row=1, column=1, sticky="ew", padx=(0, 10))
        self.material_combo = ttk.Combobox(selection, textvariable=self.material_var, state="readonly")
        self.material_combo.grid(row=1, column=2, sticky="ew", padx=(0, 10))
        self.configuration_combo = ttk.Combobox(selection, textvariable=self.configuration_var, state="readonly")
        self.configuration_combo.grid(row=1, column=3, sticky="ew")

        ttk.Label(selection, text="Ansicht").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Label(selection, text="Position").grid(row=2, column=1, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Label(selection, text="Batch").grid(row=2, column=2, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Label(selection, text="Bericht").grid(row=2, column=3, sticky="w", padx=(0, 8), pady=(8, 0))
        self.analysis_mode_combo = ttk.Combobox(selection, textvariable=self.analysis_mode_var, state="readonly")
        self.analysis_mode_combo.grid(row=3, column=0, sticky="ew", padx=(0, 10), pady=(2, 0))
        self.position_combo = ttk.Combobox(selection, textvariable=self.position_var, state="readonly")
        self.position_combo.grid(row=3, column=1, sticky="ew", padx=(0, 10), pady=(2, 0))
        self.batch_combo = ttk.Combobox(selection, textvariable=self.batch_var, state="readonly")
        self.batch_combo.grid(row=3, column=2, sticky="ew", padx=(0, 10), pady=(2, 0))
        ttk.Button(selection, text="Bericht zusammenstellen…", command=self.export_report).grid(row=3, column=3, sticky="ew", pady=(2, 0))

        self.selector_note_var = tk.StringVar()
        ttk.Label(selection, textvariable=self.selector_note_var, foreground="#555", wraplength=1320, justify="left").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )
        self.study_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_selector_changed("study"))
        self.template_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_selector_changed("template"))
        self.material_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_selector_changed("material"))
        self.configuration_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_selector_changed("configuration"))
        self.analysis_mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_selector_changed("mode"))
        self.position_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_selector_changed("position"))
        self.batch_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_selector_changed("batch"))
        self._initialize_scope_selectors()

        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=2, column=0, sticky="nsew")

        self.interpretation_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.interpretation_tab, text="Interpretation")
        self._build_interpretation_tab()

        self.overview_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.overview_tab, text="Kernkennwerte")
        self._build_overview_tab()

        self.confidence_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.confidence_tab, text="Konfidenzintervalle")
        self._build_confidence_tab()

        self.ppm_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.ppm_tab, text="ppm / Grenzanteile")
        self._build_ppm_tab()

        self.distribution_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.distribution_tab, text="Verteilungsdiagnostik")
        self._build_distribution_tab()

        self.comparison_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.comparison_tab, text="Gruppenvergleich")
        self._build_comparison_tab()

        self.spatial_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.spatial_tab, text="Bauraumdiagnose")
        self._build_spatial_tab()

        self.chart_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.chart_tab, text="Diagramm")
        self._build_chart_tab()

        self.refresh()

    def _build_base_groups(self, records: Sequence[MeasurementRecord]) -> dict[tuple[str, str, str, str], list[MeasurementRecord]]:
        grouped: dict[tuple[str, str, str, str], list[MeasurementRecord]] = defaultdict(list)
        for record in records:
            key = (record.study_type, record.template_key, record.material, record.configuration)
            grouped[key].append(record)
        return dict(sorted(grouped.items(), key=lambda item: tuple(str(x) for x in item[0])))

    def _template_label(self, key: str) -> str:
        template = TEMPLATES.get(key)
        return template.label if template else key

    def _selected_base_key(self) -> tuple[str, str, str, str] | None:
        for key in self.base_groups:
            study, template_key, material, configuration = key
            if (
                study == self.study_var.get()
                and self._template_label(template_key) == self.template_var.get()
                and (material or "nicht angegeben") == self.material_var.get()
                and (configuration or "nicht angegeben") == self.configuration_var.get()
            ):
                return key
        return None

    def _matching_keys(self, *, study=None, template_label=None, material_label=None):
        keys = list(self.base_groups)
        if study is not None:
            keys = [key for key in keys if key[0] == study]
        if template_label is not None:
            keys = [key for key in keys if self._template_label(key[1]) == template_label]
        if material_label is not None:
            keys = [key for key in keys if (key[2] or "nicht angegeben") == material_label]
        return keys

    def _initialize_scope_selectors(self):
        self._selector_updating = True
        studies = [study for study in STUDY_TYPES if any(key[0] == study for key in self.base_groups)]
        studies.extend(sorted({key[0] for key in self.base_groups if key[0] not in studies}))
        self.study_combo.configure(values=studies)
        self.study_var.set(studies[0] if studies else "")
        self._sync_scope_selectors("study")
        self._selector_updating = False

    def _sync_scope_selectors(self, changed: str):
        study = self.study_var.get()
        keys = self._matching_keys(study=study)
        templates = sorted({self._template_label(key[1]) for key in keys})
        self.template_combo.configure(values=templates)
        if self.template_var.get() not in templates:
            self.template_var.set(templates[0] if templates else "")

        keys = self._matching_keys(study=study, template_label=self.template_var.get())
        materials = sorted({key[2] or "nicht angegeben" for key in keys})
        self.material_combo.configure(values=materials)
        if self.material_var.get() not in materials:
            self.material_var.set(materials[0] if materials else "")

        keys = self._matching_keys(
            study=study, template_label=self.template_var.get(), material_label=self.material_var.get()
        )
        configurations = sorted({key[3] or "nicht angegeben" for key in keys})
        self.configuration_combo.configure(values=configurations)
        if self.configuration_var.get() not in configurations:
            self.configuration_var.set(configurations[0] if configurations else "")

        base = self.base_records()
        if study == "Bauraumprüfung":
            modes = (
                "Gesamter Bauraum – alle Positionen und Batches",
                "Einzelposition",
                "Einzelbatch",
            )
        else:
            modes = ("Gesamter Datensatz",)
        self.analysis_mode_combo.configure(values=modes)
        if self.analysis_mode_var.get() not in modes:
            self.analysis_mode_var.set(modes[0])

        positions = [position for position in BED_POSITIONS if any(r.bed_position == position for r in base)]
        positions.extend(sorted({r.bed_position for r in base if r.bed_position not in positions}))
        self.position_combo.configure(values=positions)
        if self.position_var.get() not in positions:
            self.position_var.set(positions[0] if positions else "")

        batches = sorted({str(r.batch) for r in base}, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x))
        self.batch_combo.configure(values=batches)
        if self.batch_var.get() not in batches:
            self.batch_var.set(batches[0] if batches else "")

        mode = self.analysis_mode_var.get()
        self.position_combo.configure(state="readonly" if mode == "Einzelposition" else "disabled")
        self.batch_combo.configure(state="readonly" if mode == "Einzelbatch" else "disabled")
        self._update_scope_cache_key()

    def _on_selector_changed(self, changed: str):
        if self._selector_updating:
            return
        self._selector_updating = True
        self._sync_scope_selectors(changed)
        self._selector_updating = False
        self.refresh()

    def _update_scope_cache_key(self):
        base_key = self._selected_base_key()
        mode = self.analysis_mode_var.get()
        detail = self.position_var.get() if mode == "Einzelposition" else self.batch_var.get() if mode == "Einzelbatch" else "alle"
        self.scope_var.set(repr((base_key, mode, detail)))

    def base_records(self) -> list[MeasurementRecord]:
        key = self._selected_base_key()
        return list(self.base_groups.get(key, [])) if key is not None else []

    def current_records(self) -> list[MeasurementRecord]:
        records = self.base_records()
        mode = self.analysis_mode_var.get()
        if mode == "Einzelposition":
            records = [record for record in records if record.bed_position == self.position_var.get()]
        elif mode == "Einzelbatch":
            records = [record for record in records if str(record.batch) == self.batch_var.get()]
        return records

    def is_bed_study(self) -> bool:
        return self.study_var.get() == "Bauraumprüfung"

    def _build_interpretation_tab(self):
        self.interpretation_tab.columnconfigure(0, weight=1)
        self.interpretation_tab.rowconfigure(4, weight=1)

        summary_frame = ttk.LabelFrame(self.interpretation_tab, text="Kurzbewertung des gewählten Prüfumfangs", padding=8)
        summary_frame.grid(row=0, column=0, sticky="ew")
        summary_frame.columnconfigure(0, weight=1)
        self.summary_text = tk.Text(summary_frame, wrap="word", height=7, padx=8, pady=8, font=("Segoe UI", 10))
        self.summary_text.grid(row=0, column=0, sticky="ew")

        findings_frame = ttk.LabelFrame(self.interpretation_tab, text="Priorisierte Befunde", padding=8)
        findings_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        findings_frame.columnconfigure(0, weight=1)
        columns = ("level", "area", "finding")
        self.findings_tree = ttk.Treeview(findings_frame, columns=columns, show="headings", height=6)
        headings = {"level": "Stufe", "area": "Bereich", "finding": "Befund"}
        widths = {"level": 90, "area": 230, "finding": 900}
        for col in columns:
            self.findings_tree.heading(col, text=headings[col])
            self.findings_tree.column(col, width=widths[col], minwidth=70, stretch=(col == "finding"))
        ybar = ttk.Scrollbar(findings_frame, orient="vertical", command=self.findings_tree.yview)
        self.findings_tree.configure(yscrollcommand=ybar.set)
        self.findings_tree.grid(row=0, column=0, sticky="ew")
        ybar.grid(row=0, column=1, sticky="ns")
        self.findings_tree.bind("<<TreeviewSelect>>", self._show_finding_detail)

        finding_detail_frame = ttk.LabelFrame(
            self.interpretation_tab,
            text="Ausgewählter Befund und empfohlener nächster Schritt",
            padding=8,
        )
        finding_detail_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        finding_detail_frame.columnconfigure(0, weight=1)
        self.finding_detail_text = tk.Text(
            finding_detail_frame,
            wrap="word",
            height=5,
            padx=8,
            pady=8,
            font=("Segoe UI", 10),
        )
        self.finding_detail_text.grid(row=0, column=0, sticky="ew")
        self.finding_detail_text.configure(state="disabled")

        feature_controls = ttk.Frame(self.interpretation_tab)
        feature_controls.grid(row=3, column=0, sticky="ew", pady=(10, 6))
        feature_controls.columnconfigure(1, weight=1)
        ttk.Label(feature_controls, text="Merkmaldetail:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.interpret_feature_var = tk.StringVar()
        self.interpret_feature_combo = ttk.Combobox(feature_controls, textvariable=self.interpret_feature_var, state="readonly")
        self.interpret_feature_combo.grid(row=0, column=1, sticky="ew")
        self.interpret_feature_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_feature_interpretation())
        ttk.Button(feature_controls, text="Verteilungsdiagnostik", command=lambda: self.notebook.select(self.distribution_tab)).grid(row=0, column=2, padx=(10, 0))

        detail_frame = ttk.LabelFrame(self.interpretation_tab, text="Ausführliche Merkmalsinterpretation", padding=8)
        detail_frame.grid(row=4, column=0, sticky="nsew")
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        self.feature_detail_text = tk.Text(detail_frame, wrap="word", padx=10, pady=10, font=("Segoe UI", 10))
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.feature_detail_text.yview)
        self.feature_detail_text.configure(yscrollcommand=detail_scroll.set)
        self.feature_detail_text.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")

    def _build_overview_tab(self):
        self.overview_tab.columnconfigure(0, weight=1)
        self.overview_tab.rowconfigure(1, weight=1)
        self.scope_note_var = tk.StringVar()
        ttk.Label(
            self.overview_tab,
            textvariable=self.scope_note_var,
            foreground="#555",
            wraplength=1220,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        columns = ("feature", "role", "n", "mean", "dev", "s", "r", "min", "max", "cm", "cmk", "ppm_obs", "ppm_exp", "levels", "kr", "status")
        headings = {
            "feature": "Merkmal", "role": "Rolle", "n": "n", "mean": "Mittel", "dev": "Δ",
            "s": "s", "r": "R", "min": "Min", "max": "Max", "cm": "Cₘ", "cmk": "Cₘₖ",
            "ppm_obs": "ppm beob. ges.", "ppm_exp": "ppm Modell ges.",
            "levels": "Stufen", "kr": "kᵣ", "status": "Einordnung",
        }
        widths = {
            "feature": 220, "role": 120, "n": 42, "mean": 76, "dev": 68, "s": 64, "r": 64,
            "min": 70, "max": 70, "cm": 56, "cmk": 60, "ppm_obs": 92, "ppm_exp": 96,
            "levels": 54, "kr": 52, "status": 195,
        }
        frame = ttk.Frame(self.overview_tab)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.result_tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            self.result_tree.heading(col, text=headings[col])
            self.result_tree.column(col, width=widths[col], minwidth=38, stretch=(col in {"feature", "status"}))
        self.result_tree.tag_configure("reached", background="#e7f4e7")
        self.result_tree.tag_configure("limited", background="#fff3dc")
        self.result_tree.tag_configure("critical", background="#fde7e7")
        self.result_tree.tag_configure("descriptive", background="#f1f1f1")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.result_tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.result_tree.xview)
        self.result_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.result_tree.bind("<<TreeviewSelect>>", self._show_selected_warning)
        self.result_tree.bind("<Double-1>", self._open_selected_interpretation)

        warning_frame = ttk.LabelFrame(self.overview_tab, text="Interpretationshinweis", padding=8)
        warning_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        warning_frame.columnconfigure(0, weight=1)
        self.warning_var = tk.StringVar(value="Merkmal auswählen.")
        ttk.Label(warning_frame, textvariable=self.warning_var, wraplength=1200, justify="left").grid(row=0, column=0, sticky="w")

    def _build_confidence_tab(self):
        self.confidence_tab.columnconfigure(0, weight=1)
        self.confidence_tab.rowconfigure(1, weight=2)
        self.confidence_tab.rowconfigure(3, weight=3)
        level = self.project.settings.confidence_level * 100.0
        ttk.Label(
            self.confidence_tab,
            text=(
                f"Zweiseitige {level:.0f}-%-Konfidenzintervalle beschreiben die Stichprobenunsicherheit. "
                f"Die einseitige untere {level:.0f}-%-Konfidenzgrenze zeigt, wie weit der Cₘₖ-Wert unter "
                "Berücksichtigung der Stichprobenunsicherheit mindestens reicht. Sie ist kein zweiter Fähigkeitsindex und kein Bewertungsgrenzwert. Cₘ verwendet ein Chi-Quadrat-Intervall; Cₘₖ eine "
                "Bissell-/Delta-Approximation unter Normalverteilungsannahme."
            ),
            foreground="#555", wraplength=1240, justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        frame = ttk.Frame(self.confidence_tab)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = (
            "feature", "n", "mean_ci", "s_ci", "cml", "cmu", "limit",
            "cm", "cm_ci", "cm_lcb", "cmk", "cmk_ci", "cmk_lcb", "decision",
        )
        headings = {
            "feature": "Merkmal", "n": "n", "mean_ci": f"{level:.0f}-%-KI x̄", "s_ci": f"{level:.0f}-%-KI s",
            "cml": "Cₘ,USG", "cmu": "Cₘ,OSG", "limit": "limitierende Seite",
            "cm": "Cₘ", "cm_ci": f"{level:.0f}-%-KI Cₘ", "cm_lcb": f"untere {level:.0f}-%-Grenze Cₘ",
            "cmk": "Cₘₖ", "cmk_ci": f"{level:.0f}-%-KI Cₘₖ", "cmk_lcb": f"untere {level:.0f}-%-Grenze Cₘₖ",
            "decision": "Einordnung",
        }
        widths = {
            "feature": 205, "n": 45, "mean_ci": 140, "s_ci": 120, "cml": 72, "cmu": 72, "limit": 112,
            "cm": 58, "cm_ci": 110, "cm_lcb": 165, "cmk": 58, "cmk_ci": 110, "cmk_lcb": 175, "decision": 200,
        }
        self.confidence_tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            self.confidence_tree.heading(col, text=headings[col])
            self.confidence_tree.column(col, width=widths[col], minwidth=45, stretch=(col in {"feature", "decision"}))
        self.confidence_tree.tag_configure("secured", background="#e7f4e7")
        self.confidence_tree.tag_configure("not_secured", background="#fff3dc")
        self.confidence_tree.tag_configure("below", background="#fde7e7")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.confidence_tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.confidence_tree.xview)
        self.confidence_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.confidence_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

        self.confidence_note_var = tk.StringVar()
        ttk.Label(self.confidence_tab, textvariable=self.confidence_note_var, foreground="#555", wraplength=1240, justify="left").grid(
            row=2, column=0, sticky="w", pady=(8, 4)
        )
        chart_frame = ttk.LabelFrame(self.confidence_tab, text="Intervallplot", padding=4)
        chart_frame.grid(row=3, column=0, sticky="nsew")
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(0, weight=1)
        self.confidence_chart_area = ttk.Frame(chart_frame)
        self.confidence_chart_area.grid(row=0, column=0, sticky="nsew")
        self.confidence_chart_area.columnconfigure(0, weight=1)
        self.confidence_chart_area.rowconfigure(0, weight=1)

    def _build_ppm_tab(self):
        self.ppm_tab.columnconfigure(0, weight=1)
        self.ppm_tab.rowconfigure(1, weight=1)
        ttk.Label(
            self.ppm_tab,
            text=(
                "Beobachtete ppm entsprechen dem tatsächlich in der Stichprobe festgestellten Anteil außerhalb der Grenzen. "
                "Modell-ppm werden ergänzend aus einer Normalverteilung mit x̄ und s berechnet und sind nur bei hinreichender "
                "Stabilität und plausibler Verteilungsannahme interpretierbar."
            ),
            foreground="#555", wraplength=1240, justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        frame = ttk.Frame(self.ppm_tab)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = (
            "feature", "usg", "osg", "below_n", "above_n",
            "obs_below", "obs_above", "obs_total", "obs_ci", "obs_upper",
            "exp_below", "exp_above", "exp_total", "status",
        )
        level = self.project.settings.confidence_level * 100.0
        headings = {
            "feature": "Merkmal", "usg": "USG", "osg": "OSG",
            "below_n": "n<USG", "above_n": "n>OSG",
            "obs_below": "beob. ppm <USG", "obs_above": "beob. ppm >OSG", "obs_total": "beob. ppm ges.",
            "obs_ci": f"{level:.0f}-%-KI beob.", "obs_upper": f"obere {level:.0f}-%-Grenze",
            "exp_below": "Modell-ppm <USG", "exp_above": "Modell-ppm >OSG", "exp_total": "Modell-ppm ges.",
            "status": "Einordnung",
        }
        widths = {
            "feature": 215, "usg": 72, "osg": 72, "below_n": 58, "above_n": 58,
            "obs_below": 108, "obs_above": 108, "obs_total": 100, "obs_ci": 125, "obs_upper": 118,
            "exp_below": 112, "exp_above": 112, "exp_total": 104, "status": 215,
        }
        self.ppm_tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            self.ppm_tree.heading(col, text=headings[col])
            self.ppm_tree.column(col, width=widths[col], minwidth=55, stretch=(col in {"feature", "status"}))
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.ppm_tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.ppm_tree.xview)
        self.ppm_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.ppm_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.ppm_note_var = tk.StringVar()
        ttk.Label(self.ppm_tab, textvariable=self.ppm_note_var, foreground="#555", wraplength=1240, justify="left").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )

    def _build_distribution_tab(self):
        self.distribution_tab.columnconfigure(0, weight=1)
        self.distribution_tab.rowconfigure(3, weight=1)
        controls = ttk.Frame(self.distribution_tab)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Merkmal:").grid(row=0, column=0, padx=(0, 8))
        self.dist_feature_var = tk.StringVar()
        self.dist_feature_combo = ttk.Combobox(controls, textvariable=self.dist_feature_var, state="readonly")
        self.dist_feature_combo.grid(row=0, column=1, sticky="ew")
        self.dist_feature_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_distribution(run_bootstrap=False))
        self.bootstrap_button = ttk.Button(controls, text="Bootstrap für Merkmal", command=self.run_bootstrap)
        self.bootstrap_button.grid(row=0, column=2, padx=(10, 0))
        self.bootstrap_all_button = ttk.Button(controls, text="Bootstrap für alle geeigneten Merkmale", command=self.run_bootstrap_all)
        self.bootstrap_all_button.grid(row=0, column=3, padx=(8, 0))

        progress_frame = ttk.Frame(self.distribution_tab)
        progress_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        progress_frame.columnconfigure(0, weight=1)
        self.bootstrap_progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.bootstrap_progress.grid(row=0, column=0, sticky="ew")
        self.bootstrap_status_var = tk.StringVar(value="Bootstrap-Auswertung nicht ausgeführt.")
        ttk.Label(progress_frame, textvariable=self.bootstrap_status_var, foreground="#555").grid(row=1, column=0, sticky="w", pady=(3, 0))

        info = ttk.LabelFrame(self.distribution_tab, text="Kennwerte des ausgewählten Merkmals", padding=8)
        info.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for col in (1, 3, 5):
            info.columnconfigure(col, weight=1)
        keys = ("n", "levels", "kr", "usg", "osg", "sw", "jb", "boot", "fit", "status", "note")
        self.dist_vars = {key: tk.StringVar(value="–") for key in keys}
        fields = [
            ("n", "Stichprobenumfang"), ("levels", "Ablesestufen"), ("kr", "kᵣ = s/r"),
            ("usg", "USG / UGW"), ("osg", "OSG / OGW"), ("boot", "Bootstrap-p"),
            ("sw", "Shapiro-Wilk p"), ("jb", "Jarque-Bera p"), ("fit", "Quantisiertes Modell"),
        ]
        for index, (key, label) in enumerate(fields):
            block = index % 3
            row = index // 3
            col = block * 2
            ttk.Label(info, text=label, font=("Segoe UI", 9, "bold")).grid(row=row, column=col, sticky="nw", padx=(0, 8), pady=3)
            ttk.Label(info, textvariable=self.dist_vars[key], wraplength=300, justify="left").grid(row=row, column=col + 1, sticky="nw", padx=(0, 18), pady=3)
        ttk.Label(info, text="Einordnung", font=("Segoe UI", 9, "bold")).grid(row=3, column=0, sticky="nw", padx=(0, 8), pady=3)
        ttk.Label(info, textvariable=self.dist_vars["status"], wraplength=1050, justify="left").grid(row=3, column=1, columnspan=5, sticky="nw", pady=3)
        ttk.Label(info, text="Hinweis", font=("Segoe UI", 9, "bold")).grid(row=4, column=0, sticky="nw", padx=(0, 8), pady=3)
        ttk.Label(info, textvariable=self.dist_vars["note"], wraplength=1050, justify="left").grid(row=4, column=1, columnspan=5, sticky="nw", pady=3)

        diagnostic = ttk.LabelFrame(self.distribution_tab, text="Grafische Verteilungsdiagnostik", padding=4)
        diagnostic.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        diagnostic.columnconfigure(0, weight=1)
        diagnostic.rowconfigure(0, weight=1)
        self.distribution_chart_area = ttk.Frame(diagnostic)
        self.distribution_chart_area.grid(row=0, column=0, sticky="nsew")
        self.distribution_chart_area.columnconfigure(0, weight=1)
        self.distribution_chart_area.rowconfigure(0, weight=1)

        ttk.Label(
            self.distribution_tab,
            text=(
                "Das Fähigkeitshistogramm zeigt Messwerte, angepasste Normaldichte, Nennmaß, UGW/OGW und die 6s-Breite x̄ ± 3s. "
                "Q-Q-Diagramm, Shapiro-Wilk, Jarque-Bera und der quantisierte Bootstrap werden gemeinsam beurteilt; "
                "ein nicht signifikanter p-Wert bestätigt keine Normalverteilung."
            ),
            foreground="#555", wraplength=1240, justify="left",
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))

    def _build_comparison_tab(self):
        self.comparison_tab.columnconfigure(0, weight=1)
        self.comparison_tab.rowconfigure(2, weight=1)
        controls = ttk.Frame(self.comparison_tab)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(3, weight=1)
        ttk.Label(controls, text="Gruppieren nach:").grid(row=0, column=0, padx=(0, 8))
        self.group_attr_var = tk.StringVar(value="Druckbettposition")
        self.group_attr_combo = ttk.Combobox(
            controls,
            textvariable=self.group_attr_var,
            values=("Druckbettposition", "Batch", "Material", "Konfiguration"),
            state="readonly",
            width=22,
        )
        self.group_attr_combo.grid(row=0, column=1, padx=(0, 20))
        self.group_attr_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_comparison())
        ttk.Label(controls, text="Merkmal:").grid(row=0, column=2, padx=(0, 8))
        self.group_feature_var = tk.StringVar()
        self.group_feature_combo = ttk.Combobox(controls, textvariable=self.group_feature_var, state="readonly")
        self.group_feature_combo.grid(row=0, column=3, sticky="ew")
        self.group_feature_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_comparison())

        self.group_note_var = tk.StringVar()
        ttk.Label(self.comparison_tab, textvariable=self.group_note_var, foreground="#555", wraplength=1180, justify="left").grid(
            row=1, column=0, sticky="w", pady=(8, 8)
        )

        frame = ttk.Frame(self.comparison_tab)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ("group", "n", "mean", "dev", "s", "r", "cm", "cmk", "levels", "kr", "status")
        headings = {
            "group": "Gruppe", "n": "n", "mean": "Mittel", "dev": "Δ", "s": "s", "r": "R",
            "cm": "Cₘ", "cmk": "Cₘₖ", "levels": "Stufen", "kr": "kᵣ", "status": "Einordnung",
        }
        widths = {"group": 230, "n": 50, "mean": 90, "dev": 80, "s": 75, "r": 75, "cm": 70, "cmk": 70, "levels": 65, "kr": 65, "status": 300}
        self.group_tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            self.group_tree.heading(col, text=headings[col])
            self.group_tree.column(col, width=widths[col], minwidth=45, stretch=(col in {"group", "status"}))
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.group_tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.group_tree.xview)
        self.group_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.group_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

    def _build_spatial_tab(self):
        self.spatial_tab.columnconfigure(0, weight=1)
        self.spatial_tab.rowconfigure(3, weight=1)
        controls = ttk.Frame(self.spatial_tab)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Merkmal:").grid(row=0, column=0, padx=(0, 8))
        self.spatial_feature_var = tk.StringVar()
        self.spatial_feature_combo = ttk.Combobox(controls, textvariable=self.spatial_feature_var, state="readonly")
        self.spatial_feature_combo.grid(row=0, column=1, sticky="ew")
        self.spatial_feature_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_spatial())
        ttk.Button(controls, text="Heatmap anzeigen", command=self._open_spatial_heatmap).grid(row=0, column=2, padx=(10, 0))

        global_frame = ttk.LabelFrame(self.spatial_tab, text="Globale Bauraumauswertung und Positionsabhängigkeit", padding=8)
        global_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        global_frame.columnconfigure(0, weight=1)
        self.spatial_summary_var = tk.StringVar(value="Bauraumprüfung auswählen.")
        ttk.Label(global_frame, textvariable=self.spatial_summary_var, wraplength=1200, justify="left").grid(row=0, column=0, sticky="w")

        ttk.Label(
            self.spatial_tab,
            text=("Die globale Zeile fasst alle Positionen und Batches gemeinsam zusammen. Die Tabelle darunter wertet jede "
                  "Position über ihre Wiederholungen/Batches separat aus. Der Friedman-Test nutzt vollständige Batches als Blöcke. "
                  "Konfidenzintervalle werden bewusst in der eigenen Registerkarte dargestellt, damit der Positionsvergleich kompakt bleibt."),
            foreground="#555", wraplength=1200, justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(8, 8))

        frame = ttk.Frame(self.spatial_tab)
        frame.grid(row=3, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ("position", "n", "mean", "dev", "s", "r", "cm", "cmk", "levels", "kr", "status")
        headings = {
            "position": "Position", "n": "n", "mean": "Mittel", "dev": "Δ", "s": "s", "r": "R",
            "cm": "Cₘ", "cmk": "Cₘₖ", "levels": "Stufen", "kr": "kᵣ", "status": "Einordnung",
        }
        widths = {"position": 210, "n": 50, "mean": 90, "dev": 80, "s": 75, "r": 75, "cm": 70, "cmk": 70, "levels": 65, "kr": 65, "status": 330}
        self.spatial_tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            self.spatial_tree.heading(col, text=headings[col])
            self.spatial_tree.column(col, width=widths[col], minwidth=45, stretch=(col in {"position", "status"}))
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.spatial_tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.spatial_tree.xview)
        self.spatial_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.spatial_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")

    def _open_spatial_heatmap(self):
        if not self.is_bed_study():
            return
        label = self.spatial_feature_var.get()
        if label:
            self.chart_feature_var.set(label)
        self.chart_kind_var.set("Bauraum-Heatmap")
        self.notebook.select(self.chart_tab)
        self.refresh_chart()

    def _build_chart_tab(self):
        self.chart_tab.columnconfigure(0, weight=1)
        self.chart_tab.rowconfigure(1, weight=1)
        controls = ttk.Frame(self.chart_tab)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Diagramm:").grid(row=0, column=0, padx=(0, 8))
        self.chart_kind_var = tk.StringVar(value="Mittlere Abweichungen")
        self.chart_kind_combo = ttk.Combobox(
            controls, textvariable=self.chart_kind_var,
            values=("Mittlere Abweichungen", "Cₘ/Cₘₖ", "Konfidenzintervalle Cₘ/Cₘₖ", "Verlauf", "Fähigkeitshistogramm", "Histogramm (Detail)", "Q-Q-Diagramm", "Positionsprofil", "Bauraum-Heatmap"),
            state="readonly", width=24,
        )
        self.chart_kind_combo.grid(row=0, column=1, sticky="w")
        self.chart_kind_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_chart())
        ttk.Label(controls, text="Merkmal:").grid(row=0, column=2, padx=(20, 8))
        self.chart_feature_var = tk.StringVar()
        self.chart_feature_combo = ttk.Combobox(controls, textvariable=self.chart_feature_var, state="readonly", width=38)
        self.chart_feature_combo.grid(row=0, column=3)
        self.chart_feature_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_chart())
        ttk.Button(controls, text="SVG speichern…", command=self.save_chart_svg).grid(row=0, column=4, padx=(12, 0))
        self.chart_area = ttk.Frame(self.chart_tab)
        self.chart_area.grid(row=1, column=0, sticky="nsew")
        self.chart_area.columnconfigure(0, weight=1)
        self.chart_area.rowconfigure(0, weight=1)

    def refresh(self):
        self._update_scope_cache_key()
        records = self.current_records()
        base_records = self.base_records()
        self.current_results = analyze_records(records, self.project.settings)
        if self.is_bed_study():
            self.selector_note_var.set(
                f"Grunddatensatz: {len(base_records)} Messzeilen an {len({r.bed_position for r in base_records})} Positionen und "
                f"{len({r.batch for r in base_records})} Batches. Aktuelle Ansicht: {self.analysis_mode_var.get()} ({len(records)} Messzeilen). "
                "Die Bauraumdiagnose vergleicht unabhängig von der aktuellen Einzelansicht stets den vollständigen Grunddatensatz."
            )
        else:
            self.selector_note_var.set(f"Aktuelle Auswertung: {len(records)} Messzeilen des gewählten Datensatzes.")
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        for result in self.current_results:
            if result.cmk is not None and result.cmk < 0:
                tag = "critical"
            elif result.cmk is not None and result.cmk < self.project.settings.capability_orientation:
                tag = "limited"
            elif result.cmk is not None:
                tag = "reached"
            else:
                tag = "descriptive"
            self.result_tree.insert("", "end", iid=result.feature_key, tags=(tag,), values=(
                result.label, result.role, result.n, _fmt(result.mean), _fmt(result.deviation), _fmt(result.stdev),
                _fmt(result.span), _fmt(result.minimum), _fmt(result.maximum), _fmt(result.cm, 2), _fmt(result.cmk, 2),
                _fmt_ppm(result.observed_ppm_total), _fmt_ppm(result.expected_ppm_total),
                result.unique_levels, _fmt(result.k_r, 2), result.status,
            ))
        if records:
            studies = ", ".join(sorted({r.study_type for r in records}))
            positions = ", ".join(sorted({r.bed_position for r in records}))
            self.scope_note_var.set(
                f"{len(records)} Messzeilen | {studies} | Position(en): {positions}. "
                "Die Auswertung gilt ausschließlich für diesen gewählten Umfang. Doppelklick auf ein Merkmal öffnet seine Interpretation."
            )
        else:
            self.scope_note_var.set("Keine Daten im gewählten Prüfumfang.")
        self.warning_var.set("Merkmal auswählen.")

        keys = [r.feature_key for r in self.current_results]
        labels = [feature_spec(key).label for key in keys]
        base_results = analyze_records(base_records, self.project.settings) if self.is_bed_study() else self.current_results
        base_keys = [r.feature_key for r in base_results]
        base_labels = [feature_spec(key).label for key in base_keys]
        self._label_to_key = dict(zip(labels, keys))
        self._label_to_key.update(dict(zip(base_labels, base_keys)))
        for combo in (self.dist_feature_combo, self.interpret_feature_combo, self.group_feature_combo):
            combo.configure(values=labels)
        for combo in (self.chart_feature_combo, self.spatial_feature_combo):
            combo.configure(values=base_labels)
        if labels:
            for variable in (self.dist_feature_var, self.interpret_feature_var, self.group_feature_var):
                if variable.get() not in labels:
                    variable.set(labels[0])
        if base_labels:
            for variable in (self.chart_feature_var, self.spatial_feature_var):
                if variable.get() not in base_labels:
                    variable.set(base_labels[0])

        distributions = self._current_scope_distributions()
        _set_text(
            self.summary_text,
            scope_summary_text(records, self.project.settings, results=self.current_results, distributions=distributions),
        )
        self._refresh_findings(distributions)
        self.refresh_feature_interpretation()
        self.refresh_confidence()
        self.refresh_ppm()
        self.refresh_distribution(run_bootstrap=False)
        self.refresh_comparison()
        self.refresh_spatial()
        self.refresh_chart()

    def _current_scope_distributions(self) -> list[DistributionResult]:
        scope = self.scope_var.get()
        return [value for (scope_name, _), value in self.distribution_cache.items() if scope_name == scope]

    def _refresh_findings(self, distributions: Sequence[DistributionResult] = ()):
        for item in self.findings_tree.get_children():
            self.findings_tree.delete(item)
        self._finding_details.clear()
        for index, (level, area, finding, step) in enumerate(prioritized_findings(
            self.current_records(),
            self.project.settings,
            results=self.current_results,
            distributions=distributions,
        )):
            item_id = f"finding_{index}"
            self._finding_details[item_id] = (level, area, finding, step)
            self.findings_tree.insert("", "end", iid=item_id, values=(level, area, finding))
        first = self.findings_tree.get_children()
        if first:
            self.findings_tree.selection_set(first[0])
            self.findings_tree.focus(first[0])
            self._show_finding_detail()
        else:
            _set_text(self.finding_detail_text, "Im gewählten Prüfumfang wurden keine priorisierten Befunde erzeugt.")

    def _show_finding_detail(self, _event=None):
        selected = self.findings_tree.selection()
        if not selected:
            return
        detail = self._finding_details.get(selected[0])
        if detail is None:
            return
        level, area, finding, step = detail
        _set_text(
            self.finding_detail_text,
            (
                f"Stufe: {level}\n"
                f"Bereich: {area}\n\n"
                f"Befund: {finding}\n\n"
                f"Nächster Schritt: {step}"
            ),
        )

    def _show_selected_warning(self, _event=None):
        selected = self.result_tree.selection()
        if not selected:
            return
        key = selected[0]
        result = next((r for r in self.current_results if r.feature_key == key), None)
        if result:
            detail = result.warning_text or "Keine zusätzliche Warnung."
            if feature_spec(key).measurement_note:
                detail += " Messstrategie: " + feature_spec(key).measurement_note
            self.warning_var.set(detail)
            label = feature_spec(key).label
            self.interpret_feature_var.set(label)
            self.dist_feature_var.set(label)
            self.group_feature_var.set(label)
            self.chart_feature_var.set(label)
            self.refresh_feature_interpretation()

    def _open_selected_interpretation(self, _event=None):
        self._show_selected_warning()
        self.notebook.select(self.interpretation_tab)

    def _selected_feature_key(self, variable: tk.StringVar) -> str | None:
        return getattr(self, "_label_to_key", {}).get(variable.get())

    def _distribution_for(self, key: str | None) -> DistributionResult | None:
        if not key:
            return None
        return self.distribution_cache.get((self.scope_var.get(), key))

    def refresh_confidence(self):
        for item in self.confidence_tree.get_children():
            self.confidence_tree.delete(item)
        level = self.project.settings.confidence_level * 100.0
        count = 0
        secured = 0
        for result in self.current_results:
            if result.cmk is None or result.cmk_ci_lower is None:
                continue
            count += 1
            if result.cmk_lower_confidence_bound is not None and result.cmk_lower_confidence_bound >= self.project.settings.capability_orientation:
                tag = "secured"
                secured += 1
            elif result.cmk >= self.project.settings.capability_orientation:
                tag = "not_secured"
            else:
                tag = "below"
            mean_ci = f"{_fmt(result.mean_ci_lower)} … {_fmt(result.mean_ci_upper)}"
            s_ci = f"{_fmt(result.stdev_ci_lower)} … {_fmt(result.stdev_ci_upper)}"
            cm_ci = f"{_fmt(result.cm_ci_lower, 2)} … {_fmt(result.cm_ci_upper, 2)}"
            cmk_ci = f"{_fmt(result.cmk_ci_lower, 2)} … {_fmt(result.cmk_ci_upper, 2)}"
            orientation = self.project.settings.capability_orientation
            if result.cmk < orientation:
                decision = f"Cₘₖ < {orientation:.2f}"
            elif result.cmk_lower_confidence_bound is not None and result.cmk_lower_confidence_bound >= orientation:
                decision = f"untere Grenze ≥ {orientation:.2f}"
            else:
                decision = f"Cₘₖ ≥ {orientation:.2f}; Untergrenze darunter"
            self.confidence_tree.insert("", "end", tags=(tag,), values=(
                result.label, result.n, mean_ci, s_ci, _fmt(result.cml, 2), _fmt(result.cmu, 2),
                result.limiting_side or "–", _fmt(result.cm, 2), cm_ci, _fmt(result.cm_lower_confidence_bound, 2),
                _fmt(result.cmk, 2), cmk_ci, _fmt(result.cmk_lower_confidence_bound, 2), decision,
            ))
        self.confidence_note_var.set(
            f"{count} reguläre Fähigkeitsmerkmale mit Intervallen; bei {secured} liegt die einseitige untere "
            f"{level:.0f}-%-Konfidenzgrenze von Cₘₖ mindestens bei der Orientierungsgrenze "
            f"{self.project.settings.capability_orientation:.2f}. Auch eine erreichte untere Konfidenzgrenze ersetzt keinen normkonformen Freigabenachweis. "
            "Bei wenigen Ablesestufen, kᵣ < 1 oder auffälliger Verteilungsdiagnostik sind die modellbasierten Intervalle zurückhaltend zu interpretieren."
        )
        if self.confidence_canvas is not None:
            self.confidence_canvas.get_tk_widget().destroy()
            self.confidence_canvas = None
        try:
            figure = capability_confidence_figure(self.current_records(), self.project.settings)
            figure.tight_layout()
            self.confidence_canvas = FigureCanvasTkAgg(figure, master=self.confidence_chart_area)
            self.confidence_canvas.draw()
            self.confidence_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        except Exception as exc:
            self.confidence_note_var.set(self.confidence_note_var.get() + f" Intervallplot konnte nicht erstellt werden: {exc}")

    def refresh_ppm(self):
        for item in self.ppm_tree.get_children():
            self.ppm_tree.delete(item)
        shown = 0
        for result in self.current_results:
            if result.lower_limit is None or result.upper_limit is None:
                continue
            shown += 1
            self.ppm_tree.insert("", "end", values=(
                result.label, _fmt(result.lower_limit), _fmt(result.upper_limit),
                result.observed_below_count if result.observed_below_count is not None else "–",
                result.observed_above_count if result.observed_above_count is not None else "–",
                _fmt_ppm(result.observed_ppm_below), _fmt_ppm(result.observed_ppm_above), _fmt_ppm(result.observed_ppm_total),
                f"{_fmt_ppm(result.observed_ppm_total_ci_lower)} … {_fmt_ppm(result.observed_ppm_total_ci_upper)}",
                _fmt_ppm(result.observed_ppm_total_upper_bound),
                _fmt_ppm(result.expected_ppm_below), _fmt_ppm(result.expected_ppm_above), _fmt_ppm(result.expected_ppm_total),
                result.status,
            ))
        self.ppm_note_var.set(
            f"{shown} Merkmal(e) mit Bewertungsgrenzen. Beobachtete ppm sind Stichprobenanteile; bei n = 25 entspricht bereits ein Wert 40.000 ppm. "
            "Das exakte Clopper-Pearson-Intervall und die einseitige obere Konfidenzgrenze zeigen die erhebliche Unsicherheit kleiner Stichproben. "
            "Modell-ppm sind eine ergänzende Normalmodellrechnung und keine beobachtete Ausschussquote oder exakte Zukunftsprognose."
        )

    def _refresh_distribution_figure(self, distribution: DistributionResult | None = None):
        if self.distribution_canvas is not None:
            self.distribution_canvas.get_tk_widget().destroy()
            self.distribution_canvas = None
        key = self._selected_feature_key(self.dist_feature_var)
        if not key:
            return
        records = self.current_records()
        if not records:
            return
        try:
            figure = distribution_diagnostics_figure(records, key, self.project.settings, distribution)
        except Exception as exc:
            messagebox.showerror("Verteilungsdiagramm", str(exc), parent=self)
            return
        self._current_distribution_figure = figure
        self.distribution_canvas = FigureCanvasTkAgg(figure, master=self.distribution_chart_area)
        self.distribution_canvas.draw()
        self.distribution_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def refresh_feature_interpretation(self):
        key = self._selected_feature_key(self.interpret_feature_var)
        if not key:
            _set_text(self.feature_detail_text, "Kein Merkmal ausgewählt.")
            return
        result = next((item for item in self.current_results if item.feature_key == key), None)
        if result is None:
            return
        _set_text(
            self.feature_detail_text,
            feature_interpretation_text(result, self.project.settings, self._distribution_for(key)),
        )

    def refresh_distribution(self, *, run_bootstrap: bool):
        key = self._selected_feature_key(self.dist_feature_var)
        if not key:
            return
        cache_key = (self.scope_var.get(), key)
        result = self.distribution_cache.get(cache_key)
        if result is None or (run_bootstrap and result.bootstrap_p is None):
            try:
                result = distribution_analysis(self.current_records(), key, self.project.settings, run_bootstrap=run_bootstrap)
            except Exception as exc:
                messagebox.showerror("Verteilungsdiagnostik", str(exc), parent=self)
                return
            self.distribution_cache[cache_key] = result
        self._display_distribution(result)

    def _display_distribution(self, result: DistributionResult):
        self.dist_vars["n"].set(str(result.n))
        self.dist_vars["levels"].set(str(result.unique_levels))
        self.dist_vars["kr"].set(_fmt(result.k_r, 2))
        self.dist_vars["sw"].set(_fmt_p(result.shapiro_p))
        self.dist_vars["jb"].set(_fmt_p(result.jarque_bera_p))
        self.dist_vars["boot"].set(_fmt_p(result.bootstrap_p))
        key = result.feature_key
        capability = next((item for item in self.current_results if item.feature_key == key), None)
        self.dist_vars["usg"].set("–" if capability is None else _fmt(capability.lower_limit))
        self.dist_vars["osg"].set("–" if capability is None else _fmt(capability.upper_limit))
        if result.fitted_mu is None:
            fit = "Darstellung basiert auf x̄ und s; das quantisierte Modell wird bei der Bootstrap-Auswertung angepasst"
        else:
            fit = f"μ̂ = {_fmt(result.fitted_mu)}, σ̂ = {_fmt(result.fitted_sigma)}, Q_obs = {_fmt(result.bootstrap_q)}"
        self.dist_vars["fit"].set(fit)
        self.dist_vars["status"].set(result.status)
        self.dist_vars["note"].set(result.note)
        self._refresh_distribution_figure(result)

    def _set_bootstrap_controls(self, running: bool, text: str | None = None):
        self._bootstrap_running = running
        state = "disabled" if running else "normal"
        self.bootstrap_button.configure(state=state)
        self.bootstrap_all_button.configure(state=state)
        if text is not None:
            self.bootstrap_status_var.set(text)

    def run_bootstrap(self):
        if self._bootstrap_running:
            return
        key = self._selected_feature_key(self.dist_feature_var)
        if not key:
            return
        repetitions = int(self.project.settings.bootstrap_repetitions)
        self._set_bootstrap_controls(True, f"Bootstrap läuft für {feature_spec(key).label} (0/{repetitions}) …")
        self.bootstrap_progress.configure(maximum=max(repetitions, 1), value=0)
        scope_label = self.scope_var.get()
        records = self.current_records()
        settings = self.project.settings

        def progress(done: int, total: int):
            self.after(0, lambda: self._bootstrap_single_progress(done, total, key))

        def worker():
            try:
                result = distribution_analysis(records, key, settings, run_bootstrap=True, progress=progress)
                error = None
            except Exception as exc:  # noqa: BLE001
                result = None
                error = exc
            self.after(0, lambda: self._bootstrap_finished(scope_label, key, result, error))

        threading.Thread(target=worker, daemon=True).start()

    def _bootstrap_single_progress(self, done: int, total: int, key: str):
        self.bootstrap_progress.configure(maximum=max(total, 1), value=done)
        self.bootstrap_status_var.set(f"{feature_spec(key).label}: {done}/{total} Bootstrap-Wiederholungen")

    def _bootstrap_finished(self, scope_label, key, result, error):
        self._set_bootstrap_controls(False)
        self.bootstrap_progress.configure(value=self.bootstrap_progress.cget("maximum") if error is None else 0)
        if error is not None:
            self.bootstrap_status_var.set("Bootstrap fehlgeschlagen.")
            messagebox.showerror("Bootstrap", str(error), parent=self)
            return
        self.distribution_cache[(scope_label, key)] = result
        self.bootstrap_status_var.set(f"Bootstrap abgeschlossen: {feature_spec(key).label}.")
        if self.scope_var.get() == scope_label:
            if self._selected_feature_key(self.dist_feature_var) == key:
                self._display_distribution(result)
            self.refresh_feature_interpretation()
            distributions = self._current_scope_distributions()
            _set_text(self.summary_text, scope_summary_text(self.current_records(), self.project.settings, results=self.current_results, distributions=distributions))
            self._refresh_findings(distributions)

    def run_bootstrap_all(self):
        if self._bootstrap_running or not self.current_results:
            return
        eligible = [
            item for item in self.current_results
            if feature_spec(item.feature_key).unit == "mm" and item.stdev > 0 and item.unique_levels >= 3
        ]
        keys = [item.feature_key for item in eligible]
        skipped = len(self.current_results) - len(keys)
        if not keys:
            messagebox.showinfo(
                "Bootstrap für alle",
                "Im gewählten Prüfumfang liegt kein geeignetes geometrisches Merkmal mit positiver Streuung und mindestens drei Ablesestufen vor.",
                parent=self,
            )
            return
        scope_label = self.scope_var.get()
        records = self.current_records()
        settings = self.project.settings
        total = len(keys)
        repetitions = int(settings.bootstrap_repetitions)
        if not messagebox.askyesno(
            "Bootstrap für alle geeigneten Merkmale",
            f"Für {total} Merkmale werden jeweils {repetitions} Bootstrap-Wiederholungen berechnet. "
            f"{skipped} nicht geeignete Merkmale werden übersprungen.\n\nDie Berechnung läuft im Hintergrund und kann je nach Rechner einige Zeit dauern. Fortfahren?",
            parent=self,
        ):
            return
        all_steps = total * repetitions
        self._set_bootstrap_controls(
            True,
            f"Bootstrap für {total} geeignete geometrische Merkmale gestartet; {skipped} nicht geeignete Merkmale werden übersprungen.",
        )
        self.bootstrap_progress.configure(maximum=max(all_steps, 1), value=0)

        def worker():
            completed: list[tuple[str, DistributionResult]] = []
            error = None
            try:
                for index, key in enumerate(keys, 1):
                    def progress(done: int, per_feature_total: int, *, idx=index, current_key=key):
                        overall = (idx - 1) * per_feature_total + done
                        self.after(
                            0,
                            lambda o=overall, d=done, t=per_feature_total, i=idx, k=current_key: self._bootstrap_all_progress(o, all_steps, i, total, d, t, k),
                        )
                    result = distribution_analysis(records, key, settings, run_bootstrap=True, progress=progress)
                    completed.append((key, result))
            except Exception as exc:  # noqa: BLE001
                error = exc
            self.after(0, lambda: self._bootstrap_all_finished(scope_label, completed, error))

        threading.Thread(target=worker, daemon=True).start()

    def _bootstrap_all_progress(
        self,
        overall: int,
        all_steps: int,
        feature_index: int,
        feature_total: int,
        done: int,
        repetitions: int,
        key: str,
    ):
        self.bootstrap_progress.configure(maximum=max(all_steps, 1), value=overall)
        self.bootstrap_status_var.set(
            f"Merkmal {feature_index}/{feature_total}: {feature_spec(key).label} – {done}/{repetitions} Wiederholungen"
        )

    def _bootstrap_all_finished(self, scope_label: str, completed: list[tuple[str, DistributionResult]], error):
        for key, result in completed:
            self.distribution_cache[(scope_label, key)] = result
        self._set_bootstrap_controls(False)
        if error is not None:
            self.bootstrap_status_var.set(f"Abbruch nach {len(completed)} Merkmal(en).")
            messagebox.showerror("Bootstrap für alle", str(error), parent=self)
        else:
            self.bootstrap_status_var.set(f"Bootstrap für {len(completed)} geeignete geometrische Merkmal(e) abgeschlossen.")
        if self.scope_var.get() == scope_label:
            self.refresh_distribution(run_bootstrap=False)
            self.refresh_feature_interpretation()
            distributions = self._current_scope_distributions()
            _set_text(self.summary_text, scope_summary_text(self.current_records(), self.project.settings, results=self.current_results, distributions=distributions))
            self._refresh_findings(distributions)

    def refresh_comparison(self):
        for item in self.group_tree.get_children():
            self.group_tree.delete(item)
        key = self._selected_feature_key(self.group_feature_var)
        if not key:
            return
        mapping = {
            "Druckbettposition": "bed_position",
            "Batch": "batch",
            "Material": "material",
            "Konfiguration": "configuration",
        }
        attribute = mapping.get(self.group_attr_var.get(), "bed_position")
        rows = group_comparison_rows(self.current_records(), key, self.project.settings, attribute)
        for label, result in rows:
            self.group_tree.insert("", "end", values=(
                label, result.n, _fmt(result.mean), _fmt(result.deviation), _fmt(result.stdev), _fmt(result.span),
                _fmt(result.cm, 2), _fmt(result.cmk, 2),
                result.unique_levels, _fmt(result.k_r, 2), result.status,
            ))
        if attribute == "bed_position":
            note = "Positionswerte beschreiben den Gesamteffekt der dokumentierten Anordnung; lokale Temperatur-, Batch- und Werkzeugpfadeinflüsse können enthalten sein."
        elif attribute == "batch":
            note = "Der Batchvergleich dient der Erkennung zeitlicher oder druckjobbezogener Veränderungen; kleine Gruppen besitzen nur begrenzte Aussagekraft."
        else:
            note = "Gruppen nur vergleichen, wenn Messstrategie, Untersuchungsobjektgeometrie und Bewertungsgrenzen gleich sind."
        if len(rows) < 2:
            note = "Im gewählten Auswertungsumfang ist nur eine Gruppe vorhanden; ein Gruppenvergleich ist daher nicht möglich. " + note
        self.group_note_var.set(note)

    def refresh_spatial(self):
        for item in self.spatial_tree.get_children():
            self.spatial_tree.delete(item)
        if not self.is_bed_study():
            self.spatial_summary_var.set("Die Bauraumdiagnose ist nur für eine Bauraumprüfung verfügbar.")
            self.spatial_feature_combo.configure(state="disabled")
            return
        self.spatial_feature_combo.configure(state="readonly")
        key = self._selected_feature_key(self.spatial_feature_var)
        if not key:
            self.spatial_summary_var.set("Kein Merkmal ausgewählt.")
            return
        result = analyze_spatial_feature(self.base_records(), key, self.project.settings)
        self.spatial_summary_var.set(spatial_summary_text(result, self.project.settings))
        if result.global_result is not None:
            row = result.global_result
            self.spatial_tree.insert("", "end", values=(
                "GESAMT – alle Positionen", row.n, _fmt(row.mean), _fmt(row.deviation), _fmt(row.stdev), _fmt(row.span),
                _fmt(row.cm, 2), _fmt(row.cmk, 2),
                row.unique_levels, _fmt(row.k_r, 2), row.status,
            ), tags=("global",))
        for position, row in result.position_results:
            self.spatial_tree.insert("", "end", values=(
                position, row.n, _fmt(row.mean), _fmt(row.deviation), _fmt(row.stdev), _fmt(row.span),
                _fmt(row.cm, 2), _fmt(row.cmk, 2),
                row.unique_levels, _fmt(row.k_r, 2), row.status,
            ))
        self.spatial_tree.tag_configure("global", background="#eaf0f7")

    def refresh_chart(self):
        if self.chart_canvas is not None:
            self.chart_canvas.get_tk_widget().destroy()
            self.chart_canvas = None
        records = self.current_records()
        key = self._selected_feature_key(self.chart_feature_var)
        kind = self.chart_kind_var.get()
        if kind in {"Bauraum-Heatmap", "Positionsprofil"}:
            records = self.base_records()
        if not records:
            return
        if kind not in {"Mittlere Abweichungen", "Cₘ/Cₘₖ"} and not key:
            return
        try:
            figure = build_figure(kind, records, key or "x_outer", self.project.settings)
            figure.tight_layout()
        except Exception as exc:
            messagebox.showerror("Diagramm", str(exc), parent=self)
            return
        self._current_figure = figure
        self.chart_canvas = FigureCanvasTkAgg(figure, master=self.chart_area)
        self.chart_canvas.draw()
        self.chart_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def save_chart_svg(self):
        if not hasattr(self, "_current_figure"):
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Diagramm als SVG speichern",
            defaultextension=".svg",
            filetypes=[("SVG", "*.svg")],
        )
        if path:
            self._current_figure.savefig(path, format="svg", bbox_inches="tight")

    def export_report(self):
        base_records = self.base_records()
        if not base_records:
            return
        dialog = ReportExportDialog(
            self,
            is_bed_study=self.is_bed_study(),
            has_distributions=bool(self._current_scope_distributions()),
        )
        self.wait_window(dialog)
        options = dialog.result
        if options is None:
            return
        records = base_records if options.data_scope == "Gesamter gewählter Datensatz" else self.current_records()
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Bericht speichern",
            defaultextension=".html",
            filetypes=[
                ("HTML-Bericht", "*.html"),
                ("PDF-Bericht", "*.pdf"),
                ("Textbericht", "*.txt"),
                ("Kennwert-CSV der aktuellen Ansicht", "*.csv"),
            ],
        )
        if not path:
            return
        # Bootstrap-Ergebnisse sind an den genauen Auswertungsumfang gebunden. Beim Export des
        # vollständigen Grunddatensatzes werden sie nur übernommen, wenn auch die aktuelle Ansicht
        # genau diesem Umfang entspricht.
        if records == self.current_records():
            distributions = self._current_scope_distributions()
        else:
            distributions = []
        try:
            suffix = Path(path).suffix.lower()
            if suffix == ".pdf":
                save_pdf_report(path, records, self.project.settings, distributions=distributions, options=options)
            elif suffix == ".txt":
                save_text_report(path, records, self.project.settings, distributions=distributions, options=options)
            elif suffix == ".csv":
                save_analysis_csv(path, analyze_records(records, self.project.settings))
            else:
                if not suffix:
                    path += ".html"
                save_html_report(path, records, self.project.settings, distributions=distributions, options=options)
        except Exception as exc:
            messagebox.showerror("Exportfehler", str(exc), parent=self)
            return
        messagebox.showinfo("Export", "Bericht wurde gespeichert.", parent=self)

