"""Bibliothek und Export der Untersuchungsobjekte."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..config import FEATURES, TEMPLATES
from ..models import ProjectSettings
from ..stl_library import MODEL_SPECS, export_model, export_step_model


class SpecimenLibraryWindow(tk.Toplevel):
    def __init__(self, parent, settings: ProjectSettings):
        super().__init__(parent)
        self.title("Untersuchungsobjektbibliothek")
        self.geometry("1120x720")
        self.minsize(940, 600)
        self.transient(parent)
        self.settings = settings

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, minsize=390)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(2, weight=1)

        ttk.Label(outer, text="Untersuchungsobjektbibliothek", font=("Segoe UI", 19, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            outer,
            text=(
                "Wähle links ein Untersuchungsobjekt aus. Das ausgewählte Modell kann anschließend als STL- oder "
                "STEP-Datei in einem frei gewählten Ordner gespeichert werden. Die Z-Naht wird nicht in der Modelldatei "
                "festgelegt, sondern anschließend im Slicer positioniert."
            ),
            foreground="#555",
            wraplength=1060,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 12))

        left = ttk.LabelFrame(outer, text="Untersuchungsobjekte", padding=8)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(left, width=48, height=22, exportselection=False, font=("Segoe UI", 10))
        y_scroll = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        x_scroll = ttk.Scrollbar(left, orient="horizontal", command=self.listbox.xview)
        self.listbox.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.keys = list(MODEL_SPECS)
        for key in self.keys:
            self.listbox.insert("end", MODEL_SPECS[key].label)
        self.listbox.selection_set(0)
        self.listbox.bind("<<ListboxSelect>>", self._selection_changed)

        right = ttk.LabelFrame(outer, text="Beschreibung und Export", padding=12)
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        self.title_var = tk.StringVar()
        self.meta_var = tk.StringVar()
        ttk.Label(right, textvariable=self.title_var, font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(right, textvariable=self.meta_var, foreground="#555", wraplength=650, justify="left").grid(
            row=1, column=0, sticky="w", pady=(4, 10)
        )

        self.detail = tk.Text(right, wrap="word", height=20, padx=10, pady=10, font=("Segoe UI", 10))
        detail_scroll = ttk.Scrollbar(right, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.grid(row=3, column=0, sticky="nsew")
        detail_scroll.grid(row=3, column=1, sticky="ns")

        buttons = ttk.Frame(right)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(buttons, text="Als STL speichern…", command=self.save_stl).pack(side="left")
        ttk.Button(buttons, text="Als STEP speichern…", command=self.save_step).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Schließen", command=self.destroy).pack(side="right")

        self._selection_changed()

    def _current_key(self) -> str:
        selection = self.listbox.curselection()
        if not selection:
            return "reference"
        return self.keys[int(selection[0])]

    def _selection_changed(self, _event=None):
        key = self._current_key()
        model = MODEL_SPECS[key]
        self.title_var.set(model.label)

        if key == "reference_batch":
            template = TEMPLATES["reference"]
            purpose = (
                "Bauraumanordnung für die gemeinsame Fertigung von neun Referenzuntersuchungsobjekten. "
                "Die Zuordnung und Auswertung erfolgt anschließend weiterhin für jede Druckbettposition getrennt."
            )
            self.meta_var.set("Prüfstufe: Bauraumprüfung | 3×3-Raster mit 9 Positionen")
        else:
            template = TEMPLATES[key]
            purpose = template.description
            target = "nicht festgelegt" if template.target_n is None else f"n = {template.target_n}"
            self.meta_var.set(f"Prüfstufe: {template.default_study_type} | empfohlener Umfang: {target}")

        feature_lines = []
        for feature_key in template.features:
            spec = FEATURES.get(feature_key)
            if spec is not None:
                feature_lines.append(f"• {spec.label} – {spec.role}")

        text = (
            f"Zweck\n{purpose}\n\n"
            f"Modellgeometrie\n{model.description}\n{model.dimensions_note}\n\n"
            "Auswertemerkmale\n" + "\n".join(feature_lines) + "\n\n"
            f"Z-Naht\nAktuelle Strategie: {self.settings.seam_position}.\n"
            "Die Nahtposition wird im Slicer festgelegt und vor dem Druck kontrolliert.\n\n"
            "Dateiformate\n"
            "Die STL-Datei enthält die triangulierte Druckgeometrie. Die STEP-Datei bildet dieselbe Geometrie als "
            "facettierte B-Rep ab. Sie eignet sich für den neutralen Datenaustausch, enthält jedoch keine parametrische "
            "Feature-Historie eines ursprünglichen CAD-Modells."
        )
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def save_stl(self):
        key = self._current_key()
        spec = MODEL_SPECS[key]
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Untersuchungsobjekt als STL speichern",
            initialfile=f"{spec.cad_basename}.stl",
            defaultextension=".stl",
            filetypes=[("STL-Datei", "*.stl")],
        )
        if not path:
            return
        try:
            export_model(key, path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("STL-Export", str(exc), parent=self)
            return
        messagebox.showinfo("STL-Export", "Die STL-Datei wurde gespeichert.", parent=self)

    def save_step(self):
        key = self._current_key()
        spec = MODEL_SPECS[key]
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Untersuchungsobjekt als STEP speichern",
            initialfile=f"{spec.cad_basename}.step",
            defaultextension=".step",
            filetypes=[("STEP-Datei", "*.step"), ("STP-Datei", "*.stp")],
        )
        if not path:
            return
        try:
            export_step_model(key, path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("STEP-Export", str(exc), parent=self)
            return
        messagebox.showinfo("STEP-Export", "Die STEP-Datei wurde gespeichert.", parent=self)
