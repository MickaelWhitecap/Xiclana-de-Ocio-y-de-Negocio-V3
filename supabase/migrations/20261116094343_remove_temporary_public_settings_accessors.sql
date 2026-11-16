-- El acceso público queda limitado a las columnas id y public_data.
-- Se eliminan los accesores temporales utilizados durante la transición.
drop view if exists public.site_settings_public;
drop function if exists public.get_public_site_settings();
