#!/usr/bin/env python3
"""Recupera direcciones OSM y guarda propuestas dentro del catálogo maestro."""
import json,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
CATALOG=Path(__file__).resolve().parent/"fichas_completas.json"
ENDPOINTS=("https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter")
BATCH=25
KEYS=("addr:full","addr:street","addr:housenumber","addr:place","addr:postcode","addr:city","addr:suburb","addr:district","addr:province","addr:state","addr:unit","addr:floor")

def osm_id(value):
    p=str(value or "").split(":")
    return (p[1],p[2]) if len(p)==3 and p[0] in {"osm","osm-extra"} and p[1] in {"node","way","relation"} and p[2].isdigit() else None

def fetch(kind,ids):
    query=f"[out:json][timeout:90];{kind}(id:{','.join(ids)});out tags;"
    body=urllib.parse.urlencode({"data":query}).encode(); last=None
    for endpoint in ENDPOINTS:
        for attempt in range(3):
            try:
                req=urllib.request.Request(endpoint,data=body,headers={"User-Agent":"Xiclana-OSM/2.0"})
                with urllib.request.urlopen(req,timeout=120) as response: payload=json.loads(response.read())
                if payload.get("remark"): raise RuntimeError(payload["remark"])
                return {f'{x["type"]}:{x["id"]}':x.get("tags",{}) for x in payload.get("elements",[])}
            except Exception as exc: last=exc; time.sleep(3*(attempt+1))
    raise RuntimeError(str(last))

def address(tags):
    if tags.get("addr:full"): return tags["addr:full"].strip()
    street=tags.get("addr:street") or tags.get("addr:place"); number=tags.get("addr:housenumber")
    main=f"{street.strip()}, {number.strip()}" if street and number else (street.strip() if street else "")
    extra=[f"{label} {tags[key].strip()}" for key,label in (("addr:unit","local"),("addr:floor","planta"),("addr:postcode","CP"),("addr:city","localidad")) if tags.get(key)]
    return ", ".join(x for x in (main,*extra) if x)

def main():
    if not CATALOG.is_file(): raise SystemExit("No existe catálogo maestro.")
    data=json.loads(CATALOG.read_text(encoding="utf-8")); items=data.get("items")
    if not isinstance(items,list): raise SystemExit("Catálogo inválido.")
    pending=[x for x in items if not x.get("_xiclana_deleted") and not x.get("deleted") and not x.get("eliminado") and not str(x.get("a") or "").strip()]
    groups={"node":[],"way":[],"relation":[]}; not_osm=[]
    for item in pending:
        parsed=osm_id(item.get("id"))
        if parsed: groups[parsed[0]].append((parsed[1],item))
        else: not_osm.append({"id":item.get("id"),"nombre":item.get("n"),"categoria":item.get("c")})
    found={}; errors=[]; total=sum((len(v)+BATCH-1)//BATCH for v in groups.values()); done=0
    for kind,values in groups.items():
        for start in range(0,len(values),BATCH):
            batch=values[start:start+BATCH]; done+=1
            try: found.update(fetch(kind,[oid for oid,_ in batch]))
            except Exception as exc: errors.append({"tipo":kind,"ids":[oid for oid,_ in batch],"error":str(exc)[:300]})
            if done<total: time.sleep(2)
    proposals=[]
    for kind,values in groups.items():
        for oid,item in values:
            tags=found.get(f"{kind}:{oid}")
            if tags is None: continue
            selected={k:tags[k] for k in KEYS if tags.get(k)}
            if selected:
                proposals.append({"id_ficha":item.get("id"),"nombre":item.get("n"),"direccion_propuesta":address(tags) or None,"etiquetas_osm":selected,"url_osm":f"https://www.openstreetmap.org/{kind}/{oid}","estado":"pendiente_revision"})
    data["propuestas_direcciones_osm"]={"fecha_utc":datetime.now(timezone.utc).isoformat(),"fichas_sin_direccion":len(pending),"objetos_osm_consultados":sum(map(len,groups.values())),"objetos_recuperados":len(found),"propuestas":proposals,"fichas_sin_id_osm":not_osm,"errores_lotes":errors,"nota":"Propuestas pendientes; no se modifican direcciones ni se publica ninguna ficha automáticamente."}
    data["actualizado"]=datetime.now().strftime("%Y-%m-%d")
    CATALOG.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(json.dumps({"fichas_sin_direccion":len(pending),"objetos_recuperados":len(found),"propuestas":len(proposals),"errores":len(errors),"destino":CATALOG.name},ensure_ascii=False))
    if not found: raise SystemExit("No se recuperó ningún objeto OSM.")
if __name__=="__main__": main()
