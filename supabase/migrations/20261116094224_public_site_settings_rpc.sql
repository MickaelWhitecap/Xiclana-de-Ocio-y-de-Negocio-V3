-- RPC pública mínima: solo fecha de actualización y destacados.
-- La función no expone candidatas ni metadatos internos.
create or replace function public.get_public_site_settings()
returns table (id text, data jsonb)
language sql
stable
security definer
set search_path = ''
as $function$
  select
    s.id,
    jsonb_build_object(
      'actualizado', s.data->'actualizado',
      'destacados', s.data->'destacados'
    ) as data
  from public.site_settings as s
  where s.id = 'catalogo';
$function$;

revoke all on function public.get_public_site_settings() from public;
revoke all on function public.get_public_site_settings() from authenticated;
grant execute on function public.get_public_site_settings() to anon;
