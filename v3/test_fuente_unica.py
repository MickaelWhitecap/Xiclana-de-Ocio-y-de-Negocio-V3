import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class RadSafeEnrichmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("catalogo_supabase", ROOT / "v3/catalogo_supabase.py")
        cls.catalog = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.catalog)

    def _run(self, status="Verificada", extra_field=None):
        timestamp = "2026-11-12T12:00:00+00:00"
        before_item = {
            "id": "listing-1", "n": "Empresa de prueba", "a": "", "p": "",
            "estado_verificacion": status, "is_published": True,
            "verified_at": timestamp, "_xiclana_updated_at": timestamp
        }
        after_item = dict(before_item)
        after_item["a"] = "Calle Real 10, Chiclana"
        if extra_field:
            after_item[extra_field] = "cambio no permitido"
        before = {"items": [before_item]}
        after = {"items": [after_item]}
        current = [{
            "id": "listing-1",
            "data": {k:v for k,v in before_item.items() if k not in {"id","is_published","verified_at","_xiclana_updated_at"}},
            "is_published": True, "is_deleted": False,
            "verified_at": timestamp, "updated_at": timestamp
        }]
        with tempfile.TemporaryDirectory() as directory:
            before_path = Path(directory) / "before.json"
            after_path = Path(directory) / "after.json"
            before_path.write_text(json.dumps(before),encoding="utf-8")
            after_path.write_text(json.dumps(after),encoding="utf-8")
            with patch.object(self.catalog,"connection",return_value=("https://example.supabase.co/rest/v1","secret")), \
                 patch.object(self.catalog,"fetch_all",return_value=current), \
                 patch.object(self.catalog,"request",return_value=([{"id":"listing-1"}],{})) as request:
                result = self.catalog.sync_enrichment(before_path,after_path)
        return result, request

    def test_only_verified_active_listing_receives_safe_missing_field(self):
        result, request = self._run()
        self.assertEqual(result["fichas_actualizadas"],1)
        self.assertEqual(result["campos_actualizados"],1)
        self.assertIn("/listings?",request.call_args.args[0])
        self.assertEqual(request.call_args.kwargs["payload"]["data"]["a"],"Calle Real 10, Chiclana")

    def test_unverified_listing_is_not_changed(self):
        result, request = self._run(status="Pendiente de Verificar")
        self.assertEqual(result["fichas_actualizadas"],0)
        self.assertEqual(result["saltadas_por_no_verificadas_o_inactivas"],1)
        request.assert_not_called()

    def test_rad_cannot_change_verification_or_publication_fields(self):
        with self.assertRaises(RuntimeError):
            self._run(extra_field="estado_verificacion")


class SingleSupabaseMasterTests(unittest.TestCase):
    def test_exporter_reads_listings_and_syncs_only_metadata(self):
        source = (ROOT / "v3/catalogo_supabase.py").read_text(encoding="utf-8")
        self.assertIn('fetch_all(base, key, "listings"', source)
        self.assertIn('site_settings?select=id,data,updated_at&id=eq.catalogo', source)
        self.assertIn('"updated_at": "eq." + timestamp if timestamp else "is.null"', source)
        self.assertIn('"fichas_modificadas": 0', source)
        self.assertNotIn('"/listing_overrides?', source)

    def test_weekly_osm_exports_from_supabase_and_syncs_metadata(self):
        workflow = (ROOT / ".github/workflows/auditoria-osm-municipal.yml").read_text(encoding="utf-8")
        self.assertIn("catalogo_supabase.py export", workflow)
        self.assertIn("catalogo_supabase.py sync-metadata", workflow)
        self.assertIn("XICLANA_CATALOG_PATH", workflow)
        self.assertIn('cron: "30 4 * * 1"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("\n  push:", workflow)
        self.assertNotIn("git add v3/fichas_completas.json", workflow)
        self.assertNotIn("git push origin HEAD:main", workflow)



    def test_rad_and_osm_candidate_lists_merge_without_lost_updates(self):
        spec = importlib.util.spec_from_file_location("catalogo_supabase_merge", ROOT / "v3/catalogo_supabase.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        current = [{"id":"osm:node:1","n":"Local OSM","nota":"conservada"}]
        incoming = [{"id":"rad:abc","n":"Local RAD"},{"id":"osm:node:1","direccion":"Calle Real"}]
        merged = module.merge_candidate_lists(current,incoming)
        by_id = {item["id"]:item for item in merged}
        self.assertEqual(set(by_id),{"osm:node:1","rad:abc"})
        self.assertEqual(by_id["osm:node:1"]["nota"],"conservada")
        self.assertEqual(by_id["osm:node:1"]["direccion"],"Calle Real")

    def test_rad_and_osm_use_separate_concurrency_groups(self):
        osm = (ROOT / ".github/workflows/auditoria-osm-municipal.yml").read_text(encoding="utf-8")
        rad = (ROOT / ".github/workflows/rad-enrich-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("group: xiclana-osm-semanal", osm)
        self.assertIn("group: rad-descubrimiento-supabase", rad)
        helper = (ROOT / "v3/catalogo_supabase.py").read_text(encoding="utf-8")
        self.assertIn("updated_at", helper)
        self.assertIn("merge_candidate_lists", helper)


    def test_rad_enrichment_updates_only_verified_listings_and_allowed_fields(self):
        source = (ROOT / "v3/catalogo_supabase.py").read_text(encoding="utf-8")
        self.assertIn('status != "verificada"', source)
        self.assertIn('"a", "h", "d", "t", "c", "rta_registro"', source)
        self.assertIn('base + "/listings?"', source)
        self.assertIn('"publicacion_automatica": False', source)
        self.assertIn('saltadas_por_cambio_concurrente', source)

    def test_weekly_rad_exports_from_supabase_and_never_writes_catalog_json(self):
        workflow = (ROOT / ".github/workflows/rad-enrich-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("catalogo_supabase.py export", workflow)
        self.assertIn("catalogo_supabase.py sync-metadata", workflow)
        self.assertIn("catalogo_supabase.py sync-enrichment", workflow)
        self.assertIn("Aplicar enriquecimientos seguros a fichas verificadas", workflow)
        self.assertIn('cron: "47 6 * * 1"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("\\n  push:", workflow)
        self.assertIn("--catalog", workflow)
        self.assertNotIn("git add", workflow)
        self.assertNotIn("git push", workflow)

    def test_rad_candidate_report_reads_supabase_export(self):
        workflow = (ROOT / ".github/workflows/rad-pending-review.yml").read_text(encoding="utf-8")
        self.assertIn("catalogo_supabase.py export", workflow)
        self.assertIn("xiclana-catalogo.json", workflow)
        self.assertNotIn("fichas_completas.json", workflow)

    def test_legacy_json_writers_are_retired(self):
        for name in ("integrar-candidatas-rad.yml", "incorporar-auditoria-osm.yml", "auditar-bajas-catalogo.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertIn("retirad", workflow.lower())
            self.assertNotIn("git push", workflow)
            self.assertNotIn("git add", workflow)

    def test_backup_json_is_generated_from_supabase_not_repository_snapshot(self):
        workflow = (ROOT / ".github/workflows/backup-supabase.yml").read_text(encoding="utf-8")
        self.assertIn("catalogo_supabase.py export --output fichas_completas.json", workflow)
        self.assertIn('"v3/catalogo_supabase.py"', workflow)
        self.assertIn("gzip -9 -c fichas_completas.json", workflow)
        self.assertNotIn("test -s v3/fichas_completas.json", workflow)
        self.assertNotIn("gzip -9 -c v3/fichas_completas.json", workflow)

    def test_admin_compatibility_adapter_routes_every_legacy_call_to_listings(self):
        admin = (ROOT / "v3/admin.html").read_text(encoding="utf-8")
        self.assertIn('client.from=(table)=>', admin)
        self.assertIn('supabaseFrom("listings").select("id,data,is_deleted,verified_at,updated_at")', admin)
        self.assertIn('return supabaseFrom("listings").upsert(prepared,{onConflict:"id"})', admin)
        self.assertIn('is_published:!deleted,is_deleted:deleted', admin)



    def test_legacy_json_writing_scripts_are_disabled(self):
        for name in ("actualizar.py", "ampliar_catalogo.py", "extraccion_inicial_osm.py",
                     "incorporar_auditoria_osm.py", "recuperar_direcciones_osm.py"):
            source = (ROOT / "v3" / name).read_text(encoding="utf-8")
            self.assertIn("retirad", source.lower())

    def test_osm_and_audit_scripts_require_a_supabase_export_path(self):
        for name in ("auditar_osm_municipal.py", "incorporar_candidatas_osm.py",
                     "proponer_direcciones_osm.py", "auditar_catalogo.py"):
            source = (ROOT / "v3" / name).read_text(encoding="utf-8")
            self.assertIn('os.environ["XICLANA_CATALOG_PATH"]', source)

    def test_osm_weekly_comparison_uses_separate_immutable_baseline(self):
        source = (ROOT / "v3/comparar_cambios_osm.py").read_text(encoding="utf-8")
        self.assertIn('BASELINE = ROOT / "osm_extraccion_inicial.json.gz"', source)
        self.assertIn("gzip.decompress(BASELINE.read_bytes())", source)
        self.assertNotIn('MASTER = ROOT / "fichas_completas.json"', source)
        with gzip.open(ROOT / "v3/osm_extraccion_inicial.json.gz", "rt", encoding="utf-8") as stream:
            baseline = json.load(stream)
        if isinstance(baseline, dict):
            baseline = baseline.get("objetos") or baseline.get("elementos") or []
        self.assertEqual(len(baseline), 132875)

    def test_manual_rad_checks_use_supabase_export(self):
        for name in ("prueba-rad-real.yml", "rad-review-old-candidates.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertIn("catalogo_supabase.py export", workflow)
            self.assertNotIn("v3/fichas_completas.json", workflow)

    def test_historical_import_and_extraction_workflows_are_retired(self):
        for name in ("extraccion-inicial-osm.yml", "migrar-catalogo-supabase.yml",
                     "rad-catalog-validation.yml", "recuperar-direcciones-osm.yml",
                     "integrar-candidatas-rad.yml", "incorporar-auditoria-osm.yml",
                     "auditar-bajas-catalogo.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertIn("retirad", workflow.lower())
            self.assertNotIn("git push", workflow)
            self.assertNotIn("git add", workflow)

    def test_public_web_and_exporter_use_supabase_listings(self):
        public = (ROOT / "v3/index.html").read_text(encoding="utf-8")
        exporter = (ROOT / "v3/exportar-fichas.html").read_text(encoding="utf-8")
        self.assertIn('listings?select=id,data,verified_at', public)
        self.assertIn('listings?select=id,data,verified_at', exporter)
        self.assertNotIn('fetch("fichas_completas.json', public)
        self.assertNotIn('fetch("fichas_completas.json', exporter)


if __name__ == "__main__":
    unittest.main()
