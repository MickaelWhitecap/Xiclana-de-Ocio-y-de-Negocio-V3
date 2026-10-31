#!/usr/bin/env python3
"""Recupera etiquetas postales existentes en OSM; solo genera propuestas, nunca edita fichas."""
import json, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

CATALOG=Path("v3/fichas_completas.json")
OUTPUT=Path("v3/propuestas_direcciones_osm.json")
ENDPOINT="https://overpass-api.de/api/interpreter"
BATCH_SIZE=80
PAUSE_SECONDS=2.5
ADDRESS_KEYS=("addr:full","addr:street","addr:housenumber","addr:place","addr:postcode","addr:city","addr:suburb","addr:district","addr:province","addr:state","addr:unit","addr:floor")

def object_parts(value):
    p=str(value or "").split(":")
    return (p[1],p[2]) if len(p)==3 and p[0] in {"osm","osm-extra"} and p[1] in {"node","way","relation"} and p[2].isdigit() else None

def fetch_batch(kind, ids):
    query = f"[out:json][timeout:90];{kind}(id:{','.join(ids)});out tags;"
    data = urllib.parse.urlencode({"data": query}).encode()
    last_error = None
    for endpoint in ENDPOINTS:
        for attempt in range(3):
            request = urllib.request.Request(
                endpoint, data=data, headers={
                    "User-Agent": "XiclanaDirectoryAddressAudit/1.0 (public-data quality audit)",
                    "Content-Type": "application/x-www-form-urlencoded",
                }
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                return {f"{kind}:{obj['id']}": obj.get("tags", {}) for obj in payload.get("elements", [])}
            except Exception as exc:
                last_error = exc
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(str(last_error)[:400])

def format_address(tags):
    if tags.get("addr:full"): return tags["addr:full"].strip()
    street=tags.get("addr:street") or tags.get("addr:place")
    number=tags.get("addr:housenumber")
    result=f"{street.strip()}, {number.strip()}" if street and number else (street.strip() if street else "")
    extra=[f"{label} {tags[key].strip()}" for key,label in (("addr:unit","local"),("addr:floor","planta"),("addr:postcode","CP"),("addr:city","localidad")) if tags.get(key)]
    return ", ".join(part for part in (result,*extra) if part)

def main():
    items=json.loads(CATALOG.read_text(encoding="utf-8")).get("items",[])
    pending=[x for x in items if not x.get("_xiclana_deleted") and not x.get("deleted") and not x.get("eliminado") and not str(x.get("a") or "").strip()]
    grouped={"node":[],"way":[],"relation":[]}; ignored=[]
    for item in pending:
        parsed=object_parts(item.get("id"))
        (grouped[parsed[0]].append((parsed[1],item)) if parsed else ignored.append(item))
    fetched={}; errors=[]
    batches=sum((len(v)+BATCH_SIZE-1)//BATCH_SIZE for v in grouped.values()); done=0
    for kind,values in grouped.items():
        for start in range(0,len(values),BATCH_SIZE):
            batch=values[start:start+BATCH_SIZE]; done+=1
            try: fetched.update(fetch_batch(kind,[oid for oid,_ in batch]))
            except Exception as exc: errors.append({"tipo":kind,"primer_id":batch[0][0],"cantidad":len(batch),"error":str(exc)[:400]})
            if done<batches: time.sleep(PAUSE_SECONDS)
    proposals=[]; found=tagged=0
    for kind,values in grouped.items():
        for oid,item in values:
            tags=fetched.get(f"{kind}:{oid}")
            if tags is None: continue
            found+=1
            selected={k:tags[k] for k in ADDRESS_KEYS if tags.get(k)}
            if not selected: continue
            tagged+=1; address=format_address(tags)
            proposals.append({"id":item.get("id"),"nombre":item.get("n"),"categoria":item.get("c"),"tipo":item.get("t"),"direccion_propuesta":address or None,"etiquetas_direccion_osm":selected,"url_objeto_osm":f"https://www.openstreetmap.org/{kind}/{oid}","estado":"propuesta_pendiente_revision" if address else "etiquetas_parciales_sin_direccion_completa"})
    report={"fecha_consulta_utc":datetime.now(timezone.utc).isoformat(),"fuente":"OpenStreetMap / Overpass API","metodo":"Consulta de etiquetas de objetos OSM ya identificados; sin geocodificación inversa.","total_fichas_sin_direccion":len(pending),"objetos_osm_identificados":sum(map(len,grouped.values())),"objetos_osm_recuperados":found,"objetos_con_etiquetas_postales":tagged,"propuestas_con_direccion_formateable":sum(bool(p["direccion_propuesta"]) for p in proposals),"propuestas":proposals,"fichas_sin_id_osm_consultable":[{"id":x.get("id"),"nombre":x.get("n"),"categoria":x.get("c")} for x in ignored],"errores_lotes":errors,"nota":"Propuestas únicamente. No modifica fichas_completas.json ni publica direcciones; requiere validación antes de incorporar."}
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("total_fichas_sin_direccion","objetos_osm_identificados","objetos_osm_recuperados","objetos_con_etiquetas_postales","propuestas_con_direccion_formateable","errores_lotes")},ensure_ascii=False))
    if not fetched: raise SystemExit("No se recuperó ningún objeto OSM.")
if __name__=="__main__": main()
