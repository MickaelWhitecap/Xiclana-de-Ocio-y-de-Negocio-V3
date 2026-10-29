#!/usr/bin/env python3
"""Pruebas de regresión para las reglas de auditoría del catálogo."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("auditar_catalogo.py")
SPEC = importlib.util.spec_from_file_location("auditar_catalogo", MODULE_PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class AuditDuplicateTests(unittest.TestCase):
    def test_duplicate_catalog_ids_abort_instead_of_rewriting_ids(self):
        import importlib.util
        updater_path = Path(__file__).with_name("actualizar.py")
        spec = importlib.util.spec_from_file_location("actualizar_catalogo_test", updater_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "catalog.json"
            data_path.write_text(json.dumps({"items": [
                {"id": "manual:same", "n": "Ficha A", "t": "ocio", "c": "Deportes", "a": "Calle 1"},
                {"id": "manual:same", "n": "Ficha B", "t": "ocio", "c": "Deportes", "a": "Calle 2"}
            ]}), encoding="utf-8")
            old_data = updater.DATA
            updater.DATA = data_path
            try:
                with self.assertRaises(SystemExit):
                    updater.main()
                stored = json.loads(data_path.read_text(encoding="utf-8"))
                self.assertEqual([x["id"] for x in stored["items"]], ["manual:same", "manual:same"])
            finally:
                updater.DATA = old_data

    def test_supabase_override_sync_uses_pagination(self):
        source = Path(__file__).with_name("actualizar.py").read_text(encoding="utf-8")
        self.assertIn('"Range":f"{offset}-{offset + page_size - 1}"', source)
        self.assertIn('while True:', source)
        self.assertIn('page_size = 500', source)

    def test_automatic_expansion_does_not_remove_existing_catalog_records(self):
        source = Path(__file__).with_name("ampliar_catalogo.py").read_text(encoding="utf-8")
        self.assertNotIn("items.remove(", source)

    def test_different_types_are_not_duplicates_but_same_type_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "catalog.json"
            baseline_path = root / "baseline.json"
            report_path = root / "report.json"
            plan_path = root / "plan.json"
            items = [
                {"id": "manual:1", "n": "Centro", "c": "Deportes", "t": "ocio", "a": "Calle Uno 1"},
                {"id": "manual:2", "n": "Centro", "c": "Deportes", "t": "negocio", "a": "Calle Uno 1"},
                {"id": "oficial:3", "n": "Centro", "c": "Deportes", "t": "ocio", "a": "Calle Uno 1"},
            ]
            data_path.write_text(json.dumps({"items": items, "candidatas_revision": []}), encoding="utf-8")
            baseline_path.write_text(json.dumps({"ids": []}), encoding="utf-8")
            old = (audit.DATA, audit.BASELINE, audit.REPORT, audit.MERGE_PLAN)
            audit.DATA, audit.BASELINE, audit.REPORT, audit.MERGE_PLAN = data_path, baseline_path, report_path, plan_path
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    audit.main()
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(report["grupos_duplicados_exactos_nombre_categoria_direccion"], 1)
                group = report["propuestas_consolidacion_no_destructivas"][0]
                self.assertEqual(group["tipo_normalizado"], "ocio")
                self.assertEqual(group["direccion_normalizada"], "calle uno 1")
                self.assertEqual(set(group["ids"]), {"manual:1", "oficial:3"})
            finally:
                audit.DATA, audit.BASELINE, audit.REPORT, audit.MERGE_PLAN = old


if __name__ == "__main__":
    unittest.main()
