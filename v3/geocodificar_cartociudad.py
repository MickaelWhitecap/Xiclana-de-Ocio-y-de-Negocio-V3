#!/usr/bin/env python3
"""
Geocodificación de direcciones de Xiclana con CartoCiudad (IGN/CNIG).
Solo lectura: nunca escribe en Supabase ni modifica el catálogo.
Produce CSV por ficha, CSV con candidatos e informe JSON.

Catálogo exportado:
  python v3/geocodificar_cartociudad.py --catalog catalogo.json --output revision.csv --max 20
CSV propio:
  python v3/geocodificar_cartociudad.py entrada.csv revision.csv --max 0
--max 0 procesa todas las fichas elegibles. Todas las coordenadas son propuestas y requieren revisión.
"""
import argparse
import csv
import difflib
import json
import math
import pathlib
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

BASE_URL = "https://www.cartociudad.es/geocoder/api/geocoder"
MUNICIPIO = "Chiclana de la Frontera"
MUNICIPIO_CODE = "11015"
PROVINCIA_CODE = "11"
PAUSA = 0.5
TIMEOUT = 20
MAX_CANDIDATES = 33
USER_AGENT = "Xiclana-CartoCiudad/1.0 (+https://github.com/MickaelWhitecap/Xiclana-de-Ocio-y-de-Negocio-V3)"
# Caja amplia de plausibilidad. Nunca sustituye al código/nombre oficial del municipio.
LAT_MIN, LAT_MAX = 36.25, 36.60
LON_MIN, LON_MAX = -6.38, -5.90
LAST_REQUEST = 0.0
STOP_WORDS = {
    "chiclana", "frontera", "espana", "municipio", "provincia",
    "cp", "codigo", "postal", "11130", "11138", "11139",
    "centro", "casco", "historico", "zona", "ciudad", "cercanias",
    "numero", "num", "sn", "s", "de", "la", "del", "el",
}


def normalizar(texto):
    texto = unicodedata.normalize("NFD", str(texto or ""))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", texto.lower()))


def parse_float(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def coordinates_from_point(value):
    """Extrae coordenadas solo de un punto, nunca del centro de una línea/calle."""
    if not isinstance(value, dict):
        return None, None
    lat = parse_float(value.get("lat"))
    lon = parse_float(value.get("lng", value.get("lon", value.get("long"))))
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    geom = value.get("geom")
    if isinstance(geom, str):
        match = re.fullmatch(
            r"\s*POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s*",
            geom, flags=re.I
        )
        if match:
            lon, lat = float(match.group(1)), float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    geometry = value.get("geometry")
    if isinstance(geometry, dict) and str(geometry.get("type", "")).lower() == "point":
        coords = geometry.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon, lat = parse_float(coords[0]), parse_float(coords[1])
            if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    return None, None


def unpack_records(payload):
    """Normaliza las variantes JSON usadas por candidates/find."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    if payload.get("type") == "FeatureCollection":
        return [x for x in payload.get("features", []) if isinstance(x, dict)]
    if payload.get("type") == "Feature":
        return [payload]
    for key in ("results", "candidates", "data", "features", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = unpack_records(value)
            if nested:
                return nested
    return [payload]


def as_properties(record):
    if not isinstance(record, dict):
        return {}
    props = record.get("properties")
    if isinstance(props, dict):
        merged = dict(props)
        if record.get("geometry"):
            merged["geometry"] = record["geometry"]
        return merged
    return record


def get_json(endpoint, params):
    """GET con pausa por host y reintentos limitados para fallos transitorios."""
    global LAST_REQUEST
    url = BASE_URL + "/" + endpoint + "?" + urllib.parse.urlencode(params)
    last_error = None
    for attempt in range(3):
        wait = PAUSA - (time.monotonic() - LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                raw = response.read(2_000_000)
                LAST_REQUEST = time.monotonic()
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            LAST_REQUEST = time.monotonic()
            last_error = exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = min(15, max(1, int(retry_after)))
            except (TypeError, ValueError):
                delay = 2 ** (attempt + 1)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            LAST_REQUEST = time.monotonic()
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"Falló la consulta CartoCiudad: {last_error}")


def limpiar_direccion_busqueda(direccion):
    """Quita ruido municipal/postal y normaliza abreviaturas habituales."""
    text = str(direccion or "").strip()
    text = re.sub(r"(?i)\b(?:e-?mail|correo electr[oó]nico|tel[eé]fono)\s*:?.*$", "", text)
    text = re.sub(r"(?<!\d)(11130|11138|11139)(?!\d)", " ", text)
    text = re.sub(r"(?i)\bchiclana(?:\s+de\s+la\s+frontera)?\b", " ", text)
    # No eliminar Andalucía/Cádiz de forma global: pueden formar parte de un nombre de vía.
    text = re.sub(r"(?i),\s*c[aá]diz(?:\s*,\s*(?:andaluc[ií]a|espa[nñ]a))?\s*$", " ", text)
    text = re.sub(r"(?i),\s*(?:andaluc[ií]a|espa[nñ]a)\s*$", " ", text)
    replacements = [
        (r"(?i)^\s*c\s*/\s*", "Calle "),
        (r"(?i)^\s*c\.?\s+", "Calle "),
        (r"(?i)^\s*cjon\.?\s+", "Callejón "),
        (r"(?i)^\s*(?:avda?|av\.?)\s+", "Avenida "),
        (r"(?i)^\s*pza\.?\s+", "Plaza "),
        (r"(?i)^\s*ctra\.?\s+", "Carretera "),
        (r"(?i)^\s*urb\.?\s+", "Urbanización "),
        (r"(?i)^\s*pol\.?\s+", "Polígono "),
        (r"(?i)^\s*cam\.?\s+", "Camino "),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"(?i)\b(?:s\s*/\s*n|s\.?\s*n\.?)\b", " ", text)
    text = re.sub(r"[\s,;]+", " ", text).strip(" ,;.-")
    return text


def direccion_especifica(direccion):
    """Evita consultar CartoCiudad con valores genéricos que no son direcciones."""
    text = limpiar_direccion_busqueda(direccion)
    if not text:
        return False
    tokens = address_tokens(text)
    useful = [x for x in tokens if x not in {
        "calle", "callejon", "avenida", "av", "plaza", "paseo", "carretera",
        "camino", "travesia", "ronda", "urbanizacion", "poligono", "parque",
        "comercial", "residencial",
    }]
    has_road_type = bool(re.search(
        r"(?i)\b(calle|callejon|avenida|avda|plaza|paseo|carretera|camino|"
        r"travesia|ronda|urbanizacion|poligono|ctra)\b", text
    ))
    has_number = bool(extract_house_number(text))
    return len(useful) >= 2 or (has_road_type and len(useful) >= 1) or (has_number and len(useful) >= 1)


def variantes_consulta(direccion):
    """Busca primero el portal exacto y después la vía sin número."""
    base = limpiar_direccion_busqueda(direccion)
    variants = []
    if base:
        variants.append(base)
    without_number = re.sub(
        r"(?i)\b(?:n(?:umero|[º°o.]?)|num\.?)\s*[:.]?\s*\d{1,4}[a-z]?\b",
        " ", base
    )
    without_number = re.sub(r"(?i),?\s+\d{1,4}[a-z]?\s*$", "", without_number)
    without_number = re.sub(r"(?i)\bkm\s*\d+(?:[.,]\d+)?\b", " ", without_number)
    without_number = re.sub(r"[\s,;]+", " ", without_number).strip(" ,;.-")
    if without_number and normalizar(without_number) != normalizar(base):
        variants.append(without_number)
    return list(dict.fromkeys(variants))


def consultar_candidatos(direccion, limit=MAX_CANDIDATES, municipio_filter=True):
    query = f"{direccion}, {MUNICIPIO}"
    params = {
        "q": query,
        "limit": str(min(MAX_CANDIDATES, max(1, int(limit)))),
        "countrycodes": "es",
    }
    if municipio_filter:
        params["municipio_filter"] = MUNICIPIO
    payload = get_json("candidates", params)
    return [as_properties(x) for x in unpack_records(payload)]


def consultar_find(candidate):
    ident, tipo = candidate.get("id"), candidate.get("type")
    if not ident or not tipo:
        return {}
    payload = get_json("find", {"id": str(ident), "type": str(tipo)})
    rows = [as_properties(x) for x in unpack_records(payload)]
    return rows[0] if rows else {}


def es_chiclana(candidate):
    muni = normalizar(candidate.get("muni") or candidate.get("municipality") or "")
    code = str(candidate.get("muniCode") or candidate.get("municipalityCode") or "").strip()
    prov_code = str(candidate.get("provinceCode") or "").strip()
    if code and code != MUNICIPIO_CODE:
        return False
    if prov_code and prov_code != PROVINCIA_CODE:
        return False
    return code == MUNICIPIO_CODE or muni == normalizar(MUNICIPIO)


def address_tokens(value):
    return [x for x in normalizar(value).split()
            if x not in STOP_WORDS and not x.isdigit()]


def similarity_address(source, candidate):
    left, right = address_tokens(source), address_tokens(candidate)
    if not left or not right:
        return 0.0
    a, b = " ".join(left), " ".join(right)
    sequence = difflib.SequenceMatcher(None, a, b).ratio()
    aset, bset = set(left), set(right)
    union = len(aset | bset)
    token_score = len(aset & bset) / union if union else 0.0
    containment = len(aset & bset) / min(len(aset), len(bset))
    return round(max(sequence, token_score, containment * 0.92), 4)


def extract_house_number(value):
    text = re.sub(r"(?<!\d)(11130|11138|11139)(?!\d)", " ", str(value or ""))
    patterns = (
        r"\b(?:n(?:umero|[º°o.]?)|num\.?)\s*[:.]?\s*(\d{1,4}[a-z]?)\b",
        r",\s*(\d{1,4}[a-z]?)\s*(?:,|$)",
        r"\s(\d{1,4}[a-z]?)\s*(?:,|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).lower()
    return ""


def candidate_number(candidate):
    value = candidate.get("portalNumber")
    return "" if value is None else str(value).strip().lower()


def candidate_type(candidate):
    return normalizar(candidate.get("type") or "").replace(" ", "")


def candidate_features(source_address, candidate):
    result_number = candidate_number(candidate)
    source_number = extract_house_number(source_address)
    if source_number and result_number:
        number_match = source_number == result_number
    elif source_number:
        number_match = False
    else:
        number_match = None
    lat, lon = coordinates_from_point(candidate)
    return {
        "similaridad_direccion": similarity_address(source_address, candidate.get("address", "")),
        "numero_origen": source_number,
        "numero_cartociudad": result_number,
        "numero_coincide": number_match,
        "lat": lat,
        "lon": lon,
        "es_chiclana": es_chiclana(candidate),
        "tipo_normalizado": candidate_type(candidate),
    }


def candidate_rank(candidate, features):
    """Orden interno; no es una puntuación oficial del servicio."""
    return (
        1 if features["es_chiclana"] else 0,
        1 if features["tipo_normalizado"] == "portal" else 0,
        1 if features["numero_coincide"] is True else 0,
        1 if features["numero_coincide"] is None else 0,
        1 if features["lat"] is not None and features["lon"] is not None else 0,
        features["similaridad_direccion"],
    )


def in_sanity_bounds(lat, lon):
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def is_valid_current_coordinate(item):
    lat, lon = parse_float(item.get("lat")), parse_float(item.get("lon"))
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def catalog_rows(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("El JSON exportado no contiene una lista items.")
    rows = []
    stats = {
        "fichas_en_catalogo": len(items), "excluidas_papelera": 0,
        "excluidas_no_publicadas": 0, "excluidas_sin_direccion": 0,
        "omitidas_ya_con_coordenadas_validas": 0,
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("_xiclana_deleted") or item.get("is_deleted"):
            stats["excluidas_papelera"] += 1
            continue
        if item.get("is_published") is not True:
            stats["excluidas_no_publicadas"] += 1
            continue
        if str(item.get("t") or "").strip().lower() not in ("ocio", "negocio"):
            continue
        address = str(item.get("a") or item.get("direccion") or item.get("address") or "").strip()
        if not address:
            stats["excluidas_sin_direccion"] += 1
            continue
        if is_valid_current_coordinate(item):
            stats["omitidas_ya_con_coordenadas_validas"] += 1
            continue
        rows.append({
            "id": str(item.get("id") or ""),
            "nombre": str(item.get("n") or item.get("nombre") or item.get("name") or ""),
            "direccion": address, "lat": item.get("lat", ""), "lon": item.get("lon", ""),
        })
    return rows, stats


def csv_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"id", "nombre", "direccion"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError("Faltan columnas obligatorias: " + ", ".join(missing))
        rows = list(reader)
        return rows, {"filas_csv_entrada": len(rows), "origen": "CSV proporcionado"}


def empty_result(row):
    return {
        "id": str(row.get("id") or ""), "nombre": str(row.get("nombre") or ""),
        "direccion_origen": str(row.get("direccion") or ""),
        "lat_propuesta": "", "lon_propuesta": "", "direccion_cartociudad": "",
        "tipo_cartociudad": "", "municipio_cartociudad": "", "codigo_municipio": "",
        "provincia_cartociudad": "", "codigo_postal": "", "numero_origen": "",
        "numero_cartociudad": "", "numero_coincide": "", "similitud_direccion": "",
        "estado": "", "motivo": "", "fuente": "CartoCiudad (IGN/CNIG)",
        "consulta": "", "candidatos_encontrados": 0, "id_cartociudad": "",
        "control_caja_geografica": "",
    }


def geocode_one(row):
    out = empty_result(row)
    address = out["direccion_origen"]
    if not address:
        out.update(estado="SIN_DIRECCION", motivo="La ficha no contiene dirección.")
        return out, []
    if not direccion_especifica(address):
        out.update(
            estado="DIRECCION_NO_ESPECIFICA",
            motivo="El dato de dirección es genérico, incompleto o no es una dirección postal consultable."
        )
        return out, []

    queries = variantes_consulta(address)
    candidates_by_key = {}
    query_attempts = []
    query_errors = []
    stop_search = False
    for query_index, query_text in enumerate(queries):
        for use_filter in (True, False):
            try:
                found = consultar_candidatos(query_text, municipio_filter=use_filter)
                query_attempts.append(
                    ("filtro municipal" if use_filter else "sin filtro") + ": " + query_text
                )
                for candidate in found:
                    key = (
                        str(candidate.get("id") or ""),
                        str(candidate.get("type") or ""),
                        normalizar(candidate.get("address") or ""),
                        str(candidate.get("muniCode") or ""),
                    )
                    candidates_by_key.setdefault(key, candidate)
                local_candidates = [x for x in candidates_by_key.values() if es_chiclana(x)]
                local_portals = [x for x in local_candidates if candidate_type(x) == "portal"]
                if local_portals:
                    stop_search = True
                    break
                # Si el filtro municipal devolvió cualquier entidad local, el intento sin filtro
                # para esta misma variante no añade seguridad; pasamos a la variante de vía.
                if use_filter and local_candidates:
                    break
            except Exception as exc:
                query_errors.append(f"{query_text} [{ 'filtro' if use_filter else 'sin filtro' }]: {type(exc).__name__}: {str(exc)[:180]}")
        if stop_search:
            break

    candidates = list(candidates_by_key.values())
    out["consulta"] = " || ".join(query_attempts)
    out["candidatos_encontrados"] = len(candidates)
    if not candidates:
        if query_errors:
            out.update(
                estado="ERROR_CONSULTA",
                motivo="No se obtuvieron candidatos tras los intentos alternativos. " + " | ".join(query_errors[:2])
            )
        else:
            out.update(
                estado="SIN_RESULTADO",
                motivo="CartoCiudad no devolvió candidatos ni para la dirección normalizada ni para la vía sin número."
            )
        return out, []

    candidate_rows, ranked = [], []
    for index, candidate in enumerate(candidates, 1):
        feat = candidate_features(address, candidate)
        candidate_rows.append({
            "id_ficha": out["id"], "nombre_ficha": out["nombre"],
            "direccion_origen": address, "orden_cartociudad": index,
            "id_cartociudad": candidate.get("id", ""),
            "tipo_cartociudad": candidate.get("type", ""),
            "direccion_cartociudad": candidate.get("address", ""),
            "municipio_cartociudad": candidate.get("muni", ""),
            "codigo_municipio": candidate.get("muniCode", ""),
            "provincia_cartociudad": candidate.get("province", ""),
            "codigo_provincia": candidate.get("provinceCode", ""),
            "codigo_postal": candidate.get("postalCode", ""),
            "numero_cartociudad": feat["numero_cartociudad"],
            "numero_origen": feat["numero_origen"],
            "numero_coincide": feat["numero_coincide"],
            "lat": feat["lat"] if feat["lat"] is not None else "",
            "lon": feat["lon"] if feat["lon"] is not None else "",
            "similaridad_direccion_local": feat["similaridad_direccion"],
            "es_chiclana": feat["es_chiclana"],
            "codigo_municipio_esperado": MUNICIPIO_CODE,
            "fuente": "CartoCiudad (IGN/CNIG)",
        })
        ranked.append((candidate_rank(candidate, feat), candidate, feat))

    local = [entry for entry in ranked if entry[2]["es_chiclana"]]
    if not local:
        out.update(
            estado="FUERA_MUNICIPIO",
            motivo="Ningún candidato acredita el municipio 11015 / Chiclana de la Frontera."
        )
        return out, candidate_rows

    portals = [entry for entry in local if entry[2]["tipo_normalizado"] == "portal"]
    portals.sort(key=lambda entry: entry[0], reverse=True)
    if not portals:
        best_local = sorted(local, key=lambda entry: entry[0], reverse=True)[0]
        candidate, features = best_local[1], best_local[2]
        if features["similaridad_direccion"] < 0.50:
            out.update(
                estado="SIN_COINCIDENCIA_UTIL",
                motivo="CartoCiudad devolvió entidades del municipio, pero ninguna guarda relación textual suficiente con la dirección de la ficha."
            )
            return out, candidate_rows
        geometry_note = ""
        try:
            found = consultar_find(candidate)
            geometry_note = str(found.get("geom") or found.get("geometry") or "")[:500]
        except Exception as exc:
            geometry_note = f"find_error:{type(exc).__name__}:{str(exc)[:150]}"
        out.update(
            estado="REVISION_SIN_PORTAL",
            motivo="Solo se encontró un vial/topónimo u otro elemento no puntual. No se asigna el centro de una calle como coordenada."
        )
        if geometry_note:
            out["motivo"] += " Geometría find: " + geometry_note
        out.update(
            direccion_cartociudad=candidate.get("address", ""),
            tipo_cartociudad=candidate.get("type", ""),
            municipio_cartociudad=candidate.get("muni", ""),
            codigo_municipio=candidate.get("muniCode", ""),
            provincia_cartociudad=candidate.get("province", ""),
            codigo_postal=candidate.get("postalCode", ""),
            id_cartociudad=candidate.get("id", ""),
        )
        return out, candidate_rows

    selected = next((entry for entry in portals
                     if entry[2]["lat"] is not None and entry[2]["lon"] is not None), None)
    if selected is None:
        candidate = portals[0][1]
        try:
            found = consultar_find(candidate)
            lat, lon = coordinates_from_point(found)
            if lat is not None and lon is not None:
                selected = (portals[0][0], {**candidate, **found},
                            {**portals[0][2], "lat": lat, "lon": lon})
        except Exception:
            selected = None
    if selected is None:
        out.update(
            estado="PORTAL_SIN_COORDENADAS",
            motivo="Se identificó un portal municipal, pero no se obtuvieron coordenadas puntuales."
        )
        return out, candidate_rows

    _, candidate, feat = selected
    lat, lon = feat["lat"], feat["lon"]
    number_match, similarity = feat["numero_coincide"], feat["similaridad_direccion"]
    in_bounds = in_sanity_bounds(lat, lon)
    out.update({
        "lat_propuesta": f"{lat:.8f}", "lon_propuesta": f"{lon:.8f}",
        "direccion_cartociudad": candidate.get("address", ""),
        "tipo_cartociudad": candidate.get("type", ""),
        "municipio_cartociudad": candidate.get("muni", ""),
        "codigo_municipio": candidate.get("muniCode", ""),
        "provincia_cartociudad": candidate.get("province", ""),
        "codigo_postal": candidate.get("postalCode", ""),
        "numero_origen": feat["numero_origen"],
        "numero_cartociudad": feat["numero_cartociudad"],
        "numero_coincide": "" if number_match is None else ("si" if number_match else "no"),
        "similitud_direccion": similarity, "id_cartociudad": candidate.get("id", ""),
        "control_caja_geografica": "dentro" if in_bounds else "fuera",
    })

    if not in_bounds:
        out.update(
            estado="REVISION_COORDENADAS_ANOMALAS",
            motivo="El municipio declarado coincide, pero las coordenadas quedan fuera de la caja geográfica amplia de control."
        )
    elif number_match is False:
        out.update(
            estado="REVISION_NUMERO_NO_COINCIDE",
            motivo="El portal pertenece a Chiclana, pero el número no coincide con el de la ficha."
        )
    elif similarity < 0.65:
        out.update(
            estado="REVISION_DIRECCION_POCO_SIMILAR",
            motivo="El portal está en Chiclana, pero la dirección devuelta se parece poco a la dirección de la ficha."
        )
    elif number_match is True and similarity >= 0.65:
        out.update(
            estado="PROPUESTA_ALTA_COINCIDENCIA",
            motivo="Municipio 11015 confirmado, portal puntual y número coincidente. Requiere revisión visual antes de aplicarse."
        )
    elif not feat["numero_origen"] and similarity >= 0.80:
        out.update(
            estado="PROPUESTA_REVISAR",
            motivo="Portal puntual municipal y dirección parecida; la ficha no aporta número de portal comprobable."
        )
    else:
        out.update(
            estado="REVISION_MANUAL",
            motivo="Candidato puntual dentro del municipio; falta coincidencia suficientemente sólida del número o del texto."
        )
    return out, candidate_rows


RESULT_COLUMNS = [
    "id", "nombre", "direccion_origen", "lat_propuesta", "lon_propuesta",
    "direccion_cartociudad", "tipo_cartociudad", "municipio_cartociudad",
    "codigo_municipio", "provincia_cartociudad", "codigo_postal",
    "numero_origen", "numero_cartociudad", "numero_coincide",
    "similitud_direccion", "estado", "motivo", "fuente", "consulta",
    "candidatos_encontrados", "id_cartociudad", "control_caja_geografica",
]
CANDIDATE_COLUMNS = [
    "id_ficha", "nombre_ficha", "direccion_origen", "orden_cartociudad",
    "id_cartociudad", "tipo_cartociudad", "direccion_cartociudad",
    "municipio_cartociudad", "codigo_municipio", "provincia_cartociudad",
    "codigo_provincia", "codigo_postal", "numero_cartociudad", "numero_origen",
    "numero_coincide", "lat", "lon", "similaridad_direccion_local",
    "es_chiclana", "codigo_municipio_esperado", "fuente",
]


def write_csv(path, rows, columns):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def ejecutar(rows, max_rows, output, candidates_output, report_output, source_stats):
    eligible = rows[:max_rows] if max_rows > 0 else rows
    results, candidates_all = [], []
    counts = Counter()
    total = len(eligible)
    print(f"Fichas elegibles: {len(rows)}. Se procesarán: {total}.", flush=True)
    for index, row in enumerate(eligible, 1):
        result, candidate_rows = geocode_one(row)
        results.append(result)
        candidates_all.extend(candidate_rows)
        counts[result["estado"]] += 1
        print(
            f"{index}/{total} | {result['estado']} | {result['nombre'][:60]} | "
            f"{result['direccion_origen'][:90]}",
            flush=True,
        )

    write_csv(output, results, RESULT_COLUMNS)
    if candidates_output:
        write_csv(candidates_output, candidates_all, CANDIDATE_COLUMNS)
    report = {
        "estado": "completado",
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "fuente": "CartoCiudad (IGN/CNIG)",
        "municipio": MUNICIPIO,
        "codigo_municipio_ine": MUNICIPIO_CODE,
        "solo_lectura": True,
        "escritura_supabase": False,
        "fichas_elegibles": len(rows),
        "fichas_procesadas": len(eligible),
        "candidatos_totales": len(candidates_all),
        "resultados_por_estado": dict(sorted(counts.items())),
        "origen": source_stats,
        "csv_revision": str(output),
        "csv_candidatos": str(candidates_output) if candidates_output else "",
        "criterios": {
            "municipio": "Se exige muniCode 11015 o municipio exacto Chiclana de la Frontera. También se aplica municipio_filter en la petición.",
            "coordenadas": "Solo se proponen coordenadas de portales puntuales. Nunca se toma el centro de una calle o carretera como punto del establecimiento.",
            "confianza": "CartoCiudad no devuelve actualmente una puntuación de confianza utilizable. La similaridad local es una comparación textual, no una puntuación oficial.",
            "aplicacion": "Ninguna coordenada se escribe en el catálogo. Todas requieren revisión.",
        },
    }
    pathlib.Path(report_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entrada", nargs="?", help="CSV de entrada con id,nombre,direccion.")
    parser.add_argument("salida_posicional", nargs="?", help="CSV de revisión (modo CSV).")
    parser.add_argument("--catalog", help="JSON temporal exportado con catalogo_supabase.py.")
    parser.add_argument("--output", help="CSV de propuestas por ficha.")
    parser.add_argument("--candidates-output", default="cartociudad_candidatos.csv")
    parser.add_argument("--report-output", default="cartociudad_informe.json")
    parser.add_argument("--max", type=int, default=20,
                        help="Número máximo de fichas; 0 procesa todas. Por defecto 20.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.max < 0:
        raise SystemExit("--max debe ser 0 o un entero positivo.")
    if args.catalog:
        if args.entrada or args.salida_posicional or args.output is None:
            raise SystemExit("Con --catalog indica --output y no uses rutas posicionales.")
        rows, stats = catalog_rows(args.catalog)
        output = args.output
    else:
        if not args.entrada or not (args.output or args.salida_posicional):
            raise SystemExit("Indica --catalog ... --output ... o bien entrada.csv salida.csv.")
        if args.output and args.salida_posicional:
            raise SystemExit("Usa solo una ruta de salida.")
        rows, stats = csv_rows(args.entrada)
        output = args.output or args.salida_posicional
    ejecutar(rows, args.max, output, args.candidates_output, args.report_output, stats)


if __name__ == "__main__":
    main()
