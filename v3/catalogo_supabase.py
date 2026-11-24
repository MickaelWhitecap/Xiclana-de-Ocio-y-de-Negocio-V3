#!/usr/bin/env python3
"""Exporta listings de Supabase a un JSON temporal y sincroniza solo metadatos de revisión.

El JSON generado es una copia de trabajo/exportación; nunca es una fuente de escritura
para las fichas. Las fichas se modifican exclusivamente en public.listings.

Los cambios en este exportador disparan también la copia cifrada y su prueba de restauración.
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


# Guardar sin pedir la fila de vuelta: Supabase solo responde con el número de
# filas afectadas (cabecera Content-Range), no con los ~4 MB del catálogo.
PREFER_MINIMAL = {"Prefer": "return=minimal,count=exact"}
RPC_FUSIONAR = "xiclana_fusionar_catalogo"
RPC_LIMPIAR_CHECKPOINT = "xiclana_limpiar_checkpoint_rad"
LISTING_SELECT = "id,data,is_published,is_deleted,verified_at,updated_at"
_RPC_NO_INSTALADA = object()
_rpc_instalada = True


def affected_rows(result, headers):
    """Filas modificadas por un PATCH con return=minimal (o representation en pruebas)."""
    content_range = ""
    try:
        content_range = str((headers or {}).get("Content-Range") or "")
    except AttributeError:
        content_range = ""
    total = content_range.rsplit("/", 1)[-1] if "/" in content_range else ""
    if total.isdigit():
        return int(total)
    return len(result) if isinstance(result, list) else 0


def call_rpc(base, key, name, args):
    """Llama a una función SQL; si aún no está instalada, avisa una vez y usa el método antiguo."""
    global _rpc_instalada
    if not _rpc_instalada:
        return _RPC_NO_INSTALADA
    try:
        result, _ = request(base + "/rpc/" + name, key, method="POST", payload=args)
        return result
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            _rpc_instalada = False
            print(json.dumps({
                "aviso": "Falta instalar supabase/sql/instalar-ahorro-ancho-banda.sql; "
                         "se usa el método antiguo, que gasta mucho más ancho de banda.",
                "funcion": name,
            }, ensure_ascii=False), flush=True)
            return _RPC_NO_INSTALADA
        raise


def in_filter(ids):
    quoted = ['"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"' for x in ids]
    return "in.(" + ",".join(quoted) + ")"


def fetch_by_ids(base, key, ids, select=LISTING_SELECT):
    """Descarga solo las fichas indicadas (no las ~3.000 del catálogo)."""
    ids = [str(x) for x in dict.fromkeys(ids) if str(x)]
    rows = []
    for start in range(0, len(ids), 80):
        chunk = ids[start:start + 80]
        query = urllib.parse.urlencode({"select": select, "id": in_filter(chunk)})
        page, _ = request(base + "/listings?" + query, key)
        if not isinstance(page, list):
            raise RuntimeError("Respuesta inesperada al leer fichas concretas de public.listings.")
        rows.extend(page)
    return rows


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


def item_from_row(row):
    ident = str(row.get("id") or "")
    if not ident:
        raise RuntimeError("public.listings contiene un ID vacío o duplicado.")
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
    return item


def refresh_items(data, ids):
    """Actualiza en la copia local solo las fichas indicadas, leyéndolas de Supabase.

    Sustituye a volver a exportar el catálogo entero (~7 MB) antes de cada ficha.
    """
    base, key = connection()
    wanted = {str(x) for x in ids if x}
    fresh = {str(r.get("id")): item_from_row(r) for r in fetch_by_ids(base, key, wanted)}
    items = []
    for item in data.get("items", []):
        ident = str(item.get("id") or "") if isinstance(item, dict) else ""
        if ident in wanted:
            if ident in fresh:
                items.append(fresh.pop(ident))
            continue
        items.append(item)
    items.extend(fresh.values())
    data["items"] = items
    data["total_fichas"] = len(items)
    return data


def drop_local_checkpoints(data, target_id):
    """Quita de la copia local los checkpoints RAD ya limpiados en Supabase."""
    progress = data.get("rad_crawl_progress")
    if not isinstance(progress, dict):
        return data
    checkpoints = progress.get("checkpoints")
    if isinstance(checkpoints, dict):
        remaining = {k: v for k, v in checkpoints.items()
                     if not isinstance(v, dict) or str(v.get("target_id") or "") != str(target_id)}
        if remaining:
            data["rad_crawl_progress"] = {**progress, "checkpoints": remaining}
        else:
            data.pop("rad_crawl_progress", None)
    elif str(progress.get("target_id") or "") == str(target_id):
        data.pop("rad_crawl_progress", None)
    return data


def export_catalog(path):
    base, key = connection()
    rows = fetch_all(base, key, "listings", "id,data,is_published,is_deleted,verified_at,updated_at", "id.asc")
    settings, _ = request(base + "/site_settings?select=data&id=eq.catalogo", key)
    if not isinstance(settings, list) or not settings or not isinstance(settings[0].get("data"), dict):
        raise RuntimeError("No se encontraron los metadatos canónicos en public.site_settings.")
    items = []
    seen = set()
    for row in rows:
        item = item_from_row(row)
        if item["id"] in seen:
            raise RuntimeError("public.listings contiene un ID vacío o duplicado.")
        seen.add(item["id"])
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



def sync_enrichment(before_path, after_path, allowed_ids=None):
    """Aplica enriquecimientos RAD solo a IDs autorizados y fichas aún publicadas."""
    allowed_ids = None if allowed_ids is None else {str(x) for x in allowed_ids}
    base, key = connection()
    before = json.loads(pathlib.Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(pathlib.Path(after_path).read_text(encoding="utf-8"))
    if not isinstance(before.get("items"), list) or not isinstance(after.get("items"), list):
        raise RuntimeError("Las copias RAD no contienen listas items válidas.")
    before_by_id = {str(x.get("id")): x for x in before["items"] if isinstance(x, dict) and x.get("id")}
    if allowed_ids is not None:
        # Solo las fichas autorizadas: no hace falta bajar las ~3.000 fichas.
        current_rows = fetch_by_ids(base, key, allowed_ids) if allowed_ids else []
    else:
        current_rows = fetch_all(base, key, "listings", LISTING_SELECT, "id.asc")
    current_by_id = {str(x.get("id")): x for x in current_rows}
    meta_keys = {"id", "is_published", "_xiclana_deleted", "verified_at", "_xiclana_updated_at", "_rad_official_verified"}
    allowed_fields = {
        "a", "h", "d", "t", "c", "rta_registro", "direcciones_alternativas",
        "p", "e", "w", "web_alternativas", "fuentes_datos", "estado_verificacion", "f", "v",
        "r",  # redes sociales enlazadas desde la web propia
    }
    to_update = []
    detected_count = conflict_count = inactive_count = verification_count = 0
    for item in after["items"]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        ident = str(item["id"])
        if allowed_ids is not None and ident not in allowed_ids:
            continue
        original = before_by_id.get(ident)
        current = current_by_id.get(ident)
        if original is None:
            continue
        before_data = {k: v for k, v in original.items() if k not in meta_keys}
        after_data = {k: v for k, v in item.items() if k not in meta_keys}
        changed_keys = [k for k, v in after_data.items() if before_data.get(k) != v]
        verify_official = bool(item.get("_rad_official_verified"))
        if not changed_keys and not verify_official:
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
        promote = verify_official and status != "verificada"
        if current.get("is_deleted") or current.get("is_published") is not True or (status != "verificada" and not promote):
            inactive_count += 1
            continue
        if promote:
            source = str(after_data.get("f") or "").strip()
            date_value = str(after_data.get("v") or "").strip()
            if after_data.get("estado_verificacion") != "verificada" or not source.startswith(("https://", "http://")) or not date_value:
                raise RuntimeError(f"RAD intentó verificar {ident} sin estado, web oficial o fecha válidos.")
        unsafe = sorted(set(changed_keys) - allowed_fields)
        if unsafe:
            raise RuntimeError(f"RAD intentó modificar campos no autorizados en {ident}: {unsafe}")
        safe_changed_keys = []
        for field in changed_keys:
            new_value = after_data[field]
            old_value = current_data.get(field)
            new_is_empty = new_value is None or new_value == "" or new_value == [] or new_value == {}
            old_is_present = old_value is not None and old_value != "" and old_value != [] and old_value != {}
            if new_is_empty and old_is_present:
                continue
            safe_changed_keys.append(field)
        verification_fields = sorted(set(safe_changed_keys) & {"estado_verificacion", "f", "v"})
        if verification_fields and not promote:
            raise RuntimeError(f"RAD intentó cambiar el estado o la procedencia de verificación sin prueba de web oficial en {ident}: {verification_fields}")
        current_clean = {k: v for k, v in current_data.items() if k not in meta_keys}
        if current_clean != before_data or current.get("updated_at") != original.get("_xiclana_updated_at"):
            conflict_count += 1
            continue
        if not safe_changed_keys and not promote:
            continue
        merged = dict(current_data)
        for field in safe_changed_keys:
            merged[field] = after_data[field]
        to_update.append((ident, current, merged, len(safe_changed_keys), promote))

    updated_count = field_count = 0
    for ident, current, merged, changed_count, promote in to_update:
        timestamp = current.get("updated_at")
        filters = {"id": "eq." + ident, "updated_at": "eq." + timestamp if timestamp else "is.null"}
        result, response_headers = request(
            base + "/listings?" + urllib.parse.urlencode(filters),
            key,
            method="PATCH",
            payload={
                "data": merged,
                "verified_at": datetime.now(timezone.utc).isoformat() if promote else current.get("verified_at"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            headers=PREFER_MINIMAL,
        )
        if affected_rows(result, response_headers):
            updated_count += 1
            field_count += changed_count
            if promote:
                verification_count += 1
        else:
            conflict_count += 1
    summary = {
        "tabla": "public.listings",
        "fichas_detectadas": detected_count,
        "fichas_actualizadas": updated_count,
        "campos_actualizados": field_count,
        "saltadas_por_cambio_concurrente": conflict_count,
        "saltadas_por_no_verificadas_o_inactivas": inactive_count,
        "fichas_verificadas_desde_web_oficial": verification_count,
        "publicacion_automatica": False,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return summary



def merge_candidate_lists(current, incoming):
    """Combina candidatas RAD/OSM por ID sin perder altas de ejecuciones concurrentes."""
    merged = []
    positions = {}
    for item in (current if isinstance(current, list) else []):
        if isinstance(item, dict) and item.get("id"):
            ident = str(item["id"])
            if ident in positions:
                merged[positions[ident]] = {**merged[positions[ident]], **item}
            else:
                positions[ident] = len(merged)
                merged.append(dict(item))
        elif item not in merged:
            merged.append(item)
    for item in (incoming if isinstance(incoming, list) else []):
        if isinstance(item, dict) and item.get("id"):
            ident = str(item["id"])
            if ident in positions:
                merged[positions[ident]] = {**merged[positions[ident]], **item}
            else:
                positions[ident] = len(merged)
                merged.append(dict(item))
        elif item not in merged:
            merged.append(item)
    return merged


def clear_rad_crawl_progress(target_id):
    """Elimina checkpoints de una ficha.

    Con la función SQL instalada se borra dentro de la base de datos y no se
    descarga nada; si no, se usa el método antiguo (lee rad_crawl_progress).
    """
    base, key = connection()
    removed = call_rpc(base, key, RPC_LIMPIAR_CHECKPOINT, {"p_ficha": str(target_id)})
    if removed is not _RPC_NO_INSTALADA:
        if removed:
            print(json.dumps({"checkpoint_web_limpiado": True, "ficha_id": str(target_id)}, ensure_ascii=False))
        return
    for attempt in range(3):
        # Solo se lee la clave rad_crawl_progress, no el catálogo entero.
        settings, _ = request(base + "/site_settings?select=id,updated_at,rad_crawl_progress:data->rad_crawl_progress&id=eq.catalogo", key)
        if not isinstance(settings, list) or not settings:
            raise RuntimeError("No existe public.site_settings(id='catalogo').")
        current = drop_local_checkpoints({"rad_crawl_progress": settings[0].get("rad_crawl_progress")}, target_id)
        before = settings[0].get("rad_crawl_progress")
        if current.get("rad_crawl_progress") == before:
            return
        timestamp = settings[0].get("updated_at")
        if not _write_catalog_keys(base, key, current, ["rad_crawl_progress"], timestamp):
            continue
        print(json.dumps({"checkpoint_web_limpiado": True, "ficha_id": str(target_id)}, ensure_ascii=False))
        return
    raise RuntimeError("No se pudo limpiar el checkpoint RAD por conflicto concurrente.")


def _write_catalog_keys(base, key, values, keys, expected_updated_at):
    """Método antiguo (sin función SQL): lee el catálogo y lo guarda entero.

    Aun así, al guardar ya no pide la fila de vuelta (return=minimal).
    Las claves de `keys` ausentes en `values` se eliminan.
    """
    settings, _ = request(base + "/site_settings?select=id,data,updated_at&id=eq.catalogo", key)
    if not isinstance(settings, list) or not settings:
        raise RuntimeError("No existe public.site_settings(id='catalogo').")
    timestamp = settings[0].get("updated_at")
    if expected_updated_at is not None and timestamp != expected_updated_at:
        return False
    current = settings[0].get("data") or {}
    if not isinstance(current, dict):
        raise RuntimeError("Los metadatos actuales de Supabase no son un objeto.")
    updated = dict(current)
    for name in keys:
        if name in values:
            updated[name] = values[name]
        else:
            updated.pop(name, None)
    filters = {"id": "eq.catalogo", "updated_at": "eq." + timestamp if timestamp else "is.null"}
    result, response_headers = request(
        base + "/site_settings?" + urllib.parse.urlencode(filters),
        key,
        method="PATCH",
        payload={"data": updated, "updated_at": datetime.now(timezone.utc).isoformat()},
        headers=PREFER_MINIMAL,
    )
    return bool(affected_rows(result, response_headers))


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
    # Ya no se descarga el catálogo entero (~4 MB): solo, si hace falta, la lista de
    # candidatas para combinarla; el resto de claves se fusiona dentro de Supabase.
    for attempt in range(3):
        patch_to_apply = dict(patch)
        timestamp = None
        if "candidatas_revision" in patch_to_apply:
            settings, _ = request(
                base + "/site_settings?select=id,updated_at,candidatas_revision:data->candidatas_revision&id=eq.catalogo", key)
            if not isinstance(settings, list) or not settings:
                raise RuntimeError("No existe public.site_settings(id='catalogo').")
            timestamp = settings[0].get("updated_at")
            patch_to_apply["candidatas_revision"] = merge_candidate_lists(
                settings[0].get("candidatas_revision") or [],
                patch_to_apply["candidatas_revision"],
            )
            patch_to_apply["total_candidatas_revision"] = len(patch_to_apply["candidatas_revision"])
        saved = call_rpc(base, key, RPC_FUSIONAR, {"p_cambios": patch_to_apply, "p_esperado": timestamp})
        if saved is _RPC_NO_INSTALADA:
            saved = _write_catalog_keys(base, key, patch_to_apply, list(patch_to_apply), timestamp)
        if saved:
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
