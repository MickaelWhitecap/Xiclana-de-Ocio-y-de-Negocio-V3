#!/usr/bin/env python3
"""Valida y normaliza el único catálogo JSON de Xiclana V3."""
import json, pathlib, datetime, hashlib, sys
ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "fichas_completas.json"
def main():
    if not DATA.exists(): sys.exit("No existe el fichero maestro; se cancela para proteger el catálogo.")
    try: data = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception as exc: sys.exit(f"El fichero maestro no es JSON válido: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list): sys.exit("El fichero maestro no contiene una lista items; no se modifica.")
    items, seen = [], set()
    for raw in data["items"]:
        if not isinstance(raw, dict): continue
        item = dict(raw); name = str(item.get("n", "")).strip()
        if " ".join(name.casefold().split()) in {"agua", "agua potable"}: continue
        if not item.get("id"):
            seed = "\\x1f".join(str(item.get(k, "") or "").strip().casefold() for k in ("n", "t", "c", "a"))
            item["id"] = "consolidado:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
        ident = str(item["id"])
        if ident in seen:
            seed = ident + "\\x1f" + str(item.get("n", "")) + "\\x1f" + str(item.get("a", ""))
            item["id"] = ident + ":dup:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
            ident = item["id"]
        seen.add(ident); items.append(item)
    items.sort(key=lambda x: str(x.get("n", "")).casefold())
    data["items"] = items
    if not isinstance(data.get("candidatas_revision"), list): data["candidatas_revision"] = []
    data["actualizado"] = datetime.date.today().isoformat()
    data["total_fichas"] = len(items); data["total_candidatas_revision"] = len(data["candidatas_revision"])
    data["fuente_unica"] = "fichas_completas.json"
    DATA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Catálogo maestro validado: {len(items)} fichas y {len(data['candidatas_revision'])} candidatas.")
if __name__ == "__main__": main()
