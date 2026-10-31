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

    def test_updater_reads_all_override_pages_before_writing_catalog(self):
        import importlib.util
        from unittest import mock
        import urllib.request

        updater_path = Path(__file__).with_name("actualizar.py")
        spec = importlib.util.spec_from_file_location("actualizar_paginacion_test", updater_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)

        class FakeResponse(io.StringIO):
            def __init__(self, payload):
                super().__init__(json.dumps(payload))
                self.headers = {"Content-Range": "*/*"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "catalog.json"
            config_path = root / "supabase-config.js"
            data_path.write_text(json.dumps({"items": [
                {"id": "manual:existing", "n": "Ficha existente", "t": "ocio", "c": "Deportes", "a": "Calle 1"}
            ]}), encoding="utf-8")
            config_path.write_text(
                'window.XICLANA_SUPABASE = { url: "https://example.supabase.co", anonKey: "public-test-key" };',
                encoding="utf-8"
            )
            first_page = [
                {"listing_id": f"manual:{i}", "fields": {"n": f"Ficha {i}", "t": "ocio", "c": "Deportes", "a": f"Calle {i}"},
                 "is_new": True, "verified_at": None, "updated_at": "2026-01-01T00:00:00Z"}
                for i in range(500)
            ]
            second_page = [
                {"listing_id": "manual:500", "fields": {"n": "Ficha 500", "t": "ocio", "c": "Deportes", "a": "Calle 500"},
                 "is_new": True, "verified_at": None, "updated_at": "2026-01-01T00:00:00Z"}
            ]
            old_data, old_root = updater.DATA, updater.ROOT
            updater.DATA, updater.ROOT = data_path, root
            with mock.patch.object(urllib.request, "urlopen", side_effect=[FakeResponse(first_page), FakeResponse(second_page)]) as mocked_urlopen:
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        updater.main()
                    self.assertEqual(mocked_urlopen.call_count, 2)
                    ranges = [call.args[0].get_header("Range") for call in mocked_urlopen.call_args_list]
                    self.assertEqual(ranges, ["0-499", "500-999"])
                    stored = json.loads(data_path.read_text(encoding="utf-8"))
                    self.assertEqual(stored["sincronizacion_supabase"]["overrides_leidos"], 501)
                    self.assertEqual(stored["sincronizacion_supabase"]["fichas_nuevas_incorporadas"], 501)
                    self.assertTrue(any(item.get("id") == "manual:500" for item in stored["items"]))
                finally:
                    updater.DATA, updater.ROOT = old_data, old_root

    def test_malformed_catalog_item_aborts_without_rewriting_file(self):
        import importlib.util
        updater_path = Path(__file__).with_name("actualizar.py")
        spec = importlib.util.spec_from_file_location("actualizar_malformado_test", updater_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "catalog.json"
            original = json.dumps({"items": [{"id": "manual:1", "n": "Ficha"}, None]})
            data_path.write_text(original, encoding="utf-8")
            old_data = updater.DATA
            updater.DATA = data_path
            try:
                with self.assertRaises(SystemExit):
                    updater.main()
                self.assertEqual(data_path.read_text(encoding="utf-8"), original)
            finally:
                updater.DATA = old_data


    def test_tombstones_are_not_revived_or_reintroduced_by_sync(self):
        import importlib.util
        from unittest import mock
        import urllib.request

        updater_path = Path(__file__).with_name("actualizar.py")
        spec = importlib.util.spec_from_file_location("actualizar_tombstones_test", updater_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)

        class FakeResponse(io.StringIO):
            def __init__(self, payload):
                super().__init__(json.dumps(payload))
                self.headers = {"Content-Range": "0-1/2"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        rows = [
            {"listing_id": "manual:deleted-existing", "fields": {"n": "Ficha retirada", "t": "ocio", "c": "Deportes"}, "is_new": False, "updated_at": "2026-01-01T00:00:00Z"},
            {"listing_id": "manual:deleted-missing", "fields": {"n": "No reintroducir", "_xiclana_deleted": True}, "is_new": True, "updated_at": "2026-01-01T00:00:00Z"},
            {"listing_id": "manual:active-existing", "fields": {"n": "Ficha activa actualizada"}, "is_new": False, "updated_at": "2026-01-01T00:00:00Z"},
            {"listing_id": "manual:agua-generica", "fields": {"n": "Agua potable", "t": "ocio", "c": "Servicios públicos"}, "is_new": True, "updated_at": "2026-01-01T00:00:00Z"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "catalog.json"
            config_path = root / "supabase-config.js"
            data_path.write_text(json.dumps({"items": [
                {"id": "manual:deleted-existing", "n": "Ficha retirada", "_xiclana_deleted": True},
                {"id": "manual:active-existing", "n": "Ficha activa"},
            ]}), encoding="utf-8")
            config_path.write_text(
                'window.XICLANA_SUPABASE = { url: "https://example.supabase.co", anonKey: "public-test-key" };',
                encoding="utf-8"
            )
            old_data, old_root = updater.DATA, updater.ROOT
            updater.DATA, updater.ROOT = data_path, root
            with mock.patch.object(urllib.request, "urlopen", return_value=FakeResponse(rows)):
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        updater.main()
                    stored = json.loads(data_path.read_text(encoding="utf-8"))
                    by_id = {item["id"]: item for item in stored["items"]}
                    self.assertTrue(by_id["manual:deleted-existing"]["_xiclana_deleted"])
                    self.assertNotIn("manual:deleted-missing", by_id)
                    self.assertNotIn("manual:agua-generica", by_id)
                    self.assertEqual(by_id["manual:active-existing"]["n"], "Ficha activa actualizada")
                    self.assertNotIn("_xiclana_deleted", by_id["manual:active-existing"])
                finally:
                    updater.DATA, updater.ROOT = old_data, old_root


    def test_contact_quality_accepts_multiple_emails_and_phone_extensions(self):
        items = [
            {"id": "1", "n": "Dos correos", "e": "reservas@example.com, info@example.com",
             "p": "956 123 456 ext. 708", "w": "https://example.com", "lat": 36.4, "lon": -6.2},
            {"id": "2", "n": "URL en email", "e": "www.example.com", "p": "676 363 718 (piraguas)/ 633 283 546 (veleros)"},
            {"id": "3", "n": "Email inválido", "e": "reservas@dominio"},
        ]
        result = audit.validar_calidad_campos(items)
        self.assertEqual(len(result["correos_invalidos"]), 1)
        self.assertEqual(len(result["urls_colocadas_en_campo_email"]), 1)
        self.assertEqual(result["telefonos_sospechosos"], [])
        self.assertEqual(result["urls_invalidas"], [])
        self.assertEqual(result["coordenadas_invalidas"], [])

    def test_public_page_excludes_generic_water_overrides(self):
        page = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")
        self.assertIn("const esAguaGenerica=", page)
        self.assertIn("!esAguaGenerica(o.fields?.n", page)


if __name__ == "__main__":
    unittest.main()
