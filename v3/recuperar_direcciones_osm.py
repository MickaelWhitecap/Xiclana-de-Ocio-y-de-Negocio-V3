#!/usr/bin/env python3
"""Genera propuestas de dirección usando exclusivamente la extracción OSM ya archivada."""
import json, re
from datetime import datetime, timezone
from pathlib import Path

CATALOG = Path(__file__).resolve().parent / "fichas_completas.json"
KEYS = ("addr:full", "addr:street", "addr:housenumber", "addr:place",
        "addr:postcode", "addr:city", "addr:suburb", "addr:district",
        "addr:province", "addr:state", "addr:unit", "addr:floor")

def osm_id(value):
    p = str(value or "").split(":")
    if len(p) == 3 and p[0] in {"osm", "osm-extra"} and p[1] in {"node", "way", "relation"} and p[2].isdigit():
        return f"{p[1]}:{p[2]}"
    return None

def address(tags):
    if tags.get("addr:full"):
        return tags["addr:full"].strip()
    street = tags.get("addr:street") or tags.get("addr:place")
    number = tags.get("addr:housenumber")
    main = f"{street.strip()}, {number.strip()}" if street and number else (street.strip() if street else "")
    extra = [f"{label} {tags[key].strip()}" for key, label in (
        ("addr:unit", "local"), ("addr:floor", "planta"),
        ("addr:postcode", "CP"), ("addr:city", "localidad"),
        ("addr:suburb", "zona"), ("addr:district", "distrito")
    ) if tags.get(key)]
    return ", ".join(x for x in (main, *extra) if x)

def main():
    if not CATALOG.is_file():
        raise SystemExit("No existe catálogo maestro.")
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit("Catálogo inválido.")
    extraction = data.get("osm_extraccion_inicial") or {}
    objects = extraction.get("objetos")
    if not isinstance(objects, list) or len(objects) != 132875:
        raise SystemExit("No existe una extracción OSM completa verificada dentro del catálogo maestro; no se consulta otra vez Overpass.")
    by_id = {}
    for obj in objects:
        key = f'{obj.get("type")}:{obj.get("id")}'
        by_id[key] = obj.get("tags") or {}
    pending = [x for x in items if not x.get("_xiclana_deleted") and not x.get("deleted") and not x.get("eliminado") and not str(x.get("a") or "").strip()]
    proposals, not_osm, not_found, no_address = [], [], [], []
    consulted = 0
    for item in pending:
        key = osm_id(item.get("id"))
        if not key:
            not_osm.append({"id": item.get("id"), "nombre": item.get("n"), "categoria": item.get("c")})
            continue
        consulted += 1
        tags = by_id.get(key)
        if tags is None:
            not_found.append({"id": item.get("id"), "nombre": item.get("n")})
            continue
        # Un CP o una localidad aislados no constituyen una dirección utilizable.
        # Exigimos una dirección completa, calle o lugar identificado.
        if not any(tags.get(k) for k in ("addr:full", "addr:street", "addr:place")):
            no_address.append({"id": item.get("id"), "nombre": item.get("n")})
            continue
        selected = {k: tags[k] for k in KEYS if tags.get(k)}
        if not selected:
            no_address.append({"id": item.get("id"), "nombre": item.get("n")})
            continue
        proposals.append({
            "id_ficha": item.get("id"),
            "nombre": item.get("n"),
            "direccion_propuesta": address(tags) or None,
            "etiquetas_osm": selected,
            "url_osm": f"https://www.openstreetmap.org/{key.replace(':', '/', 1)}",
            "estado": "pendiente_revision",
            "fuente_extraccion": extraction.get("fecha_extraccion_utc"),
        })
    # Direcciones contrastadas en fuentes oficiales o fichas comerciales verificadas.
    # Se añaden como propuestas: nunca modifican una ficha ni se publican automáticamente.
    external_candidates = [
        {
            "id_ficha": "oficial:5eb71868a9d4c10c1bfa",
            "direccion_propuesta": "Calle El Choco, s/n, 11130 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Ficha comercial de Waterman School y web oficial",
            "source_url": "https://www.watermanschool.com/",
            "nota": "Ubicación comercial en la zona de Playa La Barrosa / Novo Sancti Petri.",
        },
        {
            "id_ficha": "oficial:81e45eab4a9f35e54e02",
            "direccion_propuesta": "Avenida Octavio Augusto, s/n, Urbanización Novo Sancti Petri, 11130 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Web oficial de Valentín Sancti Petri",
            "source_url": "https://www.valentinsanctipetri.com/es/ubicacion/",
            "nota": "Dirección postal oficial del hotel donde se encuentra el spa.",
        },
        {
            "id_ficha": "oficial:94abed2977cbdf584917",
            "direccion_propuesta": "Polígono Industrial El Torno, Avenida de los Descubrimientos, 107D, 11130 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Turismo de Chiclana y Junta de Andalucía",
            "source_url": "https://turismo.chiclana.es/detalle-de-recurso/multicines-las-salinas/",
            "nota": "Dirección publicada en el directorio oficial de recursos turísticos.",
        },
        {
            "id_ficha": "oficial:69c0d1be602b8dfca6b3",
            "direccion_propuesta": "Poblado de Sancti Petri, s/n, 11139 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Agencia Pública de Puertos de Andalucía",
            "source_url": "https://www.puertosdeandalucia.es/puertos/puertos/cadiz/puerto-de-sancti-petri",
            "nota": "Dirección postal general del puerto deportivo.",
        },
        {
            "id_ficha": "osm:relation:21447370",
            "direccion_propuesta": "Calle Marco Aurelio, s/n, Urbanización Loma de Sancti Petri, 11130 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Web oficial de Sancti Petri Hills Golf",
            "source_url": "https://sanctipetrihillsgolf.com/es/contacto/",
            "url_osm": "https://www.openstreetmap.org/relation/21447370",
            "nota": "Dirección publicada por el propio club de golf.",
        },
        {
            "id_ficha": "osm:node:1568359220",
            "direccion_propuesta": "Calle Jardines, 14, 11130 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Web oficial de Farmacia La Banda",
            "source_url": "https://farmacialabanda.com/contacto/",
            "url_osm": "https://www.openstreetmap.org/node/1568359220",
            "nota": "La farmacia confirma esta dirección y su teléfono en su web.",
        },
        {
            "id_ficha": "osm-extra:node:8986139365",
            "direccion_propuesta": "Puerto Deportivo de Sancti Petri, s/n, 11139 Chiclana de la Frontera, Cádiz",
            "confianza": "media",
            "fuente": "Web oficial de Escuela de Vela Zaida",
            "source_url": "https://www.escueladevelazaida.es/",
            "url_osm": "https://www.openstreetmap.org/node/8986139365",
            "nota": "Ubicación dentro del puerto deportivo; no consta número de local.",
        },
        {
            "id_ficha": "osm-extra:node:12978473976",
            "direccion_propuesta": "Calle Volga, 1, 11130 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Registro municipal de asociaciones de Chiclana",
            "source_url": "https://www.chiclana.es/areas-municipales/turismo-y-desarrollo/delegacion-de-participacion-ciudadana/registro-municipal-de-asociaciones/asociaciones-culturales",
            "url_osm": "https://www.openstreetmap.org/node/12978473976",
            "nota": "El registro municipal identifica la asociación Kung Fu / Wu Shu Dragón Rojo en esta calle.",
        },
        {
            "id_ficha": "osm:node:10304712843",
            "direccion_propuesta": "Calle Boquerón, 3, 11139 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Web oficial de La Azotea by Aroma de Mar",
            "source_url": "https://laazoteabyaromademar.com/contacto/",
            "url_osm": "https://www.openstreetmap.org/node/10304712843",
            "nota": "Dirección publicada en la página de contacto del restaurante.",
        },
        {
            "id_ficha": "osm:node:11392548114",
            "direccion_propuesta": "Avenida del Torno, 10, Polígono Urbisur, 11130 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Turismo de Chiclana y web oficial de Viamed",
            "source_url": "https://turismo.chiclana.es/detalle-de-recurso/centro-medico-viamed-las-salinas/",
            "url_osm": "https://www.openstreetmap.org/node/11392548114",
            "nota": "Dirección publicada por el directorio turístico municipal.",
        },
        {
            "id_ficha": "osm:way:52495343",
            "direccion_propuesta": "Urbanización Novo Sancti Petri, s/n (Avenida Octavio Augusto), 11139 Chiclana de la Frontera, Cádiz",
            "confianza": "alta",
            "fuente": "Web oficial de Viamed Novo Sancti Petri",
            "source_url": "https://www.viamedsalud.com/hospital-novo-sancti-petri/info/",
            "url_osm": "https://www.openstreetmap.org/way/52495343",
            "nota": "Dirección del centro médico confirmada por Viamed.",
        },
    ]
    pending_by_id = {str(item.get("id")): item for item in pending}
    existing_proposal_ids = {str(proposal.get("id_ficha")) for proposal in proposals}
    external_added = 0
    for candidate in external_candidates:
        item = pending_by_id.get(candidate["id_ficha"])
        if not item or candidate["id_ficha"] in existing_proposal_ids:
            continue
        proposal = dict(candidate)
        proposal.update({
            "nombre": item.get("n"),
            "categoria": item.get("c"),
            "tipo": item.get("t"),
            "direccion_actual": None,
            "campos_osm_utilizados": [],
            "etiquetas_direccion_osm": {},
            "estado": "pendiente_revision_manual",
            "fecha_comprobacion": "2026-11-05",
        })
        proposals.append(proposal)
        existing_proposal_ids.add(candidate["id_ficha"])
        external_added += 1

    data["propuestas_direcciones_osm"] = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "fuente": "Extracción OSM archivada y fuentes oficiales externas; sin nuevas consultas a Overpass",
        "sha256_extraccion": extraction.get("sha256_archivo_extraccion"),
        "fichas_sin_direccion": len(pending),
        "fichas_con_id_osm_consultables": consulted,
        "objetos_recuperados_en_extraccion": consulted - len(not_found),
        "propuestas": proposals,
        "fichas_sin_id_osm": not_osm,
        "ids_osm_no_presentes_en_extraccion": not_found,
        "fichas_osm_sin_etiquetas_de_direccion": no_address,
        "nota": "Propuestas pendientes; no se modifican direcciones existentes ni se publica ninguna ficha automáticamente.",
    }
    data["actualizado"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    CATALOG.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({
        "fichas_sin_direccion": len(pending),
        "ids_osm_consultables": consulted,
        "objetos_recuperados": consulted - len(not_found),
        "propuestas_direccion": len(proposals),
        "propuestas_externas_verificadas": external_added,
        "sin_id_osm": len(not_osm),
        "sin_objeto_en_extraccion": len(not_found),
        "sin_tags_direccion": len(no_address),
        "consultas_overpass_nuevas": 0,
        "destino": CATALOG.name,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()

# Activación controlada de la recuperación basada exclusivamente en la extracción OSM archivada.
# Auditoría de direcciones 2026-11-05: recalcular sobre la extracción archivada sin consultas nuevas.
