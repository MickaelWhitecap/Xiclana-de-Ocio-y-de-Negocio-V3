import gzip
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SingleSupabaseMasterTests(unittest.TestCase):
    def test_exporter_reads_listings_and_syncs_only_metadata(self):
        source = (ROOT / "v3/catalogo_supabase.py").read_text(encoding="utf-8")
        self.assertIn('fetch_all(base, key, "listings"', source)
        self.assertIn('base + "/site_settings?select=id,data&id=eq.catalogo"', source)
        self.assertIn('base + "/site_settings?id=eq.catalogo"', source)
        self.assertIn('"fichas_modificadas": 0', source)
        self.assertNotIn('"/listing_overrides?', source)

    def test_weekly_osm_exports_from_supabase_and_syncs_metadata(self):
        workflow = (ROOT / ".github/workflows/auditoria-osm-municipal.yml").read_text(encoding="utf-8")
        self.assertIn("catalogo_supabase.py export", workflow)
        self.assertIn("catalogo_supabase.py sync-metadata", workflow)
        self.assertIn("XICLANA_CATALOG_PATH", workflow)
        self.assertNotIn("git add v3/fichas_completas.json", workflow)
        self.assertNotIn("git push origin HEAD:main", workflow)

    def test_weekly_rad_exports_from_supabase_and_never_writes_catalog_json(self):
        workflow = (ROOT / ".github/workflows/rad-enrich-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("catalogo_supabase.py export", workflow)
        self.assertIn("catalogo_supabase.py sync-metadata", workflow)
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
