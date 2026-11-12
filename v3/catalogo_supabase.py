#!/usr/bin/env python3
"""Exporta listings de Supabase a un JSON temporal y sincroniza solo metadatos de revisión.

El JSON generado es una copia de trabajo/exportación; nunca es una fuente de escritura
para las fichas. Las fichas se modifican exclusivamente en public.listings.
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG = ROOT / "supabase-config.js"
DEFAULT_METADATA_KEYS = (
    "candidatas_revision",
    "total_candidatas_revision",
    "propuestas_direcciones_osm",
    "integracion_osm_revision",
    "auditoria_osm_objetos_sin_ficha",
    "rad_ultima_ejecucion",
)


def connection():
    config = CONFIG.read_text(encoding="utf-8")
    url = re.search(r'url:\s*"([^"]+)"', config)
    key = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError("Falta URL de Supabase o el secreto SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY.")
    return url.group(1).rstrip("/") + "/rest/v1", key


def request(url, key, method="GET", payload=None, headers=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request_headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "User-Agent": "Xiclana-Supabase-catalog-export/1.0",
    }
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read()
        return json.loads(raw) if raw else None, response.headers


def fetch_all(base, key, table, select, order):
    rows, offset, page_size = [], 0, 500
    query = urllib.parse.urlencode({"select": select, "order": order})
    while True:
        url = f"{base}/{table}?{query}"
        page, _ = request(url, key, headers={
            "Range": f"{offset}-{offset + page_size - 1}",
            "Range-Unit": "items",
        })
        if not isinstance(page, list):
            raise RuntimeError(f"Respuesta inesperada al leer public.{table}.")
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += len(page)
        if offset > 100000:
            raise RuntimeError(f"Se superó el límite defensivo al leer public.{table}.")


def export_catalog(path):
    base, key = connection()
    rows = fetch_all(base, key, "listings", "id,data,is_published,is_deleted,verified_at,updated_at", "id.asc")
    settings, _ = request(base + "/site_settings?select=data&id=eq.catalogo", key)
    if not isinstance(settings, list) or not settings or not isinstance(settings[0].get("data"), dict):
        raise RuntimeError("No se encontraron los metadatos canónicos en public.site_settings.")
    items = []
    seen = set()
    for row in rows:
        ident = str(row.get("id") or "")
        if not ident or ident in seen:
            raise RuntimeError("public.listings contiene un ID vacío o duplicado.")
        seen.add(ident)
        data = row.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(f"La ficha {ident} no contiene un objeto data válido.")
        item = dict(data)
        item["id"] = ident
        item["is_published"] = bool(row.get("is_published"))
        if row.get("is_deleted"):
            item["_xiclana_deleted"] = True
        else:
            item.pop("_xiclana_deleted", None)
        if row.get("verified_at"):
            item["verified_at"] = row["verified_at"]
        items.append(item)
    result = dict(settings[0]["data"])
    result["items"] = items
    result["total_fichas"] = len(items)
    result["exportado_desde"] = "Supabase public.listings"
    result["exportado_utc"] = datetime.now(timezone.utc).isoformat()
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "fuente": "public.listings",
        "fichas_exportadas": len(items),
        "publicadas": sum(1 for x in items if x.get("is_published") and not x.get("_xiclana_deleted")),
        "papelera": sum(1 for x in items if x.get("_xiclana_deleted")),
        "destino_temporal": str(path),
    }, ensure_ascii=False))


def sync_metadata(path, keys):
    base, key = connection()
    working = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(working, dict) or not isinstance(working.get("items"), list):
        raise RuntimeError("El catálogo temporal no tiene una estructura válida.")
    settings, _ = request(base + "/site_settings?select=id,data&id=eq.catalogo", key)
    if not isinstance(settings, list) or not settings:
        raise RuntimeError("No existe public.site_settings(id='catalogo').")
    current = settings[0].get("data") or {}
    if not isinstance(current, dict):
        raise RuntimeError("Los metadatos actuales de Supabase no son un objeto.")
    updated = dict(current)
    for name in keys:
        if name in working:
            updated[name] = working[name]
    if "candidatas_revision" in keys and "candidatas_revision" in updated:
        if not isinstance(updated["candidatas_revision"], list):
            raise RuntimeError("candidatas_revision debe ser una lista.")
        updated["total_candidatas_revision"] = len(updated["candidatas_revision"])
    payload = {
        "data": updated,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result, _ = request(
        base + "/site_settings?id=eq.catalogo",
        key,
        method="PATCH",
        payload=payload,
        headers={"Prefer": "return=representation"},
    )
    if not isinstance(result, list) or not result:
        raise RuntimeError("Supabase no confirmó la actualización de metadatos.")
    print(json.dumps({
        "tabla": "public.site_settings",
        "id": "catalogo",
        "metadatos_actualizados": [name for name in keys if name in working],
        "fichas_modificadas": 0,
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Exporta fichas y metadatos desde Supabase a un JSON temporal.")
    export.add_argument("--output", required=True)
    sync = sub.add_parser("sync-metadata", help="Actualiza solo metadatos de revisión en Supabase.")
    sync.add_argument("--input", required=True)
    sync.add_argument("--keys", nargs="+", default=list(DEFAULT_METADATA_KEYS))
    args = parser.parse_args()
    try:
        if args.command == "export":
            export_catalog(args.output)
        else:
            sync_metadata(args.input, args.keys)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise SystemExit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
