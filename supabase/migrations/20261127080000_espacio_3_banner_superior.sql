-- Espacio 3 · Banner superior: un tercer espacio publicitario justo debajo de la cabecera.
-- Amplía los espacios permitidos de 1-2 a 1-3 y el contador anónimo para que también lo mida.

alter table public.advertising_slots drop constraint if exists advertising_slots_slot_id_check;
alter table public.advertising_slots add constraint advertising_slots_slot_id_check check (slot_id in (1, 2, 3));

insert into public.advertising_slots (slot_id, status)
values (3, 'available')
on conflict (slot_id) do nothing;

alter table public.web_stats_daily drop constraint if exists web_stats_daily_slot_id_check;
alter table public.web_stats_daily add constraint web_stats_daily_slot_id_check check (slot_id between 0 and 3);

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
  elsif p_slot is null or p_slot not in (1, 2, 3) then
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
