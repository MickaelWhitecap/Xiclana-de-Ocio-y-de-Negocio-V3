#!/usr/bin/env python3
"""Incorpora al catálogo maestro la extracción OSM y auditoría ya verificadas."""
import collections, hashlib, json, pathlib, sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = ROOT / "fichas_completas.json"
RAW = ROOT / "osm_import" / "osm_chiclana_extraccion_completa.json"
REPORT = ROOT / "osm_import" / "osm_chiclana_cruce_catalogo.json"

def fail(message):
    raise SystemExit("ERROR: " + message)

def main():
    for path in (MASTER, RAW, REPORT):
        if not path.is_file() or path.stat().st_size == 0:
            fail(f"Falta archivo o está vacío: {path}")
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    raw_bytes = RAW.read_bytes()
    raw = json.loads(raw_bytes)
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    if not isinstance(master.get("items"), list):
        fail("El catálogo maestro no contiene una lista items válida.")
    if raw.get("relacion_municipal_osm") != 346951 or raw.get("area_overpass") != 3600346951:
        fail("La extracción no corresponde al ámbito municipal esperado.")
    elements = raw.get("elementos")
    if not isinstance(elements, list) or len(elements) != 132875:
        fail(f"Cantidad inesperada de elementos OSM: {len(elements) if isinstance(elements,list) else 'inválida'}.")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    expected = report.get("extraccion", {}).get("sha256_archivo_extraccion")
    if digest != expected:
        fail(f"SHA-256 no coincide: archivo={digest}, auditoría={expected}.")
    keys = [f'{e.get("type")}:{e.get("id")}' for e in elements]
    if len(set(keys)) != len(keys):
        fail("La extracción contiene IDs OSM duplicados.")
    if report.get("extraccion", {}).get("total_elementos") != len(elements):
        fail("El total del informe no coincide con la extracción.")
    # Verificación del recuento por tipo antes de guardar.
    counts = dict(collections.Counter(e.get("type", "unknown") for e in elements))
    if counts != report.get("extraccion", {}).get("por_tipo"):
        fail(f"Los recuentos por tipo no coinciden: {counts}.")
    if master.get("osm_extraccion_inicial", {}).get("sha256_archivo_extraccion") == digest:
        print("La extracción ya está incorporada con la misma huella; no se modifica el catálogo.")
        return
    original_items = len(master["items"])
    original_candidates = len(master.get("candidatas_revision") or [])
    master["osm_extraccion_inicial"] = {
        "fecha_extraccion_utc": raw["fecha_extraccion_utc"],
        "fuente": raw["fuente"],
        "relacion_municipal_osm": raw["relacion_municipal_osm"],
        "area_overpass": raw["area_overpass"],
        "consulta": raw["consulta"],
        "total_objetos": len(elements),
        "objetos_por_tipo": counts,
        "sha256_archivo_extraccion": digest,
        "bytes_archivo_extraccion": len(raw_bytes),
        "objetos": elements,
    }
    master["auditoria_osm"] = report
    master["auditoria_osm"]["integridad_verificada_al_incorporar"] = {
        "sha256_verificado": digest,
        "total_objetos_verificados": len(elements),
        "ids_duplicados": 0,
        "recuentos_por_tipo_verificados": counts,
        "fecha_verificacion_utc": datetime.now(timezone.utc).isoformat(),
        "items_catalogo_modificados": False,
        "candidatas_publicadas": False,
    }
    if len(master["items"]) != original_items or len(master.get("candidatas_revision") or []) != original_candidates:
        fail("La operación alteró inesperadamente el número de fichas o candidatas.")
    master["actualizado"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    MASTER.write_text(json.dumps(master, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({
        "resultado": "incorporacion_verificada",
        "objetos": len(elements),
        "por_tipo": counts,
        "sha256": digest,
        "fichas_maestro_preservadas": original_items,
        "candidatas_revision_preservadas": original_candidates,
        "publicacion_automatica": False,
        "destino": MASTER.name,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
