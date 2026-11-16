-- La web pública debe consultar site_settings_public.
-- Se retira el acceso anónimo directo al JSON administrativo completo.
revoke select on table public.site_settings from anon;
