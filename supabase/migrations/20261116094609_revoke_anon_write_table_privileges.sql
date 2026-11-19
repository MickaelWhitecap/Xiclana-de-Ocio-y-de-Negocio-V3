-- El rol anon solo necesita leer fichas publicadas y los campos públicos
-- de configuración. No debe conservar privilegios de escritura ni DDL.
revoke all privileges on table public.listings from anon;
grant select on table public.listings to anon;

revoke all privileges on table public.site_settings from anon;
grant select (id, public_data) on table public.site_settings to anon;
