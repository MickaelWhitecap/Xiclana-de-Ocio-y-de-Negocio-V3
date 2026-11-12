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
        item["_xiclana_updated_at"] = row.get("updated_at")
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



def sync_enrichment(before_path, after_path):
    """Aplica solo campos seguros añadidos por RAD a fichas verificadas y activas."""
    base, key = connection()
    before = json.loads(pathlib.Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(pathlib.Path(after_path).read_text(encoding="utf-8"))
    if not isinstance(before.get("items"), list) or not isinstance(after.get("items"), list):
        raise RuntimeError("Las copias RAD no contienen listas items válidas.")
    before_by_id = {str(x.get("id")): x for x in before["items"] if isinstance(x, dict) and x.get("id")}
    current_rows = fetch_all(base, key, "listings", "id,data,is_published,is_deleted,verified_at,updated_at", "id.asc")
    current_by_id = {str(x.get("id")): x for x in current_rows}
    meta_keys = {"id", "is_published", "_xiclana_deleted", "verified_at", "_xiclana_updated_at"}
    allowed_fields = {
        "a", "h", "d", "t", "c", "rta_registro", "direcciones_alternativas",
        "p", "e", "w", "web_alternativas", "fuentes_datos",
    }
    to_update = []
    detected_count = conflict_count = inactive_count = 0
    for item in after["items"]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        ident = str(item["id"])
        original = before_by_id.get(ident)
        current = current_by_id.get(ident)
        if original is None:
            continue
        before_data = {k: v for k, v in original.items() if k not in meta_keys}
        after_data = {k: v for k, v in item.items() if k not in meta_keys}
        changed_keys = [k for k, v in after_data.items() if before_data.get(k) != v]
        if not changed_keys:
            continue
        detected_count += 1
        if current is None:
            conflict_count += 1
            continue
        current_data = current.get("data") or {}
        if not isinstance(current_data, dict):
            conflict_count += 1
            continue
        status = str(current_data.get("estado_verificacion") or "").strip().casefold()
        if current.get("is_deleted") or not current.get("is_published") or status != "verificada":
            inactive_count += 1
            continue
        unsafe = sorted(set(changed_keys) - allowed_fields)
        if unsafe:
            raise RuntimeError(f"RAD intentó modificar campos no autorizados en {ident}: {unsafe}")
        current_clean = {k: v for k, v in current_data.items() if k not in meta_keys}
        if current_clean != before_data or current.get("updated_at") != original.get("_xiclana_updated_at"):
            conflict_count += 1
            continue
        merged = dict(current_data)
        for field in changed_keys:
            merged[field] = after_data[field]
        to_update.append((ident, current, merged, len(changed_keys)))

    if len(to_update) > 500:
        raise RuntimeError(f"RAD propone modificar {len(to_update)} fichas; se supera el límite defensivo de 500 y no se aplica ninguna.")

    updated_count = field_count = 0
    for ident, current, merged, changed_count in to_update:
        timestamp = current.get("updated_at")
        filters = {"id": "eq." + ident, "updated_at": "eq." + timestamp if timestamp else "is.null"}
        result, _ = request(
            base + "/listings?" + urllib.parse.urlencode(filters),
            key,
            method="PATCH",
            payload={"data": merged, "updated_at": datetime.now(timezone.utc).isoformat()},
            headers={"Prefer": "return=representation"},
        )
        if isinstance(result, list) and result:
            updated_count += 1
            field_count += changed_count
        else:
            conflict_count += 1
    summary = {
        "tabla": "public.listings",
        "fichas_detectadas": detected_count,
        "fichas_actualizadas": updated_count,
        "campos_actualizados": field_count,
        "saltadas_por_cambio_concurrente": conflict_count,
        "saltadas_por_no_verificadas_o_inactivas": inactive_count,
        "publicacion_automatica": False,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def sync_metadata(path, keys):
    base, key = connection()
    working = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(working, dict) or not isinstance(working.get("items"), list):
        raise RuntimeError("El catálogo temporal no tiene una estructura válida.")
    patch = {name: working[name] for name in keys if name in working}
    if "candidatas_revision" in patch:
        if not isinstance(patch["candidatas_revision"], list):
            raise RuntimeError("candidatas_revision debe ser una lista.")
        patch["total_candidatas_revision"] = len(patch["candidatas_revision"])
    if not patch:
        print(json.dumps({"metadatos_actualizados": [], "fichas_modificadas": 0}, ensure_ascii=False))
        return

    # Control optimista de concurrencia: evita pisar cambios recientes de Administración.
    for attempt in range(3):
        settings, _ = request(base + "/site_settings?select=id,data,updated_at&id=eq.catalogo", key)
        if not isinstance(settings, list) or not settings:
            raise RuntimeError("No existe public.site_settings(id='catalogo').")
        current = settings[0].get("data") or {}
        if not isinstance(current, dict):
            raise RuntimeError("Los metadatos actuales de Supabase no son un objeto.")
        updated = dict(current)
        updated.update(patch)
        timestamp = settings[0].get("updated_at")
        filters = {"id": "eq.catalogo", "updated_at": "eq." + timestamp if timestamp else "is.null"}
        result, _ = request(
            base + "/site_settings?" + urllib.parse.urlencode(filters),
            key,
            method="PATCH",
            payload={"data": updated, "updated_at": datetime.now(timezone.utc).isoformat()},
            headers={"Prefer": "return=representation"},
        )
        if isinstance(result, list) and result:
            print(json.dumps({
                "tabla": "public.site_settings",
                "id": "catalogo",
                "metadatos_actualizados": sorted(patch),
                "fichas_modificadas": 0,
                "control_concurrencia": "ok",
            }, ensure_ascii=False))
            return
    raise RuntimeError("Los metadatos cambiaron durante tres intentos; no se sobrescribió ningún cambio concurrente.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Exporta fichas y metadatos desde Supabase a un JSON temporal.")
    export.add_argument("--output", required=True)
    enrich = sub.add_parser("sync-enrichment", help="Aplica a listings solo los campos vacíos completados por RAD.")
    enrich.add_argument("--before", required=True)
    enrich.add_argument("--after", required=True)
    sync = sub.add_parser("sync-metadata", help="Actualiza solo metadatos de revisión en Supabase.")
    sync.add_argument("--input", required=True)
    sync.add_argument("--keys", nargs="+", default=list(DEFAULT_METADATA_KEYS))
    args = parser.parse_args()
    try:
        if args.command == "export":
            export_catalog(args.output)
        elif args.command == "sync-enrichment":
            sync_enrichment(args.before, args.after)
        else:
            sync_metadata(args.input, args.keys)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise SystemExit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
