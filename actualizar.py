#!/usr/bin/env python3
"""Descarga de OpenStreetMap los comercios y lugares de Chiclana y crea data.json."""
import json, sys, time, datetime, pathlib, re, unicodedata, urllib.parse, urllib.request, hashlib

RAIZ = pathlib.Path(__file__).parent
SERVIDORES = ["https://overpass-api.de/api/interpreter",
              "https://overpass.kumi.systems/api/interpreter"]
CONSULTA = """[out:json][timeout:60];
area["boundary"="administrative"]["name"="Chiclana de la Frontera"]->.z;
(
 nwr["shop"](area.z);
 nwr["amenity"~"^(restaurant|bar|cafe|pub|fast_food|ice_cream|pharmacy|clinic|dentist|doctors|veterinary|bank|cinema|theatre|nightclub|marketplace|fuel|car_wash|car_rental|driving_school|school|kindergarten|post_office|townhall|library)$"](area.z);
 nwr["tourism"~"^(hotel|hostel|guest_house|apartment|camp_site|museum|attraction|gallery|viewpoint|zoo|theme_park)$"](area.z);
 nwr["leisure"~"^(sports_centre|fitness_centre|golf_course|marina|park|water_park|swimming_pool|dance|miniature_golf|stadium|nature_reserve|beach_resort)$"](area.z);
 nwr["craft"](area.z);
 nwr["office"](area.z);
 nwr["historic"~"^(castle|monument|church|ruins|memorial|archaeological_site)$"](area.z);
 nwr["natural"="beach"](area.z);
);
out center tags;"""

SHOP = {"supermarket":"Supermercado","convenience":"Tienda de barrio","bakery":"Panadería","butcher":"Carnicería",
 "clothes":"Ropa","shoes":"Calzado","hairdresser":"Peluquería","beauty":"Estética","car_repair":"Taller mecánico",
 "hardware":"Ferretería","florist":"Floristería","optician":"Óptica","jewelry":"Joyería","mobile_phone":"Telefonía",
 "electronics":"Electrónica","furniture":"Muebles","books":"Librería","bicycle":"Bicicletas","sports":"Deportes",
 "pet":"Mascotas","greengrocer":"Frutería","seafood":"Pescadería","alcohol":"Bodega y licores","wine":"Vinos",
 "kiosk":"Quiosco","tobacco":"Estanco","estate_agent":"Inmobiliaria","laundry":"Lavandería","chemist":"Droguería",
 "gift":"Regalos","toys":"Juguetes","car":"Concesionario","car_parts":"Recambios","tyres":"Neumáticos",
 "deli":"Delicatessen","variety_store":"Bazar","stationery":"Papelería","travel_agency":"Agencia de viajes",
 "bag":"Bolsos","fabric":"Telas","bed":"Colchones","interior_decoration":"Decoración","garden_centre":"Jardinería"}
AMEN = {"restaurant":("Restaurante","ocio"),"bar":("Bar","ocio"),"pub":("Bar","ocio"),"cafe":("Cafetería","ocio"),
 "fast_food":("Comida rápida","ocio"),"ice_cream":("Heladería","ocio"),"pharmacy":("Farmacia","negocio"),
 "clinic":("Clínica","negocio"),"dentist":("Dentista","negocio"),"doctors":("Consulta médica","negocio"),
 "veterinary":("Veterinario","negocio"),"bank":("Banco","negocio"),"cinema":("Cine","ocio"),"theatre":("Teatro","ocio"),
 "nightclub":("Discoteca","ocio"),"marketplace":("Mercado","negocio"),"fuel":("Gasolinera","negocio"),
 "car_wash":("Lavado de coches","negocio"),"car_rental":("Alquiler de coches","negocio"),
 "driving_school":("Autoescuela","negocio"),"school":("Colegio","negocio"),"kindergarten":("Guardería","negocio"),
 "post_office":("Correos","negocio"),"townhall":("Administración","negocio"),"library":("Biblioteca","ocio")}
TUR = {"hotel":("Hotel","negocio"),"hostel":("Hostal","negocio"),"guest_house":("Alojamiento","negocio"),
 "apartment":("Apartamentos","negocio"),"camp_site":("Camping","negocio"),"museum":("Museo","ocio"),
 "attraction":("Atracción","ocio"),"gallery":("Galería de arte","ocio"),"viewpoint":("Mirador","ocio"),
 "zoo":("Zoo","ocio"),"theme_park":("Parque temático","ocio")}
LEI = {"sports_centre":"Deporte","fitness_centre":"Gimnasio","golf_course":"Golf","marina":"Puerto deportivo",
 "park":"Parque","water_park":"Parque acuático","swimming_pool":"Piscina","dance":"Baile","miniature_golf":"Minigolf",
 "stadium":"Estadio","nature_reserve":"Naturaleza","beach_resort":"Playa"}
OFI = {"estate_agent":"Inmobiliaria","lawyer":"Abogado","accountant":"Gestoría","tax_advisor":"Asesoría fiscal",
 "insurance":"Seguros","architect":"Arquitecto","financial":"Servicios financieros","company":"Empresa"}

def clasificar(t):
    if "shop" in t: return SHOP.get(t["shop"], "Comercio"), "negocio"
    if t.get("amenity") in AMEN: return AMEN[t["amenity"]]
    if t.get("tourism") in TUR: return TUR[t["tourism"]]
    if t.get("leisure") in LEI: return LEI[t["leisure"]], "ocio"
    if t.get("natural") == "beach": return "Playa", "ocio"
    if "historic" in t: return "Patrimonio", "ocio"
    if "office" in t: return OFI.get(t["office"], "Oficina"), "negocio"
    if "craft" in t: return "Oficios y artesanía", "negocio"
    return None

def direccion(t):
    calle = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
    resto = " ".join(x for x in (t.get("addr:postcode"), t.get("addr:city")) if x)
    return ", ".join(x for x in (calle, resto) if x)

COCINA = {"seafood":"mariscos y pescado","fish":"pescado","tapas":"tapas","pizza":"pizza","burger":"hamburguesas",
 "spanish":"cocina española","regional":"cocina regional","mediterranean":"mediterránea","italian":"italiana",
 "chinese":"china","japanese":"japonesa","sushi":"sushi","kebab":"kebab","steak_house":"carnes","grill":"parrilla",
 "ice_cream":"helados","coffee_shop":"café","sandwich":"bocadillos","vegetarian":"vegetariana","vegan":"vegana",
 "chicken":"pollo","andalusian":"andaluza","mexican":"mexicana","indian":"india","asian":"asiática","bakery":"panadería"}

def distintivo(t):
    """Solo datos que figuran en OpenStreetMap; nada inventado."""
    partes = []
    d = (t.get("description:es") or t.get("description") or "").strip()
    if d and len(d) <= 140: partes.append(d.rstrip("."))
    cocina = [COCINA[c.strip()] for c in t.get("cuisine", "").split(";") if c.strip() in COCINA]
    if cocina: partes.append("Cocina: " + ", ".join(cocina))
    if t.get("stars"): partes.append(t["stars"] + " estrellas")
    if t.get("tourism") == "viewpoint": partes.append("Mirador con vistas")
    for k, v in (("outdoor_seating", "terraza"), ("takeaway", "para llevar"), ("delivery", "a domicilio"),
                 ("wheelchair", "accesible")):
        if t.get(k) == "yes": partes.append(v)
    if t.get("internet_access") == "wlan": partes.append("wifi")
    return "; ".join(partes)

def convertir(elementos):
    vistos, salida = set(), []
    for e in elementos:
        t = e.get("tags", {}); nombre = t.get("name", "").strip()
        cl = clasificar(t)
        if not nombre or not cl: continue
        lat = e.get("lat") or e.get("center", {}).get("lat"); lon = e.get("lon") or e.get("center", {}).get("lon")
        clave = (nombre.lower(), cl[0], direccion(t) or (round(lat or 0, 2), round(lon or 0, 2)))
        if clave in vistos: continue
        vistos.add(clave)
        web = t.get("website") or t.get("contact:website") or ""
        if web and not web.startswith("http"): web = "https://" + web
        item = {"id": f"osm:{e.get('type', 'element')}:{e.get('id', '')}", "n": nombre, "c": cl[0], "t": cl[1], "a": direccion(t),
                "p": t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or t.get("mobile") or "", "w": web,
                "s": distintivo(t),
                "h": t.get("opening_hours", ""), "e": t.get("email") or t.get("contact:email") or "", "lat": lat, "lon": lon, "f": "OpenStreetMap"}
        salida.append(item)
    return salida

def descargar():
    """Pide los datos a OpenStreetMap. Si no responde a tiempo, devuelve None (sin abortar)."""
    datos = urllib.parse.urlencode({"data": CONSULTA}).encode()
    for _ in range(3):
        for url in SERVIDORES:
            try:
                req = urllib.request.Request(url, data=datos, headers={"User-Agent": "chiclana-directorio/1.0"})
                with urllib.request.urlopen(req, timeout=240) as r:
                    return json.load(r)["elements"]
            except Exception as err:
                print("Fallo en", url, err, file=sys.stderr)
        time.sleep(30)
    return None

PARO = {"de", "del", "la", "las", "el", "los", "y", "en", "hotel", "chiclana"}
CAMPOS = ("p", "e", "w", "h", "d", "s", "m", "a", "lat", "lon")

def _tokens(texto):
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return frozenset(w for w in re.findall(r"[a-z0-9]+", t) if w not in PARO)

def _mismo(a, b):
    ka, kb = a["_k"], b["_k"]
    if not ka or not kb or len(ka & kb) / len(ka | kb) < 0.7: return False
    if a.get("t") != b.get("t"): return False
    if a.get("lat") and b.get("lat"):
        return abs(a["lat"] - b["lat"]) < 0.003 and abs(a["lon"] - b["lon"]) < 0.004
    da, db = _tokens(a.get("a", "")), _tokens(b.get("a", ""))
    if da and db and len(da & db) / min(len(da), len(db)) < 0.5: return False
    return True

def fusionar(*listas):
    """Une fuentes por orden de prioridad: la primera manda y las siguientes solo rellenan huecos."""
    todo = []
    for lista in listas:
        for it in lista:
            it = dict(it); it["_k"] = _tokens(it["n"])
            cand = [x for x in todo if _mismo(x, it)]
            if len(cand) != 1:   # ninguna o varias candidatas: se deja como ficha aparte
                todo.append(it); continue
            otro = cand[0]
            nuevo = False
            for c in CAMPOS:
                if not otro.get(c) and it.get(c): otro[c] = it[c]; nuevo = True
            if nuevo and it.get("f") and it["f"] not in otro.get("f", ""):
                otro["f"] = (otro.get("f", "") + " + " + it["f"]).strip(" +")
    for x in todo: x.pop("_k")
    return todo

def _leer(nombre, defecto):
    f = RAIZ / nombre
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else defecto

def _asegurar_ids(lista, fuente):
    """Asigna identificadores estables a las fichas que no los tengan."""
    salida = []
    for original in lista:
        item = dict(original)
        if not item.get("id"):
            base = "\\x1f".join(str(item.get(k, "") or "").strip().casefold()
                                for k in ("n", "t", "c", "a"))
            digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]
            item["id"] = f"{fuente}:{digest}"
        salida.append(item)
    return salida


def principal():
    manuales = _asegurar_ids(_leer("manuales.json", []), "manual")
    oficiales = _asegurar_ids(_leer("oficiales.json", []), "oficial")
    turismo = _asegurar_ids(_leer("turismo.json", []), "turismo")
    destacados = _leer("destacados.json", {})
    elementos = descargar()
    osm = convertir(elementos) if elementos else []
    if len(osm) >= 30:                      # descarga buena: se guarda copia para futuros fallos
        fecha = datetime.date.today().isoformat()
        copia = RAIZ / "datos" / "osm.json"
        copia.parent.mkdir(exist_ok=True)
        copia.write_text(json.dumps({"fecha": fecha, "items": osm}, ensure_ascii=False), encoding="utf-8")
    else:                                   # OpenStreetMap no respondió: se usa la última copia buena
        previa = _leer("datos/osm.json", None)
        if previa:
            osm, fecha = previa["items"], previa["fecha"]
            print(f"::warning::OpenStreetMap no respondió; se usa la copia del {fecha}")
        else:
            # Recuperación de emergencia: usar como caché los registros OSM que ya figuran
            # en el catálogo V3 publicado, sin descartar las fichas manuales ni inventar datos.
            v3_path = RAIZ / "v3" / "data.json"
            v3_data = json.loads(v3_path.read_text(encoding="utf-8")) if v3_path.exists() else {}
            prev_items = v3_data.get("items", [])
            osm_prev = [dict(x) for x in prev_items
                        if str(x.get("id", "")).startswith("osm:")
                        or "openstreetmap" in str(x.get("f", "")).casefold()
                        or "osm-extra:" in str(x.get("id", ""))]
            if len(osm_prev) >= 30:
                osm = osm_prev
                fecha = v3_data.get("actualizado", datetime.date.today().isoformat())
                print(f"::warning::Overpass no respondió; se recuperan {len(osm)} registros OSM del catálogo V3 anterior ({fecha}).")
                copia = RAIZ / "datos" / "osm.json"
                copia.parent.mkdir(exist_ok=True)
                copia.write_text(json.dumps({"fecha": fecha, "items": osm}, ensure_ascii=False), encoding="utf-8")
            else:
                sys.exit("OpenStreetMap no respondió y no hay copia local ni registros OSM recuperables en V3; se cancela la publicación para proteger el catálogo.")
    todo = fusionar(manuales, oficiales, turismo, osm)
    todo.sort(key=lambda x: x["n"].lower())
    (RAIZ / "data.json").write_text(json.dumps({"actualizado": fecha, "items": todo, "destacados": destacados},
                                               ensure_ascii=False), encoding="utf-8")
    print(len(todo), "fichas guardadas", "(sin datos de OpenStreetMap)" if not osm else "(datos de OpenStreetMap del " + fecha + ")")

if __name__ == "__main__":
    principal()
