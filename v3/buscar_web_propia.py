#!/usr/bin/env python3
"""Busca la web propia de las fichas que no tienen web y, si la encuentra, la lee.

Por qué existe (26-nov-2026, caso Greda): la lectura de webs
(rastreo_fichas_con_web.py) solo trabaja con fichas que YA tienen web. Las altas
del detector de Google, de los «dudosos» y de otras listas entran solo con
nombre y dirección (Google no deja copiar sus datos), así que nadie les buscaba
la web y se quedaban vacías aunque el negocio tenga una (gredarestaurante.com).

Cómo busca, sin gastar nada: prueba nombres de dominio probables a partir del
nombre y la categoría (greda.com, gredarestaurante.com, restaurantegreda.es,
gredachiclana.com...). Primero pregunta al DNS si el dominio existe (gratis y
rápido) y solo abre los que existen, respetando robots.txt.

Cuándo acepta una web (más estricto que la lectura normal, porque aquí la web
la hemos adivinado nosotros):
- El TEXTO de la página nombra el negocio (no basta con que el dominio lo diga).
- El texto nombra Chiclana (o sus códigos postales, Sancti Petri...).
- Y además coincide algo concreto de la ficha: su calle, su teléfono, o la
  palabra de su categoría (restaurante, bar, peluquería...).
- No es una página de dominio en venta, ni un dominio que ya use otra ficha,
  ni una cadena o portal (mismas listas que leer_web_propia.py).

Si la acepta: guarda la web en la ficha (marcada en fuentes_datos como «web
encontrada por nombre de dominio») y en la misma pasada la lee con
leer_web_propia.py para rellenar teléfono, correo, horario, descripción y redes,
y la marca verificada (igual que la lectura normal). Nunca cambia un dato que
ya existe. Cada intento se guarda en site_settings.catalogo.busqueda_web_propia
y no se repite hasta pasados REINTENTO_DIAS.
"""
import argparse, json, pathlib, re, socket, sys, tempfile, time, urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import leer_web_propia as lector
import rastreo_web_publico as rad

CLAVE_ESTADO = "busqueda_web_propia"
REINTENTO_DIAS = 60
MAX_CANDIDATOS = 24
TLDS = ("com", "es")
PALABRAS_ZONA = {"costa", "luz", "bahia", "barrosa", "labarrosa", "sancti", "santi", "petri", "novo", "poblado", "playa", "urbanizacion",
                 "urb", "centro", "poligono", "carretera", "ctra", "pinar", "cadiz", "andalucia", "spain", "espana"}
# Palabra de la categoría que suele ir en el dominio (gredarestaurante.com, barpepe.es...).
PREFIJOS_CATEGORIA = (
    ("restaur", ("restaurante",)), ("bar", ("bar", "cafebar")), ("cafeter", ("cafeteria", "cafe")),
    ("pub", ("pub",)), ("discoteca", ("discoteca",)), ("chiringuito", ("chiringuito",)),
    ("helad", ("heladeria",)), ("panader", ("panaderia",)), ("pasteler", ("pasteleria", "confiteria")),
    ("peluquer", ("peluqueria",)), ("barber", ("barberia",)), ("estetic", ("estetica",)),
    ("hotel", ("hotel",)), ("hostal", ("hostal",)), ("apartamento", ("apartamentos",)),
    ("inmobiliaria", ("inmobiliaria",)), ("clinica", ("clinica",)), ("dental", ("clinicadental", "dental")),
    ("veterin", ("veterinaria", "clinicaveterinaria")), ("fisio", ("fisioterapia", "fisio")),
    ("taller", ("talleres", "taller")), ("autoescuela", ("autoescuela",)), ("academia", ("academia",)),
    ("gimnasio", ("gimnasio", "gym")), ("farmacia", ("farmacia",)), ("optica", ("optica",)),
    ("abogad", ("abogados",)), ("asesor", ("asesoria",)), ("gestor", ("gestoria",)),
    ("floris", ("floristeria",)), ("muebles", ("muebles",)), ("ferreter", ("ferreteria",)),
    ("bodega", ("bodegas", "bodega")), ("venta", ("venta",)), ("asador", ("asador",)),
    ("marisquer", ("marisqueria",)), ("freidur", ("freiduria",)), ("pizz", ("pizzeria",)),
)
APARCADO = re.compile(r"(?i)domain (?:is )?for sale|buy this domain|dominio (?:est[aá] )?en venta|este dominio|"
                      r"parked|sedo|dan\.com|hugedomains|afternic|godaddy|domain name|coming soon|pr[oó]ximamente|"
                      r"en construcci[oó]n|under construction|cuenta suspendida|account suspended|index of /")


# Una web que nombra muchas otras ciudades suele ser de una cadena o franquicia
# (26-nov-2026: «Bubble TAI», cinco tiendas): sus teléfonos y textos no son del local.
OTRAS_CIUDADES = ("madrid", "barcelona", "sevilla", "malaga", "granada", "cordoba", "valencia", "bilbao",
                  "zaragoza", "murcia", "alicante", "huelva", "almeria", "jaen", "jerez", "algeciras",
                  "san fernando", "puerto real", "el puerto de santa maria", "conil", "vejer", "tarifa",
                  "rota", "sanlucar", "marbella", "palma", "toledo", "salamanca", "valladolid", "lisboa")
RE_FRANQUICIA = re.compile(r"(?i)franquicia|nuestras tiendas|nuestros locales|tiendas abiertas|encuentra tu tienda|"
                           r"nuestros restaurantes en")


def parece_cadena(texto):
    t = " " + rad.norm(texto) + " "
    otras = sum(1 for c in OTRAS_CIUDADES if f" {c} " in t)
    return otras >= 3 or bool(RE_FRANQUICIA.search(texto))


def ahora():
    return datetime.now(timezone.utc)


def limpiar_nombre(nombre):
    """«Greda - Restaurante en La Barrosa» -> «Greda»; quita paréntesis y sufijos societarios."""
    n = re.split(r"\s+[-|–—·:]\s+|\(", str(nombre or ""))[0]
    return re.sub(r"(?i)\b(s\.?l\.?u?\.?|s\.?a\.?|c\.?b\.?)\s*$", "", n).strip()


def tokens(nombre):
    return [t for t in lector.tokens_nombre(limpiar_nombre(nombre)) if t not in PALABRAS_ZONA]


# Tipos de local que no están en leer_web_propia.GENERICAS pero tampoco distinguen a un negocio.
GENERICAS_EXTRA = {"taperia", "cerveceria", "tapas", "gastrobar", "freiduria", "heladeria", "pizzeria", "marisqueria",
                   "pub", "taberna", "tasca", "bodeguita", "cafebar", "lounge", "grill", "food", "beach", "club",
                   "restaurant", "coffee", "shop", "store", "barberia", "salon", "spa", "studio", "estudio"}


def propias(nombre):
    return [t for t in tokens(nombre) if t not in lector.GENERICAS and t not in GENERICAS_EXTRA]


def prefijos_categoria(categoria, nombre):
    texto = rad.norm(f"{categoria} {limpiar_nombre(nombre)}")
    salida = []
    for clave, prefijos in PREFIJOS_CATEGORIA:
        if any(t.startswith(clave) for t in texto.split()):
            salida.extend(p for p in prefijos if p not in salida)
    return salida[:3]


def candidatos(ficha):
    """Dominios probables, de más a menos probable. Vacío si el nombre no tiene nada propio."""
    nombre = str(ficha.get("n") or "")
    todos, mias = tokens(nombre), propias(nombre)
    if not mias:
        return []
    base_propia = "".join(mias)
    if len(base_propia) < 4:
        return []
    bases = [base_propia, "".join(todos)] + [t for t in mias if len(mias) > 1 and len(t) >= 5][:1] \
        + ["-".join(mias), "-".join(todos)]
    bases = [b for b in dict.fromkeys(bases) if 4 <= len(b) <= 40]
    pref = prefijos_categoria(ficha.get("c"), nombre)
    salida = []

    def add(host):
        if host not in salida:
            salida.append(host)

    for tld in TLDS:  # Lo más probable primero: el nombre tal cual y con la categoría.
        for b in bases[:3]:
            add(f"{b}.{tld}")
        for p in pref:
            if not base_propia.startswith(p):
                add(f"{base_propia}{p}.{tld}")
                add(f"{p}{base_propia}.{tld}")
        add(f"{base_propia}chiclana.{tld}")
    for tld in TLDS:
        for b in bases[3:]:
            add(f"{b}.{tld}")
        for p in pref:
            add(f"{p}-{base_propia}.{tld}")
            add(f"{base_propia}-{p}.{tld}")
        add(f"{base_propia}-chiclana.{tld}")
    return salida[:MAX_CANDIDATOS]


def existe(host):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except (socket.gaierror, UnicodeError, OSError):
        return False


def calle_de(direccion):
    """Palabras propias de la calle de la ficha (para comprobar que la web es la misma)."""
    primera = rad.norm(str(direccion or "").split(",")[0])
    vacias = {"calle", "c", "avenida", "av", "avda", "plaza", "pl", "pza", "carretera", "ctra", "camino",
              "paseo", "urbanizacion", "urb", "de", "del", "la", "el", "los", "las", "s", "n", "local", "km"}
    # Las palabras de zona («Barrosa», «Sancti Petri»...) no cuentan: «Ctra. de la Barrosa»
    # coincidía con cualquier web de la zona (26-nov-2026: un alquiler vacacional «Ohana»).
    return [t for t in primera.split() if len(t) >= 4 and t not in vacias and not t.isdigit()
            and t not in PALABRAS_ZONA and t not in lector.GENERICAS]


def comprobar(ficha, url):
    """Abre la portada y decide si es la web de este negocio. Devuelve (ok, motivo)."""
    try:
        portada, final = lector.leer_pagina(url)
    except Exception:
        return False, "no_abre"
    if not portada:
        return False, "no_abre_o_robots"
    p, jsonld = portada
    host_final = lector.host_de(final)
    if any(host_final == h or host_final.endswith("." + h) for h in lector.HOSTS_NO_PROPIOS):
        return False, "redirige_a_portal"
    texto = " ".join(p.title_parts + p.headings + p.text + p.paragraphs) + " " + p.meta.get("description", "") \
        + " " + p.meta.get("og:description", "") + " " + p.meta.get("og:title", "")
    texto = " ".join(texto.split())
    if len(texto) < 80 or APARCADO.search(texto[:3000]) and not lector.menciona_chiclana(texto):
        return False, "dominio_aparcado_o_vacio"
    palabras = set(rad.norm(texto).split())
    mias = propias(ficha.get("n"))
    if not all(t in palabras for t in mias):
        return False, "no_nombra_el_negocio"
    if not lector.identifica_negocio(limpiar_nombre(ficha.get("n")), texto, ""):
        return False, "no_nombra_el_negocio"
    if not lector.menciona_chiclana(texto):
        return False, "no_menciona_chiclana"
    # Una web que se presenta (título o descripción) como un local de Chiclana no es la de
    # una franquicia aunque su grupo tenga otros locales (26-nov-2026: Greda, Grupo Feduchy).
    portada_chiclana = lector.menciona_chiclana(" ".join(p.title_parts) + " " + p.meta.get("description", "")
                                                + " " + p.meta.get("og:description", ""))
    if parece_cadena(texto) and not portada_chiclana:
        return False, "parece_cadena_o_franquicia"
    tel_ficha = set(rad.extract_phones(ficha.get("p") or ""))
    tel_web = set(lector.telefonos_de(p, jsonld))
    calle = calle_de(ficha.get("a"))
    pref = prefijos_categoria(ficha.get("c"), ficha.get("n"))
    if tel_ficha & tel_web:
        return True, "coincide_telefono"
    if calle and sum(1 for t in calle if t in palabras) >= max(1, (len(calle) + 1) // 2):
        return True, "coincide_calle"
    # Palabra entera (o comienzo de palabra si es larga): «bar» no vale dentro de «Barrosa».
    # También vale la palabra de tipo que lleva el propio nombre («Erizo Gastrobar»).
    del_nombre = [t for t in tokens(ficha.get("n")) if len(t) >= 5 and t not in propias(ficha.get("n"))]
    if any(w == pp or (len(pp) >= 6 and w.startswith(pp)) for pp in pref + del_nombre for w in palabras):
        return True, "coincide_categoria"
    return False, "nada_coincide_con_la_ficha"


def buscar(ficha, hosts_usados):
    """Devuelve {"web": url|"", "motivo": str, "probados": n, "existen": [...]} sin escribir nada."""
    lista = [h for h in candidatos(ficha) if h not in hosts_usados]
    if not lista:
        return {"web": "", "motivo": "nombre_sin_palabra_propia", "probados": 0, "existen": []}
    with ThreadPoolExecutor(max_workers=8) as pool:
        vivos = [h for h, ok in zip(lista, pool.map(existe, lista)) if ok]
    motivos = []
    for host in vivos[:6]:
        for url in (f"https://{host}/", f"http://{host}/"):
            ok, motivo = comprobar(ficha, url)
            if ok:
                return {"web": url, "motivo": "encontrada:" + motivo, "probados": len(lista), "existen": vivos}
            motivos.append(f"{host}:{motivo}")
            if motivo != "no_abre":
                break
    return {"web": "", "motivo": "no_encontrada" if not vivos else "ninguna_valida",
            "probados": len(lista), "existen": vivos, "rechazos": motivos[:6]}


def sin_web(item):
    return not str(item.get("w") or "").strip()


def cadenas(items):
    cuenta = Counter(rad.norm(limpiar_nombre(x.get("n"))) for x in items)
    return {n for n, c in cuenta.items() if n and c >= 3}


def pendientes(items, intentos, hoy=None):
    hoy = hoy or ahora()
    de_cadena = cadenas(items)
    cola = []
    for item in items:
        if not sin_web(item) or rad.norm(limpiar_nombre(item.get("n"))) in de_cadena:
            continue
        previo = intentos.get(str(item["id"]))
        if isinstance(previo, dict):
            try:
                # Si alguna web probable no abrió (caída o lenta), se reintenta a la semana.
                dias = 7 if previo.get("alguna_no_abrio") else REINTENTO_DIAS
                if datetime.fromisoformat(str(previo.get("fecha_utc"))) >= hoy - timedelta(days=dias):
                    continue
            except ValueError:
                pass
        cola.append(item)
    cola.sort(key=lambda x: str(x.get("_xiclana_updated_at") or ""), reverse=True)
    return [str(x["id"]) for x in cola]


def contador(items):
    """El mismo contador de Administración: 7 datos por ficha activa."""
    campos = {k: sum(1 for x in items if str(x.get(k) or "").strip()) for k in "apewhdr"}
    llenos = sum(campos.values())
    return {"fichas": len(items), "campos": campos, "llenos": llenos,
            "completitud_pct": round(100 * llenos / (7 * len(items)), 1) if items else 0,
            "completas_7de7": sum(1 for x in items if all(str(x.get(k) or "").strip() for k in "apewhdr")),
            "vacias_0de7": sum(1 for x in items if not any(str(x.get(k) or "").strip() for k in "apewhdr")),
            "verificadas": sum(1 for x in items if str(x.get("estado_verificacion") or "").lower() == "verificada")}


def guardar_intentos(catalog, intentos):
    with tempfile.TemporaryDirectory(prefix="xiclana-buscar-web-meta-") as tmp:
        ruta = pathlib.Path(tmp) / "meta.json"
        ruta.write_text(json.dumps({"items": [], CLAVE_ESTADO: intentos}, ensure_ascii=False), encoding="utf-8")
        catalog.sync_metadata(ruta, [CLAVE_ESTADO])


def guardar_web(catalog, base, key, ident, web, motivo):
    """Pone la web solo si la ficha sigue sin web (control de concurrencia por updated_at)."""
    filas, _ = catalog.request(base + "/listings?" + urllib.parse.urlencode(
        {"select": "id,data,is_published,is_deleted,updated_at", "id": "eq." + ident}), key)
    if not filas:
        return False
    fila = filas[0]
    datos = dict(fila.get("data") or {})
    if fila.get("is_deleted") or str(datos.get("w") or "").strip():
        return False
    datos["w"] = web
    fuentes = list(datos.get("fuentes_datos") or []) if isinstance(datos.get("fuentes_datos"), list) else []
    fuentes.append({"url": web, "tipo": "web_encontrada", "metodo": "nombre_de_dominio", "comprobacion": motivo,
                    "campos": ["web"], "fecha": ahora().date().isoformat()})
    datos["fuentes_datos"] = fuentes
    filtro = {"id": "eq." + ident, "updated_at": "eq." + fila["updated_at"] if fila.get("updated_at") else "is.null"}
    res, cab = catalog.request(base + "/listings?" + urllib.parse.urlencode(filtro), key, method="PATCH",
                               payload={"data": datos, "updated_at": ahora().isoformat()}, headers=catalog.PREFER_MINIMAL)
    return bool(catalog.affected_rows(res, cab))


def diagnosticar(fichas, limite):
    """Para webs que la lectura no pudo abrir: ¿robots.txt, cortafuegos, caída? Solo lee."""
    import urllib.error, urllib.request
    filas = []
    for f in fichas[:limite]:
        url = str(f.get("w") or "")
        partes = urllib.parse.urlsplit(url)
        origen = f"{partes.scheme}://{partes.netloc}"
        fila = {"id": f.get("id"), "web": url}
        # Siempre con nuestro nombre de robot: si una web nos bloquea, se respeta.
        for nombre, destino, agente in (("robots", origen + "/robots.txt", rad.UA), ("pagina", url, rad.UA)):
            try:
                req = urllib.request.Request(destino, headers={"User-Agent": agente, "Accept": "text/html,*/*"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    fila[nombre] = r.status
            except urllib.error.HTTPError as exc:
                fila[nombre] = exc.code
            except Exception as exc:
                fila[nombre] = type(exc).__name__ + ":" + str(exc)[:60]
        try:
            rad.CACHE_ROBOTS.clear()
            fila["permitido"] = rad.allowed(url)
        except Exception as exc:
            fila["permitido"] = "error:" + type(exc).__name__
        filas.append(fila)
        print("DIAGNOSTICO " + json.dumps(fila, ensure_ascii=False), flush=True)
    return filas


def self_test():
    greda = {"n": "Greda", "c": "Restaurante", "a": "Ctra. de la Barrosa, 109, 11139 Chiclana de la Frontera, Cádiz"}
    c = candidatos(greda)
    assert c[:2] == ["greda.com", "gredarestaurante.com"] or "gredarestaurante.com" in c[:4], c
    assert "restaurantegreda.es" in c and len(c) <= MAX_CANDIDATOS
    assert candidatos({"n": "Bar Restaurante", "c": "Bar"}) == []
    assert candidatos({"n": "Greda - Restaurante en La Barrosa", "c": "Restaurante"})[0] == "greda.com"
    assert "benitez.com" in candidatos({"n": "Bar Benitez", "c": "Bar"})
    assert "barbenitez.com" in candidatos({"n": "Bar Benitez", "c": "Bar"})
    assert calle_de("Ctra. de la Barrosa, 109, 11139 Chiclana") == []
    assert calle_de("C. Ayala, 1, 11130 Chiclana") == ["ayala"]
    assert candidatos({"n": "Costa De La Luz", "c": "Hotel"}) == []
    items = [{"id": str(i), "n": "Mercadona", "w": ""} for i in range(3)] + [
        {"id": "g", "n": "Greda", "w": "", "_xiclana_updated_at": "2026-11-23"},
        {"id": "v", "n": "Venta Bonilla", "w": "http://ventabonilla.com/"},
        {"id": "x", "n": "Ya probada", "w": ""}]
    hoy = datetime(2026, 11, 26, tzinfo=timezone.utc)
    assert pendientes(items, {"x": {"fecha_utc": "2026-11-20T00:00:00+00:00"}}, hoy) == ["g"]
    assert pendientes(items, {"x": {"fecha_utc": "2026-11-18T00:00:00+00:00", "alguna_no_abrio": True}}, hoy) == ["g", "x"]
    assert contador([{"a": "x", "p": "1"}, {}])["llenos"] == 2
    p = rad.Page()
    p.feed("<title>Greda</title><h1>Greda</h1><p>Cocina de producto en La Barrosa, Chiclana de la Frontera. "
           "Reservas en nuestro restaurante.</p>")
    orig = lector.leer_pagina
    try:
        lector.leer_pagina = lambda url: ((p, []), url)
        assert comprobar(greda, "https://gredarestaurante.com/") == (True, "coincide_categoria")
        assert comprobar({"n": "Greda", "c": "Restaurante", "a": "C. Real, 3"}, "https://x.com/") == (True, "coincide_categoria")
        assert comprobar({"n": "Picasso", "c": "Tienda", "a": "C. Real, 3"}, "https://x.com/")[1] == "no_nombra_el_negocio"
        o = rad.Page()
        o.feed("<h1>Ohana Chiclana</h1><p>Alquiler vacacional en Chiclana de la Frontera. Casa con piscina "
               "a 1,7 km de la Playa La Barrosa.</p>")
        lector.leer_pagina = lambda url: ((o, []), url)
        assert comprobar({"n": "Chiringuito Ohana La Barrosa", "c": "Restaurante",
                          "a": "Ctra. de la Barrosa, 11139 Chiclana"}, "https://ohanachiclana.com/")[0] is False
        q = rad.Page()
        q.feed("<h1>Greda</h1><p>Restaurante Greda en Madrid, cocina de producto y vinos de la tierra.</p>")
        lector.leer_pagina = lambda url: ((q, []), url)
        assert comprobar(greda, "https://greda.com/")[1] == "no_menciona_chiclana"
        e = rad.Page()
        e.feed("<title>Erizo</title><h1>Erizo Gastrobar</h1><p>Tapas creativas en Chiclana.</p>")
        lector.leer_pagina = lambda url: ((e, []), url)
        assert comprobar({"n": "Erizo Gastrobar", "c": "Bar", "a": "Av. Real, 3"}, "https://x.com/") == (True, "coincide_categoria")
        g = rad.Page()
        g.feed('<title>Greda</title><meta name="description" content="Greda es un restaurante en La Barrosa, Chiclana.">'
               "<p>Greda. Nuestros restaurantes en Conil, Vejer y Chiclana.</p>")
        lector.leer_pagina = lambda url: ((g, []), url)
        assert comprobar(greda, "https://gredarestaurante.com/")[0] is True
    finally:
        lector.leer_pagina = orig
    assert parece_cadena("Cinco tiendas abiertas en diferentes ciudades desde 2015")
    assert parece_cadena("Estamos en Madrid, Sevilla, Málaga y Chiclana")
    assert not parece_cadena("Restaurante en La Barrosa, Chiclana. Cerca de Conil.")
    print("buscar_web_propia: pruebas internas OK")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-fichas", type=int, default=2500)
    parser.add_argument("--minutos", type=float, default=300)
    parser.add_argument("--ids", default="", help="IDs concretos separados por comas.")
    parser.add_argument("--simular", action="store_true", help="Busca y comprueba, pero no guarda nada.")
    parser.add_argument("--solo-contador", action="store_true", help="Solo mide el contador de completitud.")
    parser.add_argument("--diagnosticar", type=int, default=0,
                        help="Diagnostica N webs que la lectura normal no pudo abrir (solo lee) y termina.")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    import catalogo_supabase as catalog
    import rastreo_fichas_con_web as rastreo

    inicio = time.monotonic()
    base, key = catalog.connection()
    with tempfile.TemporaryDirectory(prefix="xiclana-buscar-web-") as tmp:
        ruta = pathlib.Path(tmp) / "catalogo.json"
        catalog.export_catalog(ruta)
        data = json.loads(ruta.read_text(encoding="utf-8"))
    todas = [x for x in data.get("items", []) if isinstance(x, dict) and not x.get("_xiclana_deleted")]
    resumen = {"contador_antes": contador(todas)}
    activas = rastreo.activas(data)
    resumen["activas_sin_web"] = sum(1 for x in activas if sin_web(x))
    if args.diagnosticar:
        lecturas = data.get("lectura_web_propia") if isinstance(data.get("lectura_web_propia"), dict) else {}
        fallidas = [x for x in activas if (lecturas.get(str(x["id"])) or {}).get("motivo") in
                    ("web_no_accesible_o_robots", "error")]
        resumen["webs_no_accesibles"] = len(fallidas)
        filas = diagnosticar(fallidas, args.diagnosticar)
        resumen["diagnostico"] = {
            "robots": dict(Counter(str(f["robots"]) for f in filas)),
            "pagina": dict(Counter(str(f["pagina"])[:30] for f in filas)),
            "permitido_ahora": dict(Counter(str(f["permitido"]) for f in filas))}
        pathlib.Path("buscar-web-propia-result.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(resumen, ensure_ascii=False), flush=True)
        return
    if args.solo_contador:
        pathlib.Path("buscar-web-propia-result.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(resumen, ensure_ascii=False), flush=True)
        return
    estado = data.get(CLAVE_ESTADO)
    intentos = estado if isinstance(estado, dict) else {}
    por_id = {str(x["id"]): x for x in activas}
    hosts_usados = {lector.host_de(x.get("w")) for x in data.get("items", []) if isinstance(x, dict)} - {""}
    for x in data.get("items", []):  # webs que ya se descartaron por equivocadas
        for k in ("w_descartada", "web_descartada"):
            if isinstance(x, dict) and x.get(k):
                hosts_usados.add(lector.host_de(x.get(k)))
    cola = [x.strip() for x in args.ids.split(",") if x.strip()] if args.ids else pendientes(activas, intentos)
    resumen.update({"pendientes_al_empezar": len(cola), "fichas_probadas": 0, "webs_encontradas": 0,
                    "fichas_mejoradas": 0, "datos_anadidos": Counter(), "motivos": Counter(), "detalle": []})
    cola = cola[:args.max_fichas]
    print(json.dumps({"evento": "inicio", "pendientes": len(cola)}, ensure_ascii=False), flush=True)
    for numero, ident in enumerate(cola, 1):
        if (time.monotonic() - inicio) / 60 > args.minutos:
            break
        ficha = por_id.get(ident)
        if not ficha or not sin_web(ficha):
            continue
        fila = {"id": ident, "nombre": ficha.get("n"), "categoria": ficha.get("c")}
        try:
            r = buscar(ficha, hosts_usados)
            fila.update({k: v for k, v in r.items() if v})
            motivo = r["motivo"]
            if r["web"]:
                resumen["webs_encontradas"] += 1
                hosts_usados.add(lector.host_de(r["web"]))
                leido = lector.leer_web({**ficha, "w": r["web"]}, ())
                fila["encontrado"] = {k: v for k, v in leido["campos"].items() if v}
                fila["lectura"] = leido["motivo"]
                if leido.get("otro_municipio"):
                    fila["otro_municipio"] = leido["otro_municipio"]
                if not args.simular and guardar_web(catalog, base, key, ident, r["web"], motivo):
                    añadidos = ["w"]
                    if leido["campos"] or leido.get("otro_municipio"):
                        extra, estado_ficha = rastreo.aplicar(base, key, ident, leido["campos"], leido["paginas"],
                                                              leido.get("otro_municipio", ""))
                        añadidos += extra
                        fila["estado"] = estado_ficha
                    fila["añadidos"] = añadidos
                    resumen["fichas_mejoradas"] += 1
                    resumen["datos_anadidos"].update(rastreo.NOMBRES_CAMPO.get(k, "web") for k in añadidos)
        except Exception as exc:  # un dominio raro no debe parar la tanda
            motivo = "error"
            fila["error"] = str(exc)[:200]
        fila["motivo"] = motivo
        resumen["motivos"][motivo.split(":")[0]] += 1
        resumen["fichas_probadas"] += 1
        resumen["detalle"].append(fila)
        intentos[ident] = {"fecha_utc": ahora().isoformat(), "motivo": motivo, "web": fila.get("web", ""),
                           "alguna_no_abrio": not fila.get("web") and any(":no_abre" in r for r in fila.get("rechazos", []))}
        print(json.dumps({"n": numero, **fila}, ensure_ascii=False), flush=True)
        if not args.simular and numero % 100 == 0:  # menos guardados = menos tráfico
            guardar_intentos(catalog, intentos)
    if not args.simular:
        guardar_intentos(catalog, intentos)
        with tempfile.TemporaryDirectory(prefix="xiclana-buscar-web-") as tmp:
            ruta = pathlib.Path(tmp) / "catalogo.json"
            catalog.export_catalog(ruta)
            despues = json.loads(ruta.read_text(encoding="utf-8"))
        resumen["contador_despues"] = contador([x for x in despues.get("items", []) if isinstance(x, dict) and not x.get("_xiclana_deleted")])
    restantes = 0 if args.ids or args.simular else len(pendientes(activas, intentos))
    resumen["pendientes_al_terminar"] = restantes
    resumen["status"] = "more" if restantes and resumen["fichas_probadas"] else "done"
    resumen["datos_anadidos"] = dict(resumen["datos_anadidos"])
    resumen["motivos"] = dict(resumen["motivos"])
    pathlib.Path("buscar-web-propia-result.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    for d in resumen["detalle"]:  # lista corta para revisar a mano
        if d.get("web"):
            print("ENCONTRADA | " + " | ".join(str(x) for x in (d["id"], d.get("nombre"), d.get("categoria"), d["web"],
                  d.get("motivo") + (" | DUDOSA: se presenta en " + d["otro_municipio"] if d.get("otro_municipio") else ""), json.dumps(d.get("encontrado", {}), ensure_ascii=False)[:300])), flush=True)
    print(json.dumps({k: v for k, v in resumen.items() if k != "detalle"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
