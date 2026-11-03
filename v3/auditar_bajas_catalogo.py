#!/usr/bin/env python3
"""Audita las bajas del catálogo sin modificar fichas ni Supabase."""
import collections
import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
MASTER = ROOT / "fichas_completas.json"
OUT = ROOT / "auditoria_bajas_catalogo.json"


def main():
    if not MASTER.is_file() or MASTER.stat().st_size == 0:
        raise SystemExit("No existe el catálogo maestro.")
    data = json.loads(MASTER.read_text(encoding="utf-8"))
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit("El catálogo maestro no contiene items válidos.")

    deleted = [x for x in items if isinstance(x, dict) and x.get("_xiclana_deleted") is True]
    active = [x for x in items if isinstance(x, dict) and x.get("_xiclana_deleted") is not True]
    by_prefix = collections.Counter(str(x.get("id") or "").split(":", 1)[0] for x in deleted)
    by_category = collections.Counter((str(x.get("t") or "sin tipo"), str(x.get("c") or "sin categoría")) for x in deleted)

    records = []
    for x in sorted(deleted, key=lambda item: str(item.get("n") or "").casefold()):
        records.append({
            "id": x.get("id"),
            "nombre": x.get("n"),
            "tipo": x.get("t"),
            "categoria": x.get("c"),
            "direccion": x.get("a"),
            "fuente": x.get("f"),
            "fuente_estado": x.get("fuente_estado"),
            "fecha": x.get("v"),
        })

    result = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "catalogo": "v3/fichas_completas.json",
        "total_registros": len(items),
        "total_activos": len(active),
        "total_marcados_borrados": len(deleted),
        "bajas_por_prefijo_id": dict(sorted(by_prefix.items())),
        "bajas_por_tipo_categoria": [
            {"tipo": k[0], "categoria": k[1], "total": v}
            for k, v in sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "bajas": records,
        "nota": "Lectura exclusivamente. No restaura, elimina ni modifica fichas."
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "total_registros": result["total_registros"],
        "total_activos": result["total_activos"],
        "total_marcados_borrados": result["total_marcados_borrados"],
        "bajas_por_prefijo_id": result["bajas_por_prefijo_id"],
        "fichas_modificadas": 0
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
