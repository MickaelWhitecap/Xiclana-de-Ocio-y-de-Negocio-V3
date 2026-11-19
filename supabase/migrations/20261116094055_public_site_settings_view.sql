-- Exposición pública limitada a los datos necesarios para la web.
-- Las candidatas y los metadatos internos permanecen en site_settings y
-- solo son accesibles mediante el flujo administrativo autorizado.
create or replace view public.site_settings_public
with (security_barrier = true)
as
select
  id,
  jsonb_build_object(
    'actualizado', data->'actualizado',
    'destacados', data->'destacados'
  ) as data
from public.site_settings
where id = 'catalogo';

grant select on public.site_settings_public to anon;
