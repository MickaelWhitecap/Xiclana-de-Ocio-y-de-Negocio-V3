#!/usr/bin/env python3
"""Genera propuestas de dirección usando exclusivamente la extracción OSM ya archivada."""
import json, re
from datetime import datetime, timezone
from pathlib import Path

CATALOG = Path(__file__).resolve().parent / "fichas_completas.json"
KEYS = ("addr:full", "addr:street", "addr:housenumber", "addr:place",
        "addr:postcode", "addr:city", "addr:suburb", "addr:district",
        "addr:province", "addr:state", "addr:unit", "addr:floor")

def osm_id(value):
    p = str(value or "").split(":")
    if len(p) == 3 and p[0] in {"osm", "osm-extra"} and p[1] in {"node", "way", "relation"} and p[2].isdigit():
        return f"{p[1]}:{p[2]}"
    return None

def address(tags):
    if tags.get("addr:full"):
        return tags["addr:full"].strip()
    street = tags.get("addr:street") or tags.get("addr:place")
    number = tags.get("addr:housenumber")
    main = f"{street.strip()}, {number.strip()}" if street and number else (street.strip() if street else "")
    extra = [f"{label} {tags[key].strip()}" for key, label in (
        ("addr:unit", "local"), ("addr:floor", "planta"),
        ("addr:postcode", "CP"), ("addr:city", "localidad"),
        ("addr:suburb", "zona"), ("addr:district", "distrito")
    ) if tags.get(key)]
    return ", ".join(x for x in (main, *extra) if x)

def main():
    if not CATALOG.is_file():
        raise SystemExit("No existe catálogo maestro.")
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit("Catálogo inválido.")
    extraction = data.get("osm_extraccion_inicial") or {}
    objects = extraction.get("objetos")
    if not isinstance(objects, list) or len(objects) != 132875:
        raise SystemExit("No existe una extracción OSM completa verificada dentro del catálogo maestro; no se consulta otra vez Overpass.")
    by_id = {}
    for obj in objects:
        key = f'{obj.get("type")}:{obj.get("id")}'
        by_id[key] = obj.get("tags") or {}
    pending = [x for x in items if not x.get("_xiclana_deleted") and not x.get("deleted") and not x.get("eliminado") and not str(x.get("a") or "").strip()]
    proposals, not_osm, not_found, no_address = [], [], [], []
    consulted = 0
    for item in pending:
        key = osm_id(item.get("id"))
        if not key:
            not_osm.append({"id": item.get("id"), "nombre": item.get("n"), "categoria": item.get("c")})
            continue
        consulted += 1
        tags = by_id.get(key)
        if tags is None:
            not_found.append({"id": item.get("id"), "nombre": item.get("n")})
            continue
        # Un CP o una localidad aislados no constituyen una dirección utilizable.
        # Exigimos una dirección completa, calle o lugar identificado.
        if not any(tags.get(k) for k in ("addr:full", "addr:street", "addr:place")):
            no_address.append({"id": item.get("id"), "nombre": item.get("n")})
            continue
        selected = {k: tags[k] for k in KEYS if tags.get(k)}
        if not selected:
            no_address.append({"id": item.get("id"), "nombre": item.get("n")})
            continue
        proposals.append({
            "id_ficha": item.get("id"),
            "nombre": item.get("n"),
            "direccion_propuesta": address(tags) or None,
            "etiquetas_osm": selected,
            "url_osm": f"https://www.openstreetmap.org/{key.replace(':', '/', 1)}",
            "estado": "pendiente_revision",
            "fuente_extraccion": extraction.get("fecha_extraccion_utc"),
        })
    data["propuestas_direcciones_osm"] = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "fuente": "Extracción municipal OSM ya archivada en fichas_completas.json; sin nuevas consultas a Overpass",
        "sha256_extraccion": extraction.get("sha256_archivo_extraccion"),
        "fichas_sin_direccion": len(pending),
        "fichas_con_id_osm_consultables": consulted,
        "objetos_recuperados_en_extraccion": consulted - len(not_found),
        "propuestas": proposals,
        "fichas_sin_id_osm": not_osm,
        "ids_osm_no_presentes_en_extraccion": not_found,
        "fichas_osm_sin_etiquetas_de_direccion": no_address,
        "nota": "Propuestas pendientes; no se modifican direcciones existentes ni se publica ninguna ficha automáticamente.",
    }
    data["actualizado"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    CATALOG.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({
        "fichas_sin_direccion": len(pending),
        "ids_osm_consultables": consulted,
        "objetos_recuperados": consulted - len(not_found),
        "propuestas_direccion": len(proposals),
        "sin_id_osm": len(not_osm),
        "sin_objeto_en_extraccion": len(not_found),
        "sin_tags_direccion": len(no_address),
        "consultas_overpass_nuevas": 0,
        "destino": CATALOG.name,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()

# Activación controlada de la recuperación basada exclusivamente en la extracción OSM archivada.
# Auditoría de direcciones 2026-11-05: recalcular sobre la extracción archivada sin consultas nuevas.
