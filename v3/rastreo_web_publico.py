#!/usr/bin/env python3
"""RAD: rastreo multifuente de establecimientos de Chiclana.
Usa resultados públicos de buscadores y páginas públicas; respeta robots.txt,
limita peticiones y nunca publica: añade candidatos a candidatas_revision.
"""
import hashlib, html, json, pathlib, re, time, urllib.parse, urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = ROOT / "fichas_completas.json"
UA = "Xiclana-RAD/1.0 (directorio local; contacto: webmaster del sitio)"
CITY = '"Chiclana de la Frontera"'
QUERIES = [
    f'{CITY} tiendas comercios establecimientos',
    f'{CITY} tiendas muebles decoración colchones',
    f'{CITY} ferreterías bricolaje materiales construcción',
    f'{CITY} moda calzado complementos tiendas',
    f'{CITY} alimentación supermercados carnicerías panaderías',
    f'{CITY} restaurantes bares cafeterías pastelerías',
    f'{CITY} hoteles hostales alojamientos turismo',
    f'{CITY} talleres coches motos concesionarios',
    f'{CITY} clínicas dentistas fisioterapia veterinarios',
    f'{CITY} peluquerías estética gimnasios deporte',
    f'{CITY} inmobiliarias seguros asesorías gestorías abogados',
    f'{CITY} academias colegios formación idiomas',
    f'{CITY} ocio actividades empresas servicios profesionales',
    f'{CITY} empresas polígonos industriales directorio comercial',
    f'{CITY} directorio empresas guía comercial negocios',
    f'{CITY} asociación comerciantes empresas socios',
]
MAX_RESULTS_PER_QUERY = 12
MAX_PAGES = 100
TIMEOUT = 18
CACHE_ROBOTS = {}
LAST_REQUEST = {}

class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.title=False; self.title_parts=[]; self.text=[]
        self.meta={}; self.links=[]; self.jsonld=[]; self._script=False; self._json=False
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "title": self.title=True
        if tag == "meta" and a.get("content"):
            k=(a.get("property") or a.get("name") or "").lower()
            if k: self.meta[k]=a["content"]
        if tag == "a" and a.get("href"): self.links.append(a["href"])
        if tag == "script":
            self._script=True; self._json=(a.get("type","").lower()=="application/ld+json")
            self._script_buf=[]
    def handle_endtag(self, tag):
        if tag=="title": self.title=False
        if tag=="script" and self._script:
            if self._json and self._script_buf: self.jsonld.append("".join(self._script_buf))
            self._script=False; self._json=False
    def handle_data(self, data):
        if self.title: self.title_parts.append(data)
        if self._script: self._script_buf.append(data)
        else: self.text.append(data)

def get(url, limit=1200000):
    host=urllib.parse.urlparse(url).netloc.lower()
    now=time.time()
    wait=1.0-(now-LAST_REQUEST.get(host,0))
    if wait>0: time.sleep(wait)
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,application/rss+xml"})
    with urllib.request.urlopen(req,timeout=TIMEOUT) as r:
        data=r.read(limit+1)
        if len(data)>limit: data=data[:limit]
        charset=r.headers.get_content_charset() or "utf-8"
        LAST_REQUEST[host]=time.time()
        return data.decode(charset,errors="replace"),r.geturl(),r.headers.get_content_type()

def allowed(url):
    p=urllib.parse.urlparse(url); origin=f"{p.scheme}://{p.netloc}"
    if origin not in CACHE_ROBOTS:
        rp=urllib.robotparser.RobotFileParser()
        try: rp.set_url(origin+"/robots.txt"); rp.read()
        except Exception: rp=None
        CACHE_ROBOTS[origin]=rp
    rp=CACHE_ROBOTS[origin]
    return True if rp is None else rp.can_fetch(UA,url)

def search_ddg(query):
    url="https://html.duckduckgo.com/html/?"+urllib.parse.urlencode({"q":query})
    body,_,_=get(url,700000)
    p=Page(); p.feed(body)
    found=[]
    # DDG result links are encoded redirect URLs; parse hrefs from result__a anchors.
    for m in re.finditer(r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)',body,re.I):
        href=html.unescape(m.group(1))
        if href.startswith("//"): href="https:"+href
        u=urllib.parse.urlparse(href)
        if "duckduckgo.com" in u.netloc:
            target=urllib.parse.parse_qs(u.query).get("uddg",[""])[0]
            if target: href=target
        if href.startswith("http") and not any(x in urllib.parse.urlparse(href).netloc for x in ("duckduckgo.com",)):
            found.append(href)
        if len(found)>=MAX_RESULTS_PER_QUERY: break
    return list(dict.fromkeys(found))

def search_bing(query):
    url="https://www.bing.com/search?format=rss&"+urllib.parse.urlencode({"q":query})
    body,_,_=get(url,700000)
    return list(dict.fromkeys(html.unescape(x) for x in re.findall(r"<link>(https?://.*?)</link>",body,re.I)
                               if "bing.com" not in urllib.parse.urlparse(x).netloc))[:MAX_RESULTS_PER_QUERY]

def flatten_jsonld(value):
    out=[]
    if isinstance(value,dict):
        typ=value.get("@type","")
        types=typ if isinstance(typ,list) else [typ]
        if any(t in {"LocalBusiness","Organization","Store","ProfessionalService","Restaurant","FoodEstablishment","AutomotiveBusiness","HealthAndBeautyBusiness","HomeAndConstructionBusiness","LodgingBusiness","TouristInformationCenter"} for t in types):
            out.append(value)
        for v in value.values(): out.extend(flatten_jsonld(v))
    elif isinstance(value,list):
        for v in value: out.extend(flatten_jsonld(v))
    return out

def textval(v):
    if isinstance(v,str): return v.strip()
    if isinstance(v,dict): return textval(v.get("name") or v.get("streetAddress") or "")
    return ""

def classify(text):
    s=text.lower()
    groups=[
      (("mueble","muebles","decoración","colchón"),"Muebles y decoración"),
      (("restaurante","bar ","cafetería","comida","pizzería"),"Restauración"),
      (("hotel","hostal","apartamento turístico","alojamiento"),"Alojamiento"),
      (("taller","automóvil","automocion","concesionario"),"Automoción"),
      (("dentista","clínica","fisioterapia","veterinaria","farmacia"),"Salud"),
      (("peluquería","estética","gimnasio"),"Belleza y deporte"),
      (("inmobiliaria","alquiler","venta de viviendas"),"Inmobiliaria"),
      (("abogado","asesoría","gestoría","seguros"),"Servicios profesionales"),
      (("academia","colegio","formación","idiomas"),"Educación"),
      (("tienda","comercio","comprar","venta"),"Comercio"),
    ]
    for words,cat in groups:
        if any(w in s for w in words): return cat
    return "Servicios y negocios"

def extract(url):
    if not allowed(url): return None
    try: body,final_url,ctype=get(url)
    except Exception: return None
    if "html" not in ctype and "<html" not in body[:1000].lower(): return None
    p=Page()
    try: p.feed(body)
    except Exception: pass
    title=" ".join(" ".join(p.title_parts).split())
    desc=p.meta.get("description") or p.meta.get("og:description") or ""
    candidates=[]
    for raw in p.jsonld:
        try: candidates.extend(flatten_jsonld(json.loads(raw)))
        except Exception: pass
    obj=candidates[0] if candidates else {}
    name=textval(obj.get("name")) or title
    if not name: return None
    address=obj.get("address") or {}
    if isinstance(address,str): addr=address
    else:
        addr=", ".join(x for x in [textval(address.get("streetAddress")),textval(address.get("postalCode")),textval(address.get("addressLocality"))] if x)
    phone=textval(obj.get("telephone"))
    email=textval(obj.get("email"))
    website=textval(obj.get("url")) or final_url
    hours=obj.get("openingHours") or obj.get("openingHoursSpecification") or ""
    if isinstance(hours,list): hours="; ".join(textval(x) for x in hours)
    blob=" ".join(p.text)
    if not phone:
        m=re.search(r"(?<!\d)(?:\+34[ .-]?)?(?:[6789]\d{2})[ .-]?\d{2,3}[ .-]?\d{2,3}(?!\d)",blob)
        if m: phone=m.group(0)
    if not email:
        m=re.search(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",blob)
        if m: email=m.group(0)
    if "chiclana" not in (addr+" "+desc+" "+blob[:5000]).lower() and not any(x in final_url.lower() for x in (".chiclana","chiclana")):
        return None
    if len(name)>140: return None
    return {"name":name,"address":addr,"phone":phone,"email":email,"website":website,
            "hours":str(hours)[:500],"description":desc[:700],"source_url":final_url,
            "category":classify(name+" "+desc+" "+blob[:1500])}

def main():
    if not MASTER.is_file(): raise SystemExit("No existe el catálogo maestro.")
    data=json.loads(MASTER.read_text(encoding="utf-8"))
    if not isinstance(data.get("items"),list) or not isinstance(data.get("candidatas_revision",[]),list):
        raise SystemExit("Estructura del catálogo no válida; se cancela sin modificar.")
    existing=data["items"]+data.get("candidatas_revision",[])
    names={re.sub(r"[^a-z0-9]","",str(x.get("n","")).lower()) for x in existing if isinstance(x,dict)}
    urls={str(x.get("url_fuente_rastreo","")).rstrip("/").lower() for x in existing if isinstance(x,dict)}
    links=[]
    for q in QUERIES:
        for engine in (search_ddg,search_bing):
            try: links.extend(engine(q))
            except Exception as exc: print(f"Buscador no disponible ({engine.__name__}): {exc}",flush=True)
    links=list(dict.fromkeys(links))[:MAX_PAGES]
    added=[]; seen=set()
    for url in links:
        record=extract(url)
        if not record: continue
        key=re.sub(r"[^a-z0-9]","",record["name"].lower())
        u=record["source_url"].rstrip("/").lower()
        if not key or key in names or key in seen or u in urls: continue
        seen.add(key)
        digest=hashlib.sha256((key+"|"+u).encode()).hexdigest()[:16]
        added.append({
          "id":"rad:"+digest,"n":record["name"],"t":"negocio","c":record["category"],
          "a":record["address"],"p":record["phone"],"e":record["email"],
          "w":record["website"],"h":record["hours"],"d":record["description"],
          "f":"Rastreo web público (RAD)","url_fuente_rastreo":u,
          "fuentes_datos":[{"url":u,"campos":["nombre","direccion","telefono","correo","web","horario","descripcion"]}],
          "estado_revision":"pendiente","fuente_estado":"Candidato detectado en fuente web pública; pendiente de validación manual",
          "fecha_deteccion_utc":datetime.now(timezone.utc).isoformat()
        })
    data.setdefault("candidatas_revision",[]).extend(added)
    data["total_candidatas_revision"]=len(data["candidatas_revision"])
    data["rad_ultima_ejecucion"]={"fecha_utc":datetime.now(timezone.utc).isoformat(),
       "buscadores":["DuckDuckGo HTML","Bing RSS"],"consultas":len(QUERIES),
       "urls_encontradas":len(links),"candidatas_nuevas":len(added),
       "publicacion_automatica":False}
    MASTER.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(data["rad_ultima_ejecucion"],ensure_ascii=False),flush=True)

if __name__=="__main__": main()
