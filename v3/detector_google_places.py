#!/usr/bin/env python3
"""Detector de establecimientos que faltan en el catálogo, usando Google Places.

Uso de Google Places SOLO como detector: pregunta qué negocios hay en una zona
y los compara con el catálogo. No copia datos de Google al catálogo (sus
condiciones lo prohíben). El resultado es una lista de pistas para revisar a
mano o invitar al negocio por el portal. Solo se guarda el place_id, que
Google permite conservar.

Clave: variable de entorno GOOGLE_PLACES_API_KEY, o cabecera X-Goog-Api-Key
inyectada por el proxy (secreto de red). Nunca se escribe la clave en disco.

Ejemplo (centro de Chiclana, celdas de 250 m):
  python3 v3/detector_google_places.py --catalog catalogo.json \
      --sur 36.4120 --norte 36.4260 --oeste -6.1590 --este -6.1400 \
      --celda 250 --salida informe-places-centro.csv
"""
import argparse
import csv
import json
import math
import os
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

ENDPOINT = "https://places.googleapis.com/v1/places:searchNearby"
# Pocos campos: id, nombre, posición, dirección, tipos y estado (nivel Pro).
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.location", "places.formattedAddress",
    "places.primaryType", "places.businessStatus",
])
# Ocio y comercio de proximidad. Máximo 50 tipos por consulta.
TIPOS = [
    "restaurant", "bar", "cafe", "bakery", "meal_takeaway", "ice_cream_shop",
    "pub", "wine_bar", "night_club", "spanish_restaurant",
    "seafood_restaurant", "fast_food_restaurant", "pizza_restaurant", "coffee_shop",
    "brunch_restaurant", "breakfast_restaurant", "hamburger_restaurant",
    "clothing_store", "shoe_store", "jewelry_store", "book_store", "florist",
    "hair_care", "beauty_salon", "pharmacy", "grocery_store",
    "convenience_store", "gift_shop", "furniture_store", "hardware_store",
    "electronics_store", "pet_store", "sporting_goods_store", "liquor_store",
    "hotel", "guest_house", "gym", "dentist", "physiotherapist", "veterinary_care",
]
PALABRAS_GENERICAS = {
    "bar", "bares", "restaurante", "restaurant", "cafeteria", "cafe", "la", "el", "los",
    "las", "de", "del", "y", "the", "chiclana", "frontera", "tienda", "casa", "cerveceria",
    "taberna", "freiduria", "heladeria", "pizzeria", "peluqueria", "farmacia", "clinica",
}
MAX_LLAMADAS = 400  # tope por defecto de una ejecución
# NORMA DE MIGUEL (20-nov-2026): no gastar nada, nunca. El cupo gratuito de
# Nearby Search Pro es de 5.000 consultas al mes; nos quedamos en 4.000 para
# tener margen. El contador del mes se guarda en CONSUMO (hay que hacer commit).
TOPE_MENSUAL_GRATIS = 4000
CONSUMO = pathlib.Path(__file__).with_name("consumo_google_places.json")
CP_CHICLANA = ("11130", "11138", "11139")


def norm(value):
    value = unicodedata.normalize("NFD", str(value or "").casefold())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def palabras(value):
    return {w for w in norm(value).split() if len(w) >= 3 and w not in PALABRAS_GENERICAS}


def distancia_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parecido(nombre_a, nombre_b):
    a, b = palabras(nombre_a), palabras(nombre_b)
    if not a or not b:
        return 1.0 if norm(nombre_a) == norm(nombre_b) and norm(nombre_a) else 0.0
    juntos_a, juntos_b = "".join(sorted(a)), "".join(sorted(b))
    if juntos_a == juntos_b:
        return 1.0
    comunes = a & b
    if len(comunes) >= 2:
        return len(comunes) / min(len(a), len(b))
    # Una sola palabra en común («Santa», «Plaza») solo cuenta si es casi todo
    # el nombre de los dos lados: «El Sitio» = «Bar el Sitio», pero
    # «Farmacia La Plaza» ≠ «Cantina Plaza de Abastos».
    return len(comunes) / max(len(a), len(b))


def cargar_catalogo(path):
    fichas = []
    for x in json.loads(pathlib.Path(path).read_text(encoding="utf-8")):
        nombres = [x.get("n") or ""]
        alt = x.get("alt") or x.get("nombres_alternativos") or []
        if isinstance(alt, list):
            nombres += [a if isinstance(a, str) else (a or {}).get("nombre", "") for a in alt]
        try:
            lat, lon = float(x.get("lat")), float(x.get("lon"))
        except (TypeError, ValueError):
            lat = lon = None
        fichas.append({"id": x.get("id"), "nombres": [n for n in nombres if n],
                       "a": x.get("a") or "", "lat": lat, "lon": lon})
    return fichas


def buscar_en_catalogo(lugar, fichas):
    """Devuelve (estado, ficha). estado: 'en_catalogo', 'dudoso' o 'falta'."""
    nombre = lugar["nombre"]
    mejor, mejor_puntos = None, 0.0
    for f in fichas:
        p = max((parecido(nombre, n) for n in f["nombres"]), default=0.0)
        if p < 0.5:
            continue
        if f["lat"] is not None:
            d = distancia_m(lugar["lat"], lugar["lon"], f["lat"], f["lon"])
            if d > 400:
                continue
            p += 0.3 if d < 120 else 0.0
        if p > mejor_puntos:
            mejor, mejor_puntos = f, p
    if mejor and mejor_puntos >= 1.0:
        return "en_catalogo", mejor
    if mejor:
        return "dudoso", mejor
    return "falta", None


def consultar(clave, lat, lon, radio):
    cuerpo = json.dumps({
        "includedTypes": TIPOS, "maxResultCount": 20, "languageCode": "es",
        "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": radio}},
    }).encode()
    cabeceras = {"Content-Type": "application/json", "X-Goog-FieldMask": FIELD_MASK}
    if clave:
        cabeceras["X-Goog-Api-Key"] = clave
    req = urllib.request.Request(ENDPOINT, data=cuerpo, headers=cabeceras, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode()).get("places", [])


def rejilla(sur, norte, oeste, este, celda_m):
    dlat = celda_m / 111320
    dlon = celda_m / (111320 * math.cos(math.radians((sur + norte) / 2)))
    lat = sur + dlat / 2
    while lat < norte:
        lon = oeste + dlon / 2
        while lon < este:
            yield lat, lon
            lon += dlon
        lat += dlat


def leer_consumo():
    try:
        return json.loads(CONSUMO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_consumo(datos):
    CONSUMO.write_text(json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", required=True, help="Exportación JSON de las fichas activas")
    ap.add_argument("--sur", type=float, required=True)
    ap.add_argument("--norte", type=float, required=True)
    ap.add_argument("--oeste", type=float, required=True)
    ap.add_argument("--este", type=float, required=True)
    ap.add_argument("--celda", type=float, default=250, help="Lado de la celda en metros")
    ap.add_argument("--salida", default="informe-places.csv")
    ap.add_argument("--max-consultas", type=int, default=MAX_LLAMADAS)
    ap.add_argument("--excluir", default="",
                    help="Zona ya barrida que se salta: sur,norte,oeste,este")
    ap.add_argument("--solo-chiclana", action="store_true",
                    help="Descarta lugares cuya dirección no sea de Chiclana (el rectángulo toca San Fernando, Conil y Medina)")
    args = ap.parse_args()

    clave = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    mes = time.strftime("%Y-%m", time.gmtime())
    consumo = leer_consumo()
    usadas_mes = int((consumo.get(mes) or {}).get("nearby_search", 0))
    disponibles = TOPE_MENSUAL_GRATIS - usadas_mes
    if disponibles <= 0:
        raise SystemExit(f"Cupo gratuito agotado este mes ({usadas_mes} de {TOPE_MENSUAL_GRATIS}). No se consulta nada.")
    tope = min(args.max_consultas, disponibles)
    print(f"Consultas este mes: {usadas_mes}. Tope de esta ejecución: {tope}.", file=sys.stderr)
    fichas = cargar_catalogo(args.catalog)
    lugares, llamadas = {}, 0
    excl = [float(x) for x in args.excluir.split(",")] if args.excluir else None
    pendientes = [(lat, lon, args.celda) for lat, lon in rejilla(args.sur, args.norte, args.oeste, args.este, args.celda)
                  if not (excl and excl[0] <= lat <= excl[1] and excl[2] <= lon <= excl[3])]
    while pendientes:
        lat, lon, lado = pendientes.pop(0)
        if llamadas >= tope:
            print(f"Tope de {tope} consultas alcanzado; quedan {len(pendientes)+1} celdas.", file=sys.stderr)
            break
        radio = lado * 0.75  # el círculo cubre el cuadrado de la celda
        try:
            resultado = consultar(clave, lat, lon, radio)
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"Google respondió {exc.code}: {exc.read().decode()[:400]}")
        llamadas += 1
        consumo.setdefault(mes, {})["nearby_search"] = usadas_mes + llamadas
        guardar_consumo(consumo)
        if len(resultado) >= 20 and lado > 60:
            # Celda saturada: se divide en cuatro para no perder negocios.
            q = lado / 4
            dlat = q / 111320
            dlon = q / (111320 * math.cos(math.radians(lat)))
            for s1 in (-1, 1):
                for s2 in (-1, 1):
                    pendientes.append((lat + s1 * dlat, lon + s2 * dlon, lado / 2))
            continue
        for p in resultado:
            loc = p.get("location") or {}
            lugares[p["id"]] = {
                "place_id": p["id"], "nombre": (p.get("displayName") or {}).get("text", ""),
                "direccion": p.get("formattedAddress", ""), "tipo": p.get("primaryType", ""),
                "estado_google": p.get("businessStatus", ""),
                "lat": loc.get("latitude"), "lon": loc.get("longitude"),
            }
        time.sleep(0.1)

    filas = []
    for lugar in lugares.values():
        if lugar["lat"] is None or not (args.sur <= lugar["lat"] <= args.norte and args.oeste <= lugar["lon"] <= args.este):
            continue
        if lugar["estado_google"] == "CLOSED_PERMANENTLY":
            continue
        if args.solo_chiclana and not (
            any(cp in lugar["direccion"] for cp in CP_CHICLANA) or "chiclana" in norm(lugar["direccion"])
        ):
            continue
        estado, ficha = buscar_en_catalogo(lugar, fichas)
        filas.append({**lugar, "estado": estado,
                      "ficha_parecida": (ficha or {}).get("id", ""),
                      "nombre_ficha": ((ficha or {}).get("nombres") or [""])[0],
                      "mapa": f"https://www.google.com/maps/place/?q=place_id:{lugar['place_id']}"})
    orden = {"falta": 0, "dudoso": 1, "en_catalogo": 2}
    filas.sort(key=lambda f: (orden[f["estado"]], f["tipo"], norm(f["nombre"])))
    columnas = ["estado", "nombre", "direccion", "tipo", "estado_google", "ficha_parecida", "nombre_ficha", "mapa", "place_id", "lat", "lon"]
    with open(args.salida, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)
    resumen = {k: sum(1 for f in filas if f["estado"] == k) for k in orden}
    print(json.dumps({"consultas": llamadas, "lugares": len(filas), **resumen, "salida": args.salida}, ensure_ascii=False))


if __name__ == "__main__":
    main()
