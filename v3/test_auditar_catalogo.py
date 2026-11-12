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
    def test_address_summary_separates_valid_coordinates_and_groups_categories(self):
        items = [
            {"id": "a", "t": "ocio", "c": "Bar", "a": "", "lat": 36.4, "lon": -6.1},
            {"id": "b", "t": "ocio", "c": "Bar", "a": "", "lat": 36.5, "lon": -6.2},
            {"id": "c", "t": "negocio", "c": "Transporte", "a": "", "lat": "", "lon": ""},
            {"id": "d", "t": "ocio", "c": "Bar", "a": "Calle 1", "lat": 36.4, "lon": -6.1},
        ]
        result = audit.resumen_direcciones(items)
        self.assertEqual(result["total_sin_direccion"], 3)
        self.assertEqual(result["con_coordenadas_validas"], 2)
        self.assertEqual(result["sin_coordenadas_validas"], 1)
        self.assertEqual(result["distribucion_por_tipo_y_categoria"][0]["categoria"], "Bar")
        self.assertEqual(result["distribucion_por_tipo_y_categoria"][0]["con_coordenadas"], 2)

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
            with mock.patch.dict("os.environ", {"SUPABASE_SECRET_KEY": "sb_secret_test"}), mock.patch.object(urllib.request, "urlopen", side_effect=[FakeResponse(first_page), FakeResponse(second_page)]) as mocked_urlopen:
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
            with mock.patch.dict("os.environ", {"SUPABASE_SECRET_KEY": "sb_secret_test"}), mock.patch.object(urllib.request, "urlopen", return_value=FakeResponse(rows)):
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

    def test_public_page_uses_local_catalog_without_supabase_for_fichas(self):
        page = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")
        self.assertIn('fetch("fichas_completas.json?v=__XICLANA_BUILD_ID__")', page)
        self.assertIn("const esAguaGenerica=", page)
        self.assertIn("!esAguaGenerica(x.n", page)
        self.assertNotIn("https://cdn.jsdelivr.net/npm/@supabase/supabase-js", page)
        self.assertNotIn('sb.from("listing_overrides")', page)
        self.assertNotIn('sb.from("listing_categories")', page)


class OSMIntegrationTests(unittest.TestCase):
    def test_osm_review_proposals_are_stored_in_the_master_catalog(self):
        path = Path(__file__).with_name("incorporar_candidatas_osm.py")
        spec = importlib.util.spec_from_file_location("incorporar_candidatas_osm_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        manual = [{"id": "manual:review", "n": "Ficha manual"}]
        automatic = [{"id": "osm-extra:node:123", "n": "Candidata OSM"}]
        addresses = [{"id_ficha": "osm:node:456", "direccion_propuesta": "Calle Uno"}]
        summary = {"fecha_utc": "2026-11-04T00:00:00+00:00"}
        master = {"items": [{"id": "osm:node:456"}]}
        result = module.integrate_review_data(master, manual, automatic, addresses, summary)
        self.assertEqual(result["candidatas_revision"], manual + automatic)
        self.assertEqual(result["propuestas_direcciones_osm"], addresses)
        self.assertEqual(result["total_candidatas_revision"], 2)
        self.assertFalse(result["integracion_osm_revision"]["publicacion_automatica"])

    def test_unmatched_osm_objects_are_classified_without_promoting_them(self):
        path = Path(__file__).with_name("incorporar_candidatas_osm.py")
        spec = importlib.util.spec_from_file_location("incorporar_osm_classification_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        entries = [
            {"etiquetas": {"highway": "residential", "name": "Calle Uno"}},
            {"etiquetas": {"healthcare": "physiotherapist", "name": "Clínica"}},
            {"etiquetas": {"place": "locality", "name": "Pago"}},
            {"etiquetas": {"route": "bus", "type": "route", "name": "Línea"}},
            {"etiquetas": {"building": "yes", "name": "Edificio"}},
            {"etiquetas": {"tourism": "chalet", "name": "Casa"}},
        ]
        result = module.classify_unmatched_osm(entries)
        self.assertEqual(result["total_objetos_sin_ficha_candidata"], 6)
        self.assertEqual(result["distribucion_exclusiva"]["viales_y_circulacion"], 1)
        self.assertEqual(result["distribucion_exclusiva"]["elementos_con_etiquetas_sectoriales"], 2)
        self.assertEqual(result["distribucion_exclusiva"]["toponimos_y_lugares_geograficos"], 1)
        self.assertEqual(result["distribucion_exclusiva"]["rutas_y_lineas_de_transporte"], 1)
        self.assertEqual(result["distribucion_exclusiva"]["infraestructura_edificios_y_naturaleza"], 1)
        self.assertEqual(result["objetos_sectoriales_excluidos_por_reglas"], 1)
        self.assertEqual(result["candidatas_que_superan_el_filtro_de_relevancia"], 1)

    def test_address_proposals_are_preserved_from_master_after_auxiliary_file_removal(self):
        source = (Path(__file__).with_name("incorporar_candidatas_osm.py")).read_text(encoding="utf-8")
        self.assertIn('address_proposals = data.get("propuestas_direcciones_osm", [])', source)
        self.assertIn('stored_proposals = address_doc.get("propuestas", [])', source)
        self.assertIn('data["propuestas_direcciones_osm"] = address_proposals', source)

    def test_admin_loads_osm_review_data_from_master_not_auxiliary_json(self):
        admin = (Path(__file__).with_name("admin.html")).read_text(encoding="utf-8")
        self.assertIn('reviewCandidates=(data.candidatas_revision||[])', admin)
        self.assertIn('const rawAddressProposals=data.propuestas_direcciones_osm', admin)
        self.assertIn('Array.isArray(rawAddressProposals?.propuestas)', admin)
        self.assertIn('addressProposals=normalizedAddressProposals.filter', admin)
        self.assertNotIn('fetch("./osm_candidatas_pendientes.json"', admin)
        self.assertNotIn('fetch("./propuestas_direcciones_osm.json"', admin)
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "publicar-v3.yml").read_text(encoding="utf-8")
        self.assertIn('for key in ("osm_extraccion_inicial", "auditoria_osm"):', workflow)
        self.assertNotIn('for key in ("osm_extraccion_inicial", "auditoria_osm", "propuestas_direcciones_osm"):', workflow)


class ExplicitFieldClearingTests(unittest.TestCase):
    def test_null_override_removes_existing_value_but_empty_string_does_not(self):
        from unittest import mock
        import urllib.request
        import importlib.util

        updater_path = Path(__file__).with_name("actualizar.py")
        spec = importlib.util.spec_from_file_location("actualizar_clear_test", updater_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)

        class FakeResponse(io.StringIO):
            def __init__(self, payload):
                super().__init__(json.dumps(payload))
                self.headers = {"Content-Range": "0-0/1"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.close()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "catalog.json"
            (root / "supabase-config.js").write_text(
                'window.XICLANA_SUPABASE = { url: "https://example.supabase.co", anonKey: "public-test-key" };',
                encoding="utf-8"
            )
            data_path.write_text(json.dumps({"items": [{
                "id": "manual:clear", "n": "Ficha", "t": "ocio", "c": "Deportes",
                "p": "956 111 222", "d": "Descripción conservada"
            }]}), encoding="utf-8")
            old_data, old_root = updater.DATA, updater.ROOT
            updater.DATA, updater.ROOT = data_path, root
            response = FakeResponse([{
                "listing_id": "manual:clear",
                "fields": {"p": None, "d": ""},
                "is_new": False, "verified_at": None, "updated_at": "2026-01-01T00:00:00Z"
            }])
            with mock.patch.dict("os.environ", {"SUPABASE_SECRET_KEY": "sb_secret_test"}), mock.patch.object(urllib.request, "urlopen", return_value=response):
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        updater.main()
                    saved = json.loads(data_path.read_text(encoding="utf-8"))["items"][0]
                    self.assertNotIn("p", saved)
                    self.assertEqual(saved["d"], "Descripción conservada")
                finally:
                    updater.DATA, updater.ROOT = old_data, old_root


class UsefulCompletenessAndVerificationTests(unittest.TestCase):
    def test_completeness_uses_exactly_the_six_public_fields(self):
        items = [
            {"id": "zero", "n": "Sin datos", "t": "ocio", "c": "Cultura",
             "lat": 36.4, "lon": -6.1, "f": "fuente"},
            {"id": "three", "a": "Calle 1", "p": "956123456", "d": "Descripción",
             "n": "Ficha", "t": "ocio", "c": "Cultura", "lat": 36.4},
            {"id": "six", "a": "Calle 2", "p": "956123457", "e": "info@example.com",
             "w": "https://example.com", "h": "09:00-18:00", "d": "Descripción",
             "n": "Completa", "t": "negocio", "c": "Comercio", "lat": 36.5, "lon": -6.2},
        ]
        result = audit.resumen_completitud_y_verificacion(items)
        self.assertEqual(result["campos_contados"], ["a", "p", "e", "w", "h", "d"])
        self.assertEqual(result["distribucion_0_a_6"], {
            "0": 1, "1": 0, "2": 0, "3": 1, "4": 0, "5": 0, "6": 1
        })
        self.assertEqual(result["total_fichas"], 3)

    def test_verification_status_is_independent_and_missing_defaults_to_pending(self):
        items = [
            {"id": "a", "estado_verificacion": "insuficiente"},
            {"id": "b", "estado_verificacion": "verificada"},
            {"id": "c", "estado_verificacion": "pendiente"},
            {"id": "d"},
        ]
        result = audit.resumen_completitud_y_verificacion(items)
        self.assertEqual(result["distribucion_0_a_6"]["0"], 4)
        self.assertEqual(result["estados_verificacion"], {
            "verificada": 1, "pendiente": 2, "insuficiente": 1, "otros": 0
        })
        self.assertEqual(result["fichas_sin_estado_explicito_tratadas_como_pendientes"], 1)


if __name__ == "__main__":
    unittest.main()
