#!/usr/bin/env python3
"""Audita direcciones ausentes usando la extracción OSM inicial ya integrada.
No modifica el catálogo ni publica fichas; solo crea propuestas verificables.
"""
import json
import pathlib
import re
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = ROOT / "fichas_completas.json"
OUT = ROOT / "propuestas_direcciones_osm_inicial.json"
OSM_ID_RE = re.compile(r"^(?:osm|osm-extra):(node|way|relation):(\d+)$")


def clean(value):
    return " ".join(str(value or "").strip().split())


def osm_key(item_id):
    match = OSM_ID_RE.match(str(item_id or "").strip())
    return f"{match.group(1)}:{match.group(2)}" if match else None


def build_address(tags):
    tags = tags or {}
    full = clean(tags.get("addr:full"))
    if full:
        return full, "alta", ["addr:full"]
    street = clean(tags.get("addr:street"))
    place = clean(tags.get("addr:place"))
    number = clean(tags.get("addr:housenumber"))
    postcode = clean(tags.get("addr:postcode"))
    city = clean(tags.get("addr:city"))
    unit = clean(tags.get("addr:unit"))
    road = street or place
    if not road:
        return None, None, []
    parts = [road]
    fields = ["addr:street" if street else "addr:place"]
    if number:
        parts.append(number)
        fields.append("addr:housenumber")
    if unit:
        parts.append(unit)
        fields.append("addr:unit")
    if postcode:
        parts.append(postcode)
        fields.append("addr:postcode")
    if city:
        parts.append(city)
        fields.append("addr:city")
    confidence = "alta" if number and (postcode or city) else "media" if postcode or city else "baja"
    return ", ".join(parts), confidence, fields


def main():
    if not MASTER.is_file() or MASTER.stat().st_size == 0:
        raise SystemExit("Falta el catálogo maestro.")
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    items = master.get("items")
    baseline = master.get("osm_extraccion_inicial") or {}
    elements = baseline.get("objetos")
    if not isinstance(items, list) or not isinstance(elements, list) or len(elements) != 132875:
        raise SystemExit("El catálogo o la extracción OSM inicial no superan la validación de estructura/recuento.")
    if baseline.get("relacion_municipal_osm") != 346951 or baseline.get("area_overpass") != 3600346951:
        raise SystemExit("La extracción integrada no corresponde al ámbito municipal esperado.")

    osm_by_id = {}
    for element in elements:
        key = f"{element.get('type')}:{element.get('id')}"
        if key in osm_by_id:
            raise SystemExit(f"ID OSM duplicado en extracción inicial: {key}")
        osm_by_id[key] = element

    active = [x for x in items if isinstance(x, dict) and x.get("_xiclana_deleted") is not True]
    without_address = [x for x in active if not clean(x.get("a"))]
    with_osm_id, without_osm_id = [], []
    proposals, no_address_tags, missing_osm_objects = [], [], []
    for item in without_address:
        key = osm_key(item.get("id"))
        if not key:
            without_osm_id.append(item)
            continue
        with_osm_id.append(item)
        element = osm_by_id.get(key)
        if element is None:
            missing_osm_objects.append({"id_ficha": item.get("id"), "nombre": item.get("n"), "osm_id": key})
            continue
        tags = element.get("tags") or {}
        address, confidence, source_fields = build_address(tags)
        if not address:
            no_address_tags.append({"id_ficha": item.get("id"), "nombre": item.get("n"), "osm_id": key})
            continue
        proposals.append({
            "id_ficha": item.get("id"), "nombre": item.get("n"),
            "categoria": item.get("c"), "tipo": item.get("t"),
            "direccion_actual": clean(item.get("a")) or None,
            "direccion_propuesta": address, "confianza": confidence,
            "osm_id": key,
            "osm_nombre": clean(tags.get("name") or tags.get("name:es") or tags.get("official_name")),
            "campos_osm_utilizados": source_fields,
            "etiquetas_direccion_osm": {k: tags[k] for k in tags if k.startswith("addr:")},
            "url_osm": f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}",
            "estado": "pendiente_revision_manual",
        })

    result = {
        "fecha_generacion_utc": datetime.now(timezone.utc).isoformat(),
        "fuente": "Extracción OSM inicial integrada en el catálogo maestro",
        "extraccion_utc": baseline.get("fecha_extraccion_utc"),
        "sha256_extraccion": baseline.get("sha256_archivo_extraccion"),
        "regla": "Solo fichas activas sin dirección y con coincidencia exacta por ID OSM. No se modifica el catálogo ni se publica nada.",
        "resumen": {
            "fichas_activas": len(active),
            "fichas_activas_sin_direccion": len(without_address),
            "sin_direccion_con_id_osm": len(with_osm_id),
            "sin_direccion_sin_id_osm": len(without_osm_id),
            "id_osm_no_encontrado_en_extraccion": len(missing_osm_objects),
            "sin_etiquetas_postales_utilizables": len(no_address_tags),
            "propuestas_direccion_generadas": len(proposals),
            "direcciones_existentes_sobrescritas": 0,
            "fichas_publicadas_automaticamente": 0,
        },
        "propuestas": sorted(proposals, key=lambda x: (clean(x.get("nombre")).casefold(), x["id_ficha"])),
        "sin_etiquetas_postales_utilizables": no_address_tags,
        "ids_osm_no_encontrados": missing_osm_objects,
        "sin_identificador_osm": [{"id_ficha": x.get("id"), "nombre": x.get("n")} for x in without_osm_id],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["resumen"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
