#!/usr/bin/env python3
"""Auditoría no destructiva del catálogo maestro de Xiclana V3.

La detección de duplicados genera propuestas; nunca borra fichas por sí sola.
"""
import json, pathlib, re, sys, unicodedata, datetime
ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "fichas_completas.json"
REPORT = ROOT / "auditoria_integridad.json"
MERGE_PLAN = ROOT / "plan_consolidacion.json"
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
    active_items = [item for item in items if isinstance(item, dict) and item.get("_xiclana_deleted") is not True]
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
        if item.get("_xiclana_deleted") is not True and "candidato automático" in str(item.get("fuente_estado") or "").casefold():
            automatic.append(ident)
        address = norm(item.get("a"))
        if item.get("_xiclana_deleted") is not True and name and category and address:
            key = (norm(name), norm(category), norm(kind), address)
            exact.setdefault(key, []).append(item)

    duplicate_groups = []
    merge_plan = []
    field_keys = sorted({field for group in exact.values() for item in group for field in item.keys()})
    priority = lambda item: (0 if str(item.get("id", "")).startswith("manual:") else
                              1 if str(item.get("id", "")).startswith("oficial:") else
                              2 if str(item.get("id", "")).startswith("consolidado:") else
                              3 if str(item.get("id", "")).startswith("proposal:") else 4)
    for key, group in exact.items():
        if len(group) > 1:
            keeper = sorted(group, key=priority)[0]
            merged = dict(keeper)
            conflicts = {}
            for field in field_keys:
                values = []
                for item in group:
                    value = item.get(field)
                    if value is not None and str(value).strip() and value not in values:
                        values.append(value)
                if len(values) > 1:
                    conflicts[field] = values
                if merged.get(field) is None or not str(merged.get(field) or "").strip():
                    if values:
                        merged[field] = values[0]
            ids_group = [str(item.get("id") or "") for item in group]
            duplicate_groups.append({
                "nombre_normalizado": key[0],
                "categoria_normalizada": key[1],
                "tipo_normalizado": key[2],
                "direccion_normalizada": key[3],
                "ids": ids_group,
                "nombres": [str(item.get("n") or "") for item in group],
                "campos_por_id": {
                    str(item.get("id") or ""): sorted(
                        field for field, value in item.items()
                        if value is not None and str(value).strip()
                    ) for item in group
                },
                "id_recomendado_conservar": str(keeper.get("id") or ""),
                "accion": "consolidación propuesta; no se elimina ni fusiona automáticamente"
            })
            merge_plan.append({
                "id_recomendado_conservar": str(keeper.get("id") or ""),
                "ids_candidatos_a_consolidar": [ident for ident in ids_group if ident != str(keeper.get("id") or "")],
                "nombre": str(keeper.get("n") or ""),
                "categoria": str(keeper.get("c") or ""),
                "direccion": str(keeper.get("a") or ""),
                "campos_completos_propuestos": merged,
                "conflictos_de_datos_que_requieren_decision": conflicts,
                "requiere_migracion_de_overrides_supabase": True,
                "aplicado": False
            })
    review = data.get("candidatas_revision")
    if not isinstance(review, list):
        review = []
        data["candidatas_revision"] = review

    unexpected_auto = sorted(
        (set(automatic) - baseline_ids)
        | {
            str(item.get("id") or "")
            for item in active_items
            if isinstance(item, dict)
            and str(item.get("id") or "").startswith("osm-extra:")
            and str(item.get("id") or "") not in baseline_ids
            and "ficha administrativa sincronizada desde supabase" not in str(item.get("fuente_estado") or "").casefold()
        }
    )
    report = {
        "fecha": datetime.date.today().isoformat(),
        "total_registros_historicos": len(items),
        "total_items_publicables": len(active_items),
        "total_items_marcados_borrados": len(items) - len(active_items),
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
    MERGE_PLAN.write_text(json.dumps({
        "fecha": datetime.date.today().isoformat(),
        "total_grupos": len(merge_plan),
        "regla": "Plan no destructivo: elegir ficha maestra, completar campos vacíos, conservar conflictos para decisión y migrar referencias de Supabase antes de retirar IDs.",
        "grupos": merge_plan
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Auditoría catálogo: {len(items)} fichas; {len(review)} candidatas pendientes.")
    print(f"Candidatos automáticos en fichas públicas: {len(automatic)}; altas fuera de la línea base: {len(unexpected_auto)}.")
    print(f"Grupos exactos que requieren consolidación: {len(duplicate_groups)}.")
    print(f"Registros inválidos/IDs repetidos: {len(invalid)}; fichas incompletas: {len(missing)}.")
    print(f"Informe detallado: {REPORT}")
    print(f"Plan de consolidación no destructivo: {MERGE_PLAN}")
    if invalid or missing:
        sys.exit("ERROR: el catálogo incumple validaciones estructurales; se detiene la publicación.")
    if unexpected_auto:
        sys.exit("ERROR: hay candidatos automáticos nuevos en el catálogo público sin aprobación. Se detiene la publicación.")
if __name__ == "__main__":
    main()
