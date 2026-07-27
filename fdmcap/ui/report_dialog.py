"""Dialog zum Zusammenstellen eines Auswertungsberichts."""
from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk


@dataclass(frozen=True)
class ReportSelection:
    data_scope: str
    include_scope: bool
    include_summary: bool
    include_findings: bool
    include_core: bool
    include_confidence: bool
    include_ppm: bool
    include_warnings: bool
    include_distributions: bool
    include_spatial: bool
    include_batch_comparison: bool
    include_method: bool
    include_raw_data: bool


class ReportExportDialog(tk.Toplevel):
    def __init__(self, parent, *, is_bed_study: bool, has_distributions: bool):
        super().__init__(parent)
        self.title("Bericht zusammenstellen")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: ReportSelection | None = None

        outer = ttk.Frame(self, padding=16)
        outer.grid(row=0, column=0, sticky="nsew")
        ttk.Label(outer, text="Bericht zusammenstellen", font=("Segoe UI", 15, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            outer,
            text="Datenumfang und Berichtskapitel werden getrennt ausgewählt. Die aktuelle Bildschirmansicht wird dadurch nicht verändert.",
            foreground="#555", wraplength=650, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 12))

        scope = ttk.LabelFrame(outer, text="1. Datenumfang", padding=10)
        scope.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.data_scope_var = tk.StringVar(value="Gesamter gewählter Datensatz")
        choices = ["Gesamter gewählter Datensatz", "Nur aktuelle Auswertungsansicht"]
        ttk.Combobox(scope, textvariable=self.data_scope_var, values=choices, state="readonly", width=46).grid(row=0, column=0, sticky="w")
        ttk.Label(
            scope,
            text=("Für die Bauraumprüfung enthält der gesamte Datensatz alle Positionen und Batches. "
                  "Eine aktuelle Einzelposition oder ein Einzelbatch kann alternativ separat exportiert werden."),
            foreground="#555", wraplength=600, justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        content = ttk.LabelFrame(outer, text="2. Berichtskapitel", padding=10)
        content.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        defaults = {
            "scope": True, "summary": True, "findings": True, "core": True, "confidence": True, "ppm": True, "warnings": True,
            "distributions": has_distributions, "spatial": is_bed_study, "batch": False,
            "method": True, "raw": False,
        }
        self.vars = {key: tk.BooleanVar(value=value) for key, value in defaults.items()}
        items = [
            ("scope", "Prüfumfang und Metadaten"),
            ("summary", "Kurzbewertung"),
            ("findings", "Priorisierte Befunde und nächste Schritte"),
            ("core", "Kernkennwerte"),
            ("confidence", "Konfidenzintervalle der Fähigkeitskennwerte"),
            ("ppm", "ppm / Grenzüberschreitungsanteile"),
            ("warnings", "Interpretationshinweise und Warnlogik"),
            ("distributions", "Verteilungsdiagnostik / vorhandene Bootstrap-Ergebnisse"),
            ("spatial", "Bauraumdiagnose mit globaler und positionsbezogener Auswertung"),
            ("batch", "Batchvergleich"),
            ("method", "Methodische Einordnung und Grenzen"),
            ("raw", "Rohdatenanhang"),
        ]
        for index, (key, label) in enumerate(items):
            state = "normal"
            if key in {"spatial", "batch"} and not is_bed_study:
                state = "disabled"
            if key == "distributions" and not has_distributions:
                state = "disabled"
                self.vars[key].set(False)
            ttk.Checkbutton(content, text=label, variable=self.vars[key], state=state).grid(
                row=index // 2, column=index % 2, sticky="w", padx=(0, 28), pady=3
            )

        buttons = ttk.Frame(outer)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="Dateiformat und Speicherort wählen…", command=self.accept).grid(row=0, column=1)
        self.bind("<Escape>", lambda _e: self.destroy())

    def accept(self):
        if not any(var.get() for var in self.vars.values()):
            return
        self.result = ReportSelection(
            data_scope=self.data_scope_var.get(),
            include_scope=self.vars["scope"].get(),
            include_summary=self.vars["summary"].get(),
            include_findings=self.vars["findings"].get(),
            include_core=self.vars["core"].get(),
            include_confidence=self.vars["confidence"].get(),
            include_ppm=self.vars["ppm"].get(),
            include_warnings=self.vars["warnings"].get(),
            include_distributions=self.vars["distributions"].get(),
            include_spatial=self.vars["spatial"].get(),
            include_batch_comparison=self.vars["batch"].get(),
            include_method=self.vars["method"].get(),
            include_raw_data=self.vars["raw"].get(),
        )
        self.destroy()
