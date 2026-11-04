#!/usr/bin/env python3
"""Prepara candidatas OSM para revisión en Administración; nunca publica fichas."""
import collections
import json
import math
import pathlib
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = ROOT / "fichas_completas.json"
RAW = ROOT / "osm_chiclana_extraccion_completa.json"
REPORT = ROOT / "osm_chiclana_cruce_catalogo.json"
SUMMARY = ROOT / "osm_candidatas_resumen.json"
PENDING = ROOT / "osm_candidatas_pendientes.json"
OSM_ID_RE = re.compile(r"^(?:osm|osm-extra):(node|way|relation):(\d+)$")
INTEREST_TAGS = ("amenity", "shop", "tourism", "leisure", "office", "craft", "healthcare", "historic", "sport", "club")
EXCLUDED_AMENITY = {"drinking_water", "shower", "toilets", "fountain", "recycling", "bus_stop", "bus_station", "taxi"}


def clean(value):
    return " ".join(str(value or "").strip().split())


def norm(value):
    value = unicodedata.normalize("NFD", str(value or "").casefold())
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def osm_key(value):
    m = OSM_ID_RE.match(str(value or ""))
    return f"{m.group(1)}:{m.group(2)}" if m else None


def coords(obj):
    if not obj:
        return None
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


def item_coords(item):
    try:
        return float(item["lat"]), float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def distance_m(a, b):
    if not a or not b:
        return None
    r = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(h)))


def address(tags):
    tags = tags or {}
    if clean(tags.get("addr:full")):
        return clean(tags["addr:full"])
    street = clean(tags.get("addr:street") or tags.get("addr:place"))
    if not street:
        return ""
    parts = [street]
    for key in ("addr:housenumber", "addr:unit", "addr:postcode", "addr:city", "addr:suburb"):
        value = clean(tags.get(key))
        if value:
            parts.append(value)
    return ", ".join(parts)


def relevant(tags):
    tags = tags or {}
    if tags.get("public_transport") in {"platform", "stop_position"} or tags.get("highway") == "bus_stop":
        return False
    if tags.get("amenity") in EXCLUDED_AMENITY:
        return False
    if tags.get("tourism") == "chalet" or tags.get("historic") == "wreck":
        return False
    return any(tags.get(k) for k in INTEREST_TAGS)


def classify(tags):
    t = tags or {}
    amenity = t.get("amenity")
    if amenity in {"taxi", "ferry_terminal", "bicycle_repair_station"} or t.get("shop") == "car_repair":
        return "negocio", "Transporte"
    if amenity in {"parking", "parking_entrance"}:
        return "negocio", "Parking"
    if amenity == "police":
        return "negocio", "Emergencias"
    if amenity == "courthouse" or t.get("office") == "government":
        return "negocio", "Servicios públicos"
    if amenity == "psychologist" or t.get("healthcare"):
        return "negocio", "Salud"
    if amenity in {"nursing_home", "social_facility"}:
        return "negocio", "Servicios sociales"
    if amenity in {"prep_school", "language_school", "college", "childcare"}:
        return "negocio", "Educación"
    if amenity == "place_of_worship":
        return "ocio", "Patrimonio y culto"
    if amenity in {"social_centre", "arts_centre", "events_venue", "conference_centre"} or t.get("club") == "scout":
        return "ocio", "Espacios culturales"
    if t.get("club") == "sport" or t.get("sport") or t.get("leisure") in {"sports_centre", "pitch"}:
        return "ocio", "Instalación deportiva"
    if t.get("leisure") in {"playground", "indoor_play"}:
        return "ocio", "Ocio infantil"
    if t.get("leisure") == "marina" or amenity == "boat_rental":
        return ("ocio", "Náutica") if t.get("leisure") == "marina" else ("negocio", "Alquiler y movilidad")
    if t.get("leisure") == "bird_hide":
        return "ocio", "Naturaleza"
    if t.get("tourism") == "artwork":
        return "ocio", "Arte público"
    if t.get("tourism") == "information":
        return "ocio", "Información turística"
    if t.get("historic"):
        return "ocio", "Patrimonio y culto"
    if t.get("tourism") in {"hotel", "hostel"} or t.get("leisure") == "resort":
        return "negocio", "Hotel"
    if t.get("tourism") == "spa_resort":
        return "negocio", "Bienestar"
    if amenity == "restaurant":
        return "ocio", "Restaurante"
    return "ocio", "Ocio familiar"


def tags_to_fields(name, tags, location, ident):
    tipo, categoria = classify(tags)
    return {
        "id": ident, "n": clean(name), "t": tipo, "c": categoria,
        "a": address(tags), "p": clean(tags.get("contact:phone") or tags.get("phone")),
        "e": clean(tags.get("contact:email") or tags.get("email")),
        "w": clean(tags.get("contact:website") or tags.get("website")),
        "h": clean(tags.get("opening_hours") or tags.get("opening_hours:covid19")),
        "s": "", "d": clean(tags.get("description:es") or tags.get("description")),
        "lat": location[0] if location else None, "lon": location[1] if location else None,
        "f": "OpenStreetMap", "osm_id": ident.split(":", 1)[1] if ":" in ident else ident,
        "url_osm": "https://www.openstreetmap.org/" + ident.replace(":", "/", 1),
        "estado_revision": "nueva_deteccion_pendiente_aprobacion",
        "_xiclana_osm_auto": True,
    }


def get_overrides():
    config = (ROOT / "supabase-config.js").read_text(encoding="utf-8")
    url = re.search(r'url:\s*"([^"]+)"', config)
    key = re.search(r'anonKey:\s*"([^"]+)"', config)
    if not url or not key:
        raise RuntimeError("No se pudo leer la configuración pública de Supabase.")
    api = url.group(1).rstrip("/")
    anon = key.group(1)
    query = urllib.parse.urlencode({"select": "listing_id,fields,is_new,verified_at,updated_at", "order": "updated_at.asc,listing_id.asc"})
    headers = {"apikey": anon, "Authorization": "Bearer " + anon, "Accept": "application/json", "User-Agent": "Xiclana-OSM-candidate-sync/1.0"}
    rows, offset, page_size = [], 0, 500
    while True:
        req = urllib.request.Request(api + "/rest/v1/listing_overrides?" + query, headers={**headers, "Range": f"{offset}-{offset + page_size - 1}", "Range-Unit": "items"})
        with urllib.request.urlopen(req, timeout=30) as response:
            page = json.load(response)
        if not isinstance(page, list):
            raise RuntimeError("Supabase devolvió un formato inesperado para listing_overrides.")
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += len(page)
        if offset > 100000:
            raise RuntimeError("La lectura de overrides superó el límite defensivo.")
    return rows


def main():
    for path in (MASTER, RAW, REPORT):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"Falta archivo obligatorio: {path}")
    data = json.loads(MASTER.read_text(encoding="utf-8"))
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    items = data.get("items")
    if not isinstance(items, list) or not isinstance(raw.get("elementos"), list):
        raise SystemExit("Catálogo o extracción OSM con estructura inválida.")
    if raw.get("relacion_municipal_osm") != 346951 or raw.get("area_overpass") != 3600346951:
        raise SystemExit("La extracción no corresponde al ámbito municipal de Chiclana.")
    current = {f"{x.get('type')}:{x.get('id')}": x for x in raw["elementos"]}
    if len(current) != len(raw["elementos"]):
        raise SystemExit("La extracción OSM contiene IDs duplicados.")

    overrides = get_overrides()
    deleted_override_ids = {
        str(row.get("listing_id")) for row in overrides
        if isinstance(row.get("fields"), dict) and row["fields"].get("_xiclana_deleted") is True
    }
    active_override_rows = [
        row for row in overrides
        if isinstance(row, dict) and row.get("listing_id")
        and not (isinstance(row.get("fields"), dict) and row["fields"].get("_xiclana_deleted") is True)
    ]
    active = [x for x in items if isinstance(x, dict) and x.get("_xiclana_deleted") is not True]
    active_by_name = collections.defaultdict(list)
    for item in active:
        name = norm(item.get("n") or item.get("nombre") or item.get("name"))
        if name:
            active_by_name[name].append(item)
    # Las fichas aprobadas en Supabase también cuentan como activas aunque
    # todavía no estén integradas en el JSON maestro.
    for row in active_override_rows:
        fields = row.get("fields")
        if not isinstance(fields, dict):
            continue
        override_item = {**fields, "id": str(row.get("listing_id"))}
        name = norm(override_item.get("n") or override_item.get("nombre") or override_item.get("name"))
        if name:
            active_by_name[name].append(override_item)
    all_ids = {str(x.get("id")) for x in items if isinstance(x, dict) and x.get("id")}
    all_ids.update(str(row["listing_id"]) for row in active_override_rows)

    recovered, skipped_recovered = [], collections.Counter()
    for item in items:
        if not isinstance(item, dict) or item.get("_xiclana_deleted") is not True:
            continue
        ident = str(item.get("id") or "")
        key = osm_key(ident)
        if not key:
            skipped_recovered["sin_id_osm"] += 1
            continue
        if ident in deleted_override_ids:
            skipped_recovered["baja_manual_supabase"] += 1
            continue
        obj = current.get(key)
        if not obj:
            skipped_recovered["osm_ya_no_existe"] += 1
            continue
        tags = obj.get("tags") or {}
        if not relevant(tags):
            skipped_recovered["sin_interes_directorio"] += 1
            continue
        name = norm(item.get("n"))
        close = False
        same_name_far = False
        for active_item in active_by_name.get(name, []) if name else []:
            dist = distance_m(item_coords(item), item_coords(active_item))
            if dist is None or dist <= 150:
                close = True
                break
            same_name_far = True
        if close:
            skipped_recovered["posible_duplicado_activo"] += 1
            continue
        candidate = dict(item)
        candidate["_xiclana_osm_auto"] = True
        candidate["estado_revision"] = "recuperada_de_baja_pendiente_aprobacion"
        candidate["fuente_estado"] = "Candidata recuperada por OpenStreetMap; requiere aprobación manual"
        candidate["osm_id"] = key
        candidate["url_osm"] = f"https://www.openstreetmap.org/{key.replace(':', '/', 1)}"
        candidate["f"] = "OpenStreetMap"
        if not clean(candidate.get("a")) and address(tags):
            candidate["a"] = address(tags)
        for field, tag_keys in {
            "p": ("contact:phone", "phone"), "e": ("contact:email", "email"),
            "w": ("contact:website", "website"), "h": ("opening_hours",),
            "d": ("description:es", "description"),
        }.items():
            if not clean(candidate.get(field)):
                candidate[field] = next((clean(tags.get(k)) for k in tag_keys if clean(tags.get(k))), "")
        if same_name_far:
            candidate["nota_revision"] = "Existe otra ficha con el mismo nombre a más de 150 m; comprobar si es otro establecimiento."
        recovered.append(candidate)

    new_candidates, skipped_new = [], collections.Counter()
    for entry in report.get("posibles_nuevas_fichas_sin_incorporar", []):
        osm_id = str(entry.get("osm_id") or "")
        m = re.match(r"^(node|way|relation):(\d+)$", osm_id)
        if not m:
            skipped_new["id_invalido"] += 1
            continue
        ident = f"osm-extra:{m.group(1)}:{m.group(2)}"
        if ident in all_ids:
            skipped_new["ya_en_catalogo"] += 1
            continue
        if ident in deleted_override_ids:
            skipped_new["baja_manual_supabase"] += 1
            continue
        tags = entry.get("etiquetas") or {}
        if not relevant(tags):
            skipped_new["sin_interes_directorio"] += 1
            continue
        location = entry.get("coordenadas") or None
        latlon = (location.get("lat"), location.get("lon")) if location and location.get("lat") is not None and location.get("lon") is not None else None
        # No volver a proponer como nueva una ficha que ya fue aprobada
        # en Supabase, aunque aún no figure dentro de items del JSON maestro.
        candidate_name = norm(entry.get("nombre"))
        duplicate_active = False
        for active_item in active_by_name.get(candidate_name, []) if candidate_name else []:
            distance = distance_m(latlon, item_coords(active_item))
            if distance is None or distance <= 150:
                duplicate_active = True
                break
        if duplicate_active:
            skipped_new["posible_duplicado_activo"] += 1
            continue
        candidate = tags_to_fields(entry.get("nombre"), tags, latlon, ident)
        candidate["osm_id"] = osm_id
        candidate["url_osm"] = entry.get("url") or candidate["url_osm"]
        candidate["fuente_estado"] = "Candidata automática detectada en la consulta municipal OSM; requiere aprobación manual"
        new_candidates.append(candidate)

    existing = data.get("candidatas_revision") if isinstance(data.get("candidatas_revision"), list) else []
    manual = [x for x in existing if isinstance(x, dict) and not x.get("_xiclana_osm_auto")]
    manual_ids = {str(x.get("id")) for x in manual if x.get("id")}
    auto = [x for x in recovered + new_candidates if str(x.get("id")) not in manual_ids]
    unique = {}
    for candidate in auto:
        unique.setdefault(str(candidate.get("id")), candidate)
    ordered = sorted(unique.values(), key=lambda x: (norm(x.get("n")), str(x.get("id"))))
    auto = []
    grouped_duplicates = 0
    proximity_warnings = 0
    for candidate in ordered:
        candidate_name = norm(candidate.get("n"))
        candidate_location = item_coords(candidate)
        duplicate = None
        for kept in auto:
            distance = distance_m(candidate_location, item_coords(kept))
            same_name = candidate_name and candidate_name == norm(kept.get("n"))
            if same_name and distance is not None and distance <= 150:
                duplicate = kept
                break
            if (distance is not None and distance <= 35
                    and candidate.get("c") == kept.get("c")
                    and candidate.get("c")):
                note = f"Posible coincidencia geográfica con «{candidate.get('n')}» ({distance:.0f} m); comprobar si es el mismo lugar."
                kept["nota_revision"] = (clean(kept.get("nota_revision")) + " " + note).strip()
                candidate["nota_revision"] = (clean(candidate.get("nota_revision")) + " " + f"Posible coincidencia geográfica con «{kept.get('n')}» ({distance:.0f} m); comprobar si es el mismo lugar.").strip()
                proximity_warnings += 1
        if duplicate:
            duplicate.setdefault("osm_ids_relacionados", []).append(candidate.get("id"))
            duplicate["nota_revision"] = "Varios objetos OSM con el mismo nombre a menos de 150 m; se agrupan para evitar una ficha duplicada."
            grouped_duplicates += 1
        else:
            auto.append(candidate)
    if len(auto) > 250:
        raise SystemExit(f"Se detectaron {len(auto)} candidatas automáticas; supera el límite defensivo de 250. No se modifica el catálogo.")
    summary = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "extraccion_utc": raw.get("fecha_extraccion_utc"),
        "resumen": {
            "candidatas_manuales_conservadas": len(manual),
            "bajas_recuperadas_pendientes": len(recovered),
            "nuevas_detecciones_pendientes": len(new_candidates),
            "total_candidatas_automaticas": len(auto),
            "total_candidatas_revision": len(manual) + len(auto),
            "bajas_manual_supabase_excluidas": skipped_recovered["baja_manual_supabase"],
            "objetos_osm_desaparecidos_excluidos": skipped_recovered["osm_ya_no_existe"],
            "posibles_duplicados_activos_excluidos": skipped_recovered["posible_duplicado_activo"],
            "duplicados_entre_candidatas_agrupados": grouped_duplicates,
            "avisos_de_proximidad_entre_candidatas": proximity_warnings,
            "direcciones_existentes_sobrescritas": 0,
            "fichas_publicadas_automaticamente": 0,
        },
        "recuperadas": [{"id": x.get("id"), "nombre": x.get("n"), "categoria": x.get("c")} for x in recovered],
        "nuevas": [{"id": x.get("id"), "nombre": x.get("n"), "categoria": x.get("c")} for x in new_candidates],
        "descartes_recuperacion": dict(skipped_recovered),
        "descartes_nuevas": dict(skipped_new),
    }
    pending = {
        "fecha_generacion_utc": summary["fecha_utc"],
        "extraccion_utc": summary["extraccion_utc"],
        "resumen": summary["resumen"],
        "candidatas": auto,
    }
    PENDING.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # El catálogo maestro es la única fuente que consume Administración.
    address_path = ROOT / "propuestas_direcciones_osm.json"
    address_doc = json.loads(address_path.read_text(encoding="utf-8")) if address_path.is_file() else {}
    address_proposals = address_doc.get("propuestas", [])
    if not isinstance(address_proposals, list):
        raise SystemExit("El fichero de propuestas de direcciones tiene una estructura inválida.")
    data["candidatas_revision"] = manual + auto
    data["propuestas_direcciones_osm"] = address_proposals
    data["total_candidatas_revision"] = len(data["candidatas_revision"])
    data["integracion_osm_revision"] = {
        "fecha_utc": summary["fecha_utc"],
        "candidatas_revision": len(data["candidatas_revision"]),
        "propuestas_direcciones": len(address_proposals),
        "publicacion_automatica": False,
    }
    MASTER.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\\n", encoding="utf-8")
    print(json.dumps({**summary["resumen"], "maestro_actualizado": True, "propuestas_direcciones_en_maestro": len(address_proposals)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
