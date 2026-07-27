from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, sin, sqrt
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

Point = tuple[float, float, float]
Triangle = tuple[Point, Point, Point]


def _translate_triangles(triangles: Iterable[Triangle], dx: float, dy: float, dz: float = 0.0) -> list[Triangle]:
    return [
        tuple((x + dx, y + dy, z + dz) for x, y, z in triangle)  # type: ignore[misc]
        for triangle in triangles
    ]


@dataclass(frozen=True)
class STLModelSpec:
    key: str
    label: str
    filename: str
    cad_basename: str
    description: str
    dimensions_note: str
    generator: Callable[[], list[Triangle]]


def _normal(triangle: Triangle) -> Point:
    (a, b, c) = triangle
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-15:
        return 0.0, 0.0, 0.0
    return nx / length, ny / length, nz / length


def write_ascii_stl(path: str | Path, triangles: Iterable[Triangle], *, solid_name: str = "fdmcap_model") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"solid {solid_name}\n")
        for tri in triangles:
            nx, ny, nz = _normal(tri)
            handle.write(f"  facet normal {nx:.9g} {ny:.9g} {nz:.9g}\n")
            handle.write("    outer loop\n")
            for x, y, z in tri:
                handle.write(f"      vertex {x:.9g} {y:.9g} {z:.9g}\n")
            handle.write("    endloop\n  endfacet\n")
        handle.write(f"endsolid {solid_name}\n")
    return target




def _step_string(value: str) -> str:
    """Kodiert Unicode-Zeichen STEP-konform mit der X2-Darstellung."""
    chunks: list[str] = []
    unicode_buffer: list[str] = []

    def flush_unicode() -> None:
        if not unicode_buffer:
            return
        encoded = "".join(char.encode("utf-16-be").hex().upper() for char in unicode_buffer)
        chunks.append(f"\\X2\\{encoded}\\X0\\")
        unicode_buffer.clear()

    for char in str(value):
        if 32 <= ord(char) <= 126:
            flush_unicode()
            chunks.append("''" if char == "'" else char)
        else:
            unicode_buffer.append(char)
    flush_unicode()
    return "".join(chunks)


def _step_number(value: float) -> str:
    number = f"{float(value):.12g}"
    if "e" in number.lower():
        mantissa, exponent = number.lower().split("e")
        number = f"{mantissa}E{int(exponent):+d}"
    elif "." not in number:
        number += "."
    return number


def _triangle_components(triangles: Sequence[Triangle]) -> list[list[int]]:
    """Gruppiert Dreiecke über gemeinsam verwendete Eckpunkte zu separaten Schalen."""
    vertex_to_triangles: dict[Point, list[int]] = {}
    for index, triangle in enumerate(triangles):
        for point in triangle:
            vertex_to_triangles.setdefault(point, []).append(index)
    adjacency: list[set[int]] = [set() for _ in triangles]
    for indices in vertex_to_triangles.values():
        for index in indices:
            adjacency[index].update(indices)
    components: list[list[int]] = []
    unseen = set(range(len(triangles)))
    while unseen:
        start = unseen.pop()
        stack = [start]
        component = [start]
        while stack:
            current = stack.pop()
            neighbours = adjacency[current] & unseen
            if neighbours:
                unseen.difference_update(neighbours)
                stack.extend(neighbours)
                component.extend(neighbours)
        components.append(component)
    return components


def write_faceted_step(
    path: str | Path,
    triangles: Iterable[Triangle],
    *,
    model_name: str = "FDM-Capability-Workbench model",
) -> Path:
    """Schreibt eine ISO-10303-21-Datei als facettierte B-Rep.

    Der Export bildet die triangulierte Modellgeometrie ab. Er eignet sich für den neutralen
    Datenaustausch, enthält aber keine editierbare parametrische Feature-Historie.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    triangle_list = [tuple(tuple(float(v) for v in point) for point in triangle) for triangle in triangles]
    if not triangle_list:
        raise ValueError("Das Untersuchungsobjekt enthält keine exportierbare Geometrie.")

    lines: list[str] = []
    entity_id = 1

    def entity(expression: str) -> int:
        nonlocal entity_id
        current = entity_id
        lines.append(f"#{current}={expression};")
        entity_id += 1
        return current

    app_context = entity("APPLICATION_CONTEXT('configuration controlled 3d designs of mechanical parts and assemblies')")
    entity(f"APPLICATION_PROTOCOL_DEFINITION('international standard','config_control_design',1994,#{app_context})")
    design_context = entity(f"DESIGN_CONTEXT('',#{app_context},'design')")
    mech_context = entity(f"MECHANICAL_CONTEXT('',#{app_context},'mechanical')")
    product = entity(f"PRODUCT('{_step_string(model_name)}','{_step_string(model_name)}','',(#{mech_context}))")
    formation = entity(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',#{product},.NOT_KNOWN.)")
    definition = entity(f"PRODUCT_DEFINITION('design','',#{formation},#{design_context})")
    definition_shape = entity(f"PRODUCT_DEFINITION_SHAPE('','',#{definition})")
    length_unit = entity("(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))")
    angle_unit = entity("(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))")
    solid_angle_unit = entity("(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())")
    uncertainty = entity(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-6),#{length_unit},'distance_accuracy_value','')")
    context = entity(
        f"(GEOMETRIC_REPRESENTATION_CONTEXT(3) "
        f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{uncertainty})) "
        f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{length_unit},#{angle_unit},#{solid_angle_unit})) "
        "REPRESENTATION_CONTEXT('',''))"
    )

    unique_points: dict[Point, int] = {}
    for triangle in triangle_list:
        for point in triangle:
            if point not in unique_points:
                unique_points[point] = entity(
                    "CARTESIAN_POINT('',(" + ",".join(_step_number(value) for value in point) + "))"
                )

    face_ids: list[int] = []
    triangle_face_ids: list[int] = []
    for triangle in triangle_list:
        point_refs = ",".join(f"#{unique_points[point]}" for point in triangle)
        loop = entity(f"POLY_LOOP('',({point_refs}))")
        bound = entity(f"FACE_OUTER_BOUND('',#{loop},.T.)")
        face = entity(f"FACE('',(#{bound}))")
        triangle_face_ids.append(face)

    brep_ids: list[int] = []
    for shell_index, component in enumerate(_triangle_components(triangle_list), start=1):
        refs = ",".join(f"#{triangle_face_ids[index]}" for index in component)
        shell = entity(f"CLOSED_SHELL('Schale {shell_index}',({refs}))")
        brep_ids.append(entity(f"FACETED_BREP('Schale {shell_index}',#{shell})"))

    representation_items = ",".join(f"#{item}" for item in brep_ids)
    representation = entity(
        f"FACETED_BREP_SHAPE_REPRESENTATION('{_step_string(model_name)}',({representation_items}),#{context})"
    )
    entity(f"SHAPE_DEFINITION_REPRESENTATION(#{definition_shape},#{representation})")

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    header = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('Faceted model exported by FDM-Capability-Workbench'),'2;1');",
        (
            "FILE_NAME("
            f"'{_step_string(target.name)}','{timestamp}',"
            "('FDM-Capability-Workbench'),(''),'FDM-Capability-Workbench 1.5.0',"
            "'FDM-Capability-Workbench','');"
        ),
        "FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));",
        "ENDSEC;",
        "DATA;",
    ]
    footer = ["ENDSEC;", "END-ISO-10303-21;"]
    target.write_text("\n".join(header + lines + footer) + "\n", encoding="ascii", errors="strict")
    return target


def _box(cx: float, cy: float, z0: float, sx: float, sy: float, sz: float) -> list[Triangle]:
    x0, x1 = cx - sx / 2, cx + sx / 2
    y0, y1 = cy - sy / 2, cy + sy / 2
    z1 = z0 + sz
    p000 = (x0, y0, z0); p100 = (x1, y0, z0); p110 = (x1, y1, z0); p010 = (x0, y1, z0)
    p001 = (x0, y0, z1); p101 = (x1, y0, z1); p111 = (x1, y1, z1); p011 = (x0, y1, z1)
    return [
        (p000, p110, p100), (p000, p010, p110),
        (p001, p101, p111), (p001, p111, p011),
        (p000, p100, p101), (p000, p101, p001),
        (p100, p110, p111), (p100, p111, p101),
        (p110, p010, p011), (p110, p011, p111),
        (p010, p000, p001), (p010, p001, p011),
    ]


def _regular_prism(sides: int, across_flats: float, z0: float, height: float, *, rotation_deg: float = 22.5) -> list[Triangle]:
    radius = across_flats / (2.0 * cos(pi / sides))
    rotation = rotation_deg * pi / 180.0
    bottom = [(radius * cos(rotation + 2*pi*i/sides), radius * sin(rotation + 2*pi*i/sides), z0) for i in range(sides)]
    top = [(x, y, z0 + height) for x, y, _ in bottom]
    triangles: list[Triangle] = []
    cb = (0.0, 0.0, z0)
    ct = (0.0, 0.0, z0 + height)
    for i in range(sides):
        j = (i + 1) % sides
        triangles.append((cb, bottom[j], bottom[i]))
        triangles.append((ct, top[i], top[j]))
        triangles.append((bottom[i], bottom[j], top[j]))
        triangles.append((bottom[i], top[j], top[i]))
    return triangles


def _cylinder(radius: float, z0: float, height: float, *, segments: int = 96, cx: float = 0.0, cy: float = 0.0) -> list[Triangle]:
    bottom = [(cx + radius*cos(2*pi*i/segments), cy + radius*sin(2*pi*i/segments), z0) for i in range(segments)]
    top = [(x, y, z0 + height) for x, y, _ in bottom]
    triangles: list[Triangle] = []
    cb = (cx, cy, z0); ct = (cx, cy, z0 + height)
    for i in range(segments):
        j = (i + 1) % segments
        triangles.append((cb, bottom[j], bottom[i]))
        triangles.append((ct, top[i], top[j]))
        triangles.append((bottom[i], bottom[j], top[j]))
        triangles.append((bottom[i], top[j], top[i]))
    return triangles


def _annular_cylinder(inner_radius: float, outer_radius: float, z0: float, height: float, *, segments: int = 96, cx: float = 0.0, cy: float = 0.0) -> list[Triangle]:
    ob = [(cx + outer_radius*cos(2*pi*i/segments), cy + outer_radius*sin(2*pi*i/segments), z0) for i in range(segments)]
    ot = [(x, y, z0 + height) for x, y, _ in ob]
    ib = [(cx + inner_radius*cos(2*pi*i/segments), cy + inner_radius*sin(2*pi*i/segments), z0) for i in range(segments)]
    it = [(x, y, z0 + height) for x, y, _ in ib]
    triangles: list[Triangle] = []
    for i in range(segments):
        j = (i + 1) % segments
        triangles.extend([
            (ob[i], ob[j], ot[j]), (ob[i], ot[j], ot[i]),
            (ib[i], it[j], ib[j]), (ib[i], it[i], it[j]),
            (ot[i], ot[j], it[j]), (ot[i], it[j], it[i]),
            (ob[i], ib[j], ob[j]), (ob[i], ib[i], ib[j]),
        ])
    return triangles


def _square_frame(cx: float, cy: float, inner: float, wall: float, z0: float, height: float) -> list[Triangle]:
    """Watertight quadratischer Rahmen ohne überlappende Teilkörper."""
    outer = inner + 2 * wall
    oh = outer / 2.0
    ih = inner / 2.0
    outer_bottom = [(cx-oh,cy-oh,z0),(cx+oh,cy-oh,z0),(cx+oh,cy+oh,z0),(cx-oh,cy+oh,z0)]
    outer_top = [(x,y,z0+height) for x,y,_ in outer_bottom]
    inner_bottom = [(cx-ih,cy-ih,z0),(cx+ih,cy-ih,z0),(cx+ih,cy+ih,z0),(cx-ih,cy+ih,z0)]
    inner_top = [(x,y,z0+height) for x,y,_ in inner_bottom]
    triangles: list[Triangle] = []
    for i in range(4):
        j=(i+1)%4
        triangles += [
            (outer_bottom[i], outer_bottom[j], outer_top[j]),
            (outer_bottom[i], outer_top[j], outer_top[i]),
            (inner_bottom[i], inner_top[j], inner_bottom[j]),
            (inner_bottom[i], inner_top[i], inner_top[j]),
            (outer_top[i], outer_top[j], inner_top[j]),
            (outer_top[i], inner_top[j], inner_top[i]),
            (outer_bottom[i], inner_bottom[j], outer_bottom[j]),
            (outer_bottom[i], inner_bottom[i], inner_bottom[j]),
        ]
    return triangles


def _heightfield_block(x_edges: Sequence[float], y_edges: Sequence[float], heights: Sequence[Sequence[float]]) -> list[Triangle]:
    """Erzeugt einen watertight Block mit zellweise konstanten Oberflächenhöhen."""
    nx = len(x_edges) - 1
    ny = len(y_edges) - 1
    if len(heights) != nx or any(len(row) != ny for row in heights):
        raise ValueError("Höhenmatrix passt nicht zu den Zellkanten.")
    triangles: list[Triangle] = []
    # Oberseiten
    for i in range(nx):
        for j in range(ny):
            x0, x1 = x_edges[i], x_edges[i+1]
            y0, y1 = y_edges[j], y_edges[j+1]
            h = float(heights[i][j])
            triangles += [
                ((x0,y0,h),(x1,y0,h),(x1,y1,h)),
                ((x0,y0,h),(x1,y1,h),(x0,y1,h)),
            ]
    # Unterseite zellweise triangulieren. Die Unterteilung muss mit den Außenwänden
    # übereinstimmen; eine einzige große Fläche würde an den Zwischenknoten T-Kanten bilden.
    for i in range(nx):
        for j in range(ny):
            x0, x1 = x_edges[i], x_edges[i + 1]
            y0, y1 = y_edges[j], y_edges[j + 1]
            triangles += [
                ((x0, y0, 0.0), (x1, y1, 0.0), (x1, y0, 0.0)),
                ((x0, y0, 0.0), (x0, y1, 0.0), (x1, y1, 0.0)),
            ]

    def quad(a: Point, b: Point, c: Point, d: Point):
        triangles.extend([(a,b,c),(a,c,d)])

    # Außenwände x
    for j in range(ny):
        ya, yb = y_edges[j], y_edges[j+1]
        hl = float(heights[0][j]); hr = float(heights[-1][j])
        quad((x_edges[0],ya,0.0),(x_edges[0],yb,0.0),(x_edges[0],yb,hl),(x_edges[0],ya,hl))
        quad((x_edges[-1],ya,0.0),(x_edges[-1],ya,hr),(x_edges[-1],yb,hr),(x_edges[-1],yb,0.0))
    # Außenwände y
    for i in range(nx):
        xa, xb = x_edges[i], x_edges[i+1]
        hb = float(heights[i][0]); ht = float(heights[i][-1])
        quad((xa,y_edges[0],0.0),(xa,y_edges[0],hb),(xb,y_edges[0],hb),(xb,y_edges[0],0.0))
        quad((xa,y_edges[-1],0.0),(xb,y_edges[-1],0.0),(xb,y_edges[-1],ht),(xa,y_edges[-1],ht))
    # Innere x-Stufenwände oberhalb des niedrigeren Nachbarn
    for i in range(nx-1):
        x = x_edges[i+1]
        for j in range(ny):
            y0c, y1c = y_edges[j], y_edges[j+1]
            h1, h2 = float(heights[i][j]), float(heights[i+1][j])
            if abs(h1-h2) < 1e-12:
                continue
            lo, hi = sorted((h1,h2))
            quad((x,y0c,lo),(x,y1c,lo),(x,y1c,hi),(x,y0c,hi))
    # Innere y-Stufenwände
    for j in range(ny-1):
        y = y_edges[j+1]
        for i in range(nx):
            x0c, x1c = x_edges[i], x_edges[i+1]
            h1, h2 = float(heights[i][j]), float(heights[i][j+1])
            if abs(h1-h2) < 1e-12:
                continue
            lo, hi = sorted((h1,h2))
            quad((x0c,y,lo),(x1c,y,lo),(x1c,y,hi),(x0c,y,hi))
    return triangles


def reference_model() -> list[Triangle]:
    """Achteckiger Arbeits-Referenzkörper mit 20-mm-Messzone und Ø20-mm-Zylinder."""
    triangles: list[Triangle] = []
    # Gesamt-Z-Höhe 20 mm: Basis 3, Messkörper 7, obere Auflage 3, Zylinder 7.
    triangles += _regular_prism(8, 30.0, 0.0, 3.0)
    triangles += _regular_prism(8, 20.0, 3.0, 7.0)
    triangles += _regular_prism(8, 30.0, 10.0, 3.0)
    triangles += _cylinder(10.0, 13.0, 7.0)
    return triangles


def outer_stack_model() -> list[Triangle]:
    triangles: list[Triangle] = []
    z = 0.0
    for size in (40.0, 30.0, 20.0, 10.0):
        triangles += _box(0.0, 0.0, z, size, size, 5.0)
        z += 5.0
    return triangles


def cylinder_stack_model() -> list[Triangle]:
    triangles: list[Triangle] = []
    z = 0.0
    for diameter in (40.0, 30.0, 20.0, 10.0):
        triangles += _cylinder(diameter / 2.0, z, 5.0)
        z += 5.0
    return triangles


def inner_circle_model() -> list[Triangle]:
    triangles: list[Triangle] = []
    sizes = (10.0, 15.0, 20.0)
    x_positions = (-28.0, 0.0, 30.0)
    for x, size in zip(x_positions, sizes):
        triangles += _annular_cylinder(size / 2.0, size / 2.0 + 3.0, 0.0, 8.0, cx=x, cy=0.0)
    return triangles


def inner_square_model() -> list[Triangle]:
    triangles: list[Triangle] = []
    sizes = (10.0, 15.0, 20.0)
    x_positions = (-28.0, 0.0, 30.0)
    for x, size in zip(x_positions, sizes):
        triangles += _square_frame(x, 0.0, size, 3.0, 0.0, 8.0)
    return triangles


def reference_batch_model() -> list[Triangle]:
    """3×3-Bauraumanordnung aus neun Referenzuntersuchungsobjekten."""
    triangles: list[Triangle] = []
    source = reference_model()
    pitch = 48.0
    for row in (-1, 0, 1):
        for column in (-1, 0, 1):
            triangles += _translate_triangles(source, column * pitch, row * pitch)
    return triangles


def depth_steps_model() -> list[Triangle]:
    """Stufenuntersuchungsobjekt mit 15 Tiefen relativ zu zwei 20-mm-Referenzschienen.

    Die geschlossenen Teilvolumen überlappen sich um 0,02 mm. Dadurch vermeiden wir
    nicht-manifold T-Kanten an den unterschiedlichen Stufenhöhen; gängige Slicer vereinigen
    diese minimale Überlappung beim Import zu einem zusammenhängenden Druckkörper.
    """
    triangles: list[Triangle] = []
    step_width = 5.0
    total_length = 15 * step_width
    base_height = 2.0
    reference_height = 20.0
    rail_width = 5.0
    center_width = 20.0
    overlap = 0.02

    triangles += _box(0.0, 0.0, 0.0, total_length, center_width + 2 * rail_width, base_height)
    rail_y = center_width / 2.0 + rail_width / 2.0
    z0 = base_height - overlap
    triangles += _box(0.0, rail_y - overlap / 2.0, z0, total_length, rail_width + overlap, reference_height - z0)
    triangles += _box(0.0, -rail_y + overlap / 2.0, z0, total_length, rail_width + overlap, reference_height - z0)

    x_start = -total_length / 2.0 + step_width / 2.0
    for depth in range(1, 16):
        top_height = reference_height - float(depth)
        x = x_start + (depth - 1) * step_width
        triangles += _box(
            x,
            0.0,
            z0,
            step_width + overlap,
            center_width + overlap,
            top_height - z0,
        )
    return triangles


def gaps_model() -> list[Triangle]:
    """Kombiniertes Spalt-/Dünnwandmodell mit Merkmalen in X und Y.

    Spalte: 1/2/3/4/5/10 mm in X und Y.
    Dünnwände: 0,4 bis 1,0 mm in 0,1-mm-Schritten in X und Y.
    """
    triangles: list[Triangle] = []
    gaps = (1.0, 2.0, 3.0, 4.0, 5.0, 10.0)
    web_widths = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)

    # Gemeinsame Grundplatte; die vier Merkmalsreihen bleiben räumlich getrennt.
    triangles += _box(0.0, 0.0, 0.0, 118.0, 88.0, 2.0)

    # Spaltmerkmale. X bedeutet, dass die Spaltbreite in X-Richtung gemessen wird;
    # Y entsprechend in Y-Richtung.
    for row, axis in enumerate(("x", "y")):
        y = 30.0 if row == 0 else 10.0
        for i, gap in enumerate(gaps):
            x = -45.0 + i * 18.0
            wall = 3.0
            length = 12.0
            height = 8.0
            if axis == "x":
                triangles += _box(x - gap / 2 - wall / 2, y, 2.0, wall, length, height)
                triangles += _box(x + gap / 2 + wall / 2, y, 2.0, wall, length, height)
            else:
                triangles += _box(x, y - gap / 2 - wall / 2, 2.0, length, wall, height)
                triangles += _box(x, y + gap / 2 + wall / 2, 2.0, length, wall, height)

    # Dünnwandmerkmale. X-Wände besitzen ihre Sollbreite in X-Richtung und laufen
    # längs in Y; Y-Wände entsprechend um 90° gedreht.
    for row, axis in enumerate(("x", "y")):
        y = -14.0 if row == 0 else -34.0
        for i, width in enumerate(web_widths):
            x = -48.0 + i * 16.0
            length = 12.0
            height = 8.0
            if axis == "x":
                triangles += _box(x, y, 2.0, width, length, height)
            else:
                triangles += _box(x, y, 2.0, length, width, height)
    return triangles


def webs_model() -> list[Triangle]:
    triangles: list[Triangle] = []
    widths = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2)
    triangles += _box(0.0, 0.0, 0.0, 90.0, 26.0, 2.0)
    for index, width in enumerate(widths):
        x = -40.0 + index * 10.0
        triangles += _box(x, 0.0, 2.0, width, 16.0, 8.0)
    return triangles


MODEL_SPECS: dict[str, STLModelSpec] = {
    "reference": STLModelSpec(
        "reference", "Referenzuntersuchungsobjekt", "referenzpruefkoerper_20mm.stl",
        "fdm_referenzuntersuchungsobjekt_20mm",
        "Achteckiger Referenzkörper mit vier XY-Messrichtungen, Z-Höhe und Ø20-mm-Zylinder.",
        "Mittlere Achteck-Messzone 20 mm über Flächen, Z-Gesamthöhe 20 mm, Zylinder Ø20 mm.",
        reference_model,
    ),
    "reference_batch": STLModelSpec(
        "reference_batch", "Referenzuntersuchungsobjekt – Bauraumanordnung", "referenzuntersuchungsobjekt_batch_20mm.stl",
        "fdm_referenzuntersuchungsobjekt_batch_20mm",
        "3×3-Anordnung des Referenzuntersuchungsobjekts für die Bauraumprüfung.",
        "Neun identische Referenzuntersuchungsobjekte in einem 3×3-Raster; die Messwerte werden weiterhin je Position einzeln erfasst.",
        reference_batch_model,
    ),
    "outer_stack": STLModelSpec(
        "outer_stack", "Außenmaßstapel", "aussenmassstapel_10_20_30_40mm.stl",
        "fdm_aussenmassstapel_10_20_30_40mm",
        "Verbundener Stapel für das größenbezogene Außenmaßprofil.",
        "Vier zentrierte Stufen mit 40/30/20/10 mm und jeweils 5 mm Höhe.",
        outer_stack_model,
    ),
    "cylinder_stack": STLModelSpec(
        "cylinder_stack", "Zylinderstapel", "zylinderstapel_10_20_30_40mm.stl",
        "fdm_zylinderstapel_d10_d20_d30_d40mm",
        "Verbundener Zylinderstapel für nahtfreie und optionale nahtbezogene Zweipunktmaße.",
        "Vier zentrierte Zylinder mit Ø40/30/20/10 mm und jeweils 5 mm Höhe.",
        cylinder_stack_model,
    ),
    "inner_circle": STLModelSpec(
        "inner_circle", "Innenkonturuntersuchungsobjekt – Kreis", "innenkontur_kreis_10_15_20mm.stl",
        "fdm_innenkontur_untersuchungsobjekt_kreis_10_15_20mm",
        "Kreisförmige Innenkonturen für die getrennte Innenkonturprüfung.",
        "Drei kreisförmige Durchgangskonturen mit 10/15/20 mm Innenmaß.",
        inner_circle_model,
    ),
    "inner_square": STLModelSpec(
        "inner_square", "Innenkonturuntersuchungsobjekt – Quadrat", "innenkontur_quadrat_10_15_20mm.stl",
        "fdm_innenkontur_untersuchungsobjekt_quadrat_10_15_20mm",
        "Quadratische Innenkonturen für die getrennte Innenkonturprüfung.",
        "Drei quadratische Durchgangskonturen mit 10/15/20 mm Innenmaß.",
        inner_square_model,
    ),
    "depth_steps": STLModelSpec(
        "depth_steps", "Stufenuntersuchungsobjekt", "stufenpruefkoerper_tiefen_1_bis_15mm.stl",
        "fdm_stufenuntersuchungsobjekt_tiefen_1_bis_15mm",
        "Tiefenplattformen mit gemeinsamer seitlicher Referenzauflage.",
        "15 Tiefen von 1 bis 15 mm relativ zu 20-mm-Referenzauflagen.",
        depth_steps_model,
    ),
    "gaps": STLModelSpec(
        "gaps", "Spalt- und Dünnwanduntersuchungsobjekt",
        "spalt_duennwand_xy_1_2_3_4_5_10mm_0p4_bis_1p0mm.stl",
        "fdm_spalt_duennwand_xy_spalt_1_2_3_4_5_10mm_steg_0p4_bis_1p0mm",
        "Kombiniertes Modell mit Spalten und Dünnwänden in X- und Y-Richtung.",
        "Spalte 1/2/3/4/5/10 mm; Dünnwände 0,4/0,5/0,6/0,7/0,8/0,9/1,0 mm; jeweils X und Y.",
        gaps_model,
    ),
    "webs": STLModelSpec(
        "webs", "Dünnwanduntersuchungsobjekt",
        "stegpruefkoerper_0_4_bis_1_2mm.stl",
        "fdm_steg_duennwanduntersuchungsobjekt_0p4_bis_1p2mm",
        "Bisheriges eigenständiges Dünnwandmodell zur Prüfung diskreter Werkzeugpfadentscheidungen.",
        "Dünnwandbreiten 0,4 bis 1,2 mm in 0,1-mm-Schritten; historische Messrichtung X.",
        webs_model,
    ),
}



def export_model(template_key: str, path: str | Path) -> Path:
    spec = MODEL_SPECS[template_key]
    return write_ascii_stl(path, spec.generator(), solid_name=f"fdmcap_{template_key}")


def export_step_model(template_key: str, path: str | Path) -> Path:
    spec = MODEL_SPECS[template_key]
    return write_faceted_step(path, spec.generator(), model_name=spec.label)
