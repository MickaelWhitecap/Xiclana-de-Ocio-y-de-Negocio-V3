#!/usr/bin/env python3
"""Importa la extracción municipal OSM directamente en el único catálogo maestro."""
import hashlib, json, pathlib, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

ROOT=pathlib.Path(__file__).resolve().parent
MASTER=ROOT/"fichas_completas.json"
AREA_ID=3600346951
SERVERS=("https://overpass-api.de/api/interpreter","https://overpass.kumi.systems/api/interpreter")
KINDS=("node","way","relation")

def fetch(kind):
    query=f"[out:json][timeout:300];{kind}(area:{AREA_ID});out tags;"
    body=urllib.parse.urlencode({"data":query}).encode()
    errors=[]
    for attempt in range(3):
        for server in SERVERS:
            try:
                req=urllib.request.Request(server,data=body,headers={"User-Agent":"Xiclana-OSM/2.0","Accept":"application/json"})
                with urllib.request.urlopen(req,timeout=360) as response: payload=json.load(response)
                if payload.get("remark"): raise RuntimeError(payload["remark"])
                values=payload.get("elements")
                if not isinstance(values,list): raise RuntimeError("Respuesta sin elements")
                if any(x.get("type")!=kind or not isinstance(x.get("tags",{}),dict) for x in values):
                    raise RuntimeError("Respuesta con objetos o etiquetas no válidos")
                return values,server
            except Exception as exc: errors.append(f"{server}: {exc}")
        if attempt<2: time.sleep(20*(attempt+1))
    raise RuntimeError("Falló la consulta "+kind+": "+" | ".join(errors))

def main():
    if not MASTER.is_file(): sys.exit("No existe el catálogo maestro; cancelado.")
    data=json.loads(MASTER.read_text(encoding="utf-8"))
    if not isinstance(data.get("items"),list): sys.exit("Catálogo maestro inválido; cancelado.")
    objects={}; servers={}
    for kind in KINDS:
        values,server=fetch(kind); servers[kind]=server
        for obj in values:
            key=f'{kind}:{obj["id"]}'
            if key in objects: raise RuntimeError("ID duplicado: "+key)
            objects[key]={"type":kind,"id":obj["id"],"tags":obj.get("tags",{})}
        print(f"{kind}: {len(values)} objetos",flush=True)
    ids=set(objects)
    known=set()
    for item in data["items"]:
        m=re.search(r"(?:osm|osm-extra):(node|way|relation):(\d+)$",str(item.get("id","")))
        if m: known.add(f"{m.group(1)}:{m.group(2)}")
    unmatched=[]
    for key,obj in objects.items():
        tags=obj["tags"]; name=tags.get("name") or tags.get("name:es") or tags.get("official_name")
        if name and key not in known:
            unmatched.append({"osm_id":key,"nombre":name,"etiquetas":tags})
    unmatched.sort(key=lambda x:x["nombre"].casefold())
    counts={k:sum(1 for x in objects.values() if x["type"]==k) for k in KINDS}
    snapshot=[objects[k] for k in sorted(objects)]
    raw=json.dumps(snapshot,ensure_ascii=False,separators=(",",":")).encode()
    data["osm_extraccion_inicial"]={"fecha_utc":datetime.now(timezone.utc).isoformat(),"relacion_municipal":346951,"area_overpass":AREA_ID,"servidores":servers,"objetos_por_tipo":counts,"total_objetos":len(snapshot),"sha256_datos":hashlib.sha256(raw).hexdigest(),"objetos":snapshot}
    data["auditoria_osm"]={"estado":"extraccion_completada","fecha_utc":data["osm_extraccion_inicial"]["fecha_utc"],"total_catalogo":len(data["items"]),"ids_osm_en_catalogo":len(known),"coincidencias_por_id":len(ids&known),"objetos_osm_no_en_catalogo":len(ids-known),"objetos_catalogo_no_devuelto_por_osm":len(known-ids),"objetos_nuevos_con_nombre":len(unmatched),"candidatas_sin_ficha":unmatched,"sin_publicacion_automatica":True}
    data["actualizado"]=time.strftime("%Y-%m-%d")
    MASTER.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print(json.dumps({"objetos":counts,"total":len(snapshot),"coincidencias_id":len(ids&known),"nuevos_con_nombre":len(unmatched),"fichero_unico":MASTER.name},ensure_ascii=False))

if __name__=="__main__": main()
