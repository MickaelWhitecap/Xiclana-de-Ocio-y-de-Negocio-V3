#!/usr/bin/env python3
"""Lee la web propia de cada ficha que todavía no se ha leído y rellena sus huecos.

Por qué existe: el rastreo RAD por lotes fija la lista de fichas al empezar cada
ciclo y el último ciclo quedó cancelado, así que las fichas dadas de alta después
(p. ej. las de Overture del 21-nov-2026, como la Venta Bonilla) nunca se leían.

Cómo lee: con leer_web_propia.py (portada + hasta 4 páginas de contacto/horario,
solo datos con forma clara; ver allí las reglas). Nunca cambia un dato que ya
existe: solo rellena teléfono (hasta 2), correo, horario, descripción y redes.
Cada intento queda en site_settings.catalogo.lectura_web_propia para no repetir a
diario una web que falla (se reintenta a los REINTENTO_DIAS o si cambia la web).
"""
import argparse, json, pathlib, sys, tempfile, time, urllib.parse
from collections import Counter
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import catalogo_supabase as catalog
import leer_web_propia as lector

CLAVE_ESTADO = "lectura_web_propia"
REINTENTO_DIAS = 30
SECTORES = ("ocio", "negocio")
NOMBRES_CAMPO = {"p": "telefono", "e": "correo", "h": "horario", "d": "descripcion", "r": "redes"}


def ahora():
    return datetime.now(timezone.utc)


def tiene_web(item):
    partes = urllib.parse.urlsplit(str(item.get("w") or "").strip())
    return partes.scheme.lower() in ("http", "https") and bool(partes.netloc)


def web_ya_leida(item):
    fuentes = item.get("fuentes_datos")
    return isinstance(fuentes, list) and any(
        isinstance(x, dict) and x.get("tipo") == "web_oficial" for x in fuentes)


def activas(data):
    return [x for x in data.get("items", []) if isinstance(x, dict) and x.get("id")
            and x.get("is_published") is True and not x.get("_xiclana_deleted")
            and str(x.get("t") or "").strip().lower() in SECTORES]


def dominios_compartidos(items):
    """Un mismo dominio en varias fichas suele ser una cadena o un portal."""
    cuenta = Counter(lector.host_de(x.get("w")) for x in items if tiene_web(x))
    return {h for h, n in cuenta.items() if h and n >= 3}


def pendientes(data, intentos, hoy=None):
    hoy = hoy or ahora()
    limite = hoy - timedelta(days=REINTENTO_DIAS)
    nuevas, reintentos = [], []
    for item in activas(data):
        if not tiene_web(item) or web_ya_leida(item):
            continue
        previo = intentos.get(str(item["id"]))
        if not isinstance(previo, dict):
            nuevas.append(item)
            continue
        try:
            fecha = datetime.fromisoformat(str(previo.get("fecha_utc")))
        except ValueError:
            fecha = None
        if fecha is None or fecha < limite or previo.get("web") != item.get("w"):
            reintentos.append(item)
    nuevas.sort(key=lambda x: str(x.get("_xiclana_updated_at") or ""), reverse=True)
    return [str(x["id"]) for x in nuevas + reintentos]


def guardar_intentos(intentos):
    with tempfile.TemporaryDirectory(prefix="xiclana-web-meta-") as tmp:
        path = pathlib.Path(tmp) / "meta.json"
        path.write_text(json.dumps({"items": [], CLAVE_ESTADO: intentos}, ensure_ascii=False), encoding="utf-8")
        catalog.sync_metadata(path, [CLAVE_ESTADO])


def aplicar(base, key, ident, campos, paginas):
    """Lee la fila actual, rellena solo huecos y guarda con control de concurrencia."""
    filas, _ = catalog.request(base + "/listings?" + urllib.parse.urlencode(
        {"select": "id,data,is_published,is_deleted,updated_at", "id": "eq." + ident}), key)
    if not filas:
        return [], "ficha_no_encontrada"
    fila = filas[0]
    if fila.get("is_deleted") or fila.get("is_published") is not True:
        return [], "ficha_inactiva"
    datos = fila.get("data") or {}
    nuevo, añadidos = lector.completar(datos, campos)
    if not añadidos:
        return [], "sin_datos_nuevos"
    hoy = ahora().date().isoformat()
    fuentes = list(nuevo.get("fuentes_datos") or []) if isinstance(nuevo.get("fuentes_datos"), list) else []
    fuentes.append({"url": paginas[0] if paginas else nuevo.get("w"), "tipo": "web_oficial",
                    "campos": [NOMBRES_CAMPO[k] for k in añadidos], "fecha": hoy,
                    "paginas_leidas": paginas[:5]})
    nuevo["fuentes_datos"] = fuentes
    cuerpo = {"data": nuevo, "updated_at": ahora().isoformat()}
    if str(datos.get("estado_verificacion") or "").lower() != "verificada":
        # La propia web del negocio lo nombra y lo sitúa en Chiclana.
        nuevo["estado_verificacion"] = "verificada"
        nuevo["f"] = paginas[0] if paginas else nuevo.get("w")
        nuevo["v"] = hoy
        cuerpo["verified_at"] = ahora().isoformat()
    filtro = {"id": "eq." + ident, "updated_at": "eq." + fila["updated_at"] if fila.get("updated_at") else "is.null"}
    res, _ = catalog.request(base + "/listings?" + urllib.parse.urlencode(filtro), key, method="PATCH",
                             payload=cuerpo, headers={"Prefer": "return=representation"})
    if not res:
        return [], "cambio_concurrente"
    return añadidos, "completada"


def self_test():
    hoy = datetime(2026, 11, 21, tzinfo=timezone.utc)
    data = {"items": [
        {"id": "a", "t": "ocio", "is_published": True, "w": "http://www.ventabonilla.com/", "_xiclana_updated_at": "2026-11-21"},
        {"id": "b", "t": "ocio", "is_published": True, "w": "https://x.es", "fuentes_datos": [{"tipo": "web_oficial"}]},
        {"id": "c", "t": "negocio", "is_published": True, "w": ""},
        {"id": "d", "t": "negocio", "is_published": False, "w": "https://y.es"},
        {"id": "e", "t": "negocio", "is_published": True, "w": "https://z.es", "_xiclana_deleted": True},
        {"id": "f", "t": "negocio", "is_published": True, "w": "https://f.es", "_xiclana_updated_at": "2026-10-01"},
        {"id": "g", "t": "negocio", "is_published": True, "w": "https://g.es"},
        {"id": "h", "t": "negocio", "is_published": True, "w": "https://h-nueva.es"},
    ]}
    intentos = {
        "f": {"fecha_utc": "2026-11-20T00:00:00+00:00", "web": "https://f.es"},
        "g": {"fecha_utc": "2026-09-01T00:00:00+00:00", "web": "https://g.es"},
        "h": {"fecha_utc": "2026-11-20T00:00:00+00:00", "web": "https://h-vieja.es"},
    }
    assert pendientes(data, intentos, hoy) == ["a", "g", "h"], pendientes(data, intentos, hoy)
    assert dominios_compartidos([{"w": "https://www.repsol.es/a"}, {"w": "https://repsol.es/b"}, {"w": "https://repsol.es/c"}, {"w": "https://x.es"}]) == {"repsol.es"}
    lector.self_test()
    print("rastreo_fichas_con_web: pruebas internas OK")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-fichas", type=int, default=600)
    parser.add_argument("--minutos", type=float, default=300)
    parser.add_argument("--ids", default="", help="IDs concretos separados por comas.")
    parser.add_argument("--simular", action="store_true", help="Lee las webs pero no guarda nada.")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return

    inicio = time.monotonic()
    base, key = catalog.connection()
    resumen = {"fichas_leidas": 0, "fichas_mejoradas": 0, "datos_anadidos": Counter(), "motivos": Counter(), "detalle": []}
    with tempfile.TemporaryDirectory(prefix="xiclana-web-fichas-") as tmp:
        catalogo = pathlib.Path(tmp) / "catalogo.json"
        catalog.export_catalog(catalogo)
        data = json.loads(catalogo.read_text(encoding="utf-8"))
    estado = data.get(CLAVE_ESTADO)
    intentos = estado if isinstance(estado, dict) else {}
    por_id = {str(x["id"]): x for x in activas(data)}
    compartidos = dominios_compartidos(list(por_id.values()))
    cola = [x.strip() for x in args.ids.split(",") if x.strip()] if args.ids else pendientes(data, intentos)
    resumen["pendientes_al_empezar"] = len(cola)
    cola = cola[:args.max_fichas]
    print(json.dumps({"evento": "inicio", "pendientes": len(cola)}, ensure_ascii=False), flush=True)

    for numero, ident in enumerate(cola, 1):
        if (time.monotonic() - inicio) / 60 > args.minutos:
            break
        ficha = por_id.get(ident)
        if not ficha:
            continue
        fila = {"id": ident, "nombre": ficha.get("n"), "web": ficha.get("w")}
        try:
            leido = lector.leer_web(ficha, compartidos)
            fila["motivo"] = leido["motivo"]
            fila["encontrado"] = {k: v for k, v in leido["campos"].items() if v}
            if leido["campos"] and not args.simular:
                añadidos, estado_ficha = aplicar(base, key, ident, leido["campos"], leido["paginas"])
                fila["motivo"] = estado_ficha if leido["motivo"] == "leida" else leido["motivo"]
                fila["añadidos"] = añadidos
                if añadidos:
                    resumen["fichas_mejoradas"] += 1
                    resumen["datos_anadidos"].update(NOMBRES_CAMPO[k] for k in añadidos)
        except Exception as exc:  # una web rota no debe parar la tanda
            fila["motivo"] = "error"
            fila["error"] = str(exc)[:200]
        resumen["motivos"][fila["motivo"]] += 1
        resumen["fichas_leidas"] += 1
        resumen["detalle"].append(fila)
        intentos[ident] = {"fecha_utc": ahora().isoformat(), "web": ficha.get("w"), "motivo": fila["motivo"],
                           "añadidos": fila.get("añadidos", [])}
        print(json.dumps({"n": numero, **fila}, ensure_ascii=False), flush=True)
        if not args.simular and numero % 10 == 0:
            guardar_intentos(intentos)
    if not args.simular:
        guardar_intentos(intentos)

    restantes = 0 if args.ids or args.simular else len(pendientes(data, intentos))
    resumen["pendientes_al_terminar"] = restantes
    resumen["status"] = "more" if restantes and resumen["fichas_leidas"] else "done"
    resumen["datos_anadidos"] = dict(resumen["datos_anadidos"])
    resumen["motivos"] = dict(resumen["motivos"])
    pathlib.Path("rastreo-fichas-web-result.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in resumen.items() if k != "detalle"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
