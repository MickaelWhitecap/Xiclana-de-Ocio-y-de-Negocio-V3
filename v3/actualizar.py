#!/usr/bin/env python3
"""Valida y normaliza el único catálogo JSON de Xiclana V3."""
import json, pathlib, datetime, hashlib, sys, re, urllib.parse, urllib.request
ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "fichas_completas.json"
def main():
    if not DATA.exists(): sys.exit("No existe el fichero maestro; se cancela para proteger el catálogo.")
    try: data = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception as exc: sys.exit(f"El fichero maestro no es JSON válido: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list): sys.exit("El fichero maestro no contiene una lista items; no se modifica.")
    items, seen = [], set()
    for index, raw in enumerate(data["items"]):
        if not isinstance(raw, dict):
            sys.exit(f"Elemento inválido en items[{index}]; se cancela la sincronización para no perder datos.")
        item = dict(raw); name = str(item.get("n", "")).strip()
        if " ".join(name.casefold().split()) in {"agua", "agua potable"}: continue
        if not item.get("id"):
            seed = "\\x1f".join(str(item.get(k, "") or "").strip().casefold() for k in ("n", "t", "c", "a"))
            item["id"] = "consolidado:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
        ident = str(item["id"])
        if ident in seen:
            sys.exit(f"ID duplicado en el catálogo maestro ({ident}); se cancela la sincronización para no alterar referencias ni perder datos.")
        seen.add(ident); items.append(item)
    # Sincronizar las ediciones administrativas vigentes sin crear otro fichero de datos.
    config_text = (ROOT / "supabase-config.js").read_text(encoding="utf-8")
    url_match = re.search(r'url:\s*"([^"]+)"', config_text)
    key_match = re.search(r'anonKey:\s*"([^"]+)"', config_text)
    if not url_match or not key_match:
        sys.exit("No se pudo leer la configuración pública de Supabase; no se publica un catálogo posiblemente incompleto.")
    api_url, api_key = url_match.group(1).rstrip("/"), key_match.group(1)
    query = urllib.parse.urlencode({"select":"listing_id,fields,is_new,verified_at,updated_at","order":"updated_at.asc,listing_id.asc"})
    headers = {"apikey":api_key,"Authorization":"Bearer " + api_key,"Accept":"application/json","User-Agent":"Xiclana-V3-catalog-sync/1.0"}
    overrides = []
    page_size = 500
    offset = 0
    try:
        while True:
            request = urllib.request.Request(api_url + "/rest/v1/listing_overrides?" + query, headers={**headers,"Range":f"{offset}-{offset + page_size - 1}","Range-Unit":"items"})
            with urllib.request.urlopen(request, timeout=30) as response:
                page = json.load(response)
                content_range = response.headers.get("Content-Range", "")
            if not isinstance(page, list):
                sys.exit("Supabase devolvió un formato inesperado para listing_overrides; no se modifica el catálogo.")
            overrides.extend(page)
            if len(page) < page_size:
                break
            # Repetir con un rango explícito para no truncar catálogos grandes.
            offset += len(page)
            if offset > 100000:
                sys.exit("La sincronización superó el límite defensivo de 100.000 overrides; se cancela sin publicar.")
    except Exception as exc:
        sys.exit(f"No se pudieron sincronizar todas las fichas administrativas de Supabase: {exc}")
    by_id = {str(x.get("id", "")): x for x in items if x.get("id")}
    merged = added = hidden = 0
    for row in overrides:
        ident = str(row.get("listing_id", ""))
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        item = by_id.get(ident)
        if fields.get("_xiclana_deleted") is True:
            if item:
                item["_xiclana_deleted"] = True
                hidden += 1
            continue
        if item is None and row.get("is_new"):
            item = dict(fields)
            item["id"] = ident
            item["fuente_estado"] = "Ficha administrativa sincronizada desde Supabase"
            items.append(item)
            by_id[ident] = item
            added += 1
        elif item is not None:
            for key, value in fields.items():
                if key != "_xiclana_deleted" and value not in (None, ""):
                    item[key] = value
            if row.get("is_new"):
                item.setdefault("fuente_estado", "Ficha administrativa sincronizada desde Supabase")
            merged += 1
    items.sort(key=lambda x: str(x.get("n", "")).casefold())
    data["items"] = items
    data["sincronizacion_supabase"] = {"fecha":datetime.date.today().isoformat(),"overrides_leidos":len(overrides),"fichas_nuevas_incorporadas":added,"fichas_existentes_actualizadas":merged,"marcas_de_borrado_conservadas":hidden}
    if not isinstance(data.get("candidatas_revision"), list): data["candidatas_revision"] = []
    data["actualizado"] = datetime.date.today().isoformat()
    data["total_fichas"] = len(items); data["total_candidatas_revision"] = len(data["candidatas_revision"])
    data["fuente_unica"] = "fichas_completas.json"
    DATA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Catálogo maestro validado: {len(items)} fichas y {len(data['candidatas_revision'])} candidatas.")
if __name__ == "__main__": main()
