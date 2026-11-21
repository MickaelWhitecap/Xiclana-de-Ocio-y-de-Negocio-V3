#!/usr/bin/env python3
"""Lee la web propia de cada ficha que todavía no se ha leído y completa sus datos.

Por qué existe: el rastreo RAD por lotes recorre el catálogo entero y fija la
lista de fichas al empezar cada ciclo. Las fichas dadas de alta después (por
ejemplo, las de Overture Maps del 21-nov-2026) se quedaban sin leer su web
hasta un ciclo futuro que, además, llevaba días cancelado. Este proceso no
depende de ese ciclo: cada día busca las fichas publicadas con web que aún no
tienen datos leídos de su web oficial ni un intento reciente, y las lee.

Reglas:
- Solo lee la web que ya figura en la ficha (sin buscadores) y como máximo
  --max-paginas páginas, empezando por contacto, horario y aviso legal.
- Nunca sobrescribe un dato que ya existe; solo rellena huecos (sync_enrichment).
- Guarda cada intento en site_settings.catalogo.rastreo_web_fichas para no
  repetir una web que falla todos los días (se reintenta pasados REINTENTO_DIAS).
"""
import argparse, json, pathlib, shutil, subprocess, sys, tempfile, time, urllib.parse
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import catalogo_supabase as catalog

CLAVE_ESTADO = "rastreo_web_fichas"
REINTENTO_DIAS = 30
SECTORES = ("ocio", "negocio")


def ahora():
    return datetime.now(timezone.utc)


def tiene_web(item):
    web = str(item.get("w") or "").strip()
    partes = urllib.parse.urlsplit(web)
    return partes.scheme.lower() in ("http", "https") and bool(partes.netloc)


def web_ya_leida(item):
    fuentes = item.get("fuentes_datos")
    if not isinstance(fuentes, list):
        return False
    return any(isinstance(x, dict) and x.get("tipo") == "web_oficial" for x in fuentes)


def pendientes(data, intentos, hoy=None):
    """Fichas publicadas con web que no se han leído nunca o cuyo intento caducó.
    Primero las que nunca se intentaron; dentro de ellas, las más recientes."""
    hoy = hoy or ahora()
    limite = hoy - timedelta(days=REINTENTO_DIAS)
    nuevas, reintentos = [], []
    for item in data.get("items", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if item.get("is_published") is not True or item.get("_xiclana_deleted"):
            continue
        if str(item.get("t") or "").strip().lower() not in SECTORES:
            continue
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
        # Si cambió la web de la ficha, se vuelve a leer aunque el intento sea reciente.
        if fecha is None or fecha < limite or previo.get("web") != item.get("w"):
            reintentos.append(item)
    nuevas.sort(key=lambda x: str(x.get("_xiclana_updated_at") or ""), reverse=True)
    return [str(x["id"]) for x in nuevas + reintentos]


def guardar_intentos(intentos):
    with tempfile.TemporaryDirectory(prefix="xiclana-web-meta-") as tmp:
        path = pathlib.Path(tmp) / "meta.json"
        path.write_text(json.dumps({"items": [], CLAVE_ESTADO: intentos}, ensure_ascii=False), encoding="utf-8")
        catalog.sync_metadata(path, [CLAVE_ESTADO])


def leer_intentos(data):
    estado = data.get(CLAVE_ESTADO)
    return estado if isinstance(estado, dict) else {}


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
        "f": {"fecha_utc": "2026-11-20T00:00:00+00:00", "web": "https://f.es"},  # reciente: no
        "g": {"fecha_utc": "2026-09-01T00:00:00+00:00", "web": "https://g.es"},  # caducado: sí
        "h": {"fecha_utc": "2026-11-20T00:00:00+00:00", "web": "https://h-vieja.es"},  # web cambiada: sí
    }
    assert pendientes(data, intentos, hoy) == ["a", "g", "h"], pendientes(data, intentos, hoy)
    print("rastreo_fichas_con_web: pruebas internas OK")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-fichas", type=int, default=400)
    parser.add_argument("--max-paginas", type=int, default=12)
    parser.add_argument("--minutos", type=float, default=300,
                        help="Tiempo máximo de esta ejecución; lo que falte queda para la siguiente.")
    parser.add_argument("--ids", default="", help="IDs concretos separados por comas (prueba de un caso).")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return

    inicio = time.monotonic()
    resumen = {"fichas_leidas": 0, "fichas_mejoradas": 0, "datos_anadidos": 0,
               "web_no_confirmada": 0, "errores": 0, "detalle": []}
    with tempfile.TemporaryDirectory(prefix="xiclana-web-fichas-") as tmp:
        tmp = pathlib.Path(tmp)
        catalogo = tmp / "catalogo.json"
        antes = tmp / "antes.json"
        lote = tmp / "ids.txt"
        catalog.export_catalog(catalogo)
        data = json.loads(catalogo.read_text(encoding="utf-8"))
        intentos = leer_intentos(data)
        if args.ids:
            cola = [x.strip() for x in args.ids.split(",") if x.strip()]
        else:
            cola = pendientes(data, intentos)
        resumen["pendientes_al_empezar"] = len(cola)
        cola = cola[:args.max_fichas]
        print(json.dumps({"evento": "inicio", "pendientes": resumen["pendientes_al_empezar"], "en_esta_ejecucion": len(cola)}, ensure_ascii=False), flush=True)

        for numero, ident in enumerate(cola, 1):
            if (time.monotonic() - inicio) / 60 > args.minutos:
                print(json.dumps({"evento": "tiempo_agotado", "leidas": numero - 1}, ensure_ascii=False), flush=True)
                break
            item = next((x for x in data["items"] if str(x.get("id")) == ident), None)
            if item is None:
                continue
            shutil.copyfile(catalogo, antes)
            lote.write_text(ident + "\n", encoding="utf-8")
            fila = {"id": ident, "nombre": item.get("n"), "web": item.get("w")}
            try:
                subprocess.run([
                    sys.executable, str(ROOT / "rastreo_web_publico.py"),
                    "--catalog", str(catalogo), "--batch-ids-file", str(lote),
                    "--max-paginas", str(args.max_paginas), "--solo-web-registrada",
                    "--local-checkpoints-only",
                ], check=True, timeout=600)
                sync = catalog.sync_enrichment(antes, catalogo, allowed_ids={ident})
                data = json.loads(catalogo.read_text(encoding="utf-8"))
                rad = data.get("rad_ultima_ejecucion", {})
                res = next((r for r in rad.get("resultados_por_ficha", []) if str(r.get("id")) == ident), {})
                fila.update({
                    "resultado": res.get("resultado", "sin_resultado"),
                    "paginas": res.get("paginas_visitadas", 0),
                    "campos_en_web": res.get("campos_detectados", []),
                    "campos_aplicados": sync.get("campos_actualizados", 0),
                })
                if sync.get("fichas_actualizadas"):
                    resumen["fichas_mejoradas"] += 1
                    resumen["datos_anadidos"] += int(sync.get("campos_actualizados", 0))
                if not res.get("web_oficial_confirmada"):
                    resumen["web_no_confirmada"] += 1
            except (subprocess.SubprocessError, RuntimeError, OSError, ValueError) as exc:
                resumen["errores"] += 1
                fila["resultado"] = "error"
                fila["error"] = str(exc)[:300]
                # Restaurar la copia previa para que un fallo no contamine la siguiente ficha.
                shutil.copyfile(antes, catalogo)
                data = json.loads(catalogo.read_text(encoding="utf-8"))
            resumen["fichas_leidas"] += 1
            resumen["detalle"].append(fila)
            intentos[ident] = {"fecha_utc": ahora().isoformat(), "web": item.get("w"),
                               "resultado": fila.get("resultado"), "campos_aplicados": fila.get("campos_aplicados", 0)}
            print(json.dumps({"evento": "ficha", "n": numero, **fila}, ensure_ascii=False), flush=True)
            # Guardar el intento cada 10 fichas (y al final) para poder reanudar.
            if numero % 10 == 0:
                guardar_intentos(intentos)
        guardar_intentos(intentos)

    restantes = len(pendientes(json.loads(json.dumps({"items": data["items"]})), intentos))
    resumen["pendientes_al_terminar"] = restantes
    resumen["status"] = "more" if restantes and not args.ids and resumen["fichas_leidas"] else "done"
    pathlib.Path("rastreo-fichas-web-result.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in resumen.items() if k != "detalle"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
