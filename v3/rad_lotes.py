#!/usr/bin/env python3
"""Ejecuta un lote RAD de hasta 50 fichas y confirma su checkpoint en Supabase."""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import catalogo_supabase as catalog

ROOT = pathlib.Path(__file__).resolve().parent
BATCH_SIZE = 50
SECTORS = ("ocio", "negocio")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def active_items(data):
    return [
        item for item in data.get("items", [])
        if isinstance(item, dict)
        and item.get("id")
        and item.get("is_published") is True
        and not item.get("_xiclana_deleted")
        and str(item.get("t") or "").strip().lower() in SECTORS
    ]


def persist_metadata(data, keys):
    with tempfile.TemporaryDirectory(prefix="xiclana-rad-meta-") as tmp:
        path = pathlib.Path(tmp) / "catalogo.json"
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        catalog.sync_metadata(path, keys)


def create_state(data):
    items = active_items(data)
    invalid = [
        x for x in data.get("items", [])
        if isinstance(x, dict) and x.get("is_published") is True
        and not x.get("_xiclana_deleted")
        and str(x.get("t") or "").strip().lower() not in SECTORS
    ]
    if invalid:
        raise RuntimeError(f"Hay {len(invalid)} fichas publicadas sin sector ocio/negocio; no se inicia un manifiesto incompleto.")
    next_start = str(data.get("rad_lotes_siguiente_inicio") or "ocio").lower()
    if next_start not in SECTORS:
        next_start = "ocio"
    order = [next_start, "negocio" if next_start == "ocio" else "ocio"]
    manifest = {
        sector: sorted(str(x["id"]) for x in items if str(x.get("t") or "").lower() == sector)
        for sector in SECTORS
    }
    if not any(manifest.values()):
        raise RuntimeError("No hay fichas activas publicadas para investigar.")
    return {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "status": "running",
        "started_utc": utcnow(),
        "start_sector": next_start,
        "sector_order": order,
        "manifest": manifest,
        "cursor": {"ocio": 0, "negocio": 0},
        "global_discovery_done": False,
        "batches_completed": 0,
        "batch_size": BATCH_SIZE,
        "total_fichas": len(items),
        "resultados_por_ficha": {},
    }


def select_batch(state, current_active_ids):
    for sector in state["sector_order"]:
        ids = state["manifest"].get(sector, [])
        cursor = int(state["cursor"].get(sector, 0))
        if cursor >= len(ids):
            continue
        end = min(cursor + BATCH_SIZE, len(ids))
        selected = [ident for ident in ids[cursor:end] if ident in current_active_ids]
        return sector, selected, cursor, end
    return None


def self_test():
    sample = {"items": [
        {"id": "o-02", "t": "ocio", "is_published": True},
        {"id": "o-01", "t": "ocio", "is_published": True},
        {"id": "n-01", "t": "negocio", "is_published": True},
        {"id": "deleted", "t": "ocio", "is_published": False, "_xiclana_deleted": True},
        {"id": "unpublished", "t": "negocio", "is_published": False},
    ]}
    active = active_items(sample)
    assert {x["id"] for x in active} == {"o-01", "o-02", "n-01"}
    state = create_state(sample)
    assert state["sector_order"] == ["ocio", "negocio"]
    assert state["manifest"]["ocio"] == ["o-01", "o-02"]
    batch = select_batch(state, {x["id"] for x in active})
    assert batch == ("ocio", ["o-01", "o-02"], 0, 2), batch
    state["cursor"]["ocio"] = 2
    batch = select_batch(state, {x["id"] for x in active})
    assert batch == ("negocio", ["n-01"], 0, 1), batch
    alternate = create_state({**sample, "rad_lotes_siguiente_inicio": "negocio"})
    assert alternate["sector_order"] == ["negocio", "ocio"]
    many = {"items": [
        {"id": f"o-{i:03}", "t": "ocio", "is_published": True}
        for i in range(123)
    ]}
    large_state = create_state(many)
    first = select_batch(large_state, {x["id"] for x in active_items(many)})
    assert len(first[1]) == 50 and first[2:] == (0, 50)
    print("RAD lotes self-test: OK", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    with tempfile.TemporaryDirectory(prefix="xiclana-rad-batch-") as tmp:
        tmp = pathlib.Path(tmp)
        catalog_path = tmp / "catalogo.json"
        before_path = tmp / "antes.json"
        batch_path = tmp / "ids-lote.txt"
        catalog.export_catalog(catalog_path)
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        state = data.get("rad_lotes")
        if not isinstance(state, dict) or state.get("status") != "running":
            state = create_state(data)
            data["rad_lotes"] = state
            persist_metadata(data, ["rad_lotes", "rad_lotes_siguiente_inicio"])
            print(json.dumps({
                "evento": "manifiesto_creado",
                "run_id": state["run_id"],
                "inicio": state["start_sector"],
                "ocio": len(state["manifest"]["ocio"]),
                "negocio": len(state["manifest"]["negocio"]),
                "total": state["total_fichas"],
            }, ensure_ascii=False), flush=True)

        current_active_ids = {str(x["id"]) for x in active_items(data)}
        selection = select_batch(state, current_active_ids)
        while selection and not selection[1]:
            sector, _ids, start, end = selection
            skipped_ids = state["manifest"][sector][start:end]
            results = state.setdefault("resultados_por_ficha", {})
            for ident in skipped_ids:
                results[ident] = {
                    "id": ident, "sector": sector, "resultado": "omitida_por_inactividad",
                    "ficha_investigada": False, "motivo": "La ficha dejó de estar publicada o fue enviada a papelera antes de iniciar el lote.",
                    "registrado_utc": utcnow(),
                }
            state["cursor"][sector] = end
            data["rad_lotes"] = state
            persist_metadata(data, ["rad_lotes"])
            selection = select_batch(state, current_active_ids)

        if not selection:
            expected_ids = set(state["manifest"].get("ocio", [])) | set(state["manifest"].get("negocio", []))
            recorded_ids = set(state.setdefault("resultados_por_ficha", {}))
            missing_ids = sorted(expected_ids - recorded_ids)
            if missing_ids:
                raise RuntimeError(f"No se cierra RAD: faltan resultados individuales para {len(missing_ids)} fichas; primera: {missing_ids[0]}")
            state["status"] = "completed"
            state["completed_utc"] = utcnow()
            data["rad_lotes"] = state
            data["rad_lotes_siguiente_inicio"] = "negocio" if state["start_sector"] == "ocio" else "ocio"
            persist_metadata(data, ["rad_lotes", "rad_lotes_siguiente_inicio"])
            result = {"status": "completed", "run_id": state["run_id"], "batches_completed": state["batches_completed"],
                      "fichas_con_resultado_individual": len(state.get("resultados_por_ficha", {})),
                      "fichas_esperadas": state["total_fichas"]}
            pathlib.Path("rad-lotes-result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return

        sector, batch_ids, start, end = selection
        manifest_slice = state["manifest"][sector][start:end]
        skipped_ids = [ident for ident in manifest_slice if ident not in current_active_ids]
        batch_path.write_text("\n".join(batch_ids) + "\n", encoding="utf-8")
        before_path.write_text(catalog_path.read_text(encoding="utf-8"), encoding="utf-8")
        command = [
            sys.executable, str(ROOT / "rastreo_web_publico.py"),
            "--catalog", str(catalog_path),
            "--batch-ids-file", str(batch_path),
        ]
        global_discovery = not bool(state.get("global_discovery_done"))
        if global_discovery:
            command.append("--global-discovery")
        print(json.dumps({
            "evento": "inicio_lote",
            "run_id": state["run_id"],
            "sector": sector,
            "lote": state["batches_completed"] + 1,
            "ids": len(batch_ids),
            "posicion": f"{start + 1}-{end}",
            "descubrimiento_general": global_discovery,
        }, ensure_ascii=False), flush=True)
        subprocess.run(command, check=True)

        sync_summary = catalog.sync_enrichment(before_path, catalog_path, allowed_ids=batch_ids)
        updated = json.loads(catalog_path.read_text(encoding="utf-8"))
        rad = updated.get("rad_ultima_ejecucion", {})
        rad.update({
            "lote_sector": sector,
            "lote_numero": state["batches_completed"] + 1,
            "lote_tamano": len(batch_ids),
            "lote_ids": batch_ids,
            "fichas_modificadas_en_supabase": sync_summary.get("fichas_actualizadas", 0),
            "campos_aplicados_en_supabase": sync_summary.get("campos_actualizados", 0),
            "fichas_verificadas_desde_web_oficial": sync_summary.get("fichas_verificadas_desde_web_oficial", 0),
            "fichas_omitidas_por_cambio_concurrente": sync_summary.get("saltadas_por_cambio_concurrente", 0),
            "fichas_omitidas_por_no_verificadas_o_inactivas": sync_summary.get("saltadas_por_no_verificadas_o_inactivas", 0),
            "publicacion_automatica": False,
        })
        updated["rad_ultima_ejecucion"] = rad
        # Primero se guardan los datos y candidatas del lote. El checkpoint
        # solo avanza después de confirmar ambas sincronizaciones.
        persist_metadata(updated, ["candidatas_revision", "total_candidatas_revision", "rad_ultima_ejecucion"])

        state["cursor"][sector] = end
        state["batches_completed"] = int(state.get("batches_completed", 0)) + 1
        per_ficha = state.setdefault("resultados_por_ficha", {})
        for result_row in rad.get("resultados_por_ficha", []):
            ident = str(result_row.get("id") or "")
            if ident not in batch_ids:
                raise RuntimeError(f"El informe RAD contiene una ficha ajena al lote: {ident}")
            per_ficha[ident] = {**result_row, "lote_numero": state["batches_completed"],
                                "lote_sector": sector, "registrado_utc": utcnow()}
        if set(batch_ids) - set(per_ficha):
            raise RuntimeError("RAD no ha devuelto resultado individual para todas las fichas activas del lote.")
        for ident in skipped_ids:
            per_ficha[ident] = {
                "id": ident, "sector": sector, "resultado": "omitida_por_inactividad",
                "ficha_investigada": False,
                "motivo": "La ficha dejó de estar publicada o fue enviada a papelera antes de iniciar el lote.",
                "lote_numero": state["batches_completed"], "registrado_utc": utcnow(),
            }
        state["fichas_con_resultado_individual"] = len(per_ficha)
        state["global_discovery_done"] = True
        state["last_batch"] = {
            "sector": sector, "ids": batch_ids, "completed_utc": utcnow(),
            "fichas_actualizadas": sync_summary.get("fichas_actualizadas", 0),
        }
        updated["rad_lotes"] = state
        persist_metadata(updated, ["rad_lotes"])

        more = select_batch(state, current_active_ids) is not None
        result = {
            "status": "more" if more else "last_batch",
            "run_id": state["run_id"],
            "sector": sector,
            "lote": state["batches_completed"],
            "lote_tamano": len(batch_ids),
            "ocio_completadas": state["cursor"]["ocio"],
            "ocio_total": len(state["manifest"]["ocio"]),
            "negocio_completadas": state["cursor"]["negocio"],
            "negocio_total": len(state["manifest"]["negocio"]),
            "fichas_actualizadas_en_supabase": sync_summary.get("fichas_actualizadas", 0),
            "candidatas_revision": len(updated.get("candidatas_revision", [])),
            "publicacion_automatica": False,
            "fichas_con_resultado_individual": len(state.get("resultados_por_ficha", {})),
            "fichas_esperadas_en_manifiesto": state["total_fichas"],
        }
        pathlib.Path("rad-lotes-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"ERROR RAD LOTES: {exc}")
