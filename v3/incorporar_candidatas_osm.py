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



def integrate_review_data(data, manual, auto, address_proposals, summary):
    """Mantiene las propuestas OSM dentro del único catálogo maestro."""
    integrate_review_data(data, manual, auto, address_proposals, summary)
    MASTER.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\\n", encoding="utf-8")
    print(json.dumps({**summary["resumen"], "maestro_actualizado": True, "propuestas_direcciones_en_maestro": len(address_proposals)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
