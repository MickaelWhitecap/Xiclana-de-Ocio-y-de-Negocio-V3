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

    def test_legacy_json_updater_is_disabled(self):
        source = (Path(__file__).with_name("actualizar.py")).read_text(encoding="utf-8")
        self.assertIn("está retirado", source)
        self.assertIn("public.listings", source)
 
    def test_public_page_reads_fichas_from_the_single_supabase_catalog(self):
        page = (Path(__file__).with_name("index.html")).read_text(encoding="utf-8")
        self.assertIn("async function cargarCatalogoSupabase()", page)
        self.assertIn('listings?select=id,data,verified_at', page)
        self.assertIn('site_settings?select=data&id=eq.catalogo', page)
        self.assertIn("await aplicarCambios(", page)
        self.assertNotIn('fetch("fichas_completas.json', page)
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

    def test_admin_loads_review_metadata_from_the_canonical_supabase_database(self):
        admin = (Path(__file__).with_name("admin.html")).read_text(encoding="utf-8")
        self.assertIn('client.from("site_settings").select("data")', admin)
        self.assertIn('const metadata=settingsRes.data?.data||{}', admin)
        self.assertIn('reviewCandidates=Array.isArray(metadata.candidatas_revision)', admin)
        self.assertIn('const rawAddressProposals=metadata.propuestas_direcciones_osm', admin)
        self.assertIn('addressProposals=normalizedAddressProposals.filter', admin)
        self.assertNotIn('fetch("./osm_candidatas_pendientes.json"', admin)
        self.assertNotIn('fetch("./propuestas_direcciones_osm.json"', admin)
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "publicar-v3.yml").read_text(encoding="utf-8")
        self.assertIn("no se incluye fichas_completas.json", workflow)
        self.assertIn("SUPABASE_ANON_KEY", workflow)


if __name__ == "__main__":
    unittest.main()

