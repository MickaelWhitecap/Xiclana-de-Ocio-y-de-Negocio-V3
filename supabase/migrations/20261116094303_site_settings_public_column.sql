-- Mantiene los datos públicos en una columna separada de los metadatos internos.
-- La tabla site_settings sigue siendo única; anon solo puede leer id y public_data.
alter table public.site_settings
  add column if not exists public_data jsonb not null default '{}'::jsonb;

create or replace function public.sync_site_settings_public_data()
returns trigger
language plpgsql
set search_path = ''
as $function$
begin
  new.public_data := jsonb_build_object(
    'actualizado', new.data->'actualizado',
    'destacados', new.data->'destacados'
  );
  return new;
end;
$function$;

drop trigger if exists trg_sync_site_settings_public_data on public.site_settings;
create trigger trg_sync_site_settings_public_data
before insert or update of data on public.site_settings
for each row
execute function public.sync_site_settings_public_data();

update public.site_settings
set public_data = jsonb_build_object(
  'actualizado', data->'actualizado',
  'destacados', data->'destacados'
)
where id = 'catalogo';

revoke select on table public.site_settings from anon;
grant select (id, public_data) on public.site_settings to anon;
