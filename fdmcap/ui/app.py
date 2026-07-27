"""Hauptoberfläche der FDM-Capability-Workbench."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..config import APP_TITLE, PROGRAM_VERSION, STUDY_TYPES, TEMPLATES
from ..io import load_measurements_csv, load_project, save_measurements_csv, save_project
from ..models import MeasurementRecord, ProjectData
from .dialogs import HelpWindow, MeasurementDialog, MethodWindow, SettingsDialog
from .library import SpecimenLibraryWindow
from .results import ResultWindow


class FDMCapabilityApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_TITLE} {PROGRAM_VERSION}")
        self.root.geometry("1360x840")
        self.root.minsize(1060, 680)
        self.project = ProjectData()
        self.current_path: str | None = None
        self.dirty = False

        self.study_filter_var = tk.StringVar(value="Alle Prüfstufen")
        self.template_filter_var = tk.StringVar(value="Alle Untersuchungsobjekte")
        self.material_filter_var = tk.StringVar(value="Alle Materialien")
        self.status_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.subtitle_var = tk.StringVar(value="Messdaten verwalten, Untersuchungsobjekte dokumentieren und merkmalbezogen auswerten")
        self.card_vars = {key: tk.StringVar(value="0") for key in ("records", "visible", "configurations", "materials")}

        self._build_menu()
        self._build_ui()
        self.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_menu(self):
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Neues Projekt", command=self.new_project, accelerator="Ctrl+N")
        file_menu.add_command(label="Projekt öffnen…", command=self.open_project, accelerator="Ctrl+O")
        file_menu.add_command(label="Projekt speichern", command=self.save_project, accelerator="Ctrl+S")
        file_menu.add_command(label="Projekt speichern unter…", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="CSV importieren…", command=self.import_csv)
        file_menu.add_command(label="Messdaten als CSV exportieren…", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Beenden", command=self.close)
        menu.add_cascade(label="Datei", menu=file_menu)

        menu.add_command(label="Projekteinstellungen", command=self.edit_settings)

        menu.add_command(label="Untersuchungsobjekte", command=self.show_specimen_library)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Programmhilfe…", command=self.show_help)
        help_menu.add_command(label="Prüfablauf und Messstrategie…", command=self.show_method)
        menu.add_cascade(label="Hilfe", menu=help_menu)

        self.root.configure(menu=menu)
        self.root.bind("<Control-n>", lambda _e: self.new_project())
        self.root.bind("<Control-o>", lambda _e: self.open_project())
        self.root.bind("<Control-s>", lambda _e: self.save_project())

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, textvariable=self.title_var, font=("Segoe UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.subtitle_var, foreground="#555").grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(header, text="Auswerten", command=self.evaluate).grid(row=0, column=1, rowspan=2, padx=(10, 0), ipady=4)

        cards = ttk.Frame(outer)
        cards.grid(row=1, column=0, sticky="ew", pady=(14, 10))
        for col in range(4):
            cards.columnconfigure(col, weight=1, uniform="cards")
        card_specs = (
            ("records", "Messzeilen gesamt"),
            ("visible", "Im Filter sichtbar"),
            ("configurations", "Konfigurationen"),
            ("materials", "Materialien"),
        )
        for col, (key, label) in enumerate(card_specs):
            frame = ttk.LabelFrame(cards, text=label, padding=(12, 8))
            frame.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0))
            ttk.Label(frame, textvariable=self.card_vars[key], font=("Segoe UI", 17, "bold")).pack(anchor="w")

        filters = ttk.LabelFrame(outer, text="Ansicht eingrenzen", padding=8)
        filters.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for col in (0, 1, 2):
            filters.columnconfigure(col, weight=1, uniform="filter")
        self._build_filter_cell(filters, 0, "Prüfstufe", "study")
        self._build_filter_cell(filters, 1, "Untersuchungsobjekt", "template")
        self._build_filter_cell(filters, 2, "Material", "material")
        ttk.Button(filters, text="Filter zurücksetzen", command=self.reset_filters).grid(row=1, column=3, sticky="ew", padx=(8, 0))
        for combo in (self.study_combo, self.template_combo, self.material_combo):
            combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table())

        toolbar = ttk.Frame(outer)
        toolbar.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="Messung hinzufügen", command=self.add_record).pack(side="left")
        ttk.Button(toolbar, text="Bearbeiten", command=self.edit_record).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Löschen", command=self.delete_records).pack(side="left", padx=(8, 0))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(toolbar, text="CSV importieren", command=self.import_csv).pack(side="left")
        ttk.Button(toolbar, text="CSV exportieren", command=self.export_csv).pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, text="Doppelklick auf eine Zeile: bearbeiten", foreground="#555").pack(side="right")

        pane = ttk.PanedWindow(outer, orient="horizontal")
        pane.grid(row=4, column=0, sticky="nsew")

        table_frame = ttk.LabelFrame(pane, text="Messdaten", padding=8)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        pane.add(table_frame, weight=4)
        columns = ("id", "study", "template", "material", "config", "batch", "position")
        headings = {
            "id": "Nr.", "study": "Prüfstufe", "template": "Untersuchungsobjekt", "material": "Material",
            "config": "Konfiguration", "batch": "Batch", "position": "Position",
        }
        widths = {"id": 55, "study": 165, "template": 240, "material": 80, "config": 290, "batch": 70, "position": 125}
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], minwidth=45, stretch=(col in {"study", "template", "config"}))
        ybar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", lambda _e: self.edit_record())
        self.tree.bind("<<TreeviewSelect>>", self.update_record_detail)

        detail_frame = ttk.LabelFrame(pane, text="Ausgewählte Messzeile", padding=8)
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(1, weight=1)
        pane.add(detail_frame, weight=2)
        self.detail_title_var = tk.StringVar(value="Keine Messzeile ausgewählt")
        ttk.Label(detail_frame, textvariable=self.detail_title_var, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.detail_text = tk.Text(detail_frame, wrap="word", padx=10, pady=10, font=("Segoe UI", 10), width=42)
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.grid(row=1, column=0, sticky="nsew")
        detail_scroll.grid(row=1, column=1, sticky="ns")
        detail_buttons = ttk.Frame(detail_frame)
        detail_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(detail_buttons, text="Bearbeiten", command=self.edit_record).pack(side="left")

        status = ttk.Frame(outer)
        status.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, foreground="#555").grid(row=0, column=0, sticky="w")
        ttk.Button(status, text="Projekteinstellungen", command=self.edit_settings).grid(row=0, column=1)

    def _build_filter_cell(self, parent: ttk.LabelFrame, column: int, label: str, kind: str):
        ttk.Label(parent, text=label).grid(row=0, column=column, sticky="w", padx=(0, 8))
        if kind == "study":
            self.study_combo = ttk.Combobox(parent, textvariable=self.study_filter_var, state="readonly")
            widget = self.study_combo
        elif kind == "template":
            self.template_combo = ttk.Combobox(parent, textvariable=self.template_filter_var, state="readonly")
            widget = self.template_combo
        else:
            self.material_combo = ttk.Combobox(parent, textvariable=self.material_filter_var, state="readonly")
            widget = self.material_combo
        widget.grid(row=1, column=column, sticky="ew", padx=(0, 10), pady=(2, 0))

    def filtered_records(self) -> list[MeasurementRecord]:
        records = self.project.records
        study = self.study_filter_var.get()
        template_label = self.template_filter_var.get()
        material = self.material_filter_var.get()
        if study != "Alle Prüfstufen":
            records = [r for r in records if r.study_type == study]
        if template_label != "Alle Untersuchungsobjekte":
            keys = [key for key, spec in TEMPLATES.items() if spec.label == template_label]
            records = [r for r in records if r.template_key in keys]
        if material != "Alle Materialien":
            records = [r for r in records if r.material == material]
        return records

    def refresh(self):
        self.title_var.set(self.project.settings.project_name + (" *" if self.dirty else ""))
        studies = ["Alle Prüfstufen"] + sorted(set(STUDY_TYPES).union(r.study_type for r in self.project.records))
        templates = ["Alle Untersuchungsobjekte"] + [spec.label for spec in TEMPLATES.values()]
        materials = ["Alle Materialien"] + sorted({r.material for r in self.project.records if r.material})
        self.study_combo.configure(values=studies)
        self.template_combo.configure(values=templates)
        self.material_combo.configure(values=materials)
        if self.study_filter_var.get() not in studies:
            self.study_filter_var.set(studies[0])
        if self.template_filter_var.get() not in templates:
            self.template_filter_var.set(templates[0])
        if self.material_filter_var.get() not in materials:
            self.material_filter_var.set(materials[0])
        self.refresh_table()

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        records = self.filtered_records()
        for record in records:
            template = TEMPLATES.get(record.template_key)
            label = template.label if template else record.template_key
            self.tree.insert("", "end", iid=record.record_id, values=(
                record.specimen_id,
                record.study_type,
                label,
                record.material,
                record.configuration,
                record.batch,
                record.bed_position,
            ))
        configurations = {(r.configuration, r.material) for r in self.project.records}
        materials = {r.material for r in self.project.records if r.material}
        self.card_vars["records"].set(str(len(self.project.records)))
        self.card_vars["visible"].set(str(len(records)))
        self.card_vars["configurations"].set(str(len(configurations)))
        self.card_vars["materials"].set(str(len(materials)))
        self.status_var.set(
            f"r = {self.project.settings.resolution_mm:.3f} mm | "
            f"Bewertungsbereich ± {self.project.settings.tolerance_half_width_mm:.2f} mm | "
            f"Orientierungsgrenze {self.project.settings.capability_orientation:.2f} | "
            f"Z-Naht: {self.project.settings.seam_position}"
        )
        self.title_var.set(self.project.settings.project_name + (" *" if self.dirty else ""))
        self.update_record_detail()

    def update_record_detail(self, _event=None):
        record = self.selected_record()
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        if record is None:
            self.detail_title_var.set("Keine Messzeile ausgewählt")
            self.detail_text.insert("1.0", "Wähle links eine Messzeile aus. Die Messwerte und die vollständige Zuordnung werden hier kompakt angezeigt.")
        else:
            template = TEMPLATES.get(record.template_key)
            self.detail_title_var.set(f"{template.label if template else record.template_key} – Nr. {record.specimen_id}")
            lines = [
                f"Prüfstufe: {record.study_type}",
                f"Konfiguration: {record.configuration or 'nicht angegeben'}",
                f"Material: {record.material or 'nicht angegeben'}",
                f"Batch: {record.batch or '–'}",
                f"Druckbettposition: {record.bed_position or '–'}",
                "",
                "Messwerte",
                "-" * 38,
            ]
            from ..analysis import feature_spec
            for key, value in record.values.items():
                spec = feature_spec(key)
                lines.append(f"{spec.label}: {value:.3f} {spec.unit}")
            if record.note:
                lines.extend(["", "Notiz", "-" * 38, record.note])
            self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.configure(state="disabled")

    def reset_filters(self):
        self.study_filter_var.set("Alle Prüfstufen")
        self.template_filter_var.set("Alle Untersuchungsobjekte")
        self.material_filter_var.set("Alle Materialien")
        self.refresh_table()

    def _defaults_for_new_record(self):
        filtered = self.filtered_records()
        last = filtered[-1] if filtered else (self.project.records[-1] if self.project.records else None)
        return {
            "template_key": last.template_key if last else "reference",
            "study_type": last.study_type if last else "Basisprüfung",
            "configuration": last.configuration if last else self.project.settings.slicer_profile,
            "material": last.material if last else "PLA",
            "batch": last.batch if last else "1",
            "bed_position": last.bed_position if last else "Mitte",
            "specimen_id": str(len(filtered) + 1),
        }

    def add_record(self):
        dialog = MeasurementDialog(
            self.root,
            defaults=self._defaults_for_new_record(),
            settings=self.project.settings,
        )
        self.root.wait_window(dialog)
        if dialog.saved_records:
            self.project.records.extend(dialog.saved_records)
            self._mark_dirty()
        elif dialog.result:
            self.project.records.append(dialog.result)
            self._mark_dirty()

    def selected_record(self) -> MeasurementRecord | None:
        selected = self.tree.selection()
        if not selected:
            return None
        record_id = selected[0]
        return next((r for r in self.project.records if r.record_id == record_id), None)

    def edit_record(self):
        record = self.selected_record()
        if record is None:
            messagebox.showinfo("Bearbeiten", "Bitte eine Messzeile auswählen.", parent=self.root)
            return
        dialog = MeasurementDialog(self.root, record=record, settings=self.project.settings)
        self.root.wait_window(dialog)
        if dialog.result:
            index = self.project.records.index(record)
            self.project.records[index] = dialog.result
            self._mark_dirty()

    def delete_records(self):
        selected = self.tree.selection()
        if not selected:
            return
        if not messagebox.askyesno("Löschen", f"{len(selected)} Messzeile(n) löschen?", parent=self.root):
            return
        ids = set(selected)
        self.project.records = [r for r in self.project.records if r.record_id not in ids]
        self._mark_dirty()

    def edit_settings(self):
        dialog = SettingsDialog(self.root, self.project.settings)
        self.root.wait_window(dialog)
        if dialog.result:
            self.project.settings = dialog.result
            self._mark_dirty()

    def show_method(self):
        MethodWindow(self.root, self.project.settings)

    def show_help(self):
        HelpWindow(self.root, self.project.settings)

    def show_specimen_library(self):
        SpecimenLibraryWindow(self.root, self.project.settings)

    def evaluate(self):
        if not self.project.records:
            messagebox.showinfo("Auswertung", "Das Projekt enthält keine Messdaten. Füge zunächst mindestens eine Messung hinzu.", parent=self.root)
            return
        ResultWindow(self.root, self.project)

    def new_project(self):
        if not self._confirm_discard():
            return
        self.project = ProjectData()
        self.current_path = None
        self.dirty = False
        self.reset_filters()
        self.refresh()

    def open_project(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Projekt öffnen",
            filetypes=[("FDM-Projekt", "*.fdmcap.json *.json"), ("JSON", "*.json")],
        )
        if not path:
            return
        try:
            self.project = load_project(path)
        except Exception as exc:
            messagebox.showerror("Öffnen", str(exc), parent=self.root)
            return
        self.current_path = path
        self.dirty = False
        self.reset_filters()
        self.refresh()

    def save_project(self):
        if not self.current_path:
            return self.save_project_as()
        try:
            save_project(self.current_path, self.project)
        except Exception as exc:
            messagebox.showerror("Speichern", str(exc), parent=self.root)
            return False
        self.dirty = False
        self.refresh()
        return True

    def save_project_as(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Projekt speichern",
            defaultextension=".fdmcap.json",
            filetypes=[("FDM-Projekt", "*.fdmcap.json"), ("JSON", "*.json")],
        )
        if not path:
            return False
        self.current_path = path
        return self.save_project()

    def import_csv(self):
        path = filedialog.askopenfilename(parent=self.root, title="CSV importieren", filetypes=[("CSV", "*.csv"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            records, warnings = load_measurements_csv(path)
        except Exception as exc:
            messagebox.showerror("CSV-Import", str(exc), parent=self.root)
            return
        if not records:
            messagebox.showinfo("CSV-Import", "Keine Messzeilen gefunden.", parent=self.root)
            return
        mode = messagebox.askyesnocancel(
            "CSV-Import",
            f"{len(records)} Messzeilen gefunden.\n\nJa = anhängen\nNein = vorhandene Messdaten ersetzen",
            parent=self.root,
        )
        if mode is None:
            return
        if mode:
            self.project.records.extend(records)
        else:
            self.project.records = records
        self._mark_dirty()
        if warnings:
            messagebox.showinfo("CSV-Import", "\n".join(warnings), parent=self.root)

    def export_csv(self):
        if not self.project.records:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Messdaten exportieren", defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            save_measurements_csv(path, self.project.records)
        except Exception as exc:
            messagebox.showerror("CSV-Export", str(exc), parent=self.root)

    def _mark_dirty(self):
        self.dirty = True
        self.refresh()

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Ungespeicherte Änderungen", "Änderungen speichern?", parent=self.root)
        if answer is None:
            return False
        if answer:
            return bool(self.save_project())
        return True

    def close(self):
        if self._confirm_discard():
            self.root.destroy()


def run_app() -> None:
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    FDMCapabilityApp(root)
    root.mainloop()
