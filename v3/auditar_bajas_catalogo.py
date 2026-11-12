#!/usr/bin/env python3
"""Audita las bajas del catálogo y contrasta su vigencia con OSM y fichas activas.
No modifica fichas ni Supabase.
"""
import collections
import os
import json
import math
import pathlib
import re
import unicodedata
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = pathlib.Path(os.getenv("XICLANA_CATALOG_PATH", str(ROOT / "fichas_completas.json")))
OUT = ROOT / "auditoria_bajas_catalogo.json"
OSM_ID_RE = re.compile(r"^(?:osm|osm-extra):(node|way|relation):(\d+)$")
INTEREST_TAGS = ("amenity", "shop", "tourism", "leisure", "office", "craft", "healthcare", "historic", "sport", "club")
INFRA_AMENITIES = {"drinking_water", "toilets", "fountain", "recycling"}
TRANSPORT_TAGS = {"public_transport": {"platform", "stop_position"}, "highway": {"bus_stop"}}


def norm(value):
    value = unicodedata.normalize("NFD", str(value or "").casefold())
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def osm_key(item_id):
    m = OSM_ID_RE.match(str(item_id or ""))
    return f"{m.group(1)}:{m.group(2)}" if m else None


def item_coords(item):
    try:
        lat, lon = float(item.get("lat")), float(item.get("lon"))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (TypeError, ValueError):
        pass
    return None


def osm_coords(obj):
    if obj.get("lat") is not None and obj.get("lon") is not None:
        return float(obj["lat"]), float(obj["lon"])
    center = obj.get("center") or {}
    if center.get("lat") is not None and center.get("lon") is not None:
        return float(center["lat"]), float(center["lon"])
    geometry = obj.get("geometry") or []
    pts = [(float(p["lat"]), float(p["lon"])) for p in geometry if p.get("lat") is not None and p.get("lon") is not None]
    if pts:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return None


def distance_m(a, b):
    if not a or not b:
        return None
    r = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(h)))


def classify(tags):
    tags = tags or {}
    if any(tags.get(k) in values for k, values in TRANSPORT_TAGS.items()):
        return "transporte_publico_no_directorio"
    if tags.get("amenity") in INFRA_AMENITIES:
        return "infraestructura_publica_no_establecimiento"
    if any(tags.get(k) for k in INTEREST_TAGS):
        return "punto_interes_o_servicio_revisar"
    return "sin_etiquetas_de_interes"


def main():
    if not MASTER.is_file() or MASTER.stat().st_size == 0:
        raise SystemExit("No existe el catálogo maestro.")
    data = json.loads(MASTER.read_text(encoding="utf-8"))
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit("El catálogo maestro no contiene items válidos.")

    deleted = [x for x in items if isinstance(x, dict) and x.get("_xiclana_deleted") is True]
    active = [x for x in items if isinstance(x, dict) and x.get("_xiclana_deleted") is not True]
    baseline = data.get("osm_extraccion_inicial") or {}
    objects = baseline.get("objetos") or []
    if len(objects) != 132875:
        raise SystemExit("No se encuentra la extracción OSM inicial completa para contrastar las bajas.")
    osm_by_id = {f"{o.get('type')}:{o.get('id')}": o for o in objects}

    active_by_name = collections.defaultdict(list)
    for x in active:
        name = norm(x.get("n") or x.get("nombre") or x.get("name"))
        if name:
            active_by_name[name].append(x)

    by_prefix = collections.Counter(str(x.get("id") or "").split(":", 1)[0] for x in deleted)
    by_category = collections.Counter((str(x.get("t") or "sin tipo"), str(x.get("c") or "sin categoría")) for x in deleted)
    records, re_proposals = [], []
    classification_counts = collections.Counter()
    exact_name_matches = near_matches = osm_present = 0

    for x in sorted(deleted, key=lambda item: str(item.get("n") or "").casefold()):
        ident = x.get("id")
        key = osm_key(ident)
        obj = osm_by_id.get(key) if key else None
        tags = obj.get("tags") or {} if obj else {}
        classification = classify(tags)
        classification_counts[classification] += 1
        if obj:
            osm_present += 1

        name = norm(x.get("n") or x.get("nombre") or x.get("name"))
        candidates = active_by_name.get(name, []) if name else []
        same_name = []
        for candidate in candidates:
            dist = distance_m(item_coords(x), item_coords(candidate))
            same_name.append({
                "id": candidate.get("id"),
                "nombre": candidate.get("n"),
                "distancia_m": round(dist, 1) if dist is not None else None
            })
        if same_name:
            exact_name_matches += 1
        close = [m for m in same_name if m["distancia_m"] is not None and m["distancia_m"] <= 150]
        if close:
            near_matches += 1

        record = {
            "id": ident,
            "nombre": x.get("n"),
            "tipo": x.get("t"),
            "categoria": x.get("c"),
            "direccion": x.get("a"),
            "fuente": x.get("f"),
            "fuente_estado": x.get("fuente_estado"),
            "osm_id": key,
            "osm_presente_en_extraccion_inicial": bool(obj),
            "clasificacion_osm": classification,
            "etiquetas_osm": {k: tags[k] for k in tags if k in INTEREST_TAGS or k in ("highway", "public_transport")},
            "coordenadas_osm": osm_coords(obj) if obj else None,
            "coincidencias_activas_mismo_nombre": same_name,
        }
        records.append(record)

        # Solo se sugieren de nuevo lugares/servicios identificados en OSM,
        # sin duplicado activo evidente. La decisión final siempre es manual.
        if (obj and classification == "punto_interes_o_servicio_revisar"
                and not same_name):
            re_proposals.append({
                "id": ident,
                "n": x.get("n"),
                "t": x.get("t"),
                "c": x.get("c"),
                "a": x.get("a"),
                "lat": record["coordenadas_osm"][0] if record["coordenadas_osm"] else None,
                "lon": record["coordenadas_osm"][1] if record["coordenadas_osm"] else None,
                "f": "OpenStreetMap",
                "osm_id": key,
                "url": f"https://www.openstreetmap.org/{key.replace(':', '/', 1)}",
                "estado_revision": "recuperada_de_baja_pendiente_aprobacion",
            })

    result = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "catalogo": "v3/fichas_completas.json",
        "extraccion_osm_utc": baseline.get("fecha_extraccion_utc"),
        "total_registros": len(items),
        "total_activos": len(active),
        "total_marcados_borrados": len(deleted),
        "bajas_por_prefijo_id": dict(sorted(by_prefix.items())),
        "bajas_por_tipo_categoria": [
            {"tipo": k[0], "categoria": k[1], "total": v}
            for k, v in sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "resumen_contraste_osm": {
            "bajas_con_id_osm": sum(1 for x in deleted if osm_key(x.get("id"))),
            "bajas_cuyo_objeto_sigue_en_extraccion": osm_present,
            "bajas_sin_objeto_osm_en_extraccion": sum(1 for x in deleted if osm_key(x.get("id"))) - osm_present,
            "bajas_con_nombre_igual_a_ficha_activa": exact_name_matches,
            "bajas_con_posible_coincidencia_activa_a_150m": near_matches,
            "clasificacion_osm": dict(classification_counts),
            "candidatas_recuperables_para_revision_manual": len(re_proposals),
        },
        "candidatas_recuperables": re_proposals,
        "bajas": records,
        "nota": "Informe de lectura. Ninguna baja se restaura ni publica automáticamente. Los borrados con override de Supabase deben seguir excluidos en Administración."
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "total_registros": result["total_registros"],
        "total_activos": result["total_activos"],
        "total_marcados_borrados": result["total_marcados_borrados"],
        "bajas_por_prefijo_id": result["bajas_por_prefijo_id"],
        "resumen_contraste_osm": result["resumen_contraste_osm"],
        "fichas_modificadas": 0
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
