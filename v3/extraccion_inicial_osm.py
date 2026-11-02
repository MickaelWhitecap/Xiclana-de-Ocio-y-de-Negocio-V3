#!/usr/bin/env python3
"""Extracción inicial íntegra de etiquetas OSM para el municipio de Chiclana."""
import gzip
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = ROOT / "fichas_completas.json"
SNAPSHOT = ROOT / "osm_extraccion_inicial.json.gz"
REPORT = ROOT / "informe_extraccion_osm.json"
AREA_ID = 3600346951  # relation OSM 346951 convertida a area Overpass
SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
KINDS = ("node", "way", "relation")
USER_AGENT = "Xiclana-OSM-initial-extraction/1.0 (open-data catalog)"

def query_overpass(kind):
    q = (
        "[out:json][timeout:300];"
        f"{kind}(area:{AREA_ID});"
        "out tags;"
    )
    body = urllib.parse.urlencode({"data": q}).encode()
    errors = []
    for attempt in range(3):
        for server in SERVERS:
            try:
                req = urllib.request.Request(
                    server, data=body,
                    headers={"User-Agent": USER_AGENT,
                             "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=360) as response:
                    payload = json.load(response)
                if payload.get("remark"):
                    raise RuntimeError("Overpass devolvió remark: " + str(payload["remark"]))
                elements = payload.get("elements")
                if not isinstance(elements, list):
                    raise RuntimeError("Respuesta sin lista elements")
                for obj in elements:
                    if obj.get("type") != kind or not isinstance(obj.get("tags", {}), dict):
                        raise RuntimeError("Objeto inesperado o sin etiquetas válidas")
                return elements, server
            except Exception as exc:
                errors.append(f"{server} intento {attempt + 1}: {type(exc).__name__}: {exc}")
        if attempt < 2:
            time.sleep(20 * (attempt + 1))
    raise RuntimeError("No se pudo completar la consulta de " + kind + ". " + " | ".join(errors))

def osm_key(obj):
    return f"{obj.get('type')}:{obj.get('id')}"

def catalog_osm_ids(items):
    ids = set()
    for item in items:
        ident = str(item.get("id", ""))
        m = re.search(r"(?:osm|osm-extra):(node|way|relation):(\d+)$", ident)
        if m:
            ids.add(f"{m.group(1)}:{m.group(2)}")
    return ids

def main():
    if not MASTER.is_file():
        sys.exit("No existe el catálogo maestro; se cancela.")
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    items = master.get("items")
    if not isinstance(items, list):
        sys.exit("El catálogo maestro no contiene items válidos; se cancela.")

    collected = {}
    servers_used = {}
    for kind in KINDS:
        elements, server = query_overpass(kind)
        servers_used[kind] = server
        for obj in elements:
            key = osm_key(obj)
            if key in collected:
                raise RuntimeError("ID OSM duplicado en la extracción: " + key)
            collected[key] = {
                "type": obj["type"],
                "id": obj["id"],
                "tags": obj.get("tags", {})
            }
        print(f"{kind}: {len(elements)} objetos descargados desde {server}", flush=True)

    counts = {kind: sum(1 for x in collected.values() if x["type"] == kind) for kind in KINDS}
    known = catalog_osm_ids(items)
    extracted_ids = set(collected)
    matched = extracted_ids & known
    unmatched_named = []
    for key, obj in collected.items():
        tags = obj["tags"]
        name = tags.get("name") or tags.get("name:es") or tags.get("official_name")
        if name and key not in known:
            unmatched_named.append({
                "osm_id": key,
                "name": name,
                "tags": tags
            })
    unmatched_named.sort(key=lambda x: str(x["name"]).casefold())

    ordered = [collected[k] for k in sorted(collected)]
    raw = json.dumps(ordered, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with SNAPSHOT.open("wb") as target:
        with gzip.GzipFile(fileobj=target, mode="wb", compresslevel=9, mtime=0) as stream:
            stream.write(raw)
    digest = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()

    report = {
        "estado": "extraccion_completada_sin_errores",
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "municipio": "Chiclana de la Frontera",
        "osm_relation_id": 346951,
        "overpass_area_id": AREA_ID,
        "consulta": "Descarga separada de node, way y relation dentro del area municipal; salida tags.",
        "etiquetas": "Se conserva íntegro el diccionario tags de cada objeto devuelto por Overpass.",
        "servidores_por_tipo": servers_used,
        "objetos_por_tipo": counts,
        "total_objetos": len(ordered),
        "ids_osm_en_catalogo": len(known),
        "objetos_coincidentes_por_id": len(matched),
        "objetos_no_encontrados_por_id": len(extracted_ids - known),
        "objetos_catalogo_osm_no_devuelto": len(known - extracted_ids),
        "objetos_nuevos_con_nombre": len(unmatched_named),
        "nuevos_con_nombre": unmatched_named,
        "archivo_datos": SNAPSHOT.name,
        "sha256_archivo_gzip": digest,
        "bytes_comprimidos": SNAPSHOT.stat().st_size,
        "bytes_json_sin_comprimir": len(raw),
        "limitacion": "El resultado certifica la respuesta completa de Overpass para el area y consulta indicadas; no afirma que OSM contenga todos los establecimientos reales."
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "estado", "objetos_por_tipo", "total_objetos",
        "objetos_coincidentes_por_id", "objetos_no_encontrados_por_id",
        "objetos_catalogo_osm_no_devuelto", "objetos_nuevos_con_nombre",
        "sha256_archivo_gzip", "bytes_comprimidos"
    )}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
