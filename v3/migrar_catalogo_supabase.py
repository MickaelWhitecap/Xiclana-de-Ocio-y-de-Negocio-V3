#!/usr/bin/env python3
"""Migración idempotente del catálogo y overrides a la tabla canónica Supabase."""
import datetime, hashlib, json, os, pathlib, re, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).parent
CATALOG = ROOT / "fichas_completas.json"
CONFIG = ROOT / "supabase-config.js"

def request(url, key, method="GET", payload=None, extra=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    headers = {"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json",
               "Content-Type": "application/json", "User-Agent": "Xiclana-canonical-migration/1.0"}
    headers.update(extra or {})
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                raw = response.read()
                return json.loads(raw) if raw else None, response.headers
        except urllib.error.HTTPError as exc:
            if exc.code not in (408, 425, 429, 500, 502, 503, 504, 520, 522, 524) or attempt == 7:
                raise
            time.sleep(min(60, 3 * (2 ** attempt)))
        except (TimeoutError, urllib.error.URLError):
            if attempt == 7:
                raise
            time.sleep(min(60, 3 * (2 ** attempt)))
    raise RuntimeError("Supabase no respondió tras varios intentos.")

def paged(url, key, page_size=500):
    result, offset = [], 0
    separator = "&" if "?" in url else "?"
    while True:
        page_url = url + separator + "limit=" + str(page_size) + "&offset=" + str(offset)
        page, _headers = request(page_url, key)
        if not isinstance(page, list):
            raise RuntimeError("Respuesta inesperada al leer datos de Supabase.")
        if not page:
            return result
        result.extend(page)
        if len(page) < page_size:
            return result
        offset += len(page)
        if offset > 100000:
            raise RuntimeError("Se superó el límite defensivo de lectura.")

def main():
    if os.getenv("XICLANA_ALLOW_INITIAL_MIGRATION") != "1":
        raise SystemExit("Migración inicial ya completada. Para impedir una reimportación accidental, este script requiere XICLANA_ALLOW_INITIAL_MIGRATION=1.")
    if not CATALOG.is_file():
        raise SystemExit("No existe el catálogo fuente; migración cancelada.")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
        raise SystemExit("El catálogo no contiene items; migración cancelada.")
    config = CONFIG.read_text(encoding="utf-8")
    match = re.search(r'url:\s*"([^"]+)"', config)
    key = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not match or not key:
        raise SystemExit("Falta URL de Supabase o secreto de servicio.")
    base = match.group(1).rstrip("/") + "/rest/v1/"
    overrides = paged(base + "listing_overrides?select=listing_id,fields,is_new,verified_at,updated_at&order=updated_at.asc,listing_id.asc", key)
    items, by_id = [], {}
    for index, raw in enumerate(catalog["items"]):
        if not isinstance(raw, dict):
            raise SystemExit(f"Ficha inválida en posición {index}.")
        item = dict(raw)
        if not item.get("id"):
            seed = "\\x1f".join(str(item.get(k, "") or "").strip().casefold() for k in ("n", "t", "c", "a"))
            item["id"] = "consolidado:" + hashlib.sha256(seed.encode()).hexdigest()[:20]
        ident = str(item["id"])
        if ident in by_id:
            raise SystemExit("ID duplicado en catálogo: " + ident)
        by_id[ident] = item
        items.append(item)
    added = merged = 0
    override_by_id = {}
    for row in overrides:
        ident = str(row.get("listing_id") or "")
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        if not ident:
            continue
        item = by_id.get(ident)
        if item is None and row.get("is_new"):
            item = {k:v for k,v in fields.items() if k not in {"_xiclana_restore_deleted","_xiclana_address_proposal_rejected"}}
            item["id"] = ident
            item.setdefault("fuente_estado", "Ficha administrativa migrada a Supabase")
            by_id[ident] = item
            items.append(item)
            added += 1
        elif item is not None:
            if fields.get("_xiclana_restore_deleted") is True:
                item.pop("_xiclana_deleted", None)
            for k, v in fields.items():
                if k in {"_xiclana_deleted","_xiclana_restore_deleted","_xiclana_address_proposal_rejected"}:
                    if k == "_xiclana_deleted" and v is True:
                        item[k] = True
                    continue
                if v is None:
                    item.pop(k, None)
                elif v != "":
                    item[k] = v
            merged += 1
        if item is not None:
            override_by_id[ident] = row
    records = []
    for item in items:
        ident = str(item["id"])
        row = override_by_id.get(ident, {})
        data = dict(item)
        data["is_new"] = bool(row.get("is_new", data.get("is_new", False)))
        deleted = data.get("_xiclana_deleted") is True
        records.append({
            "id": ident, "data": data, "is_published": not deleted, "is_deleted": deleted,
            "verified_at": row.get("verified_at") or data.get("verified_at") or None,
            "updated_at": row.get("updated_at") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_by": None
        })
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        raise SystemExit("IDs duplicados tras fusionar overrides.")
    for start in range(0, len(records), 50):
        request(base + "listings?on_conflict=id", key, "POST", records[start:start+50],
                {"Prefer":"resolution=merge-duplicates,return=minimal"})
    metadata = {k:catalog[k] for k in ("destacados","candidatas_revision","total_candidatas_revision","propuestas_direcciones_osm","actualizado") if k in catalog}
    metadata["migracion_supabase"] = {"fecha":datetime.datetime.now(datetime.timezone.utc).isoformat(),
      "fichas_fuente":len(catalog["items"]), "overrides_leidos":len(overrides),
      "fichas_nuevas_de_overrides":added, "fichas_actualizadas_por_overrides":merged,
      "total_migrado":len(records)}
    request(base + "site_settings?on_conflict=id", key, "POST",
            {"id":"catalogo","data":metadata,"updated_at":datetime.datetime.now(datetime.timezone.utc).isoformat()},
            {"Prefer":"resolution=merge-duplicates,return=minimal"})
    # Verificación independiente: todas las IDs migradas deben estar presentes.
    found = paged(base + "listings?select=id&order=id.asc", key)
    found_ids = {x["id"] for x in found}
    missing = set(ids) - found_ids
    if missing:
        raise SystemExit(f"Verificación fallida: faltan {len(missing)} IDs en Supabase.")
    print(json.dumps({"fuente_items":len(catalog["items"]),"overrides":len(overrides),
      "total_registros_supabase":len(found),"nuevas_desde_overrides":added,
      "fusionadas":merged,"faltantes":len(missing)},ensure_ascii=False))
if __name__ == "__main__":
    main()
