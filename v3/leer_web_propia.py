#!/usr/bin/env python3
"""Lectura prudente de la web propia de una ficha.

Lección del 21-nov-2026: leer todas las páginas de una web y aceptar cualquier
número o párrafo llenaba las fichas de basura (avisos de cookies, opiniones de
clientes, textos legales, números sueltos de la página, la web de una cadena).
Aquí se lee poco y se acepta solo lo que tiene forma clara de dato:

- Solo la portada y como mucho 4 páginas de contacto/horario/quiénes somos.
- La web debe ser del propio negocio: no se leen enlaces profundos de cadenas
  (repsol.es/buscador/..., hipotels.com/hoteles/...), ni portales, ni dominios
  compartidos por varias fichas, y las páginas deben nombrar el negocio y Chiclana.
- Teléfono: enlaces tel:, datos estructurados o un número junto a «Tel.»,
  «Teléfono», «Móvil», «WhatsApp»... Máximo 2 por ficha.
- Correo: enlaces mailto: o datos estructurados; nunca correos de plantilla
  ni de privacidad. Máximo 1.
- Horario: datos estructurados o una frase corta con días y horas.
- Descripción: la descripción que el propio negocio da a buscadores (meta),
  nunca un párrafo cualquiera; se descartan cookies, textos legales y opiniones.
- Redes: perfiles enlazados desde su web, uno por red.
"""
import json, re, urllib.parse

import rastreo_web_publico as rad

MAX_PAGINAS_EXTRA = 4
MAX_TELEFONOS = 2
PISTAS_CONTACTO = ("contact", "horario", "quienes", "sobre-nosotros", "nosotros", "about", "donde", "ubicacion", "localizacion")
# Hosts que no son la web propia de un negocio local (cadenas, portales, prensa...).
HOSTS_NO_PROPIOS = (
    "repsol.es", "cepsa.es", "moeve.es", "galp.es", "bp.com", "shell.es", "dia.es", "mercadona.es", "lidl.es",
    "carrefour.es", "hipotels.com", "diariodecadiz.es", "lavozdelsur.es", "andaluciainformacion.es",
    "to-focus.com", "facebook.com", "instagram.com", "tiktok.com", "google.com", "goo.gl", "linktr.ee",
    "tripadvisor.es", "tripadvisor.com", "booking.com", "thefork.es", "eltenedor.es", "glovoapp.com",
    "just-eat.es", "ubereats.com", "paginasamarillas.es", "cylex.es", "qdq.com", "todociudad.es",
    "wixsite.com", "chiclana.es", "juntadeandalucia.es", "correos.es", "caixabank.es", "bbva.es",
    "santander.com", "bancosantander.es", "unicaja.es", "cajarural.com", "ibercaja.es", "sabadell.com",
)
DIAS_EN = {"monday": "lunes", "tuesday": "martes", "wednesday": "miércoles", "thursday": "jueves",
           "friday": "viernes", "saturday": "sábado", "sunday": "domingo",
           "mo": "lunes", "tu": "martes", "we": "miércoles", "th": "jueves", "fr": "viernes", "sa": "sábado", "su": "domingo"}
ORDEN_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
RE_DIA = r"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bados?|domingos?|festivos|lun|mar|mi[eé]|jue|vie|s[aá]b|dom)"
RE_HORA = r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:h\b|horas\b)?"
DESCRIPCION_PROHIBIDA = re.compile(
    r"(?i)cookie|protecci[oó]n de datos|rgpd|lopd|aviso legal|pol[ií]tica de privacidad|ley org[aá]nica|reglamento \(ue\)|"
    r"wordpress|tema:|theme|funciona gracias|todos los derechos|copyright|©|lorem ipsum|javascript|navegador|"
    r"mi experiencia|recomiendo|estrellas|rese[ñn]a|opini[oó]n|fondo europeo|feder|femp|ayuda de la uni[oó]n|"
    r"destinatarios|responsable del tratamiento|se vende|se alquila|\bref\.|precio|€"
)
CORREO_PROHIBIDO = re.compile(r"(?i)@(?:mysite|example|domain|email|tudominio|yourdomain|wix|sentry|wixpress|godaddy)\.|"
                              r"^(?:legal|privacidad|privacy|rgpd|lopd|dpo|protecciondatos|noreply|no-reply|webmaster)@")


def host_de(url):
    return (urllib.parse.urlsplit(str(url or "")).hostname or "").lower().removeprefix("www.")


def es_web_propia(url, dominios_compartidos=()):
    """La web debe ser la portada de un dominio propio, no una página interior de otro sitio."""
    partes = urllib.parse.urlsplit(str(url or "").strip())
    host = host_de(url)
    if partes.scheme.lower() not in ("http", "https") or not host:
        return False, "web_no_valida"
    if any(host == h or host.endswith("." + h) for h in HOSTS_NO_PROPIOS):
        return False, "web_de_cadena_o_portal"
    if host in dominios_compartidos:
        return False, "dominio_compartido_por_varias_fichas"
    ruta = partes.path.strip("/")
    if ruta and ruta.lower() not in ("es", "inicio", "home", "index.html", "index.php", "es/inicio"):
        return False, "enlace_a_pagina_interior"
    return True, ""


def tokens_nombre(nombre):
    vacias = {"de", "la", "el", "los", "las", "del", "y", "en", "s", "l", "sl", "sa", "slu", "cb", "chiclana", "frontera"}
    return [t for t in rad.norm(nombre).split() if len(t) > 1 and t not in vacias]


def identifica_negocio(nombre, texto, host):
    """Al menos la mitad de las palabras propias del nombre aparecen en la web o en el dominio."""
    toks = tokens_nombre(nombre)
    if not toks:
        return False
    evidencia = set(rad.norm(texto).split())
    dominio = re.sub(r"[^a-z0-9]", "", host)
    aciertos = sum(1 for t in toks if t in evidencia or (len(t) >= 4 and t in dominio))
    return aciertos >= max(1, (len(toks) + 1) // 2)


def menciona_chiclana(texto):
    t = rad.norm(texto)
    return bool(re.search(r"\b(chiclana|11130|11138|11139|sancti petri|novo sancti)\b", t))


def telefono_valido(numero):
    n = rad.normalize_phone(numero)
    if not n or n[:3] in ("900", "901", "902", "905", "803", "806", "807"):
        return ""
    if re.search(r"(\d)\1{4,}", n) or n.endswith("0000"):
        return ""
    return n


def telefonos_de(pagina, jsonld):
    encontrados = []
    for ent in jsonld:
        for v in (ent.get("telephone") if isinstance(ent.get("telephone"), list) else [ent.get("telephone")]):
            encontrados.extend(rad.extract_phones(v or ""))
    for _c, href, _t in pagina.links:
        if str(href).lower().startswith(("tel:", "callto:")):
            encontrados.extend(rad.extract_phones(urllib.parse.unquote(str(href).split(":", 1)[1])))
        if "wa.me/" in str(href) or "api.whatsapp.com" in str(href):
            m = re.search(r"(?:wa\.me/|phone=)(\+?\d{9,12})", str(href))
            if m:
                encontrados.extend(rad.extract_phones(m.group(1)))
    texto = " ".join(" ".join(pagina.text).split())
    for m in re.finditer(r"(?i)\b(?:tel[eé]fonos?|telf?s?\.?|tlfs?\.?|tlfno\.?|tfno\.?|m[oó]vil|whatsapp|ll[aá]m[ae]nos)\s*:?\s*((?:\(?\+?34\)?[\s.-]*)?[6789](?:[\s.-]?\d){8}(?:\s*(?:[/,y–-]|ó|o)\s*(?:\(?\+?34\)?[\s.-]*)?[6789](?:[\s.-]?\d){8})?)", texto):
        encontrados.extend(rad.extract_phones(m.group(1)))
    return [x for x in dict.fromkeys(telefono_valido(x) for x in encontrados) if x]


def correos_de(pagina, jsonld, host):
    cand = []
    for ent in jsonld:
        if isinstance(ent.get("email"), str):
            cand.append(ent["email"].replace("mailto:", ""))
    for _c, href, _t in pagina.links:
        if str(href).lower().startswith("mailto:"):
            cand.append(urllib.parse.unquote(str(href)[7:].split("?", 1)[0]))
    buenos = []
    for c in cand:
        c = c.strip().lower()
        if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", c) and not CORREO_PROHIBIDO.search(c):
            buenos.append(c)
    buenos = list(dict.fromkeys(buenos))
    # Preferir el correo del propio dominio de la web.
    buenos.sort(key=lambda c: 0 if c.split("@")[1].removeprefix("www.") == host else 1)
    return buenos


def horario_jsonld(jsonld):
    partes = []
    for ent in jsonld:
        oh = ent.get("openingHoursSpecification") or ent.get("openingHours")
        for e in (oh if isinstance(oh, list) else [oh] if oh else []):
            if isinstance(e, dict):
                dias = e.get("dayOfWeek") or []
                dias = dias if isinstance(dias, list) else [dias]
                dias = [DIAS_EN.get(str(d).rsplit("/", 1)[-1].lower(), "") for d in dias]
                dias = [d for d in dias if d]
                if dias and e.get("opens") and e.get("closes"):
                    partes.append(f"{resumir_dias(dias)} {str(e['opens'])[:5]}-{str(e['closes'])[:5]}")
            elif isinstance(e, str):
                txt = e
                for en, es in sorted(DIAS_EN.items(), key=lambda x: -len(x[0])):
                    txt = re.sub(rf"(?i)\b{en}\b", es, txt)
                txt = re.sub(r"\s*,\s*", ", ", txt)
                txt = txt.replace("lunes, martes, miércoles, jueves, viernes, sábado, domingo", "lunes a domingo")
                txt = txt.replace("lunes, martes, miércoles, jueves, viernes, sábado", "lunes a sábado")
                txt = txt.replace("lunes, martes, miércoles, jueves, viernes", "lunes a viernes")
                partes.append(txt[:1].upper() + txt[1:])
    return "; ".join(dict.fromkeys(partes))[:200]


def resumir_dias(dias):
    idx = sorted({ORDEN_DIAS.index(d) for d in dias if d in ORDEN_DIAS})
    if len(idx) >= 3 and idx == list(range(idx[0], idx[-1] + 1)):
        return f"{ORDEN_DIAS[idx[0]].capitalize()} a {ORDEN_DIAS[idx[-1]]}"
    return ", ".join(ORDEN_DIAS[i] for i in idx).capitalize()


def horario_texto(pagina):
    bloques = pagina.paragraphs + pagina.headings + [" ".join(x.split()) for x in pagina.text if x.strip()]
    candidatos = []
    for b in bloques:
        b = " ".join(str(b).split())
        if not (8 <= len(b) <= 160):
            continue
        if not re.search(rf"(?i)\b{RE_DIA}\b", b) or not re.search(r"\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s*h\b", b):
            continue
        if re.search(r"@|\b\d{9}\b|\d{3}\s\d{2,3}\s\d{2,3}|\b(19|20)\d{2}\b|\bde (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b|partido|charla|jornada|evento", b, re.I):
            continue
        b = re.sub(r"(?i)^\s*(?:nuestro\s+)?horarios?\s*(?:de\s+(?:apertura|atenci[oó]n|recepci[oó]n))?\s*[:：-]?\s*", "", b)
        candidatos.append(b)
    # El bloque más completo, pero no un párrafo largo.
    return max(candidatos, key=len) if candidatos else ""


def descripcion_de(pagina, jsonld, nombre):
    opciones = [rad.textval(e.get("description")) for e in jsonld]
    opciones += [pagina.meta.get("description", ""), pagina.meta.get("og:description", "")]
    for d in opciones:
        d = " ".join(str(d or "").split())
        if not (40 <= len(d) <= 400):
            continue
        if DESCRIPCION_PROHIBIDA.search(d):
            continue
        if re.search(r"[Ѐ-ӿ֐-ۿ぀-ヿ一-鿿]", d):  # otro alfabeto
            continue
        if re.search(r"@|https?://|\b[6789]\d{2}\s?\d{3}\s?\d{3}\b", d):
            continue
        if re.search(r"(\.\.\.|…|\[…\]|\[\.\.\.\])\s*$", d):  # recortada por la plantilla
            continue
        palabras = len(d.split())
        if d.count(",") >= 5 and palabras / (d.count(",") + 1) < 4:  # lista de palabras clave
            continue
        return d
    return ""


def redes_de(pagina, host):
    por_red = {}
    for _c, href, _t in pagina.links:
        canon = rad.social_profile_url(urllib.parse.urljoin("https://" + host + "/", str(href)))
        if not canon:
            continue
        red = host_de(canon).split(".")[0]
        usuario = urllib.parse.urlsplit(canon).path.strip("/").lower().lstrip("@")
        if usuario in ("wix", "wordpress", "squarespace", "share.php", "sharer", "sharer.php", "godaddy", "webnode", "jimdo"):
            continue
        actual = por_red.get(red)
        # Mejor un nombre de página que un número interno de Facebook.
        if actual is None or (re.fullmatch(r"\d+", urllib.parse.urlsplit(actual).path.strip("/")) and not re.fullmatch(r"\d+", usuario)):
            por_red[red] = canon
    return list(por_red.values())


def leer_pagina(url):
    if not rad.allowed(url):
        return None, url
    cuerpo, final, tipo = rad.get(url)
    if "html" not in tipo and "<html" not in cuerpo[:1000].lower():
        return None, final
    p = rad.Page()
    try:
        p.feed(cuerpo)
    except Exception:
        pass
    jsonld = []
    for raw in p.jsonld:
        try:
            jsonld.extend(rad.flatten_jsonld(json.loads(raw)))
        except Exception:
            pass
    return (p, jsonld), final


def leer_web(ficha, dominios_compartidos=()):
    """Devuelve {"campos": {...}, "motivo": str, "paginas": [...]} sin escribir nada."""
    web = str(ficha.get("w") or "").strip()
    nombre = str(ficha.get("n") or "")
    ok, motivo = es_web_propia(web, dominios_compartidos)
    if not ok:
        return {"campos": {}, "motivo": motivo, "paginas": []}
    portada, final = leer_pagina(web)
    if not portada:
        return {"campos": {}, "motivo": "web_no_accesible_o_robots", "paginas": [web]}
    host = host_de(final)
    if host != host_de(web) and any(host == h or host.endswith("." + h) for h in HOSTS_NO_PROPIOS):
        return {"campos": {}, "motivo": "redirige_a_otro_sitio", "paginas": [final]}
    paginas = [(final, portada)]
    extra = []
    for _c, href, texto in portada[0].links:
        u = urllib.parse.urljoin(final, str(href)).split("#")[0]
        if host_de(u) != host or u.rstrip("/") == final.rstrip("/"):
            continue
        clave = rad.norm(urllib.parse.unquote(urllib.parse.urlsplit(u).path) + " " + texto).replace(" ", "-")
        if any(h in clave for h in PISTAS_CONTACTO) and u not in extra:
            extra.append(u)
    for u in extra[:MAX_PAGINAS_EXTRA]:
        try:
            datos, fin = leer_pagina(u)
        except Exception:
            datos = None
        if datos:
            paginas.append((fin, datos))
    texto_total = " ".join(" ".join(p.title_parts + p.headings + p.text) + " " + p.meta.get("description", "") for _u, (p, _j) in paginas)
    if not identifica_negocio(nombre, texto_total, host):
        return {"campos": {}, "motivo": "la_web_no_nombra_el_negocio", "paginas": [u for u, _ in paginas]}
    if not menciona_chiclana(texto_total) and not menciona_chiclana(str(ficha.get("a") or "")):
        return {"campos": {}, "motivo": "la_web_no_menciona_chiclana", "paginas": [u for u, _ in paginas]}
    if not menciona_chiclana(texto_total):
        # La web no nombra Chiclana: solo es aceptable si su teléfono coincide con el de la ficha.
        tel_ficha = set(rad.extract_phones(ficha.get("p") or ""))
        tel_web = {t for _u, (p, j) in paginas for t in telefonos_de(p, j)}
        if not (tel_ficha & tel_web):
            return {"campos": {}, "motivo": "la_web_no_menciona_chiclana", "paginas": [u for u, _ in paginas]}
    p0, j0 = portada
    tels, correos, horario, redes = [], [], "", []
    for _u, (p, j) in paginas:
        tels += telefonos_de(p, j)
        correos += correos_de(p, j, host)
        horario = horario or horario_jsonld(j) or horario_texto(p)
        redes += [r for r in redes_de(p, host) if r not in redes]
    campos = {
        "p": list(dict.fromkeys(tels))[:MAX_TELEFONOS],
        "e": (list(dict.fromkeys(correos)) or [""])[0],
        "h": horario,
        "d": descripcion_de(p0, j0, nombre),
        "r": redes_de_unicas(redes),
    }
    return {"campos": campos, "motivo": "leida", "paginas": [u for u, _ in paginas]}


def redes_de_unicas(redes):
    por_red = {}
    for r in redes:
        red = host_de(r).split(".")[0]
        por_red.setdefault(red, r)
    return list(por_red.values())


def completar(ficha_data, campos):
    """Rellena solo huecos. Devuelve (datos_nuevos, lista_de_campos_añadidos)."""
    nuevo = dict(ficha_data)
    añadidos = []
    actuales = rad.extract_phones(nuevo.get("p") or "")
    if campos.get("p"):
        extra = [t for t in campos["p"] if t not in actuales][:max(0, MAX_TELEFONOS - len(actuales))]
        if extra:
            nuevo["p"] = " / ".join(([str(nuevo.get("p")).strip()] if actuales else []) + extra)
            añadidos.append("p")
    for k in ("e", "h", "d"):
        if campos.get(k) and not str(nuevo.get(k) or "").strip():
            nuevo[k] = campos[k]
            añadidos.append(k)
    if campos.get("r"):
        valor, nuevas = rad.merge_social_value(nuevo.get("r"), campos["r"])
        if nuevas:
            nuevo["r"] = valor
            añadidos.append("r")
    return nuevo, añadidos


def self_test():
    assert es_web_propia("https://www.repsol.es/buscador-eess/cadiz/x/")[0] is False
    assert es_web_propia("https://www.hipotels.com/hoteles/barrosapalace/")[0] is False
    assert es_web_propia("http://www.ventabonilla.com/")[0] is True
    assert es_web_propia("https://x.es/es/")[0] is True
    assert es_web_propia("https://x.es/carta/")[1] == "enlace_a_pagina_interior"
    assert es_web_propia("https://x.es", {"x.es"})[0] is False
    assert telefono_valido("620000000") == "" and telefono_valido("+34 956 40 63 99") == "956406399"
    assert telefono_valido("900118866") == ""
    p = rad.Page()
    p.feed('<p>Tlf: 617 60 38 15 - 956 53 08 64</p><p>Ref. 817808080 803581780</p><a href="tel:630348717">x</a>')
    assert telefonos_de(p, []) == ["630348717", "617603815", "956530864"], telefonos_de(p, [])
    p = rad.Page()
    p.feed('<meta name="description" content="Este sitio usa Cookies propias que nos ayudan a mejorar el funcionamiento de la web.">')
    assert descripcion_de(p, [], "x") == ""
    p = rad.Page()
    p.feed('<meta name="description" content="Disfruta de variada comida casera en un ambiente acogedor. Ven a probar nuestros vinos locales.">')
    assert descripcion_de(p, [], "x").startswith("Disfruta")
    p = rad.Page()
    p.feed("<p>Horario: Lunes a domingo de 7:00 a 23:00</p><p>El próximo lunes, 7 de noviembre, a partir de las 9:15 horas, charla.</p>")
    assert horario_texto(p) == "Lunes a domingo de 7:00 a 23:00", horario_texto(p)
    assert horario_jsonld([{"openingHours": "Mo-Su 12:00-16:00"}]) == "Lunes-domingo 12:00-16:00"
    assert horario_jsonld([{"openingHours": ["Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday 12:00-16:00"]}]) == "Lunes a domingo 12:00-16:00"
    p = rad.Page()
    p.feed('<meta name="description" content="LM INMOBILIARIA - Chiclana con multitud de propiedades, pisos y casas en toda la provincia de Cád...">')
    assert descripcion_de(p, [], "x") == ""
    p = rad.Page()
    p.feed('<meta name="description" content="clinica veterinaria chiclana, clinica veterinaria, veterinarios chiclana, rocio, clinica en la barrosa, veterinarios en la barrosa">')
    assert descripcion_de(p, [], "x") == ""
    p = rad.Page()
    p.feed('<a href="https://www.tiktok.com/@wix">t</a><a href="https://www.tiktok.com/@minegocio">t</a>')
    assert redes_de(p, "x.es") == ["https://www.tiktok.com/@minegocio"], redes_de(p, "x.es")
    assert horario_jsonld([{"openingHoursSpecification": [{"dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "opens": "09:00", "closes": "21:00"}]}]) == "Lunes a viernes 09:00-21:00"
    p = rad.Page()
    p.feed('<a href="https://facebook.com/203330216480504">f</a><a href="https://facebook.com/AgricentroGarola/">f</a><a href="https://www.instagram.com/wix/">i</a><a href="https://www.facebook.com/sharer.php?u=x">s</a>')
    assert redes_de(p, "x.es") == ["https://www.facebook.com/AgricentroGarola/"], redes_de(p, "x.es")
    p = rad.Page()
    p.feed('<a href="mailto:info@mysite.com">a</a><a href="mailto:legal@viajes.com">b</a><a href="mailto:hola@gmail.com">c</a><a href="mailto:info@viajes.com">d</a>')
    assert correos_de(p, [], "viajes.com") == ["info@viajes.com", "hola@gmail.com"]
    assert identifica_negocio("Venta Bonilla", "Restaurante Venta Bonilla en Chiclana", "ventabonilla.com")
    assert not identifica_negocio("Sushi Toqui", "Empresa de diseño web", "to-focus.com")
    nuevo, añ = completar({"p": "+34 956 53 08 64", "e": "", "h": "x", "d": "", "r": ""},
                          {"p": ["956530864", "617603815", "644276888"], "e": "a@b.es", "h": "y", "d": "Desc", "r": ["https://www.instagram.com/a/"]})
    assert nuevo["p"] == "+34 956 53 08 64 / 617603815" and nuevo["h"] == "x" and añ == ["p", "e", "d", "r"], (nuevo, añ)
    print("leer_web_propia: pruebas internas OK")


if __name__ == "__main__":
    self_test()
