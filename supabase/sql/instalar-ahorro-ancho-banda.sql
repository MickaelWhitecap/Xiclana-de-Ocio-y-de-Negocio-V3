-- Ahorro de ancho de banda (egress) en Supabase · 24-nov-2026
--
-- Problema: los procesos automáticos (User-Agent «Xiclana-Supabase-catalog-export»)
-- descargaban la fila completa site_settings('catalogo') (~4 MB) y la volvían a
-- recibir entera al guardarla, cientos de veces al día, solo para cambiar una clave.
--
-- Solución: dos funciones que hacen el cambio DENTRO de la base de datos.
-- El programa envía solo las claves que cambian y recibe como respuesta una fecha
-- (unos pocos bytes) en lugar de 4 MB.
--
-- Solo puede usarlas la clave secreta (service_role). La web pública y los
-- usuarios conectados NO pueden ejecutarlas.
-- Se puede ejecutar varias veces sin problema. Para quitarlo:
-- supabase/sql/desinstalar-ahorro-ancho-banda.sql

-- 1) Añade o sustituye claves del catálogo sin descargarlo.
--    p_cambios: objeto con las claves a guardar, p. ej. {"rad_lotes": {...}}
--    p_esperado: (opcional) fecha updated_at que se leyó antes; si alguien ha
--                cambiado la fila mientras tanto, no guarda nada y devuelve NULL.
--    Devuelve la nueva fecha updated_at, o NULL si no guardó.
create or replace function public.xiclana_fusionar_catalogo(
  p_cambios jsonb,
  p_esperado timestamptz default null
)
returns timestamptz
language plpgsql
security invoker
set search_path = ''
as $function$
declare
  v_nueva timestamptz;
begin
  if p_cambios is null or jsonb_typeof(p_cambios) <> 'object' then
    raise exception 'p_cambios debe ser un objeto JSON';
  end if;
  update public.site_settings
     set data = coalesce(data, '{}'::jsonb) || p_cambios,
         updated_at = clock_timestamp()
   where id = 'catalogo'
     and (p_esperado is null or updated_at = p_esperado)
  returning updated_at into v_nueva;
  return v_nueva;
end;
$function$;

-- 2) Borra los puntos de control del rastreo RAD de una ficha sin descargar
--    los ~3 MB de rad_crawl_progress. Devuelve cuántos ha borrado.
create or replace function public.xiclana_limpiar_checkpoint_rad(p_ficha text)
returns integer
language plpgsql
security invoker
set search_path = ''
as $function$
declare
  v_progreso jsonb;
  v_quedan jsonb;
  v_borrados integer := 0;
begin
  select data->'rad_crawl_progress' into v_progreso
    from public.site_settings where id = 'catalogo' for update;
  if v_progreso is null or jsonb_typeof(v_progreso) <> 'object' then
    return 0;
  end if;

  if jsonb_typeof(v_progreso->'checkpoints') = 'object' then
    select coalesce(jsonb_object_agg(k, v), '{}'::jsonb)
      into v_quedan
      from jsonb_each(v_progreso->'checkpoints') as e(k, v)
     where jsonb_typeof(v) <> 'object' or coalesce(v->>'target_id', '') <> p_ficha;
    select count(*) into v_borrados
      from jsonb_each(v_progreso->'checkpoints') as e(k, v)
     where jsonb_typeof(v) = 'object' and coalesce(v->>'target_id', '') = p_ficha;
    if v_borrados = 0 then
      return 0;
    end if;
    if v_quedan = '{}'::jsonb then
      update public.site_settings
         set data = data - 'rad_crawl_progress', updated_at = clock_timestamp()
       where id = 'catalogo';
    else
      update public.site_settings
         set data = jsonb_set(data, '{rad_crawl_progress,checkpoints}', v_quedan),
             updated_at = clock_timestamp()
       where id = 'catalogo';
    end if;
    return v_borrados;
  end if;

  -- Formato antiguo: un único punto de control plano.
  if coalesce(v_progreso->>'target_id', '') = p_ficha then
    update public.site_settings
       set data = data - 'rad_crawl_progress', updated_at = clock_timestamp()
     where id = 'catalogo';
    return 1;
  end if;
  return 0;
end;
$function$;

revoke all on function public.xiclana_fusionar_catalogo(jsonb, timestamptz) from public, anon, authenticated;
revoke all on function public.xiclana_limpiar_checkpoint_rad(text) from public, anon, authenticated;
grant execute on function public.xiclana_fusionar_catalogo(jsonb, timestamptz) to service_role;
grant execute on function public.xiclana_limpiar_checkpoint_rad(text) to service_role;

-- Que la API de Supabase vea las funciones nuevas al momento.
notify pgrst, 'reload schema';

-- Comprobación: debe salir una fila con las dos funciones.
select string_agg(proname, ' y ' order by proname) as funciones_instaladas
  from pg_proc
 where pronamespace = 'public'::regnamespace
   and proname in ('xiclana_fusionar_catalogo', 'xiclana_limpiar_checkpoint_rad');
