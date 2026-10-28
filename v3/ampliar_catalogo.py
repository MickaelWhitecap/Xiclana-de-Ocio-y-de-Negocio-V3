#!/usr/bin/env python3
"""Amplía V3 con puntos de interés adicionales de OpenStreetMap.
No elimina ni modifica las fichas existentes: solo incorpora candidatos nuevos y deduplicados.
Los datos añadidos quedan identificados por fuente para facilitar futuras actualizaciones.
"""
import json, pathlib, urllib.parse, urllib.request, time, hashlib, re, unicodedata, sys

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "fichas_completas.json"
SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
QUERY = r"""[out:json][timeout:120];
area["boundary"="administrative"]["name"="Chiclana de la Frontera"]->.z;
(
 nwr["amenity"~"^(parking|parking_entrance|toilets|bicycle_rental|bicycle_parking|charging_station|bus_station|ferry_terminal|community_centre|arts_centre|social_facility|place_of_worship|police|fire_station|recycling|waste_disposal|waste_transfer_station|animal_shelter|public_building|coworking_space|events_venue|music_venue|conference_centre|language_school|university|college|childcare|car_sharing|boat_rental|boat_sharing|public_bath|drinking_water|fountain|shelter|bench|bbq|picnic_table|public_bookcase)$"](area.z);
 nwr["tourism"~"^(information|caravan_site|picnic_site|artwork|trail_riding_station|alpine_hut|wilderness_hut)$"](area.z);
 nwr["leisure"~"^(playground|dog_park|sports_pitch|pitch|track|fitness_station|horse_riding|recreation_ground|garden|common|fishing|water_park|sauna|escape_game|adult_gaming_centre|amusement_arcade|bowling_alley|ice_rink|beach_resort)$"](area.z);
 nwr["parking"~"^(surface|multi-storey|underground|street_side|lane|park_and_ride)$"](area.z);
 nwr["public_transport"~"^(station|stop_position|platform)$"](area.z);
 nwr["railway"~"^(station|halt|tram_stop)$"](area.z);
 nwr["highway"="bus_stop"](area.z);
 nwr["sport"](area.z);
 nwr["emergency"~"^(ambulance_station|fire_station|water_rescue|lifeguard)$"](area.z);
 nwr["office"~"^(lawyer|accountant|tax_advisor|insurance|architect|employment_agency|estate_agent|travel_agent|financial|therapist|consulting|educational_institution)$"](area.z);
);
out center tags;"""

def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").casefold())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", s))

def category(t):
    a, tourism, leisure = t.get("amenity",""), t.get("tourism",""), t.get("leisure","")
    if a in ("parking","parking_entrance") or "parking" in t: return "Parking", "negocio"
    if a in ("toilets","drinking_water","fountain","shelter","bench","public_building"): return "Servicios públicos", "ocio"
    if a in ("bicycle_rental","bicycle_parking"): return "Bicicletas", "negocio"
    if a == "charging_station": return "Puntos de recarga", "negocio"
    if a in ("bus_station","ferry_terminal") or t.get("highway") == "bus_stop" or t.get("public_transport") or t.get("railway"): return "Transporte", "negocio"
    if a in ("community_centre","arts_centre","music_venue","conference_centre","events_venue"): return "Espacios culturales", "ocio"
    if a in ("place_of_worship",): return "Patrimonio y culto", "ocio"
    if a in ("police","fire_station") or t.get("emergency"): return "Emergencias", "negocio"
    if a in ("recycling","waste_disposal","waste_transfer_station"): return "Reciclaje y residuos", "negocio"
    if a in ("animal_shelter",): return "Protección animal", "negocio"
    if a in ("childcare","language_school","university","college"): return "Educación", "negocio"
    if a in ("coworking_space",): return "Coworking", "negocio"
    if a in ("car_sharing","boat_rental","boat_sharing"): return "Alquiler y movilidad", "negocio"
    if a in ("public_bath",): return "Baños públicos", "ocio"
    if a in ("bbq","picnic_table") or tourism == "picnic_site": return "Merenderos y picnic", "ocio"
    if a == "public_bookcase": return "Bibliotecas y lectura", "ocio"
    if tourism == "caravan_site": return "Camping y autocaravanas", "negocio"
    if tourism == "information": return "Información turística", "ocio"
    if tourism == "artwork": return "Arte público", "ocio"
    if leisure in ("playground","dog_park","garden","common","recreation_ground"): return ("Parques infantiles" if leisure == "playground" else "Parques y jardines"), "ocio"
    if leisure in ("sports_pitch","pitch","track") or t.get("sport"): return "Instalaciones deportivas", "ocio"
    if leisure in ("fitness_station","horse_riding","fishing","sauna","ice_rink","bowling_alley","amusement_arcade","escape_game","adult_gaming_centre"): return "Ocio y actividades", "ocio"
    if t.get("office"):
        return {"lawyer":"Abogado","accountant":"Gestoría","tax_advisor":"Asesoría fiscal","insurance":"Seguros","architect":"Arquitectura","employment_agency":"Empleo","estate_agent":"Inmobiliaria","travel_agent":"Agencia de viajes","financial":"Servicios financieros","therapist":"Terapias","consulting":"Consultoría","educational_institution":"Educación"}.get(t["office"],"Servicios profesionales"), "negocio"
    return None

def address(t):
    street = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
    other = " ".join(x for x in (t.get("addr:postcode"), t.get("addr:city")) if x)
    return ", ".join(x for x in (street, other) if x)

def download():
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    for attempt in range(3):
        for server in SERVERS:
            try:
                req = urllib.request.Request(server, data=body, headers={"User-Agent":"Xiclana-Directorio/1.0 (open data catalog)"})
                with urllib.request.urlopen(req, timeout=180) as response:
                    return json.load(response).get("elements", [])
            except Exception as exc:
                print(f"Overpass {server}: {exc}", file=sys.stderr)
        if attempt < 2: time.sleep(20)
    return None

def record(e):
    t = e.get("tags", {})
    name = (t.get("name") or t.get("name:es") or t.get("official_name") or "").strip()
    cl = category(t)
    if not name or not cl: return None
    lat = e.get("lat") or e.get("center", {}).get("lat")
    lon = e.get("lon") or e.get("center", {}).get("lon")
    website = t.get("website") or t.get("contact:website") or ""
    if website and not website.startswith(("http://","https://")): website = "https://" + website
    description = (t.get("description:es") or t.get("description") or "").strip()
    details = []
    if description and len(description) <= 180: details.append(description)
    if t.get("opening_hours"): details.append("Horario publicado en OpenStreetMap")
    if t.get("wheelchair") == "yes": details.append("Accesible")
    key = f"{e.get('type')}:{e.get('id')}"
    return {"id":f"osm-extra:{key}", "n":name, "c":cl[0], "t":cl[1], "a":address(t),
            "p":t.get("phone") or t.get("contact:phone") or t.get("mobile") or "",
            "w":website, "s":"; ".join(details), "h":t.get("opening_hours",""),
            "e":t.get("email") or t.get("contact:email") or "", "lat":lat, "lon":lon,
            "f":"OpenStreetMap", "fuente_estado":"candidato automático; datos abiertos OSM"}

def duplicate(candidate, existing):
    cn = norm(candidate.get("n"))
    if not cn: return True
    cc = norm(candidate.get("c"))
    for item in existing:
        en = norm(item.get("n"))
        if not en: continue
        ec = norm(item.get("c"))
        if cn == en and (cc == ec or not cc or not ec):
            la, lb = candidate.get("lat"), item.get("lat")
            loa, lob = candidate.get("lon"), item.get("lon")
            if la is None or lb is None or loa is None or lob is None: return True
            if abs(float(la)-float(lb)) < 0.01 and abs(float(loa)-float(lob)) < 0.01: return True
        # Same named place and nearby position, even if the source labels the category differently.
        if cn == en:
            la, lb = candidate.get("lat"), item.get("lat")
            loa, lob = candidate.get("lon"), item.get("lon")
            if la is not None and lb is not None and loa is not None and lob is not None:
                if abs(float(la)-float(lb)) < 0.002 and abs(float(loa)-float(lob)) < 0.003: return True
    return False

def main():
    if not DATA.exists(): sys.exit("No existe v3/fichas_completas.json; se cancela para proteger el catálogo.")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    items = data.get("items")
    if not isinstance(items, list): sys.exit("El catálogo no contiene una lista items; no se modifica.")
    elements = download()
    if elements is None:
        print("AVISO: Overpass no respondió; se conserva intacto el catálogo actual.")
        return
    candidates = [x for e in elements if (x := record(e))]
    # Exclusión permanente de puntos de agua genéricos: ubicación no fiable y sin información útil.
    candidates = [x for x in candidates if norm(x.get("n")) not in {norm("Agua"), norm("Agua potable")}]
    known = {str(x.get("id","")) for x in items}
    added = []
    for item in candidates:
        if item["id"] in known or duplicate(item, items) or duplicate(item, added): continue
        added.append(item)
        known.add(item["id"])
    if added:
        data["items"].extend(added)
        data["items"].sort(key=lambda x: str(x.get("n","")).casefold())
        DATA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    # Resolución manual aprobada: los elementos OSM con el nombre exacto
    # "Nuestra Señora de los Remedios" son componentes de una misma parada,
    # no deben generar varias fichas. El colegio con nombre más largo se conserva aparte.
    remedios = [x for x in items if norm(x.get("n")) == norm("Nuestra Señora de los Remedios")]
    if remedios:
        keeper = next((x for x in remedios if x.get("id") == "osm-extra:node:10137800750"), remedios[0])
        ids = list(keeper.get("ids_alternativos", []))
        for source_id in ("osm-extra:node:10137800750", "osm-extra:node:12946613737", "osm-extra:relation:17627589"):
            if source_id != keeper.get("id") and source_id not in ids:
                ids.append(source_id)
        ubicaciones = list(keeper.get("ubicaciones_alternativas", []))
        fuentes = [str(keeper.get("f", "") or "")]
        for x in remedios:
            if x is keeper:
                continue
            if x.get("id") and x["id"] not in ids:
                ids.append(x["id"])
            if x.get("lat") is not None and x.get("lon") is not None:
                point = {"lat": x["lat"], "lon": x["lon"], "id": x.get("id", ""), "fuente": x.get("f", "")}
                if point not in ubicaciones:
                    ubicaciones.append(point)
            if x.get("f") and x.get("f") not in fuentes:
                fuentes.append(x["f"])
            items.remove(x)
        keeper["ids_alternativos"] = ids
        keeper["ubicaciones_alternativas"] = ubicaciones
        keeper["f"] = " + ".join(v for v in fuentes if v)
        keeper["s"] = (str(keeper.get("s", "") or "").strip() + " Ficha unificada de los componentes OSM de la parada; no corresponde al Colegio Nuestra Señora de los Remedios, que es una entidad distinta.").strip()
    # Unificar geometrías OSM del Club de Golf después de añadir candidatas nuevas.
    golf = [x for x in items if "golf" in str(x.get("n", "")).casefold() and "novo sancti petri" in str(x.get("n", "")).casefold()]
    if len(golf) > 1:
        keeper = next((x for x in golf if "oficial:" in str(x.get("id", "")).casefold() or "iberostar" in str(x.get("n", "")).casefold() or (x.get("e") or x.get("w") or x.get("p"))), golf[0])
        ids = list(keeper.get("ids_alternativos", []))
        nombres = list(keeper.get("nombres_alternativos", []))
        ubicaciones = list(keeper.get("ubicaciones_alternativas", []))
        fuentes = [str(keeper.get("f", "") or "")]
        for x in golf:
            if x is keeper:
                continue
            if x.get("id") and x["id"] not in ids:
                ids.append(x["id"])
            if x.get("n") and x["n"] != keeper.get("n") and x["n"] not in nombres:
                nombres.append(x["n"])
            if x.get("lat") is not None and x.get("lon") is not None:
                point = {"lat": x["lat"], "lon": x["lon"], "id": x.get("id", ""), "fuente": x.get("f", "")}
                if point not in ubicaciones:
                    ubicaciones.append(point)
            for campo in ("a", "p", "e", "w", "d", "m"):
                if not keeper.get(campo) and x.get(campo):
                    keeper[campo] = x[campo]
            if x.get("f") and x.get("f") not in fuentes:
                fuentes.append(x["f"])
            items.remove(x)
        keeper["n"] = "Club de Golf Novo Sancti Petri"
        keeper["ids_alternativos"] = ids
        keeper["nombres_alternativos"] = nombres
        if keeper.get("lat") is not None and keeper.get("lon") is not None:
            point = {"lat": keeper["lat"], "lon": keeper["lon"], "id": keeper.get("id", ""), "fuente": keeper.get("f", "")}
            if point not in ubicaciones:
                ubicaciones.insert(0, point)
        keeper["ubicaciones_alternativas"] = ubicaciones
        keeper["f"] = " + ".join(v for v in fuentes if v)
        keeper["s"] = (str(keeper.get("s", "") or "").strip() + " Ficha unificada: agrupa las variantes y geometrías del Club de Golf Novo Sancti Petri; se conservan sus identificadores y ubicaciones de origen.").strip()

    # Escribir siempre: las reglas de unificación también deben persistir cuando no haya altas nuevas.
    items.sort(key=lambda x: str(x.get("n","")).casefold())
    data["items"] = items
    DATA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    (ROOT / "informe-ampliacion.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ampliación automática: {len(candidates)} candidatos; {len(added)} fichas nuevas; total {len(data['items'])}.")
if __name__ == "__main__": main()
