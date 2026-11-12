#!/usr/bin/env python3
"""Auditoría municipal completa de OSM. No modifica el catálogo maestro."""
import collections, hashlib, json, math, os, pathlib, re, time, unicodedata, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = pathlib.Path(os.getenv("XICLANA_CATALOG_PATH", str(ROOT / "fichas_completas.json")))
OUT_RAW = ROOT / "osm_chiclana_extraccion_completa.json"
OUT_REPORT = ROOT / "osm_chiclana_cruce_catalogo.json"
AREA_ID = 3600346951  # área Overpass derivada de la relación OSM 346951
SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
QUERY = f"""[out:json][timeout:900];
area({AREA_ID})->.a;
(
  node(area.a);
  way(area.a);
  relation(area.a);
);
out meta geom;"""

def norm(value):
    value = unicodedata.normalize("NFD", str(value or "").casefold())
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", value))

def coords(element):
    if element.get("lat") is not None and element.get("lon") is not None:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if center.get("lat") is not None and center.get("lon") is not None:
        return float(center["lat"]), float(center["lon"])
    geometry = element.get("geometry") or []
    pts = [(float(p["lat"]), float(p["lon"])) for p in geometry if p.get("lat") is not None and p.get("lon") is not None]
    if pts:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return None, None

def distance_m(a, b):
    if None in (a[0], a[1], b[0], b[1]): return None
    r = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0]-a[0]), math.radians(b[1]-a[1])
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(min(1, math.sqrt(h)))

def download():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    errors = []
    for attempt in range(4):
        for server in SERVERS:
            try:
                req = urllib.request.Request(server, data=body, headers={
                    "User-Agent": "Xiclana-Directorio/1.0 (municipal OSM audit; open data)",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                })
                with urllib.request.urlopen(req, timeout=1000) as response:
                    payload = json.load(response)
                if payload.get("remark"):
                    raise RuntimeError(payload["remark"])
                elements = payload.get("elements")
                if not isinstance(elements, list) or not elements:
                    raise RuntimeError("Respuesta sin lista de elementos o vacía.")
                return payload
            except Exception as exc:
                errors.append(f"{server}: {type(exc).__name__}: {exc}")
                print(errors[-1], flush=True)
        if attempt < 3: time.sleep(30 * (attempt + 1))
    raise RuntimeError("No se pudo completar la extracción en ningún servidor:\n" + "\n".join(errors))

def main():
    if not MASTER.exists():
        raise SystemExit(f"No existe el catálogo maestro: {MASTER}")
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    items = master.get("items")
    if not isinstance(items, list):
        raise SystemExit("El catálogo maestro no contiene items; se cancela.")
    payload = download()
    elements = payload["elements"]
    seen, duplicates = set(), []
    for e in elements:
        key = f'{e.get("type")}:{e.get("id")}'
        if key in seen: duplicates.append(key)
        seen.add(key)
    if duplicates:
        raise SystemExit(f"Respuesta OSM con {len(duplicates)} IDs repetidos; extracción no validada.")
    # Conserva la respuesta completa de Overpass, incluidas etiquetas, metadatos y geometría.
    raw = {
        "fecha_extraccion_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fuente": "OpenStreetMap / Overpass API",
        "relacion_municipal_osm": 346951,
        "area_overpass": AREA_ID,
        "consulta": QUERY,
        "elementos": elements,
    }
    raw_bytes = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    OUT_RAW.write_bytes(raw_bytes)
    sha = hashlib.sha256(raw_bytes).hexdigest()

    catalog_by_id = collections.defaultdict(list)
    catalog_by_name = collections.defaultdict(list)
    for item in items:
        iid = str(item.get("id") or "")
        m = re.match(r"^(?:osm|osm-extra):(node|way|relation):(\d+)$", iid)
        if m: catalog_by_id[f"{m.group(1)}:{m.group(2)}"].append(item)
        name = norm(item.get("n") or item.get("nombre") or item.get("name"))
        if name: catalog_by_name[name].append(item)

    counts = collections.Counter(e.get("type", "unknown") for e in elements)
    tagged = sum(bool(e.get("tags")) for e in elements)
    named = [e for e in elements if (e.get("tags") or {}).get("name") or (e.get("tags") or {}).get("name:es") or (e.get("tags") or {}).get("official_name")]
    matches, unmatched_named = [], []
    for e in named:
        t = e.get("tags") or {}
        name = t.get("name") or t.get("name:es") or t.get("official_name")
        key = f'{e.get("type")}:{e.get("id")}'
        latlon = coords(e)
        by_id = catalog_by_id.get(key, [])
        if by_id:
            matches.append({"osm_id": key, "nombre_osm": name, "tipo_coincidencia": "id_osm", "fichas_catalogo": [x.get("n") or x.get("nombre") for x in by_id]})
            continue
        candidates = []
        for item in catalog_by_name.get(norm(name), []):
            ilat, ilon = item.get("lat"), item.get("lon")
            dist = distance_m(latlon, (float(ilat), float(ilon))) if ilat is not None and ilon is not None else None
            candidates.append((dist, item))
        near = [(d, x) for d, x in candidates if d is not None and d <= 150]
        if near:
            near.sort(key=lambda z: z[0])
            matches.append({"osm_id": key, "nombre_osm": name, "tipo_coincidencia": "nombre_y_coordenadas_150m", "fichas_catalogo": [{"nombre": x.get("n") or x.get("nombre"), "id": x.get("id"), "distancia_m": round(d, 1)} for d, x in near]})
        elif candidates:
            matches.append({"osm_id": key, "nombre_osm": name, "tipo_coincidencia": "nombre_sin_confirmacion_espacial", "fichas_catalogo": [{"nombre": x.get("n") or x.get("nombre"), "id": x.get("id"), "distancia_m": round(d, 1) if d is not None else None} for d, x in candidates]})
        else:
            unmatched_named.append({
                "osm_id": key, "tipo_osm": e.get("type"), "nombre": name,
                "coordenadas": {"lat": latlon[0], "lon": latlon[1]},
                "etiquetas": t, "url": f'https://www.openstreetmap.org/{e.get("type")}/{e.get("id")}',
            })

    report = {
        "fecha_extraccion_utc": raw["fecha_extraccion_utc"],
        "fuente": raw["fuente"], "relacion_municipal_osm": 346951,
        "catalogo_maestro": "Supabase public.listings",
        "catalogo_actualizado": master.get("actualizado"),
        "total_fichas_catalogo": len(items),
        "total_candidatas_revision_catalogo": len(master.get("candidatas_revision") or []),
        "extraccion": {
            "total_elementos": len(elements),
            "por_tipo": dict(counts),
            "elementos_con_etiquetas": tagged,
            "elementos_con_nombre": len(named),
            "elementos_con_geometria_completa": sum(bool(e.get("geometry")) for e in elements),
            "ids_duplicados_en_respuesta": len(duplicates),
            "sha256_archivo_extraccion": sha,
            "bytes_archivo_extraccion": len(raw_bytes),
        },
        "cruce": {
            "elementos_osm_con_nombre_cruzados": len(matches),
            "coincidencia_por_id_osm": sum(x["tipo_coincidencia"] == "id_osm" for x in matches),
            "coincidencia_nombre_y_coordenadas_150m": sum(x["tipo_coincidencia"] == "nombre_y_coordenadas_150m" for x in matches),
            "coincidencia_nombre_sin_confirmacion_espacial": sum(x["tipo_coincidencia"] == "nombre_sin_confirmacion_espacial" for x in matches),
            "elementos_osm_con_nombre_sin_ficha_candidata": len(unmatched_named),
        },
        "coincidencias": matches,
        "posibles_nuevas_fichas_sin_incorporar": unmatched_named,
        "reglas": [
            "La extracción incluye nodos, vías y relaciones dentro del área municipal, con metadatos, etiquetas y geometría.",
            "El cruce por ID es exacto; el cruce por nombre y coordenadas es orientativo y requiere revisión.",
            "Los elementos sin coincidencia se entregan como candidatos; no se incorporan al catálogo.",
            "No se modifica public.listings ni se publica ninguna ficha.",
        ],
    }
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"extraccion": report["extraccion"], "cruce": report["cruce"], "archivos": [OUT_RAW.name, OUT_REPORT.name]}, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
