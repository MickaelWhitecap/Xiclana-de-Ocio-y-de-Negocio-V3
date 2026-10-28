#!/usr/bin/env python3
"""Auditoría no destructiva del catálogo maestro de Xiclana V3.

La detección de duplicados genera propuestas; nunca borra fichas por sí sola.
"""
import json, pathlib, re, sys, unicodedata, datetime
ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "fichas_completas.json"
REPORT = ROOT / "auditoria_integridad.json"
BASELINE = ROOT / "catalogo_auto_baseline.json"

def norm(value):
    value = unicodedata.normalize("NFD", str(value or "").casefold())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", value))

def main():
    if not DATA.exists():
        sys.exit("ERROR: falta fichas_completas.json.")
    try:
        data = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception as exc:
        sys.exit(f"ERROR: JSON maestro inválido: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        sys.exit("ERROR: el catálogo maestro debe contener items como lista.")

    items = data["items"]
    if not BASELINE.exists():
        sys.exit("ERROR: falta catalogo_auto_baseline.json; no se puede distinguir el legado de nuevas altas automáticas.")
    try:
        baseline_data = json.loads(BASELINE.read_text(encoding="utf-8"))
        baseline_ids = set(map(str, baseline_data.get("ids", [])))
    except Exception as exc:
        sys.exit(f"ERROR: línea base de candidatos automáticos inválida: {exc}")
    ids, invalid, missing = set(), [], []
    automatic = []
    exact = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            invalid.append({"indice": i, "motivo": "registro no es objeto"})
            continue
        ident = str(item.get("id") or "").strip()
        name, category, kind = str(item.get("n") or "").strip(), str(item.get("c") or "").strip(), str(item.get("t") or "").strip()
        if not ident:
            invalid.append({"indice": i, "motivo": "falta id"})
        elif ident in ids:
            invalid.append({"indice": i, "id": ident, "motivo": "id duplicado"})
        ids.add(ident)
        if not name or not category or kind not in {"ocio", "negocio"}:
            missing.append({"id": ident, "nombre": name, "categoria": category, "tipo": kind})
        if "candidato automático" in str(item.get("fuente_estado") or "").casefold():
            automatic.append(ident)
        address = norm(item.get("a"))
        if name and category and address:
            key = (norm(name), norm(category), address)
            exact.setdefault(key, []).append(item)

    duplicate_groups = []
    for key, group in exact.items():
        if len(group) > 1:
            duplicate_groups.append({
                "nombre_normalizado": key[0],
                "categoria_normalizada": key[1],
                "direccion_normalizada": key[2],
                "ids": [str(x.get("id") or "") for x in group],
                "nombres": [str(x.get("n") or "") for x in group],
                "accion": "propuesta de consolidación; no se elimina ni fusiona automáticamente"
            })
    review = data.get("candidatas_revision")
    if not isinstance(review, list):
        review = []
        data["candidatas_revision"] = review

    unexpected_auto = sorted(set(automatic) - baseline_ids)
    report = {
        "fecha": datetime.date.today().isoformat(),
        "total_items_publicables": len(items),
        "total_candidatas_revision": len(review),
        "candidatos_automaticos_heredados_en_items": len(automatic),
        "ids_automaticos_heredados": automatic,
        "ids_automaticos_nuevos_no_aprobados": unexpected_auto,
        "registros_invalidos_o_ids_repetidos": invalid,
        "fichas_sin_nombre_categoria_o_tipo_valido": missing,
        "grupos_duplicados_exactos_nombre_categoria_direccion": len(duplicate_groups),
        "propuestas_consolidacion_no_destructivas": duplicate_groups,
        "regla": "Los nuevos hallazgos automáticos deben permanecer en candidatas_revision hasta aprobación."
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Auditoría catálogo: {len(items)} fichas; {len(review)} candidatas pendientes.")
    print(f"Candidatos automáticos en fichas públicas: {len(automatic)}; altas fuera de la línea base: {len(unexpected_auto)}.")
    print(f"Grupos exactos que requieren consolidación: {len(duplicate_groups)}.")
    print(f"Registros inválidos/IDs repetidos: {len(invalid)}; fichas incompletas: {len(missing)}.")
    print(f"Informe detallado: {REPORT}")
    if invalid or missing:
        sys.exit("ERROR: el catálogo incumple validaciones estructurales; se detiene la publicación.")
    if unexpected_auto:
        sys.exit("ERROR: hay candidatos automáticos nuevos en el catálogo público sin aprobación. Se detiene la publicación.")
if __name__ == "__main__":
    main()
