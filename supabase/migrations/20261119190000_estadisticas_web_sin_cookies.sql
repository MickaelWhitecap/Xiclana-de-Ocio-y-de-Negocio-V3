-- Estadísticas de la web sin cookies ni datos personales.
-- Solo se guardan contadores por día: visitas a la página, veces que se ve
-- cada espacio publicitario y clics en cada anuncio. No se guarda IP,
-- navegador ni ningún identificador del visitante.

create table if not exists public.web_stats_daily (
  day date not null default current_date,
  metric text not null check (metric in ('visita', 'vista_anuncio', 'clic_anuncio')),
  slot_id smallint not null default 0 check (slot_id between 0 and 2),
  total integer not null default 0 check (total >= 0),
  primary key (day, metric, slot_id)
);

comment on table public.web_stats_daily is
  'Contadores diarios anónimos: visitas, vistas y clics de los espacios publicitarios (slot_id 0 = página).';

alter table public.web_stats_daily enable row level security;

-- Nadie anónimo lee ni escribe la tabla directamente.
revoke all on table public.web_stats_daily from anon, authenticated;

-- Solo el administrador puede leer las cifras.
grant select on table public.web_stats_daily to authenticated;
drop policy if exists "Xiclana admin can read web stats" on public.web_stats_daily;
create policy "Xiclana admin can read web stats"
on public.web_stats_daily
for select
to authenticated
using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);

-- La web pública suma uno al contador mediante esta función.
create or replace function public.registrar_evento_web(p_metric text, p_slot smallint default 0)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if p_metric not in ('visita', 'vista_anuncio', 'clic_anuncio') then
    return;
  end if;
  if p_metric = 'visita' then
    p_slot := 0;
  elsif p_slot is null or p_slot not in (1, 2) then
    return;
  end if;

  insert into public.web_stats_daily as s (day, metric, slot_id, total)
  values ((now() at time zone 'Europe/Madrid')::date, p_metric, p_slot, 1)
  on conflict (day, metric, slot_id)
  do update set total = s.total + 1;
end;
$function$;

revoke all on function public.registrar_evento_web(text, smallint) from public;
grant execute on function public.registrar_evento_web(text, smallint) to anon, authenticated;
