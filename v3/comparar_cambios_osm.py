#!/usr/bin/env python3
"""Compara la consulta OSM semanal con la extracción inicial inmutable del catálogo maestro."""
import collections
import gzip
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
BASELINE = ROOT / "osm_extraccion_inicial.json.gz"
CURRENT = ROOT / "osm_chiclana_extraccion_completa.json"
OUT = ROOT / "osm_chiclana_cambios_semanales.json"

# Campos que representan contenido del objeto OSM, no quién/cuándo editó sus metadatos.
CONTENT_FIELDS = ("tags", "lat", "lon", "center", "geometry", "nodes", "members", "bounds")
META_FIELDS = ("version", "timestamp", "changeset")


def key(obj):
    kind, ident = obj.get("type"), obj.get("id")
    if kind not in {"node", "way", "relation"} or not isinstance(ident, int):
        raise ValueError(f"Objeto OSM con tipo/ID inválido: {kind}:{ident}")
    return f"{kind}:{ident}"


def projection(obj, fields):
    return {field: obj[field] for field in fields if field in obj}


def counts(records):
    result = collections.Counter()
    for record in records:
        kind = record.get("type") or record.get("osm_id", "").split(":", 1)[0]
        result[kind] += 1
    return dict(sorted(result.items()))


def main():
    if not BASELINE.is_file() or not CURRENT.is_file():
        raise SystemExit("Falta la extracción inicial OSM inmutable o la extracción semanal; no se genera comparación.")
    baseline_doc = json.loads(gzip.decompress(BASELINE.read_bytes()).decode("utf-8"))
    baseline = baseline_doc if isinstance(baseline_doc, list) else (
        baseline_doc.get("objetos") or baseline_doc.get("elementos") or []
    )
    if not isinstance(baseline, list) or len(baseline) != 132875:
        raise SystemExit("La extracción inicial OSM no contiene los 132.875 objetos esperados.")
    current_doc = json.loads(CURRENT.read_text(encoding="utf-8"))
    if current_doc.get("relacion_municipal_osm") != 346951 or current_doc.get("area_overpass") != 3600346951:
        raise SystemExit("La consulta semanal no corresponde al ámbito municipal de Chiclana.")
    current = current_doc.get("elementos")
    if not isinstance(current, list) or not current:
        raise SystemExit("La consulta semanal no contiene elementos.")
    before, after = {}, {}
    for obj in baseline:
        k = key(obj)
        if k in before:
            raise SystemExit(f"ID duplicado en la extracción inicial: {k}")
        before[k] = obj
    for obj in current:
        k = key(obj)
        if k in after:
            raise SystemExit(f"ID duplicado en la consulta semanal: {k}")
        after[k] = obj

    new_records, changed_records, deleted_records = [], [], []
    metadata_only = 0
    for k, obj in after.items():
        old = before.get(k)
        if old is None:
            new_records.append({"osm_id": k, "objeto": obj})
            continue
        old_content = projection(old, CONTENT_FIELDS)
        new_content = projection(obj, CONTENT_FIELDS)
        if old_content != new_content:
            changed_records.append({
                "osm_id": k,
                "nombre_anterior": (old.get("tags") or {}).get("name"),
                "nombre_actual": (obj.get("tags") or {}).get("name"),
                "antes": old_content,
                "ahora": new_content,
                "objeto_actual": obj,
            })
        elif projection(old, META_FIELDS) != projection(obj, META_FIELDS):
            metadata_only += 1
    for k, obj in before.items():
        if k not in after:
            deleted_records.append({
                "osm_id": k,
                "tipo": obj.get("type"),
                "nombre": (obj.get("tags") or {}).get("name"),
                "etiquetas_anteriores": obj.get("tags") or {},
            })

    now = datetime.now(timezone.utc).isoformat()
    result = {
        "fecha_comparacion_utc": now,
        "fecha_extraccion_inicial_utc": (master.get("osm_extraccion_inicial") or {}).get("fecha_extraccion_utc"),
        "fecha_consulta_actual_utc": current_doc.get("fecha_extraccion_utc"),
        "ambito": {"relacion_osm": 346951, "area_overpass": 3600346951},
        "referencia": "Extracción inicial verificada e inmutable en osm_extraccion_inicial.json.gz",
        "resumen": {
            "objetos_iniciales": len(before),
            "objetos_actuales": len(after),
            "objetos_nuevos": len(new_records),
            "objetos_con_cambios_de_contenido": len(changed_records),
            "objetos_eliminados_de_osm": len(deleted_records),
            "objetos_con_solo_cambio_de_metadatos": metadata_only,
            "nuevos_por_tipo": counts([x["objeto"] for x in new_records]),
            "modificados_por_tipo": counts([{"type": x["osm_id"].split(":",1)[0]} for x in changed_records]),
            "eliminados_por_tipo": counts(deleted_records),
        },
        "nuevos": new_records,
        "modificados": changed_records,
        "eliminados": deleted_records,
        "criterio": {
            "cambio_de_contenido": "Cambios en etiquetas, coordenadas, centro, geometría, nodos, miembros o límites.",
            "solo_metadatos": "Cambió versión, fecha de edición o changeset, pero no el contenido del objeto.",
            "eliminado": "El ID estaba en la extracción inicial y ya no aparece en la consulta municipal actual.",
            "publicacion": "Este informe no modifica ni publica fichas del catálogo.",
            "referencia": "La comparación se hace siempre contra la extracción inicial, que no se sobrescribe; así se conserva una referencia histórica estable.",
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(result["resumen"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
