-- Ahorro de tráfico en Supabase: la web pública pregunta primero esta «huella»
-- (unos 40 bytes) y solo descarga las fichas (~1,2 MB) si han cambiado.
-- Ejecutar UNA vez en el SQL Editor del proyecto V3 (pewfqucupmbkgamwvaic).
-- Solo lee; respeta los permisos de lectura que ya tienen los visitantes.
create or replace function public.xiclana_huella_catalogo()
returns text
language sql
stable
security invoker
set search_path = ''
as $function$
  select md5(coalesce(string_agg(
    l.id || '|' || coalesce(l.verified_at::text, '') || '|' ||
    (select coalesce(jsonb_object_agg(k, l.data->k), '{}'::jsonb)::text
       from unnest(array['n','t','c','a','p','e','w','h','r','d','s','f','m','lat','lon',
                         'contactos_alternativos','estado_verificacion','_xiclana_deleted']) k
      where l.data ? k),
    E'\n' order by l.id), ''))
  from public.listings l
  where l.is_published and not l.is_deleted;
$function$;

revoke all on function public.xiclana_huella_catalogo() from public;
grant execute on function public.xiclana_huella_catalogo() to anon, authenticated;
