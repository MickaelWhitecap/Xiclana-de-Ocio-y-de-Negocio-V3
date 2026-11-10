#!/usr/bin/env python3
"""RAD: rastreo multifuente de establecimientos de Chiclana.
Usa resultados públicos de buscadores y páginas públicas; respeta robots.txt,
limita peticiones y nunca publica: añade candidatos a candidatas_revision.
"""
import argparse, hashlib, html, json, pathlib, re, time, urllib.error, urllib.parse, urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = ROOT / "fichas_completas.json"
UA = "Xiclana-RAD/1.0 (+https://mickaelwhitecap.github.io/Xiclana-de-Ocio-y-de-Negocio-V3/)"
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
MAX_PAGES = 260
TIMEOUT = 18
DIRECTORY_SEEDS = [
    "https://aechiclana.org/directorio/",
    "https://www.chiclanaguiadempresas.com/empresas/",
    "https://www.cadizturismo.com/es/listado-de-empresas/alojamientos/chiclana-de-la-frontera/todas-las-empresas",
    "https://turismo.chiclana.es/planifica-tu-viaje/alojamientos/",
    "https://turismo.chiclana.es/sol-y-playa/ocio-y-diversion/",
]
TRUSTED_DIRECTORY_PATHS = {
    "aechiclana.org": ("/directorio/trabajo/",),
    "www.chiclanaguiadempresas.com": ("/empresas/empresa/",),
    "www.cadizturismo.com": ("/es/empresa/",),
    "turismo.chiclana.es": (
        "/planifica-tu-viaje/alojamientos/alojamiento/",
        "/detalle-de-recurso/",
    ),
}
CACHE_ROBOTS = {}
LAST_REQUEST = {}
LOCAL_POSTCODES = {'11130', '11138', '11139'}

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title=False; self.title_parts=[]; self.text=[]
        self.meta={}; self.links=[]; self.jsonld=[]; self.headings=[]
        self._heading_tag=None; self._heading_buf=[]
        self._paragraph=False; self._paragraph_buf=[]; self.paragraphs=[]
        self._script=False; self._json=False; self._script_buf=[]
        self._anchor=None; self._anchor_text=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "title": self.title=True
        if tag in ("h1","h2","h3","h4","h5"):
            self._heading_tag=tag; self._heading_buf=[]
        if tag == "p":
            self._paragraph=True; self._paragraph_buf=[]
        if tag == "meta" and a.get("content"):
            k=(a.get("property") or a.get("name") or "").lower()
            if k: self.meta[k]=a["content"]
        if tag == "a" and a.get("href"):
            self._anchor=(a.get("class",""),a["href"]); self._anchor_text=[]
        if tag == "script":
            self._script=True; self._json=(a.get("type","").lower()=="application/ld+json")
            self._script_buf=[]
    def handle_endtag(self, tag):
        if tag=="title": self.title=False
        if tag in ("h1","h2","h3","h4","h5") and self._heading_tag==tag:
            heading=" ".join(" ".join(self._heading_buf).split())
            if heading: self.headings.append(heading)
            self._heading_tag=None; self._heading_buf=[]
        if tag == "p" and self._paragraph:
            paragraph=" ".join(" ".join(self._paragraph_buf).split())
            if paragraph: self.paragraphs.append(paragraph)
            self._paragraph=False; self._paragraph_buf=[]
        if tag=="a" and self._anchor:
            self.links.append((self._anchor[0],self._anchor[1]," ".join(self._anchor_text).strip()))
            self._anchor=None; self._anchor_text=[]
        if tag=="script" and self._script:
            if self._json and self._script_buf: self.jsonld.append("".join(self._script_buf))
            self._script=False; self._json=False; self._script_buf=[]
    def handle_data(self, data):
        if self.title: self.title_parts.append(data)
        if self._heading_tag: self._heading_buf.append(data)
        if self._paragraph: self._paragraph_buf.append(data)
        if self._anchor is not None: self._anchor_text.append(data)
        if self._script: self._script_buf.append(data)
        else: self.text.append(data)

class SearchLinks(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.href=None; self.links=[]
    def handle_starttag(self, tag, attrs):
        if tag != "a": return
        a=dict(attrs)
        if "result__a" in a.get("class","").split() and a.get("href"):
            self.active=True; self.href=a["href"]
    def handle_endtag(self, tag):
        if tag=="a" and self.active:
            self.links.append(self.href); self.active=False; self.href=None

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
    """Consulta robots.txt con timeout; ante un fallo de red, no rastrea ese host."""
    p=urllib.parse.urlparse(url)
    if p.scheme not in ("http","https") or not p.netloc: return False
    origin=f"{p.scheme}://{p.netloc}"
    if origin not in CACHE_ROBOTS:
        rp=urllib.robotparser.RobotFileParser()
        robots_url=origin+"/robots.txt"
        try:
            req=urllib.request.Request(robots_url,headers={"User-Agent":UA})
            with urllib.request.urlopen(req,timeout=8) as response:
                raw=response.read(256000).decode("utf-8",errors="replace")
            LAST_REQUEST[p.netloc.lower()]=time.time()
            rp.set_url(robots_url); rp.parse(raw.splitlines())
            CACHE_ROBOTS[origin]=(rp,True)
        except urllib.error.HTTPError as exc:
            if exc.code in (404,410):
                LAST_REQUEST[p.netloc.lower()]=time.time()
                rp.set_url(robots_url); rp.parse([])
                CACHE_ROBOTS[origin]=(rp,True)
            else: CACHE_ROBOTS[origin]=(None,False)
        except Exception: CACHE_ROBOTS[origin]=(None,False)
    rp,valid=CACHE_ROBOTS[origin]
    return bool(valid and rp and rp.can_fetch(UA,url))

def search_ddg(query):
    url="https://html.duckduckgo.com/html/?"+urllib.parse.urlencode({"q":query})
    if not allowed(url): return []
    body,_,_=get(url,700000)
    parser=SearchLinks()
    try: parser.feed(body)
    except Exception: return []
    found=[]
    for raw in parser.links:
        href=urllib.parse.urljoin(url,html.unescape(raw))
        u=urllib.parse.urlparse(href)
        if "duckduckgo.com" in u.netloc:
            target=urllib.parse.parse_qs(u.query).get("uddg",[""])[0]
            if target: href=urllib.parse.unquote(target)
        parsed=urllib.parse.urlparse(href)
        if parsed.scheme in ("http","https") and "duckduckgo.com" not in parsed.netloc:
            found.append(href)
        if len(found)>=MAX_RESULTS_PER_QUERY: break
    return list(dict.fromkeys(found))

def search_bing(query):
    url="https://www.bing.com/search?format=rss&"+urllib.parse.urlencode({"q":query})
    if not allowed(url): return []
    body,_,_=get(url,700000)
    try:
        import xml.etree.ElementTree as ET
        root=ET.fromstring(body)
        found=[]
        for item in root.findall(".//item"):
            link=item.findtext("link") or ""
            parsed=urllib.parse.urlparse(link)
            if parsed.scheme in ("http","https") and "bing.com" not in parsed.netloc:
                found.append(link)
        return list(dict.fromkeys(found))[:MAX_RESULTS_PER_QUERY]
    except Exception: return []

def flatten_jsonld(value):
    out=[]
    if isinstance(value,dict):
        typ=value.get("@type","")
        types=typ if isinstance(typ,list) else [typ]
        known={
            "LocalBusiness","Organization","Store","ProfessionalService","Restaurant","FoodEstablishment",
            "AutomotiveBusiness","HealthAndBeautyBusiness","HomeAndConstructionBusiness","LodgingBusiness",
            "Hotel","BedAndBreakfast","Campground","TouristInformationCenter","TouristAttraction",
            "SportsActivityLocation","SportsClub","BowlingAlley","MovieTheater","Museum",
            "PerformingArtsTheater","ShoppingCenter","HealthClub","CivicStructure"
        }
        if any(str(t).rsplit("/",1)[-1].rsplit("#",1)[-1] in known for t in types):
            out.append(value)
        for v in value.values(): out.extend(flatten_jsonld(v))
    elif isinstance(value,list):
        for v in value: out.extend(flatten_jsonld(v))
    return out

def textval(v):
    if isinstance(v,str): return v.strip()
    if isinstance(v,dict): return textval(v.get("name") or v.get("streetAddress") or "")
    return ""


def normalize_phone(value):
    """Devuelve solo un teléfono español completo de nueve cifras."""
    digits=re.sub(r"\D","",str(value or "").strip())
    if digits.startswith("34") and len(digits)==11: digits=digits[2:]
    if len(digits)==9 and digits[0] in "6789": return digits
    return ""


def extract_phones(value):
    """Extrae varios teléfonos españoles, incluso cuando el HTML los concatena."""
    raw=str(value or "")
    found=[]
    joined_spans=[]
    # Captura secuencias de 18 dígitos aunque cada teléfono lleve espacios.
    for match in re.finditer(r"(?<!\d)([6789](?:[ .-]?\d){17,35})(?!\d)",raw):
        digits=re.sub(r"\D","",match.group(1))
        if len(digits)>=18 and len(digits)%9==0 and all(digits[i] in "6789" for i in range(0,len(digits),9)):
            found.extend(digits[i:i+9] for i in range(0,len(digits),9))
            joined_spans.append(match.span(1))
    for match in re.finditer(r"(?<!\d)(?:\+34[ .-]?)?([6789](?:[ .-]?\d){8})(?!\d)",raw):
        if any(start <= match.start(1) and match.end(1) <= end for start,end in joined_spans):
            continue
        phone=normalize_phone(match.group(1))
        if phone: found.append(phone)
    for part in re.split(r"[/;,|]",raw):
        phone=normalize_phone(part)
        if phone: found.append(phone)
    return list(dict.fromkeys(x for x in found if len(x)==9 and x[0] in "6789"))


def extract_contact_phones(page):
    """Recupera teléfonos visibles en el bloque de contacto, sin tomar el teléfono del directorio."""
    raw=" ".join(str(x) for x in page.text)
    start_match=re.search(r"(?i)informaci[oó]n\s+(?:sobre\s+la\s+empresa|de\s+contacto)",raw)
    if not start_match:
        return []
    start=start_match.end()
    tail=raw[start:start+1800]
    endings=[
        re.search(r"(?i)encuentra\s+empresas\s+cercanas",tail),
        re.search(r"(?i)s[ií]guenos\s+en\s+(?:instagram|facebook)",tail),
    ]
    valid=[m.start() for m in endings if m]
    if valid:
        tail=tail[:min(valid)]
    # La Guía de Chiclana repite su teléfono general en el pie de cada ficha.
    # Ese bloque aparece tras una segunda etiqueta de ubicación y antes del
    # correo corporativo; se excluye para no atribuirlo al establecimiento.
    directory_email=re.search(r"(?i)\binfo@chiclanaguiadempresas\.com\b",tail)
    if directory_email:
        before_email=tail[:directory_email.start()]
        footer_locations=list(re.finditer(
            r"(?i)chiclana de la frontera,\s*c[aá]diz,\s*espa[nñ]a",before_email
        ))
        if footer_locations:
            # La dirección comercial puede no incluir la provincia («... España»),
            # mientras que el bloque común del directorio sí muestra «Chiclana de
            # la Frontera, Cádiz, España». Basta esa marca de pie para cortar.
            tail=before_email[:footer_locations[-1].start()]
        else:
            tail=before_email
    return extract_phones(tail)


def clean_business_name(value):
    """Elimina colas SEO evidentes sin recortar nombres comerciales normales."""
    name=" ".join(str(value or "").replace(" "," ").split()).strip(" |·-–—")
    # «Sofás y Colchones» forma parte del nombre comercial de Interiores;
    # se protege frente a la limpieza de términos SEO repetidos al final.
    name=re.sub(r"(?i)sof[aá]s\s+y\s+colchones", "ZZZSOFASYCOLCHONESZZZ", name)
    patterns=[
        r"(?i)[ ]+(?:[-–—|·][ ]*)?(?:AE[ ]+Chiclana|Asociaci[oó]n[ ]+de[ ]+Empresas[ ]+de?[ ]+Chiclana)(?:[ ]+de[ ]+la[ ]+Frontera)?[ ]*$",
        r"[ ]+cervecer[ií]a[ ]+bares?([ ]|$).*$",
        r"[ ]+bares?[ ]+(?:de[ ]+)?(?:chiclana|tapas|comer|paella)([ ]|$).*$",
        r"[ ]+(?:tapas[ ]+comer|comer[ ]+paella|paella[ ]+y[ ]+tapas)([ ]|$).*$",
        r"[ ]*[|·–—][ ]*(?:bares?|restaurantes?|cafeter[ií]as?|empresas?|directorio)([ ]|$).*$",
        r"(?i)[\s,]+(?:odontopediatr[ií]a|ortodoncia|dentistas?|relojer[ií]as?|joyer[ií]as?|"
        r"golosinas|chocolates?|frutos secos|caramelos?)(?:[\s,]+(?:odontopediatr[ií]a|ortodoncia|"
        r"dentistas?|relojer[ií]as?|joyer[ií]as?|golosinas|chocolates?|caramelos?))*$",
        r"(?i)\s+(?:maquinaria de jardiner[ií]a|ferreter[ií]a|suministros?|pellets?)(?:[, ]+"
        r"(?:maquinaria de jardiner[ií]a|ferreter[ií]a|suministros?|pellets?))*$",
        # Cola SEO habitual en fichas de asesorías; se exige la secuencia completa
        # para no borrar palabras que puedan formar parte del nombre comercial.
        r"(?i)[\s,]+asesor[ií]a[\s,]+gestor[ií]a[\s,]+empresas[\s,]+consultor[ií]a(?:[\s,]+integral)?$",
        # En algunos directorios el nombre comercial se concatena con una lista SEO de productos.
        r"(?i)[\s,]+(?:mobiliario|sof[aá]s?|colchones|muebles|butacas|decoraci[oó]n)(?:[\s,]+"
        r"(?:mobiliario|sof[aá]s?|colchones|muebles|butacas|decoraci[oó]n))*$",
        r"(?i)\s+(?:punto de venta\s+.+?\s+concesionario)$",
        r"(?i)\s+(?:mec[aá]nico|mec[aá]nica|autom[oó]vil)(?:\s+(?:mec[aá]nico|mec[aá]nica|autom[oó]vil))*$",
        r"(?i)\s+(?:carpinter[ií]as?|pesca|accesorios|n[aá]uticos|casas|prefabricadas|"
        r"m[oó]dulos|[oó]pticas?|[oó]pticos?|aud[ií]fonos)(?:\s+(?:carpinter[ií]as?|pesca|accesorios|"
        r"n[aá]uticos|casas|prefabricadas|m[oó]dulos|[oó]pticas?|[oó]pticos?|aud[ií]fonos))*$",
    ]
    for pattern in patterns:
        name=re.sub(pattern,"",name,flags=re.I).strip(" |·-–—")
    # «Construcción» es un descriptor insertado en el nombre de esta ficha concreta.
    # Conserva «Reformas» y la marca COYREMAR, eliminando solo el término intermedio.
    name=re.sub(r"(?i)\b(reformas)\s+construcci[oó]n\s+(coyremar)\b",r"\1 \2",name)
    # «Trabajo vertical» aparece como descriptor SEO insertado dentro del nombre.
    name=re.sub(r"(?i)\btrabajo\s+vertical\b"," ",name)
    name=re.sub(r"(?i)^taller\s+(?=talleres\b)", "", name)
    name=" ".join(name.split()).strip(" |·-–—")
    name=name.replace("ZZZSOFASYCOLCHONESZZZ","Sofás y Colchones")
    # Correcciones verificadas de nombres contaminados en directorios locales.
    verified_names={
        "jeronimo vallejo montero ituci asesores":"Ituci Asesores",
        "publicidad chiclana s l publireca":"Publireca",
        "viajes puente travel 17 s c viajes carrefour":"Viajes Carrefour",
        "concesionarios citroen seat":"Autos Colchón",
        "bicicletas centauro bikes chiclana":"Centauro Bikes",
        "carniceria el colinero charcuteria":"Carnicería El Colinero",
        "ec e abogados lola edo manzorro":"EC&E Abogados",
        "gimnasio grimaldi musculacion centros deportivos":"Gimnasio Grimaldi",
        "laboratorio seguridad alimentaria analisis biocentrol laboratorios":"BioCentrol Laboratorios",
        "lola robledo modas y complementos":"Lola Robledo Moda",
        "maquinaria de jardineria taller jose antonio garcia":"José A. García Guerrero",
        "nattex":"NATTEX",
        "atripiko restaurante cocina fusion latina restaurantes":"Atrípiko-Gastro Bar",
        "almacen de maderas molduras serrano carpinteria carpinteros":"Molduras Serrano",
        "tatuaje tattoo nono tattoo studio":"Ñoño Tattoo Studio",
        "viajes mms chiclana agencia":"Viajes MMS Chiclana",
        "dualopticos opticas opticos lentillas":"Dualópticos",
        "peluqueria barber shop sanchez peluquero":"Barber Shop Sánchez",
        "telefonia mundophone fibra telefonia movil telefonos":"MundoPhone",
        "bar cerveceria d los oliva bares":"Bar Cervecería D´Los Oliva",
        "centros deportivos amigos del aerobic pilates body combat":"Amigos del Aerobic",
        "peluqueria gernis salon de belleza cosmetica peluquerias":"Peluquería Gernis",
        "servicio tecnico paco mateo reparacion television sonido":"Servicio Técnico Paco Mateo",
        "viveros garola agricentro ferreteria peluqueria canina veterinario":"Viveros Garola",
        "rocio panes rodriguez agente en seguros allianz":"Rocío Panés Rodríguez",
    }
    name=verified_names.get(norm(name),name)
    if norm(name)=="opticos general":
        name="General Óptica"
    # Los buscadores suelen concatenar categorías y localidad al nombre real.
    # Recorta únicamente colas inequívocas, nunca palabras interiores del nombre.
    name=re.sub(
        r"(?i)(?:\s+(?:restaurantes?|bares?|cafeter[ií]as?|marisquer[ií]as|tiendas?|empresas?|"
        r"directorios?|gu[ií]as?|hoteles?|alojamientos?|servicios|negocios|"
        r"chiclana(?:\s+de\s+la\s+frontera)?)){2,}.*$",
        "", name
    ).strip(" |·-–—")
    return name


def valid_business_name(value):
    name=" ".join(str(value or "").split())
    words=re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9&'’-]+",name)
    if len(name)<3 or len(name)>80 or len(words)>8:
        return False
    n=norm(name)
    if n in {"chiclana","chiclana de la frontera","empresas de chiclana","directorio de empresas"}:
        return False
    # Evita titulares genéricos y nombres que siguen siendo una lista SEO.
    seo={"directorio","empresas","restaurantes","bares","tiendas","negocios","chiclana"}
    if sum(1 for w in n.split() if w in seo)>=2:
        return False
    generic_names={
        "la guia de chiclana","guia de chiclana","guia de empresas de chiclana",
        "directorio de empresas","directorio de empresas de chiclana",
        "asociacion de empresas de chiclana","turismo chiclana",
        "ayuntamiento de chiclana","empresas de chiclana",
    }
    if n in generic_names or n.startswith(("directorio de ","guia de empresas","portal de empresas")):
        return False
    return True


def clean_address(value, locality="", postal=""):
    """Normaliza direcciones y descarta localidades/códigos postales sin vía concreta."""
    raw=html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    raw=re.sub(r"(?i)^\s*(?:direcci[oó]n|address)\s*[:\-]?\s*", "", raw)
    # Descarta coordenadas GPS y altitud añadidas al final de una dirección.
    raw=re.sub(r"(?i),?\s*\d{1,2}[º°]\s*\d{1,2}['′]\s*\d{1,2}(?:[\.,]\d+)?(?:['′]{1,2}|[\"″])?\s*[NSEW]?(?:\s+\d{1,2}[º°]\s*\d{1,2}['′]\s*\d{1,2}(?:[\.,]\d+)?(?:['′]{1,2}|[\"″])?\s*[NSEW]?)?\s*\)?(?:\s+\d{1,4}\s*m)?\s*$", "", raw, flags=re.I)
    raw=re.split(r"(?i)\s+(?:tel[eé]fono|tel\.?|p[aá]gina web|c[oó]mo llegar|correo|email|horario)\s*[:\-]?", raw, maxsplit=1)[0]
    raw=re.sub(r"[\t\r\n]+", " ", raw)
    raw=re.sub(r"\s*,\s*", ", ", raw)
    raw=" ".join(raw.split()).strip(" ,;|·-–—")
    raw=re.sub(r"(?i)\bchiclana\s+de\s+la\s+fra\.?(?=\W|$)", "Chiclana de la Frontera", raw)
    raw=re.sub(r"(?i)\bchiclana\s+fra\.?(?=\W|$)", "Chiclana de la Frontera", raw)
    locality=" ".join(str(locality or "").split()).strip(" ,")
    postal=str(postal or "").strip()
    if postal not in LOCAL_POSTCODES:
        postal=""
    raw=re.sub(
        r"(?<!\d)\d{5}(?!\d)",
        lambda match: match.group(0) if match.group(0) in LOCAL_POSTCODES else "",
        raw
    )
    raw=re.sub(r"\s*,\s*", ", ", raw)
    raw=" ".join(re.sub(r",\s*,+", ", ", raw).split()).strip(" ,")
    raw=re.sub(r"(?i)(chiclana de la frontera)(?:[, ]+\1)+", r"\1", raw)
    raw=re.sub(r"(?i)(11130|11138|11139)(?:[, ]+\1)+", r"\1", raw)
    parts=[part.strip() for part in raw.split(",") if part.strip()]
    normalized_parts=[]
    for part in parts:
        pnorm=norm(part)
        if pnorm in {"chiclana", "chiclana de la frontera"} and any("chiclana" in norm(x) for x in parts if x != part):
            continue
        if pnorm in LOCAL_POSTCODES and any(re.search(r"(?<!\d)"+re.escape(part)+r"(?!\d)",x) for x in parts if x != part):
            continue
        if pnorm not in {norm(x) for x in normalized_parts}:
            normalized_parts.append(part)
    raw=", ".join(normalized_parts)
    raw=" ".join(raw.split()).strip(" ,")
    if norm(locality) == "chiclana de la frontera" and "chiclana" in norm(raw) and "chiclana de la frontera" not in norm(raw):
        raw=re.sub(r"(?i)\bchiclana\b", locality, raw)
    if norm(raw) in {"chiclana","chiclana de la frontera"} or re.fullmatch(r"(?:11130|11138|11139)", raw):
        raw=""
    # Una dirección debe identificar una vía, plaza, carretera, polígono o recinto concreto.
    has_detail=bool(re.search(
        r"(?i)\b(?:calle|c\.?|avenida|avda?\.?|plaza|pza\.?|paseo|carretera|ctra\.?|"
        r"camino|traves[ií]a|ronda|urbanizaci[oó]n|urb\.?|pol[ií]gono|pol\.?|"
        r"parque empresarial|centro comercial|edificio|edif\.?|bulevar|glorieta)\b", raw
    )) or bool(re.search(r"\b\d{1,4}\b", raw))
    if not raw or not has_detail:
        return ""
    parts=[raw]
    if postal and not re.search(r"(?<!\d)(11130|11138|11139)(?!\d)", raw):
        parts.append(postal)
    if locality and "chiclana" in norm(locality) and "chiclana" not in norm(raw):
        parts.append(locality)
    result=", ".join(dict.fromkeys(x for x in parts if x))
    return result[:240]


def clean_description(value, business_name=""):
    """Limpia metadatos SEO y evita descripciones genéricas o cruzadas."""
    raw=html.unescape(str(value or ""))
    raw=re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    raw=re.sub(r"<[^>]*>", " ", raw)
    # Algunas fuentes devuelven fragmentos HTML truncados (p. ej. "<p").
    raw=re.sub(r"<[^>]*$", " ", raw)
    raw=re.sub(r"[\t\r\n]+", " ", raw)
    raw=" ".join(raw.split()).strip(" |·-–—")
    raw=re.sub(
        r"(?i)\s*[|–—]\s*(?:directorio de empresas|gu[ií]a de empresas|empresas de chiclana|"
        r"la gu[ií]a de chiclana|portal comercial).*$", "", raw
    ).strip(" |·-–—")
    # Los fragmentos de buscadores/directorios con puntos suspensivos,
    # etiquetas de contacto u horarios no son descripciones comerciales.
    if re.search(r"(?:\.{3,}|…|\b(?:tel[eé]fono|tel\.)\s*[:：-]?)",raw,re.I):
        return ""
    if re.search(r"(?i)\b(?:lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)\b",raw) and re.search(r"\b\d{1,2}[:.]\d{2}\b",raw):
        return ""
    # Una frase cortada en una preposición/conector no es texto publicable.
    if raw.endswith((",", ";", ":")):
        return ""
    if re.search(r"(?i)\b(?:de|del|para|con|en|por|y|o|a|que|como|hasta|desde|asesoramie|asesoramien|asesoramient|especializ|distribuci|instalaci|mantenimien|reparaci|comercializ)$",raw):
        return ""
    n=norm(raw)
    generic_phrases=(
        "directorio de empresas","guia de empresas","portal de empresas",
        "listado de negocios","busca empresas","encuentra empresas",
        "la guia de chiclana","empresas de chiclana",
        "informacion sobre la empresa ver direccion",
        "chiclana de la frontera cadiz espana",
        "chiclana de la frontera cadiz",
    )
    if len(raw)<35 or any(x in n for x in generic_phrases):
        return ""
    # No considerar descripción comercial una llamada a seguir redes o descargar una app.
    if re.search(r"(?i)^(?:síguenos|siguenos|sígueme|siguenos en redes|síguenos en redes|descarga nuestra app|descarga nuestra aplicación)", raw):
        return ""
    if re.match(r"(?i)^(?:aviso legal|pol[ií]tica de privacidad|pol[ií]tica de cookies)\b",raw):
        return ""
    # Evita que una ficha herede una descripción que identifica claramente otro negocio.
    if "pimpam" in n and "pimpam" not in norm(business_name):
        return ""
    if len(raw)>700:
        raw=raw[:700]
        if not raw.endswith((" ",".",",",";",":")):
            raw=raw.rsplit(" ",1)[0]
    return raw.strip()


def is_directory_email(value, page_url):
    """Rechaza correos del propio portal/directorio, no del establecimiento."""
    email=str(value or "").strip().lower()
    if not email or "@" not in email: return False
    domain=email.rsplit("@",1)[-1].rstrip(".")
    source_host=(urllib.parse.urlparse(page_url).hostname or "").lower()
    blocked={"chiclanaguiadempresas.com","www.chiclanaguiadempresas.com"}
    return domain in blocked or domain==source_host or domain.removeprefix("www.")==source_host.removeprefix("www.")


def clean_website(value, page_url):
    """Acepta solo URL web HTTP(S) con host válido; no correos disfrazados de URL."""
    raw=str(value or "").strip()
    if not raw:
        return ""
    target=urllib.parse.urljoin(page_url,raw)
    parsed=urllib.parse.urlsplit(target)
    host=(parsed.hostname or "").lower()
    source_host=(urllib.parse.urlsplit(page_url).hostname or "").lower()
    if parsed.scheme.lower() not in ("http","https") or not host or "@" in parsed.netloc:
        return ""
    if "." not in host or host==source_host or host.removeprefix("www.")==source_host.removeprefix("www."):
        return ""
    return urllib.parse.urlunsplit((parsed.scheme.lower(),parsed.netloc,parsed.path,parsed.query,""))


def choose_schema_entity(candidates, page_url, headings=(), title=""):
    """Evita usar el primer JSON-LD global cuando pertenece a otra ficha."""
    page=url_key(page_url)
    page_host=urllib.parse.urlparse(page_url).netloc.lower()
    heading_keys={norm(x) for x in list(headings)+[title] if norm(x)}
    scored=[]
    for obj in candidates:
        if not isinstance(obj,dict): continue
        name=textval(obj.get("name"))
        if not name: continue
        urls=[]
        for key in ("url","@id","mainEntityOfPage"):
            value=obj.get(key)
            if isinstance(value,dict): value=value.get("@id") or value.get("url") or ""
            if isinstance(value,str) and value.strip(): urls.append(value.strip())
        exact=any(url_key(urllib.parse.urljoin(page_url,u))==page for u in urls)
        same_host=any(urllib.parse.urlparse(urllib.parse.urljoin(page_url,u)).netloc.lower()==page_host for u in urls)
        score=(100 if exact else 0)+(15 if norm(name) in heading_keys else 0)
        score+=sum(bool(obj.get(k)) for k in ("telephone","email","address","openingHours","description"))
        # Una entidad JSON-LD sin vínculo con esta página no se acepta,
        # aunque sea la única del documento. Solo vale URL exacta o URL del
        # mismo host acompañada de coincidencia exacta con un encabezado.
        heading_match=norm(name) in heading_keys
        if exact or (same_host and heading_match):
            scored.append((score,obj))
    if not scored: return {}
    scored.sort(key=lambda x:x[0],reverse=True)
    return scored[0][1]


def classify(text):
    """Clasifica por actividad principal; las menciones accesorias no deben dominar."""
    s=str(text or "").casefold()
    s_norm=norm(s)

    # Actividades explícitas de prestación de servicios: tienen prioridad sobre
    # menciones incidentales a vehículos, alojamientos, eventos o comercios.
    if any(term in s_norm for term in (
        "limpieza profesional","servicios de limpieza","empresa de limpieza",
        "limpiezas","limpieza de comunidades","limpieza de oficinas",
        "limpieza de apartamentos","limpieza industrial",
    )):
        return ("negocio","Servicios y negocios")

    if any(term in s_norm for term in (
        "asesoria","asesoramiento","gestoria","abogados","abogado",
        "despacho juridico","servicios juridicos","consultoria empresarial",
        "asesores","asesores fiscales","asesoria laboral",
    )):
        return ("negocio","Servicios profesionales")

    # La hidráulica y neumática industrial no deben clasificarse como automoción
    # por la mera presencia de la palabra «neumáticos» o «reparación».
    if any(term in s_norm for term in (
        "sistemas hidraulicos","sistemas neumaticos","hidraulica industrial",
        "componentes hidraulicos","bombas hidraulicas","cilindros hidraulicos",
        "mantenimiento hidraulico","reparacion de sistemas hidraulicos",
    )):
        return ("negocio","Servicios y negocios")

    # Alimentación incluye industria, fabricación y distribución alimentaria,
    # no solo comercios minoristas.
    if any(term in s_norm for term in (
        "comercio al por mayor de cafe","comercio al por mayor de café",
        "cafe te cacao y especias","café té cacao y especias",
        "distribucion mayorista de alimentos","mayorista de alimentacion",
        "frigorifico","frigorificos","industria alimentaria","alimentacion",
        "productos alimenticios","distribucion alimentaria","congelados",
        "carniceria","charcuteria","pescaderia","panaderia","supermercado",
        "frutos secos","golosinas","chocolate","bodega","bodegas","vinos","vinicola",
    )):
        return ("negocio","Alimentación")

    if any(term in s_norm for term in ("agencia de viajes","agencia viajes","viajes carrefour","viajes puentetravel")):
        return ("negocio","Servicios y negocios")

    # Atrípiko es restauración aunque una fuente lo describa genéricamente.
    if "atripiko" in s_norm:
        return ("ocio","Restauración")

    real_estate_terms=(
        "inmobiliaria","inmobiliarias","alquiler de vivienda","alquiler de viviendas",
        "alquiler de piso","alquiler de pisos","alquiler de casa","alquiler de casas",
        "alquiler vacacional","alquiler de local","alquiler de locales",
        "venta de vivienda","venta de viviendas","venta de inmueble","venta de inmuebles",
        "compra venta de inmuebles",
    )
    if any(term in s_norm for term in real_estate_terms):
        return ("negocio","Inmobiliaria")

    # Redes, telecomunicaciones e informática son servicios profesionales;
    # no deben caer en Alojamiento por menciones accesorias en el texto.
    if any(term in s_norm for term in (
        "redes y comunicaciones","redes informaticas","telecomunicaciones",
        "instalaciones de redes","cableado estructurado","fibra optica",
        "sistemas informaticos","servicios informaticos","soporte informatico",
    )):
        return ("negocio","Servicios y negocios")

    # Prioriza viveros y centros de jardinería frente a servicios accesorios.
    if any(term in s_norm for term in (
        "vivero","viveros","agricentro","centro de jardineria",
        "plantas ornamentales","productos de jardineria",
    )):
        return ("negocio","Comercio")

    if any(term in s_norm for term in (
        "agente de seguros","agencia de seguros","correduria de seguros",
        "seguros de vida","seguros de hogar",
    )):
        return ("negocio","Servicios profesionales")

    groups=[
      (("inoxidables","metalurgia","metalurgica","acero inoxidable","caldereria","carpinteria metalica","soldadura industrial"),("negocio","Servicios y negocios")),
      (("mudanzas","transportes","transporte","mensajeria","logistica"),("negocio","Servicios y negocios")),
      (("restaurante","cafeteria","comida","pizzeria","marisqueria","sushi","asador","taberna","meson","chiringuito","cerveceria","bar "),("ocio","Restauración")),
      (("ocio y animacion","eventos tematizados","animacion sociocultural","animacion infantil"),("ocio","Ocio y animación")),
      (("hotel","hostal","apartamento turistico","alojamiento"),("negocio","Alojamiento")),
      (("taller mecanico","taller de coches","taller de vehiculos","taller de motos","mecanica","reparacion de vehiculos","adaptaciones de vehiculos","automovil","automocion","concesionario","taller de neumaticos","venta de neumaticos","neumaticos"),("negocio","Automoción")),
      (("dentista","clinica","fisioterapia","veterinaria","veterinario","centro veterinario","farmacia","mascotas","optica","optico","optometrista","audifonos","audiologia"),("negocio","Salud")),
      (("peluqueria","estetica","gimnasio","centro deportivo","centros deportivos","aerobic","pilates","body combat","actividades deportivas"),("negocio","Belleza y deporte")),
      (("academia","colegio","formacion","idiomas"),("negocio","Educación")),
      (("joyeria","relojeria"),("negocio","Joyería y relojería")),
      (("mueble","muebles","mobiliario","decoracion","colchon"),("negocio","Muebles y decoración")),
      (("tienda","comercio","comprar","venta","moda","ropa","calzado","boutique","ferreteria"),("negocio","Comercio")),
      (("museo","teatro","cine","parque tematico","ocio","actividad turistica"),("ocio","Ocio y cultura")),
    ]
    for words,result in groups:
        if any(w in s_norm for w in words): return result
    return ("negocio","Servicios y negocios")

def url_key(value):
    """Clave de deduplicación: host normalizado, ruta y consulta conservadas."""
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return str(value or "").strip().rstrip("/")
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), host, path, parsed.query, ""))


def norm(value):
    import unicodedata
    value=unicodedata.normalize("NFD",str(value or "").casefold())
    value="".join(ch for ch in value if unicodedata.category(ch)!="Mn")
    return " ".join(re.findall(r"[a-z0-9]+",value))


def name_similarity(left, right):
    """Similitud conservadora de nombres comerciales, ignorando sufijos societarios."""
    import difflib
    ignored={"sl","sll","sa","slu","sc","coop","sociedad","limitada","anonima"}
    a_tokens=[x for x in norm(left).split() if x not in ignored]
    b_tokens=[x for x in norm(right).split() if x not in ignored]
    if not a_tokens or not b_tokens:
        return 0.0
    a=" ".join(a_tokens); b=" ".join(b_tokens)
    if a == b:
        return 1.0
    seq=difflib.SequenceMatcher(None,a,b).ratio()
    aset=set(a_tokens); bset=set(b_tokens)
    union=len(aset|bset)
    token=(len(aset&bset)/union) if union else 0.0
    containment=(len(aset&bset)/min(len(aset),len(bset))) if min(len(aset),len(bset)) else 0.0
    # La coincidencia de una sola palabra genérica no basta.
    if min(len(aset),len(bset)) == 1 and aset != bset:
        containment=0.0
    return max(seq, token, containment*0.94)


def record_value(record, *keys):
    for key in keys:
        value=record.get(key)
        if value:
            return str(value).strip()
    return ""


def compare_catalog_record(candidate, existing):
    """Clasifica una coincidencia; nunca confunde por sí sola sucursales distintas."""
    new_name=record_value(candidate,"n","nombre","name")
    old_name=record_value(existing,"n","nombre","name")
    score=name_similarity(new_name,old_name)
    if score < 0.86:
        return None
    new_addr=norm(record_value(candidate,"a","direccion","address"))
    old_addr=norm(record_value(existing,"a","direccion","address"))
    new_phones=set(extract_phones(record_value(candidate,"p","telefono","phone")))
    old_phones=set(extract_phones(record_value(existing,"p","telefono","phone")))
    new_web=url_key(record_value(candidate,"w","web","website"))
    old_web=url_key(record_value(existing,"w","web","website"))
    same_address=bool(new_addr and old_addr and new_addr==old_addr)
    different_addresses=bool(new_addr and old_addr and new_addr!=old_addr)
    same_contact=bool((new_phones and old_phones and new_phones.intersection(old_phones)) or
                      (new_web and old_web and new_web==old_web))
    exact_name=norm(new_name)==norm(old_name)
    if exact_name and same_address:
        return {"kind":"duplicate","reason":"mismo nombre y dirección","score":score}
    if score >= 0.88 and (same_address or same_contact):
        return {"kind":"duplicate","reason":"nombre coincidente y misma dirección o contacto","score":score}
    if exact_name and not new_addr:
        return {"kind":"possible","reason":"mismo nombre; candidata sin dirección para distinguir sucursal","score":score}
    if score >= 0.93 and (not new_addr or not old_addr):
        return {"kind":"possible","reason":"nombre casi idéntico y falta dirección en uno de los registros","score":score}
    if score >= 0.90 and not different_addresses:
        return {"kind":"possible","reason":"nombre muy similar; revisar posible variante o duplicado","score":score}
    if exact_name and different_addresses:
        return {"kind":"branch","reason":"mismo nombre con direcciones distintas; posible sucursal","score":score}
    return None


def find_catalog_match(candidate, records):
    best=None
    for old in records:
        if not isinstance(old,dict):
            continue
        match=compare_catalog_record(candidate,old)
        if not match:
            continue
        match["record"]=old
        priority={"duplicate":3,"possible":2,"branch":1}.get(match["kind"],0)
        if best is None or priority > best["_priority"] or (priority==best["_priority"] and match["score"]>best["score"]):
            best={**match,"_priority":priority}
    if best:
        best.pop("_priority",None)
    return best


def is_chiclana(address, locality, postal, body, title, url, trusted_local=False):
    locality_n=norm(locality)
    postal=str(postal or "").strip()
    if locality_n in {"chiclana","chiclana de la frontera"} or locality_n.startswith("chiclana de la frontera "): return True
    postal_match=re.search(r"(?<!\d)(11130|11138|11139)(?!\d)",postal+" "+str(address or ""))
    if postal_match: return True
    if address and "chiclana de la frontera" in norm(address): return True
    host=urllib.parse.urlparse(url).netloc.lower()
    if (host=="chiclana.es" or host.endswith(".chiclana.es")) and "chiclana" in norm(title+" "+body[:1200]): return True
    if trusted_local and host in TRUSTED_DIRECTORY_PATHS:
        path=urllib.parse.urlparse(url).path
        if any(path.startswith(prefix) for prefix in TRUSTED_DIRECTORY_PATHS[host]): return True
    return False

def extract(url, trusted_local=False):
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
    obj=choose_schema_entity(candidates,final_url,p.headings,title)
    # Prioriza el nombre estructurado de la ficha; el H1 puede contener SEO del portal.
    raw_name=textval(obj.get("name")) or (p.headings[0] if p.headings else "") or title
    name=clean_business_name(raw_name)
    if not name or not valid_business_name(name): return None
    # Compara JSON-LD, metadescripción y texto visible: algunos directorios
    # publican metadescripciones truncadas aunque el contenido completo esté en la ficha.
    description_blocks=[textval(obj.get("description")),desc]+p.paragraphs+p.headings[1:]
    cleaned_descriptions=[clean_description(x,name) for x in description_blocks]
    desc=max(cleaned_descriptions,key=len,default="")
    address=obj.get("address") or {}
    if isinstance(address,str): addr=address; locality=""; postal=""
    else:
        locality=textval(address.get("addressLocality"))
        postal=textval(address.get("postalCode"))
        addr=", ".join(x for x in [textval(address.get("streetAddress")),postal,locality] if x)
    phone_values=extract_phones(obj.get("telephone") or "")
    phone_values.extend(extract_contact_phones(p))
    phone=" / ".join(dict.fromkeys(phone_values))
    email=textval(obj.get("email"))
    website=clean_website(textval(obj.get("url")),final_url)
    # En fichas de directorios, el enlace externo rotulado como web oficial
    # es más fiable que cualquier enlace genérico (mapas o redes sociales).
    if not website:
        for _cls,href,label in p.links:
            target=urllib.parse.urljoin(final_url,html.unescape(href))
            host=urllib.parse.urlparse(target).netloc.lower()
            label_n=norm(label)
            host_label=re.sub(r"^www\.", "", host)
            label_host=re.sub(r"^www\.", "", str(label or "").strip().lower()).rstrip("/")
            explicit_web=any(k in label_n for k in ("sitio web","web oficial","website","pagina web"))
            domain_label=bool(re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}",label_host)) and label_host==host_label
            if host and host != urllib.parse.urlparse(final_url).netloc.lower() and (explicit_web or domain_label):
                website=clean_website(target,final_url)
                if website:
                    break
    if not addr:
        for _cls,_href,label in p.links:
            if re.search(r"(?<!\d)(11130|11138|11139)(?!\d)",label) and "chiclana" in norm(label):
                addr=label.strip()
                break
    blob=" ".join(p.text)
    if not addr:
        address_match=re.search(r"(?i)\bDirección\s*[:：]?\s*(.+?)(?:\s+Página web|\s+Cómo llegar|$)",blob)
        if address_match: addr=address_match.group(1).strip()[:240]
    if not addr:
        # Algunas fichas presentan la dirección como párrafo independiente.
        addr=next((x for x in p.paragraphs
                   if re.search(r"(?<!\d)(11130|11138|11139)(?!\d)",x)
                   and "chiclana" in norm(x)
                   and re.search(r"(?i)\b(calle|avenida|avda|camino|paseo|pol[ií]gono|carretera|plaza)\b",x)), "")
    # No conservar direcciones que no acrediten Chiclana: una página de directorio
    # puede incluir la sede de otra ciudad o datos globales de la propia guía.
    addr=clean_address(addr,locality,postal)
    if addr and not re.search(r"(?<!\d)(11130|11138|11139)(?!\d)",addr) and "chiclana" not in norm(addr):
        addr=""
    hours=obj.get("openingHours") or obj.get("openingHoursSpecification") or ""
    if isinstance(hours,dict): hours=[hours]
    if isinstance(hours,list):
        parts=[]
        for entry in hours:
            if isinstance(entry,dict):
                days=entry.get("dayOfWeek") or ""
                if isinstance(days,list): days=", ".join(textval(x).rsplit("/",1)[-1] for x in days)
                opens=entry.get("opens") or ""; closes=entry.get("closes") or ""
                part=" ".join(x for x in [str(days),(str(opens)+"-"+str(closes)).strip("-")] if x)
                if part: parts.append(part)
            elif textval(entry): parts.append(textval(entry))
        hours="; ".join(parts)
    blob=" ".join(p.text)
    if not phone:
        tel_values=[]
        for _cls,href,_label in p.links:
            if str(href).lower().startswith("tel:"):
                tel_values.extend(extract_phones(urllib.parse.unquote(str(href)[4:].split("?",1)[0])))
        phone=" / ".join(dict.fromkeys(tel_values))
    if not phone:
        phone=" / ".join(extract_phones(blob))
    if not email:
        mailto_values=[]
        for _cls,href,_label in p.links:
            if str(href).lower().startswith("mailto:"):
                value=urllib.parse.unquote(str(href)[7:].split("?",1)[0]).strip()
                if re.fullmatch(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",value):
                    mailto_values.append(value)
        mailto_values=list(dict.fromkeys(mailto_values))
        if len(mailto_values)==1: email=mailto_values[0]
    if not email:
        email_values=list(dict.fromkeys(re.findall(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",blob)))
        if len(email_values)==1: email=email_values[0]
    # Nunca atribuir al negocio el correo corporativo del directorio que aloja la ficha.
    if is_directory_email(email,final_url): email=""
    # Una localidad aislada no constituye una dirección postal verificable.
    if norm(addr) in {"chiclana","chiclana de la frontera"}: addr=""
    if not is_chiclana(addr,locality,postal,blob,title,final_url,trusted_local): return None
    # Una localidad o un código postal aislados no identifican dónde está el negocio.
    # Exigimos una vía/dirección concreta, además de una referencia municipal.
    address_detail=norm(addr)
    address_detail=re.sub(r"\b(11130|11138|11139|chiclana|de|la|frontera)\b"," ",address_detail)
    address_detail=" ".join(address_detail.split())
    if len(address_detail)<4 and not trusted_local: return None
    if not trusted_local and not re.search(r"(?<!\d)(11130|11138|11139)(?!\d)",addr) and "chiclana" not in norm(addr):
        return None
    # Una dirección válida sin ningún canal de contacto tampoco es candidata accionable.
    if not any((phone,email,website)): return None
    schema_type=obj.get("@type",[])
    schema_types=schema_type if isinstance(schema_type,list) else [schema_type]
    schema_types=" ".join(str(x).rsplit("/",1)[-1].rsplit("#",1)[-1] for x in schema_types)
    if any(x in schema_types for x in ("Restaurant","FoodEstablishment")):
        tipo,categoria="ocio","Restauración"
    else:
        # No usar menús ni pies de página del portal para decidir la actividad.
        # Los encabezados y el título pueden contener categorías del menú global.
        tipo,categoria=classify(" ".join((name,desc,schema_types)))
    return {"name":name,"type":tipo,"address":addr,"phone":phone,"email":email,"website":website,
            "hours":str(hours)[:500],"description":desc[:700],"source_url":final_url,
            "category":categoria}

def merge_existing_record(existing, record, source_url):
    """Enriquece una ficha existente sin sobrescribir datos ya guardados."""
    changed=[]
    conflicts=[]
    mapping=(("a","address"),("h","hours"),("d","description"),("t","type"),("c","category"))
    for key,source_key in mapping:
        incoming=str(record.get(source_key) or "").strip()
        if incoming and not str(existing.get(key) or "").strip():
            existing[key]=incoming
            changed.append(key)
    incoming_phones=extract_phones(record.get("phone") or "")
    old_phone=str(existing.get("p") or "").strip()
    old_phones=extract_phones(old_phone)
    additions=[x for x in incoming_phones if x not in old_phones]
    if additions:
        existing["p"]=" / ".join(([old_phone] if old_phone else [])+additions)
        changed.append("p")
    incoming_email=str(record.get("email") or "").strip()
    old_email=str(existing.get("e") or "").strip()
    if incoming_email and incoming_email.casefold() not in old_email.casefold():
        if not old_email:
            existing["e"]=incoming_email
            changed.append("e")
        else:
            existing["e"]=old_email+" / "+incoming_email
            changed.append("e")
    incoming_web=str(record.get("website") or "").strip()
    old_web=str(existing.get("w") or "").strip()
    if incoming_web and not old_web:
        existing["w"]=incoming_web
        changed.append("w")
    elif incoming_web and url_key(incoming_web)!=url_key(old_web):
        alternatives=existing.setdefault("web_alternativas",[])
        if incoming_web not in alternatives:
            alternatives.append(incoming_web)
            changed.append("web_alternativas")
            conflicts.append("La fuente aporta una web distinta; se conserva la web principal.")
    if changed:
        sources=existing.setdefault("fuentes_datos",[])
        if not isinstance(sources,list):
            sources=[]
            existing["fuentes_datos"]=sources
        if not any(isinstance(x,dict) and url_key(x.get("url",""))==url_key(source_url) for x in sources):
            sources.append({"url":source_url,"campos":changed})
    return changed,conflicts


def self_test():
    global allowed, get
    assert classify("Restaurante y cafetería") == ("ocio","Restauración")
    assert classify("Tienda de muebles") == ("negocio","Muebles y decoración")
    assert classify("TopGea Topografía. Especialistas en el sector topográfico e ingeniería técnica") == ("negocio","Servicios y negocios")
    assert classify("Eventos Piolín Golosinas y Globos. La decoración perfecta que su evento necesita") == ("negocio","Alimentación")
    assert classify("Mudanzas y Transportes Crespo. Transportes de muebles y guardamuebles") == ("negocio","Servicios y negocios")
    assert classify("Alquiler de viviendas en Chiclana") == ("negocio","Inmobiliaria")
    assert classify("Alquiler de maquinaria para construcción") != ("negocio","Inmobiliaria")
    assert classify("Alquiler de vehículos y herramientas") != ("negocio","Inmobiliaria")
    assert classify("Construcción, reformas y parques infantiles") == ("negocio","Servicios y negocios")
    assert classify("Marisquería Casa Bernardo") == ("ocio","Restauración")
    assert classify("Bar Cervecería D´Los Oliva") == ("ocio","Restauración")
    assert classify("Bodegas Vélez, fabricación y venta de vinos") == ("negocio","Alimentación")
    assert classify("Viveros Garola, agricentro, ferretería y veterinario") == ("negocio","Comercio")
    assert classify("Centros deportivos Amigos del Aerobic, Pilates y Body Combat") == ("negocio","Belleza y deporte")
    assert classify("Rocío Panés, agente de seguros Allianz") == ("negocio","Servicios profesionales")
    assert classify("Joyería Puente Chico, taller propio y soldaduras láser") == ("negocio","Joyería y relojería")
    assert classify("Frutos secos, golosinas y chocolate") == ("negocio","Alimentación")
    assert classify("Viajes Carrefour, agencia de viajes") == ("negocio","Servicios y negocios")
    assert classify("Ferretería Marchante, fontanería, piscina y electricidad") == ("negocio","Comercio")
    assert classify("Ituci Asesores, asesoría fiscal y laboral") == ("negocio","Servicios profesionales")
    assert clean_business_name("Jerónimo Vallejo Montero «Ituci Asesores»") == "Ituci Asesores"
    assert clean_business_name("Viajes Puente Travel 17, S.C. «Viajes Carrefour»") == "Viajes Carrefour"
    assert clean_business_name("Almacén de maderas Molduras Serrano Carpintería Carpinteros") == "Molduras Serrano"
    assert clean_business_name("Tatuaje Tattoo Ñoño Tattoo Studio") == "Ñoño Tattoo Studio"
    assert clean_business_name("Viajes MMS Chiclana Agencia") == "Viajes MMS Chiclana"
    assert clean_business_name("Dualópticos Ópticas Ópticos Lentillas") == "Dualópticos"
    assert clean_business_name("Peluquería Barber SHOP Sanchez peluquero") == "Barber Shop Sánchez"
    assert clean_business_name("Telefonía MundoPhone Fibra Telefonía móvil Teléfonos") == "MundoPhone"
    assert clean_description("Lunes a Jueves de: 09.30 a 14.00h y 18:00 a 20:00 UN VIAJE SIEMPRE ES LA MEJOR OPCIÓN", "Viajes MMS Chiclana") == ""
    assert clean_description("Pinturas, Barnices y suministros. Disponemos de sistema tintométrico para todo tipo de", "Pinturas Hermanos Vicario") == ""
    assert clean_description("Nuestro objetivo es ofrecer a nuestros clientes la mejor atención en todos los sentidos: asesoramie", "Dualópticos") == ""
    assert clean_description("Somos una tienda online pero el respaldo en tiendas físicas,", "MundoPhone") == ""
    assert clean_business_name("Bar Cervecería D´Los Oliva Bares") == "Bar Cervecería D´Los Oliva"
    assert clean_business_name("Centros deportivos Amigos del Aerobic pilates Body Combat") == "Amigos del Aerobic"
    assert clean_business_name("Peluquería Gernis Salón de belleza cosmética peluquerías") == "Peluquería Gernis"
    assert clean_business_name("Viveros Garola Agricentro Ferretería Peluquería canina Veterinario") == "Viveros Garola"
    assert clean_business_name("Concesionarios Citroën SEAT") == "Autos Colchón"
    assert clean_business_name("Laboratorio Seguridad alimentaria Análisis BioCentrol Laboratorios") == "BioCentrol Laboratorios"
    assert extract_phones("956 401 156650 767 055682 365 666") == ["956401156","650767055","682365666"]
    contact_page=Page()
    contact_page.feed("<html><body><p>Información de contacto</p><p>Av. del Torno, 5, Chiclana de la Frontera, Cádiz, España</p><p>613 571 762956 112 418</p><p>centauro@example.es</p><p>Síguenos en Instagram</p><p>685 51 66 19</p></body></html>")
    assert extract_contact_phones(contact_page) == ["613571762","956112418"]
    # Reproduce el pie real de La Guía: su teléfono general no es del negocio.
    directory_page=Page()
    directory_page.feed("<html><body><p>Información de contacto</p><p>Calle Real 10, Chiclana de la Frontera, Cádiz, España</p><p>956 123 456</p><p>Chiclana de la Frontera, Cádiz, España</p><p>685 51 66 19</p><p>info@chiclanaguiadempresas.com</p><p>Síguenos en Instagram</p></body></html>")
    assert extract_contact_phones(directory_page) == ["956123456"]
    # Formato real de La Guía: dirección comercial sin «Cádiz», seguida
    # del pie común con el teléfono general y el correo del directorio.
    directory_page_short_address=Page()
    directory_page_short_address.feed("""<html><body>
    <p>Información de contacto</p>
    <p>Avenida de los Descubrimientos 94, Chiclana de la Frontera, España</p>
    <p>856 179 926672 104 197</p>
    <p>interioreschiclana@gmail.com</p>
    <p>Chiclana de la Frontera, Cádiz, España</p>
    <p>685 51 66 19</p>
    <p>info@chiclanaguiadempresas.com</p>
    <p>Síguenos en Instagram</p></body></html>""")
    assert extract_contact_phones(directory_page_short_address) == ["856179926","672104197"]
    assert clean_business_name("Atrípiko Restaurante cocina fusión latina Restaurantes") == "Atrípiko-Gastro Bar"
    assert classify("Atrípiko-Gastro Bar, restaurante de cocina fusión latina") == ("ocio","Restauración")
    assert compare_catalog_record(
        {"n":"Atrípiko-Gastro Bar","a":"Av. de los Pescadores 1, 11139 Chiclana","p":"956406355"},
        {"n":"Atrípiko-Gastro Bar","a":"Avenida de los Pescadores 1, 11130 Chiclana","p":"956406355"}
    )["kind"] == "duplicate"
    assert classify("Energía Solar Placas solares. Instalación y mantenimiento de energía solar") == ("negocio","Servicios y negocios")
    assert classify("TEMATIC EVENTOS TEMATIZADOS, S.L. Ocio y animación") == ("ocio","Ocio y animación")
    assert classify("Taller Autox, mecánica y adaptaciones de vehículos") == ("negocio","Automoción")
    assert clean_business_name("Ávila Bobillo Clínica Dental Odontopediatría Ortodoncia Dentista") == "Ávila Bobillo Clínica Dental"
    assert clean_business_name("Ávila Bobillo Clínica Dental, Odontopediatría, Ortodoncia, Dentista") == "Ávila Bobillo Clínica Dental"
    assert clean_business_name("Guerrero & Asesores Asesoría Gestoría Empresas Consultoría integral") == "Guerrero & Asesores"
    assert clean_business_name("Guerrero & Asesores, Asesoría, Gestoría, Empresas, Consultoría integral") == "Guerrero & Asesores"
    assert clean_business_name("Interiores Sofás y Colchones sofá muebles butacas") == "Interiores Sofás y Colchones"
    assert clean_business_name("Reformas Construcción COYREMAR") == "Reformas COYREMAR"
    assert clean_business_name("Joyería Puente Chico Relojería Joyerías") == "Joyería Puente Chico"
    assert clean_business_name("Frutos Secos TERE golosinas chocolate") == "Frutos Secos TERE"
    assert clean_business_name("Agrojardín Reina Maquinaria de jardinería, Ferretería, Suministros, Pellets") == "Agrojardín Reina"
    assert clean_business_name("NATTEX MOBILIARIO SOFÁS SOFÁ COLCHONES MUEBLES DECORACIÓN") == "NATTEX"
    assert clean_business_name("Carpintería Somoan carpinterías") == "Carpintería Somoan"
    assert clean_business_name("Cebos Vivos la Corvina Pesca Accesorios náuticos") == "Cebos Vivos la Corvina"
    assert clean_business_name("DIGAVASA Casas prefabricadas Módulos") == "DIGAVASA"
    assert clean_business_name("Ópticos General Ópticas Audífonos") == "General Óptica"
    assert clean_business_name("Motos Mondiña Punto de venta YAMAHA Concesionario") == "Motos Mondiña"
    assert clean_business_name("Taller Talleres Miguel Catalán mecánico mecánica automóvil") == "Talleres Miguel Catalán"
    assert clean_business_name("PINTURAS Y REVESTIMIENTOS Trabajo vertical CAMACHO RAMOS") == "PINTURAS Y REVESTIMIENTOS CAMACHO RAMOS"
    assert classify("General Óptica, ópticos y audífonos") == ("negocio","Salud")
    assert classify("Fábrica de mobiliario de cocinas") == ("negocio","Muebles y decoración")
    assert is_chiclana("Calle Real 1, 11130, Chiclana","", "11130", "", "", "https://example.org")
    assert is_chiclana("","Chiclana de la Frontera","", "", "", "https://example.org")
    assert not is_chiclana("","", "", "Servicio en Chiclana y alrededores", "Empresa", "https://example.org")
    assert url_key("HTTPS://Example.COM/Ruta/ConMayusculas/") == "https://example.com/Ruta/ConMayusculas"
    page=Page(); page.feed('<h1>Empresa local</h1><a class="external" href="https://example.org">Página web</a>')
    assert page.links == [("external","https://example.org","Página web")]
    assert page.headings == ["Empresa local"]
    assert normalize_phone("856 10 20") == ""
    assert normalize_phone("956 40 16") == ""
    assert normalize_phone("956 402615") == "956402615"
    assert normalize_phone("956 402 615") == "956402615"
    assert normalize_phone("+34 610 306 074") == "610306074"
    assert extract_phones("616 914 930956 406 170") == ["616914930","956406170"]
    assert extract_phones("956400150 / 956531722") == ["956400150","956531722"]
    assert extract_phones("661 082 081626 828 032") == ["661082081","626828032"]
    assert clean_business_name("Bar Cafetería Y Bar PimPam Cervecería Bares Pim Pam tapas comer paella") == "Bar Cafetería Y Bar PimPam"
    assert clean_business_name("Talleres Gómez") == "Talleres Gómez"
    assert clean_business_name("Casa Bernardo Marisquería Marisquerías Restaurantes Restaurantes Chiclana") == "Casa Bernardo Marisquería"
    assert valid_business_name("Casa Bernardo Marisquería")
    assert not valid_business_name("Restaurantes Bares Empresas Chiclana")
    assert not valid_business_name("Empresa de servicios en Chiclana Restaurantes Bares")
    assert not valid_business_name("La Guía de Chiclana")
    assert clean_business_name("Rodamientos Chiclana – AE Chiclana") == "Rodamientos Chiclana"
    assert clean_address("Dirección: Calle Real 10, 11130, Chiclana de la Frontera") == "Calle Real 10, 11130, Chiclana de la Frontera"
    assert clean_address("Chiclana de la Frontera") == ""
    assert clean_address("Ctra. de la Barrosa, 36º23'14'' 6º11'10''W) 28 m") == "Ctra. de la Barrosa"
    assert clean_address("11130") == ""
    assert clean_address("Avda. Fernando de Magallanes 36, 11130 Chiclana de la Fra., 11130 Chiclana de la Fra.") == "Avda. Fernando de Magallanes 36, 11130 Chiclana de la Frontera"
    assert clean_address("Calle Real 10, 11130, Chiclana de la Frontera, 11130, Chiclana de la Frontera") == "Calle Real 10, 11130, Chiclana de la Frontera"
    assert clean_description("Directorio de empresas de Chiclana | La Guía de Chiclana") == ""
    assert clean_description("Motos Mondiña, concesionario oficial... Tel. 956 000 000") == ""
    assert clean_description("Piscina Rueda Piscinas... especialistas en piscinas") == ""
    assert clean_description("Q2 Cocinas | Cocinas a medida... Tel.") == ""
    assert clean_description("Empresa local con servicios profesionales. Teléfono: 956 000 000") == ""
    assert clean_description("Servicios de redes y comunicaciones para empresas en Chiclana") == "Servicios de redes y comunicaciones para empresas en Chiclana"
    assert classify("LGA Redes y Comunicaciones, S.L.U. Redes informáticas y telecomunicaciones") == ("negocio","Servicios y negocios")
    assert clean_description("Aviso legal | Política de privacidad | Política de cookies") == ""
    assert clean_description("Información sobre la empresa Ver dirección", "Gestión 10 Asesoría") == ""
    assert clean_description("Chiclana de la Frontera, Cádiz, España", "Lola Robledo Modas y Complementos") == ""
    assert clean_description("Síguenos en redes sociales o descarga nuestra App", "Sebastián Moreno Irisarri") == ""
    assert clean_description('Empresa dedicada a construcciones, reformas y parques infantiles. SERVICIOS <img src="https://ejemplo.es/imagen.jpg" <p', "Pavimentos Coyremar") == "Empresa dedicada a construcciones, reformas y parques infantiles. SERVICIOS"
    assert classify("Veterinario VeterCosta Peluquería canina") == ("negocio","Salud")
    assert classify("Frigoríficos Costa Sur. Elaboración y distribución de alimentos frescos y congelados") == ("negocio","Alimentación")
    assert classify("Asesoría RV Gestoría & Abogados. Transferencias de vehículos") == ("negocio","Servicios profesionales")
    assert classify("JR Limpiezas y Servicios. Limpieza profesional de apartamentos turísticos") == ("negocio","Servicios y negocios")
    assert classify("Lola Robledo. Tienda de moda y ropa") == ("negocio","Comercio")
    assert classify("Hidráulica Cabral. Diseño, fabricación, mantenimiento y reparación de sistemas hidráulicos y neumáticos") == ("negocio","Servicios y negocios")
    assert classify("Nova Delta. Comercio al por mayor de café, té, cacao y especias") == ("negocio","Alimentación")
    assert classify("Taller de neumáticos y mecánica del automóvil") == ("negocio","Automoción")
    assert classify("Inoxidables Chiclana, S.L.") == ("negocio","Servicios y negocios")
    assert clean_website("http://info@pedenetti.com/","https://directorio.example/ficha") == ""
    assert clean_website("https://empresa.es/","https://directorio.example/ficha") == "https://empresa.es/"
    assert clean_address("Avenida Bahía 23, 11100, Chiclana","Chiclana de la Frontera","11100") == "Avenida Bahía 23, Chiclana de la Frontera"
    assert clean_description("Bar PimPam ofrece tapas caseras y platos tradicionales en un ambiente familiar", "La Guía de Chiclana") == ""
    assert is_directory_email("info@chiclanaguiadempresas.com","https://www.chiclanaguiadempresas.com/empresas/empresa/bar")
    assert not is_directory_email("contacto@empresa.es","https://www.chiclanaguiadempresas.com/empresas/empresa/bar")
    wrong={"@type":"Organization","name":"Directorio general","url":"https://portal.example/"}
    right={"@type":"LocalBusiness","name":"Empresa concreta","url":"https://portal.example/ficha/empresa"}
    assert choose_schema_entity([wrong,right],"https://portal.example/ficha/empresa") is right
    assert choose_schema_entity([wrong,right],"https://portal.example/ficha/otra") == {}
    # Una entidad única sin URL no debe atribuirse automáticamente a la página.
    orphan={"@type":"LocalBusiness","name":"Empresa sin vínculo"}
    assert choose_schema_entity([orphan],"https://portal.example/ficha/empresa") == {}
    # La coincidencia exacta del encabezado solo basta si el enlace pertenece al host.
    same_host={"@type":"LocalBusiness","name":"Empresa concreta","url":"/otra-ruta"}
    assert choose_schema_entity([same_host],"https://portal.example/ficha/empresa",["Empresa concreta"]) is same_host
    unrelated={"@type":"LocalBusiness","name":"Otra empresa","url":"/ficha/otra"}
    assert choose_schema_entity([unrelated],"https://portal.example/ficha/empresa",["Empresa concreta"]) == {}
    assert is_chiclana("", "", "", "", "", "https://aechiclana.org/directorio/trabajo/empresa/", True)
    assert not is_chiclana("", "", "", "", "", "https://aechiclana.org/directorio/", True)

    # Deduplicación por nombre, dirección y contacto, sin bloquear sucursales reales.
    assert compare_catalog_record(
        {"n":"Casa Bernardo Marisquería","a":"Calle Real 10","p":"956123456"},
        {"n":"Casa Bernardo Marisquería","a":"Calle Real 10","p":"956123456"}
    )["kind"] == "duplicate"
    assert compare_catalog_record(
        {"n":"Casa Bernardo Marisquería","a":"Calle Real 10","p":"956123456"},
        {"n":"Casa Bernardo Marisquería S.L.","a":"Calle Real 10","p":"956999999"}
    )["kind"] == "duplicate"
    assert compare_catalog_record(
        {"n":"Casa Bernardo Marisquería","a":"Calle Real 10","p":"956123456"},
        {"n":"Casa Bernardo Marisquería","a":"Avenida Diputación 20","p":"956999999"}
    )["kind"] == "branch"
    assert compare_catalog_record(
        {"n":"Rodamientos Chiclana","a":"Calle Real 10","p":"956123456"},
        {"n":"Rodamientos Chiclana S.L.","a":"Calle Real 10","p":"956999999"}
    )["kind"] == "duplicate"
    assert compare_catalog_record(
        {"n":"Educa Dog Adiestramiento Canino","a":"Calle Real 10","p":"956123456"},
        {"n":"Adiestramiento Canino Educa Dog","a":"Calle Real 10","p":"956999999"}
    )["kind"] == "duplicate"
    assert compare_catalog_record(
        {"n":"Casa Bernardo","a":"Calle Real 10","p":"956123456"},
        {"n":"Casa Bernarda","a":"Avenida Diputación 20","p":"956999999"}
    ) is None
    assert compare_catalog_record(
        {"n":"Bodegas Primitivo Collantes","a":"Calle Real 10","p":"956400150 / 956531722"},
        {"n":"Bodegas Primitivo Collantes S.A.","a":"Avenida Diputación 20","p":"956531722 / 956400150"}
    )["kind"] in ("duplicate","possible")
    enrichment={"n":"Empresa de prueba","p":"956111111","e":"","w":"","h":"","d":"","a":""}
    changed,conflicts=merge_existing_record(enrichment,{
        "address":"Calle Real 10, 11130 Chiclana","phone":"956222222",
        "email":"info@empresa.es","website":"https://empresa.es",
        "hours":"L-V 09:00-18:00","description":"Descripción comercial de prueba"
    },"https://directorio.example/empresa")
    assert "p" in changed and enrichment["p"]=="956111111 / 956222222"
    assert enrichment["e"]=="info@empresa.es" and enrichment["w"]=="https://empresa.es"
    assert enrichment["a"]=="Calle Real 10, 11130 Chiclana"
    assert len(enrichment["fuentes_datos"])==1
    assert merge_existing_record(enrichment,{"phone":"956222222"},"https://directorio.example/empresa")[0]==[]

    # Las señales de baja calidad se muestran para revisión, nunca se publican automáticamente.
    noisy=candidate_review_notes({
        "name":"Mª Augusta Marín Aguilar Galindo",
        "address":"Centro Comercial Novo Sancti Petri, 11139 Chiclana",
        "phone":"915781701"
    })
    assert any("persona" in x for x in noisy)
    assert any("prefijo geográfico" in x for x in noisy)
    assert candidate_review_notes({
        "name":"Ofipapel Chiclana",
        "address":"Calle Real 1, 11130 Chiclana",
        "phone":"956402615"
    }) == []
    assert any("error ortográfico" in x for x in candidate_review_notes({
        "name":"Friogoríficos Puerto Mar","address":"Polígono Pelagatos","phone":"956404012"
    }))
    assert any("repetición" in x for x in candidate_review_notes({
        "name":"Taller Autox Pertsolutions Talleres","address":"Avenida Bahía 23","phone":"605060859"
    }))
    assert not any("Nombre largo" in x for x in candidate_review_notes({
        "name":"COMPLEJO INTERNACIONAL DEL ESPACIO, S.L.","address":"Calle Ugaldenea 74","phone":"610638863"
    }))

    # Prueba de integración: extracción completa con HTML controlado.
    original_allowed, original_get = allowed, get
    sample = """<html><head><title>Empresa de Prueba</title>
    <meta name="description" content="Descripción de prueba del establecimiento">
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"LocalBusiness","name":"Empresa de Prueba",
    "@id":"https://directorio.example/empresa-prueba#empresa",
    "telephone":"956123456","email":"info@empresa-prueba.es","url":"https://empresa-prueba.es",
    "address":{"@type":"PostalAddress","streetAddress":"Calle Real 10",
    "postalCode":"11130","addressLocality":"Chiclana de la Frontera"},
    "openingHours":["Mo-Fr 09:00-18:00"]}
    </script></head><body>Empresa local</body></html>"""
    try:
        allowed = lambda url: True
        get = lambda url, limit=1200000: (sample, url, "text/html")
        record = extract("https://directorio.example/empresa-prueba")
        assert record is not None, "No se ha extraído la ficha local de prueba"
        assert record["name"] == "Empresa de Prueba"
        assert "Calle Real 10" in record["address"] and "11130" in record["address"]
        assert record["phone"] == "956123456"
        assert record["email"] == "info@empresa-prueba.es"
        assert record["website"] == "https://empresa-prueba.es"
        assert record["hours"] == "Mo-Fr 09:00-18:00"
        assert record["description"] == "Descripción de prueba del establecimiento"

        multi_phone_sample = """<html><head><title>Agrojardín Reina</title>
        <meta name="description" content="Maquinaria de jardinería y suministros profesionales para el campo">
        </head><body><h1>Agrojardín Reina Maquinaria de jardinería, Ferretería, Suministros, Pellets</h1>
        <p>Especialistas en maquinaria de jardinería, ferretería y suministros para profesionales.</p>
        <p>Teléfonos: 616 914 930956 406 170</p><p>Camino del Molino 12, 11130 Chiclana de la Frontera</p>
        <a href="https://agrojardinreina.es/">agrojardinreina.es</a></body></html>"""
        get = lambda url, limit=1200000: (multi_phone_sample, url, "text/html")
        multi = extract("https://directorio.example/agrojardin")
        assert multi is not None, "No se ha extraído la ficha con teléfonos concatenados"
        assert multi["phone"] == "616914930 / 956406170", multi["phone"]
        assert multi["name"] == "Agrojardín Reina", multi["name"]
        assert multi["website"] == "https://agrojardinreina.es/", multi["website"]

        trusted_contact_sample = """<html><head><title>Hotel Local de Prueba</title></head>
        <body><h1>Hotel Local de Prueba</h1><p>956 123 456</p>
        <a href="https://hotel-local.example/">hotel-local.example</a></body></html>"""
        get = lambda url, limit=1200000: (trusted_contact_sample, url, "text/html")
        trusted = extract("https://www.cadizturismo.com/es/empresa/hotel-local", trusted_local=True)
        assert trusted is not None, "No se ha aceptado la ficha local de directorio oficial sin calle"
        assert trusted["name"] == "Hotel Local de Prueba"
        assert trusted["phone"] == "956123456" and trusted["website"] == "https://hotel-local.example/"
        assert trusted["address"] == "", "No se debe inventar una dirección que la fuente no facilita"

        nonlocal_sample = """<html><head><title>Servicio nacional</title>
        <meta name="description" content="Servicio disponible en Chiclana y toda España">
        <script type="application/ld+json">
        {"@type":"LocalBusiness","name":"Servicio nacional",
        "address":{"addressLocality":"Madrid","postalCode":"28001"}}
        </script></head><body>Servicio en Chiclana y alrededores</body></html>"""
        get = lambda url, limit=1200000: (nonlocal_sample, url, "text/html")
        assert extract("https://directorio.example/servicio-nacional") is None, "El filtro geográfico ha aceptado un negocio no local"
    finally:
        allowed, get = original_allowed, original_get
    print("RAD self-test: OK",flush=True)

def candidate_review_notes(record):
    """Detecta señales de extracción dudosa; nunca publica ni descarta automáticamente."""
    notes=[]
    name=str(record.get("name") or record.get("n") or "").strip()
    name_norm=norm(name)
    tokens=name_norm.split()
    business_markers={
        "sl","sll","sa","slu","coop","clinica","taller","restaurante","bar","hotel",
        "tienda","ferreteria","abogados","asesores","asesoria","suministros","recambios",
        "inmobiliaria","farmacia","peluqueria","fisioterapia","construcciones","transportes"
    }
    legal_entity=bool(re.search(r"(?i)(?:,?\s*)(?:s\.?\s*l\.?\s*u?\.?|s\.?\s*a\.?|sociedad limitada|sociedad anonima)\s*$",name))
    if len(tokens)>=5 and not legal_entity and not any(token in business_markers for token in tokens):
        notes.append("Nombre largo sin indicador comercial claro; comprobar si identifica a una persona o contiene texto SEO.")
    if "friogorificos" in tokens:
        notes.append("Posible error ortográfico en el nombre; comprobar la denominación en la fuente original.")
    stems=[re.sub(r"(es|s)$","",token) for token in tokens if len(token)>4]
    if len(stems)!=len(set(stems)):
        notes.append("Posible repetición de descriptor en el nombre comercial.")
    address=str(record.get("address") or record.get("a") or "")
    address_tokens=norm(address).split()
    if any(a==b for a,b in zip(address_tokens,address_tokens[1:])):
        notes.append("La dirección contiene palabras repetidas consecutivas; verificar la extracción.")
    for phone in extract_phones(record.get("phone") or record.get("p") or ""):
        if phone[0] in "89" and not phone.startswith(("856","956")):
            notes.append("El teléfono fijo no presenta prefijo geográfico de Cádiz; confirmar que corresponde al establecimiento de Chiclana.")
            break
    return notes


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--catalog",type=pathlib.Path,default=MASTER,
                        help="Catálogo JSON de entrada/salida; permite probar sobre una copia.")
    args=parser.parse_args()
    if args.self_test:
        self_test()
        return
    catalog_path=args.catalog
    if not catalog_path.is_file(): raise SystemExit("No existe el catálogo indicado.")
    data=json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(data.get("items"),list) or not isinstance(data.get("candidatas_revision",[]),list):
        raise SystemExit("Estructura del catálogo no válida; se cancela sin modificar.")
    existing=data["items"]+data.get("candidatas_revision",[])
    existing_pairs=set()
    existing_name_addresses={}
    urls=set()
    for x in existing:
        if not isinstance(x,dict): continue
        source_url=x.get("url_fuente_rastreo","")
        if source_url: urls.add(url_key(source_url))
        sources=x.get("fuentes_datos",[])
        if isinstance(sources,list):
            for source in sources:
                if isinstance(source,dict) and source.get("url"):
                    urls.add(url_key(source["url"]))
    for item in existing:
        if not isinstance(item,dict): continue
        name=norm(item.get("n") or item.get("nombre") or item.get("name"))
        addr=norm(item.get("a") or item.get("direccion") or item.get("address"))
        if name and addr: existing_pairs.add(name+"|"+addr)
        if name: existing_name_addresses.setdefault(name,set()).add(addr)
    links=[]
    trusted_urls=set()
    # Fuentes locales directas: sus fichas individuales son una vía de detección
    # independiente de los buscadores. Solo se confía en rutas de detalle conocidas.
    for seed in DIRECTORY_SEEDS:
        if not allowed(seed): continue
        try:
            seed_body,seed_final,_=get(seed,900000)
            seed_page=Page(); seed_page.feed(seed_body)
            seed_host=urllib.parse.urlparse(seed_final).netloc.lower()
            seed_count=0
            for _,href,_label in seed_page.links:
                target=urllib.parse.urljoin(seed_final,html.unescape(href))
                parsed=urllib.parse.urlparse(target)
                if parsed.scheme not in ("http","https") or parsed.netloc.lower()!=seed_host: continue
                if any(parsed.path.startswith(prefix) for prefix in TRUSTED_DIRECTORY_PATHS.get(seed_host,())):
                    trusted_urls.add(target); seed_count+=1
                    if seed_count>=160: break
        except Exception as exc:
            print(f"Fuente directa no disponible ({seed}): {exc}",flush=True)
    links.extend(sorted(trusted_urls))
    for q in QUERIES:
        for engine in (search_ddg,search_bing):
            try: links.extend(engine(q))
            except Exception as exc: print(f"Buscador no disponible ({engine.__name__}): {exc}",flush=True)
    links=list(dict.fromkeys(links))[:MAX_PAGES]
    added=[]; seen_pairs=set(); seen_urls=set(); seen_unlocated_names=set()
    coincidencias=[]; registros_conocidos=existing[:]
    fichas_enriquecidas=set(); campos_actualizados=0; conflictos_web=0
    for url in links:
        trusted_local=urllib.parse.urlparse(url).netloc.lower() in TRUSTED_DIRECTORY_PATHS and any(urllib.parse.urlparse(url).path.startswith(prefix) for prefix in TRUSTED_DIRECTORY_PATHS[urllib.parse.urlparse(url).netloc.lower()])
        record=extract(url,trusted_local=trusted_local)
        if not record: continue
        name_key=norm(record["name"]); addr_key=norm(record["address"])
        pair=name_key+"|"+addr_key if addr_key else ""
        source_url=record["source_url"]
        u_key=url_key(source_url)
        if not name_key or u_key in urls or u_key in seen_urls: continue
        if pair and pair in seen_pairs: continue
        if not pair and name_key in seen_unlocated_names: continue
        candidate={
          "n":record["name"],"a":record["address"],"p":record["phone"],
          "w":record["website"],"url_fuente_rastreo":source_url
        }
        match=find_catalog_match(candidate,registros_conocidos)
        if match and match["kind"] in ("duplicate","possible"):
            old=match["record"]
            exact_name=norm(record["name"])==norm(record_value(old,"n","nombre","name"))
            exact_name_matches=sum(
                1 for x in registros_conocidos
                if isinstance(x,dict) and norm(record["name"])==norm(record_value(x,"n","nombre","name"))
            )
            safe_to_enrich=(match["kind"]=="duplicate" or (trusted_local and exact_name and exact_name_matches==1))
            if safe_to_enrich:
                changed,conflicts=merge_existing_record(old,record,source_url)
                if changed:
                    fichas_enriquecidas.add(str(old.get("id") or record_value(old,"n","nombre","name")))
                    campos_actualizados+=len(changed)
                    conflictos_web+=len(conflicts)
                    coincidencias.append({
                        "nombre_detectado":record["name"],
                        "nombre_catalogo":record_value(old,"n","nombre","name"),
                        "tipo":"ficha_enriquecida","campos":changed,
                        "url_detectada":source_url
                    })
                else:
                    coincidencias.append({
                        "nombre_detectado":record["name"],
                        "nombre_catalogo":record_value(old,"n","nombre","name"),
                        "tipo":match["kind"],"motivo":"Coincidencia confirmada; no había campos vacíos que completar.",
                        "url_detectada":source_url
                    })
                seen_urls.add(u_key)
                continue
            coincidencias.append({
                "nombre_detectado":record["name"],
                "nombre_catalogo":record_value(old,"n","nombre","name"),
                "tipo":match["kind"],"motivo":match["reason"],
                "similitud":round(match["score"],3),"url_detectada":source_url
            })
            seen_urls.add(u_key)
            continue
        # También se comparan entre sí las candidatas del mismo rastreo.
        run_match=find_catalog_match(candidate,added)
        if run_match and run_match["kind"] in ("duplicate","possible"):
            old=run_match["record"]
            coincidencias.append({
                "nombre_detectado":record["name"],
                "nombre_catalogo":record_value(old,"n","nombre","name"),
                "tipo":"posible_duplicado_en_rastreo","motivo":run_match["reason"],
                "similitud":round(run_match["score"],3),"url_detectada":source_url
            })
            seen_urls.add(u_key)
            continue
        seen_urls.add(u_key)
        if pair: seen_pairs.add(pair)
        if not pair: seen_unlocated_names.add(name_key)
        digest=hashlib.sha256((name_key+"|"+addr_key+"|"+u_key).encode()).hexdigest()[:16]
        fields_present=["nombre"]+[k for k,v in [
            ("direccion",record["address"]),("telefono",record["phone"]),("correo",record["email"]),
            ("web",record["website"]),("horario",record["hours"]),("descripcion",record["description"])
        ] if v]
        candidate={
          "id":"rad:"+digest,"n":record["name"],"t":record["type"],"c":record["category"],
          "a":record["address"],"p":record["phone"],"e":record["email"],
          "w":record["website"],"h":record["hours"],"d":record["description"],
          "f":"Rastreo web público (RAD)","url_fuente_rastreo":source_url,
          "fuentes_datos":[{"url":source_url,"campos":fields_present}],
          "estado_revision":"pendiente","fuente_estado":"Candidato detectado en fuente web pública; pendiente de validación manual",
          "fecha_deteccion_utc":datetime.now(timezone.utc).isoformat()
        }
        review_notes=candidate_review_notes(record)
        if match and match["kind"]=="branch":
            review_notes.append("Mismo nombre que otra ficha, pero dirección distinta; posible sucursal. Validar manualmente antes de aprobar.")
        if "apartado postal" in norm(record["address"]) or "apartado de correos" in norm(record["address"]):
            review_notes.append("La fuente mezcla una dirección con un apartado postal; confirmar la ubicación física antes de aprobar.")
        if review_notes:
            candidate["nota_revision"]=" ".join(dict.fromkeys(review_notes))
        added.append(candidate)
        registros_conocidos.append(candidate)
    data.setdefault("candidatas_revision",[]).extend(added)
    data["total_candidatas_revision"]=len(data["candidatas_revision"])
    data["rad_ultima_ejecucion"]={"fecha_utc":datetime.now(timezone.utc).isoformat(),
       "buscadores":["DuckDuckGo HTML","Bing RSS"],"fuentes_directas":DIRECTORY_SEEDS,"consultas":len(QUERIES),
       "urls_encontradas":len(links),"candidatas_nuevas":len(added),
       "fichas_enriquecidas":len(fichas_enriquecidas),"campos_actualizados":campos_actualizados,
       "conflictos_web_no_sobrescritos":conflictos_web,
       "coincidencias_catalogo":len(coincidencias),
       "detalle_coincidencias":coincidencias[:100],
       "publicacion_automatica":False}
    catalog_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(data["rad_ultima_ejecucion"],ensure_ascii=False),flush=True)

if __name__=="__main__": main()