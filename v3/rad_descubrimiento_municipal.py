#!/usr/bin/env python3
"""Descubrimiento municipal de webs: solo lectura, sin Supabase ni catálogo."""
import json
import pathlib
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import rastreo_web_publico as rad

REPORT = pathlib.Path("rad-descubrimiento-municipal.json")
DIRECTORY_HOSTS = {
    h.lower().removeprefix("www.")
    for h in rad.TRUSTED_DIRECTORY_PATHS
}
NON_OWNED = DIRECTORY_HOSTS | {
    "google.com", "bing.com", "duckduckgo.com", "facebook.com",
    "instagram.com", "linkedin.com", "youtube.com", "youtu.be",
    "tripadvisor.es", "booking.com", "airbnb.com", "idealista.com",
    "fotocasa.es", "yelp.com", "paginasamarillas.es", "qdq.com",
    "cylex.es", "informa.es", "einforma.com", "empresite.eleconomista.es",
    "actualidadsur.es", "diariodecadiz.es", "lavozdigital.es",
    "cadizturismo.com", "turismo.chiclana.es", "chiclana.es",
    "todociudad.es", "busqueda-local.es", "carta.menu",
}
TRACKING_KEYS = {"gclid", "fbclid", "mc_cid", "mc_eid"}


def host_key(url):
    host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    return host.removeprefix("www.")


def canonical_page(url):
    p = urllib.parse.urlsplit(str(url or "").strip())
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        return ""
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
             if k.lower() not in TRACKING_KEYS]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/",
                                    urllib.parse.urlencode(query), ""))


def is_owned_site(url):
    host = host_key(url)
    if not host or host in NON_OWNED:
        return False
    return not any(host.endswith("." + blocked) for blocked in NON_OWNED)


def page_pagination(url, label, host):
    p = urllib.parse.urlsplit(url)
    if (p.hostname or "").lower() != host.lower():
        return False
    q = urllib.parse.parse_qs(p.query)
    if any(k.lower() in {"p", "page", "pagina", "pag", "paged", "offset", "start"} for k in q):
        return True
    if re.search(r"/(?:page|pagina|pag)/\d+/?$", p.path, re.I):
        return True
    if re.search(r"(?:siguiente|next|anterior|prev|p[aá]gina)", rad.norm(label)):
        return True
    return rad.is_pagination_link(url, label, host)


def discover_directory_profiles():
    details = set()
    listing_pages = set()
    page_errors = []
    for seed in rad.DIRECTORY_SEEDS:
        seed_host = (urllib.parse.urlsplit(seed).hostname or "").lower()
        queue = [seed]
        visited = set()
        while queue:
            page_url = queue.pop(0)
            page_key = canonical_page(page_url)
            if not page_key or page_key in visited:
                continue
            visited.add(page_key)
            listing_pages.add(page_key)
            if not rad.allowed(page_url):
                continue
            try:
                body, final_url, _ = rad.get(page_url, 1_200_000)
                parser = rad.Page()
                parser.feed(body)
            except Exception as exc:
                page_errors.append({"url": page_url, "error": str(exc)[:220]})
                continue
            final_host = (urllib.parse.urlsplit(final_url).hostname or "").lower()
            for _, href, label in parser.links:
                target = urllib.parse.urljoin(final_url, href)
                p = urllib.parse.urlsplit(target)
                if p.scheme.lower() not in ("http", "https") or (p.hostname or "").lower() != final_host:
                    continue
                target = canonical_page(target)
                if not target:
                    continue
                if page_pagination(target, label, final_host):
                    if target not in visited:
                        queue.append(target)
                    continue
                prefixes = rad.TRUSTED_DIRECTORY_PATHS.get(final_host, ())
                if rad.is_qdq_profile_url(target) or any(p.path.startswith(prefix) for prefix in prefixes):
                    if canonical_page(target) != page_key:
                        details.add(target)
            if len(visited) % 50 == 0:
                print(json.dumps({"event": "directorios_progreso", "fuente": seed,
                                  "paginas_listado": len(visited), "perfiles": len(details)},
                                 ensure_ascii=False), flush=True)
        print(json.dumps({"event": "directorio_completado", "fuente": seed,
                          "paginas_listado": len(visited), "perfiles_unicos_acumulados": len(details)},
                         ensure_ascii=False), flush=True)
    return details, listing_pages, page_errors


def search_all_pages(engine, query):
    found = []
    seen = set()
    offset = 0
    while True:
        if engine == "ddg":
            search_url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(
                {"q": query, "s": str(offset), "dc": str(offset + 1)}
            )
        else:
            search_url = "https://www.bing.com/search?format=rss&" + urllib.parse.urlencode(
                {"q": query, "first": str(offset + 1), "count": "10"}
            )
        if not rad.allowed(search_url):
            break
        try:
            body, _, _ = rad.get(search_url, 900_000)
        except Exception:
            break
        page_links = []
        if engine == "ddg":
            parser = rad.SearchLinks()
            try:
                parser.feed(body)
            except Exception:
                break
            for raw in parser.links:
                href = urllib.parse.urljoin(search_url, raw)
                p = urllib.parse.urlsplit(href)
                if "duckduckgo.com" in (p.hostname or ""):
                    target = urllib.parse.parse_qs(p.query).get("uddg", [""])[0]
                    if target:
                        href = urllib.parse.unquote(target)
                p = urllib.parse.urlsplit(href)
                if p.scheme in ("http", "https") and "duckduckgo.com" not in (p.hostname or ""):
                    page_links.append(canonical_page(href))
        else:
            try:
                root = ET.fromstring(body)
                page_links = [canonical_page(item.findtext("link") or "")
                              for item in root.findall(".//item")]
            except Exception:
                break
        page_links = [u for u in page_links if u]
        new = [u for u in page_links if u not in seen]
        if not new:
            break
        seen.update(new)
        found.extend(new)
        offset += max(len(page_links), 10)
        if len(page_links) < 10:
            break
    return list(dict.fromkeys(found))


def physical_location_evidence(record):
    address = str(record.get("address") or "")
    n = rad.norm(address)
    return bool(re.search(r"(?<!\d)(11130|11138|11139)(?!\d)", address) or
                "chiclana de la frontera" in n)


def main():
    print(json.dumps({"event": "inicio_descubrimiento_municipal",
                      "fecha_utc": datetime.now(timezone.utc).isoformat(),
                      "fuentes_directas": len(rad.DIRECTORY_SEEDS),
                      "consultas_busqueda": len(rad.QUERIES)},
                     ensure_ascii=False), flush=True)

    directory_urls, listing_pages, errors = discover_directory_profiles()
    search_urls = set()
    search_counts = {}
    for query in rad.QUERIES:
        for engine in ("ddg", "bing"):
            try:
                results = search_all_pages(engine, query)
            except Exception as exc:
                results = []
                errors.append({"fuente": engine, "consulta": query, "error": str(exc)[:220]})
            search_counts[engine] = search_counts.get(engine, 0) + len(results)
            search_urls.update(results)
            print(json.dumps({"event": "busqueda_completada", "buscador": engine,
                              "consulta": query, "urls_unicas_consulta": len(results),
                              "urls_unicas_acumuladas": len(search_urls)},
                             ensure_ascii=False), flush=True)

    # Se analizan todas las URL de detalle descubiertas y los enlaces de búsqueda,
    # deduplicados por URL; no se altera ni exporta el catálogo maestro.
    source_urls = list(dict.fromkeys(
        list(rad.DIRECT_DETAIL_URLS) + sorted(directory_urls) + sorted(search_urls)
    ))
    establishments = {}
    websites = {}
    outside_or_unconfirmed = 0
    pages_processed = 0
    failed_pages = []
    non_business_urls = 0

    for source_url in source_urls:
        pages_processed += 1
        try:
            record = rad.extract(source_url, trusted_local=False)
        except Exception as exc:
            record = None
            failed_pages.append({"url": source_url, "error": str(exc)[:220]})
        if not record:
            outside_or_unconfirmed += 1
        elif not physical_location_evidence(record):
            outside_or_unconfirmed += 1
        else:
            name = str(record.get("name") or "").strip()
            address = str(record.get("address") or "").strip()
            key = rad.norm(name) + "|" + rad.norm(address)
            row = establishments.setdefault(key, {
                "nombre": name, "direccion": address, "telefono": record.get("phone", ""),
                "correo": record.get("email", ""), "web": record.get("website", ""),
                "horario": record.get("hours", ""), "descripcion": record.get("description", ""),
                "fuentes": [],
            })
            row["fuentes"].append(record.get("source_url") or source_url)

            candidates = []
            if record.get("website"):
                candidates.append((record["website"], "enlace_web_extraido_de_ficha"))
            source_host = host_key(record.get("source_url") or source_url)
            if is_owned_site(record.get("source_url") or source_url):
                candidates.append((record.get("source_url") or source_url, "pagina_del_propio_dominio"))

            for site_url, evidence in candidates:
                domain = host_key(site_url)
                if not is_owned_site(site_url):
                    continue
                entry = websites.setdefault(domain, {
                    "dominio": domain, "url": site_url, "establecimientos": [],
                    "evidencia": [], "estado": "identificada_no_validada_en_su_web",
                })
                if name and name not in entry["establecimientos"]:
                    entry["establecimientos"].append(name)
                if evidence not in entry["evidencia"]:
                    entry["evidencia"].append(evidence)

        if pages_processed % 50 == 0:
            print(json.dumps({"event": "analisis_progreso", "paginas_analizadas": pages_processed,
                              "fuentes_totales": len(source_urls),
                              "establecimientos_locales": len(establishments),
                              "dominios_web_identificados": len(websites)},
                             ensure_ascii=False), flush=True)

    report = {
        "estado": "barrido_completado",
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "criterio_ubicacion": "Dirección postal concreta en Chiclana acreditada por la propia página, con código postal 11130, 11138 o 11139, o mención expresa a Chiclana de la Frontera.",
        "webs_unicas_identificadas": len(websites),
        "establecimientos_con_ubicacion_confirmada": len(establishments),
        "dominios_unicos": sorted(websites),
        "detalle_webs": sorted(websites.values(), key=lambda x: x["dominio"]),
        "detalle_establecimientos": sorted(establishments.values(), key=lambda x: rad.norm(x["nombre"])),
        "fuentes_directorio": len(rad.DIRECTORY_SEEDS),
        "paginas_de_directorio_recorridas": len(listing_pages),
        "perfiles_de_directorio_identificados": len(directory_urls),
        "urls_de_busqueda_unicas": len(search_urls),
        "urls_de_busqueda_por_buscador": search_counts,
        "urls_unicas_analizadas": len(source_urls),
        "paginas_analizadas": pages_processed,
        "paginas_sin_evidencia_local_suficiente": outside_or_unconfirmed,
        "errores_consulta": len(errors) + len(failed_pages),
        "errores_directorios": errors,
        "errores_paginas": failed_pages,
        "nota": "Descubrimiento de solo lectura. No se ha consultado ni modificado Supabase. Web identificada significa dominio propio detectado en una ficha con ubicación local confirmada; la validación página a página de la web propia corresponde a la fase siguiente.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "estado", "webs_unicas_identificadas", "establecimientos_con_ubicacion_confirmada",
        "paginas_de_directorio_recorridas", "perfiles_de_directorio_identificados",
        "urls_de_busqueda_unicas", "urls_unicas_analizadas",
        "paginas_sin_evidencia_local_suficiente", "errores_consulta"
    )}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
