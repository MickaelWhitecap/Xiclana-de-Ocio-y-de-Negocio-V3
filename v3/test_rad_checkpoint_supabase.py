#!/usr/bin/env python3
"""Prueba controlada de persistencia RAD en Supabase sin modificar fichas."""
import copy, json, pathlib, sys, tempfile, uuid
ROOT=pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
import catalogo_supabase as catalog
from rastreo_web_publico import store_crawl_checkpoint

def read_data(base,key):
    rows,_=catalog.request(base+"/site_settings?select=id,data&id=eq.catalogo",key)
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0].get("data"),dict):
        raise RuntimeError("No se pudo leer site_settings/catalogo")
    return rows[0]["data"]

def main():
    base,key=catalog.connection()
    test_id="__rad_checkpoint_test__"+uuid.uuid4().hex
    before=read_data(base,key)
    original=before.get("rad_crawl_progress")
    working={"version":1,"checkpoints":{}}
    if isinstance(original,dict):
        old=original.get("checkpoints")
        if isinstance(old,dict): working["checkpoints"]=copy.deepcopy(old)
        elif original.get("target_id") and original.get("seed_url"):
            store_crawl_checkpoint(working,copy.deepcopy(original))
    baseline=copy.deepcopy(working["checkpoints"])
    synthetic={"target_id":test_id,"seed_url":"https://rad-checkpoint-test.invalid/",
      "queue":["https://rad-checkpoint-test.invalid/contacto"],
      "visited":["https://rad-checkpoint-test.invalid/"],
      "records":[{"field":"email","value":"prueba@example.invalid"}],
      "paginas_visitadas":1,"completed":False}
    store_crawl_checkpoint(working,synthetic)
    try:
        with tempfile.TemporaryDirectory(prefix="rad-checkpoint-test-") as tmp:
            path=pathlib.Path(tmp)/"metadata.json"
            path.write_text(json.dumps({"items":[],"rad_crawl_progress":working}),encoding="utf-8")
            catalog.sync_metadata(path,["rad_crawl_progress"])
        persisted=read_data(base,key).get("rad_crawl_progress")
        cps=persisted.get("checkpoints",{}) if isinstance(persisted,dict) else {}
        found=[v for v in cps.values() if isinstance(v,dict) and v.get("target_id")==test_id]
        if len(found)!=1 or found[0]!=synthetic:
            raise AssertionError("No se recuperó exactamente el checkpoint guardado.")
        print(json.dumps({"prueba":"persistencia_y_lectura","resultado":"OK","cola":len(found[0]["queue"]),"registros_parciales":len(found[0]["records"])}))
        catalog.clear_rad_crawl_progress(test_id)
        after=read_data(base,key).get("rad_crawl_progress")
        remaining=after.get("checkpoints",{}) if isinstance(after,dict) else {}
        if any(isinstance(v,dict) and v.get("target_id")==test_id for v in remaining.values()):
            raise AssertionError("No se eliminó el checkpoint de prueba.")
        if remaining!=baseline:
            raise AssertionError("La limpieza alteró checkpoints preexistentes.")
        print(json.dumps({"prueba":"limpieza_aislada","resultado":"OK","checkpoints_previos_conservados":len(baseline),"fichas_modificadas":0}))
    finally:
        catalog.clear_rad_crawl_progress(test_id)

if __name__=="__main__": main()
