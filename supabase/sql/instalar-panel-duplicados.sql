-- =====================================================================
-- BOTONES DEL PANEL «Fichas duplicadas» de Administración · 21-nov-2026
-- Requiere tener instalada la vigilancia (instalar-vigilancia-duplicados.sql).
--
-- Añade tres acciones que usa la pestaña nueva de Administración:
--   · Fusionar una pareja: la ficha que se queda recibe los datos que le
--     faltan, el nombre y el identificador de la otra; la otra pasa a la
--     papelera con la nota «fusionada_en». Se guarda una copia de las dos
--     fichas antes de tocarlas.
--   · Deshacer una fusión: devuelve las dos fichas a como estaban.
--   · Marcar una pareja como «son distintas»: no vuelve a salir.
-- Solo las puede usar la cuenta de administración (o el SQL Editor).
--
-- No cambia ninguna ficha al instalarlo.
-- Para deshacerlo: desinstalar-panel-duplicados.sql
-- Pegar ENTERO en Supabase > SQL Editor y pulsar Run.
-- =====================================================================

create table if not exists public.dup_fusiones (
  id bigserial primary key,
  fecha timestamptz not null default now(),
  par_id bigint,
  quedar text not null,
  retirar text not null,
  antes_quedar jsonb not null,     -- fila completa de la ficha que se queda, antes de fusionar
  antes_retirar jsonb not null,    -- fila completa de la ficha retirada, antes de fusionar
  deshecha_el timestamptz
);
alter table public.dup_fusiones enable row level security;
revoke all on public.dup_fusiones from anon, authenticated;
grant select on public.dup_fusiones to authenticated;
drop policy if exists "Xiclana admin lee fusiones" on public.dup_fusiones;
create policy "Xiclana admin lee fusiones" on public.dup_fusiones for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);

-- ¿Quién llama? La cuenta de administración desde la web, o el SQL Editor.
create or replace function public.dup_es_admin()
returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce(auth.uid() = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid, false)
      or (auth.uid() is null and session_user in ('postgres','supabase_admin'))
$$;

-- Compara dos teléfonos, correos o webs sin fijarse en espacios, prefijo +34, http o la barra final.
create or replace function public.dup_contacto_igual(f text, x text, y text)
returns boolean
language sql immutable set search_path = public as $$
  select case f
    when 'p' then right(regexp_replace(x,'\D','','g'),9) = right(regexp_replace(y,'\D','','g'),9)
    when 'w' then regexp_replace(regexp_replace(lower(trim(x)),'^https?://(www\.)?',''),'/+$','')
                = regexp_replace(regexp_replace(lower(trim(y)),'^https?://(www\.)?',''),'/+$','')
    else lower(trim(x)) = lower(trim(y)) end
$$;

-- ---------- Fusionar ----------
create or replace function public.dup_fusionar(p_quedar text, p_retirar text, p_par bigint default null)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  fk public.listings; fr public.listings;
  k jsonb; d jsonb; f text; arr jsonb; motivo text; anadidos text[] := '{}';
  log_id bigint;
begin
  if not public.dup_es_admin() then raise exception 'Solo la cuenta de administración puede fusionar fichas'; end if;
  if p_quedar = p_retirar then raise exception 'Son la misma ficha'; end if;
  select * into fk from public.listings where id = p_quedar for update;
  select * into fr from public.listings where id = p_retirar for update;
  if fk.id is null or fr.id is null then raise exception 'Alguna de las dos fichas ya no existe'; end if;
  if fk.is_deleted or fr.is_deleted then raise exception 'Alguna de las dos fichas ya está en la papelera (quizá ya se fusionó)'; end if;

  insert into public.dup_fusiones (par_id, quedar, retirar, antes_quedar, antes_retirar)
  values (p_par, p_quedar, p_retirar, to_jsonb(fk), to_jsonb(fr)) returning id into log_id;

  k := fk.data; d := fr.data;
  select motivos into motivo from public.duplicados_revision
   where ficha_a = least(p_quedar, p_retirar) and ficha_b = greatest(p_quedar, p_retirar);

  -- Datos que le faltan a la que se queda
  foreach f in array array['a','p','e','w','h','d','r','s','m','v'] loop
    if coalesce(k->>f,'') = '' and coalesce(d->>f,'') <> '' then
      k := k || jsonb_build_object(f, d->f); anadidos := anadidos || f;
    end if;
  end loop;
  if coalesce(k->>'lat','') = '' and coalesce(d->>'lat','') <> '' then
    k := k || jsonb_build_object('lat', d->'lat', 'lon', d->'lon'); anadidos := anadidos || 'coordenadas'::text;
  end if;
  -- Teléfono, correo o web distintos: se guardan como alternativos, no se pierden
  foreach f in array array['p','e','w'] loop
    if coalesce(d->>f,'') <> '' and coalesce(k->>f,'') <> ''
       and public.dup_contacto_igual(f, d->>f, k->>f) is not true then
      arr := case when jsonb_typeof(k->'contactos_alternativos')='array' then k->'contactos_alternativos' else '[]'::jsonb end;
      k := k || jsonb_build_object('contactos_alternativos', arr || jsonb_build_array(jsonb_build_object(
             'tipo', f, 'valor', d->>f, 'fuente', coalesce(d->>'f', fr.id), 'fecha', now())));
    end if;
  end loop;
  -- Nombre e identificador de la retirada (y los que ya traía)
  arr := case when jsonb_typeof(k->'nombres_alternativos')='array' then k->'nombres_alternativos' else '[]'::jsonb end;
  if coalesce(d->>'n','') <> '' and lower(d->>'n') <> lower(coalesce(k->>'n','')) and not arr @> to_jsonb(array[d->>'n']) then
    arr := arr || to_jsonb(d->>'n');
  end if;
  k := k || jsonb_build_object('nombres_alternativos', arr);
  arr := case when jsonb_typeof(k->'ids_alternativos')='array' then k->'ids_alternativos' else '[]'::jsonb end;
  arr := arr || to_jsonb(fr.id)
             || case when jsonb_typeof(d->'ids_alternativos')='array' then d->'ids_alternativos' else '[]'::jsonb end;
  k := k || jsonb_build_object('ids_alternativos', (select coalesce(jsonb_agg(distinct x),'[]'::jsonb) from jsonb_array_elements_text(arr) x));
  if jsonb_typeof(d->'fuentes_datos')='array' then
    k := k || jsonb_build_object('fuentes_datos',
      (case when jsonb_typeof(k->'fuentes_datos')='array' then k->'fuentes_datos' else '[]'::jsonb end) || (d->'fuentes_datos'));
  end if;
  arr := case when jsonb_typeof(k->'historial_fusiones')='array' then k->'historial_fusiones' else '[]'::jsonb end;
  k := k || jsonb_build_object('historial_fusiones', arr || jsonb_build_array(jsonb_build_object(
    'fecha', now(), 'motivo', coalesce(motivo, 'fusión manual desde Administración'),
    'id_ficha_fusionada', fr.id, 'nombre_fusionado', d->>'n', 'direccion_anterior', coalesce(d->>'a',''),
    'registro_fusion', log_id)));
  -- Si la que se queda había entrado oculta por la barrera, se publica
  k := k - 'posible_duplicado_de' - 'posible_duplicado_motivos' - 'posible_duplicado_fecha';

  update public.listings
     set data = k, is_published = (fk.is_published or fr.is_published or fk.data ? 'posible_duplicado_de'),
         updated_at = now(), updated_by = coalesce(auth.uid(), fk.updated_by)
   where id = fk.id;
  update public.listings
     set is_deleted = true, is_published = false, updated_at = now(), updated_by = coalesce(auth.uid(), fr.updated_by),
         data = d || jsonb_build_object('fusionada_en', fk.id, 'fecha_fusion', now())
   where id = fr.id;

  update public.duplicados_revision
     set estado = 'fusionadas', revisada_el = now(), actualizada_el = now()
   where ficha_a = least(p_quedar, p_retirar) and ficha_b = greatest(p_quedar, p_retirar);

  return jsonb_build_object('registro', log_id, 'quedar', fk.id, 'retirada', fr.id, 'datos_anadidos', to_jsonb(anadidos));
end $$;

-- ---------- Deshacer una fusión ----------
create or replace function public.dup_deshacer_fusion(p_registro bigint)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare g public.dup_fusiones; q public.listings; r public.listings;
begin
  if not public.dup_es_admin() then raise exception 'Solo la cuenta de administración puede deshacer fusiones'; end if;
  select * into g from public.dup_fusiones where id = p_registro for update;
  if g.id is null then raise exception 'No existe esa fusión'; end if;
  if g.deshecha_el is not null then raise exception 'Esa fusión ya se deshizo'; end if;
  q := jsonb_populate_record(null::public.listings, g.antes_quedar);
  r := jsonb_populate_record(null::public.listings, g.antes_retirar);
  -- La vigilancia dejaría fuera la ficha retirada: se le quita la marca.
  delete from public.dup_vetadas where id = r.id;
  update public.listings set data = q.data, is_published = q.is_published, is_deleted = q.is_deleted,
         updated_at = now(), updated_by = coalesce(auth.uid(), q.updated_by) where id = q.id;
  update public.listings set data = r.data, is_published = r.is_published, is_deleted = r.is_deleted,
         updated_at = now(), updated_by = coalesce(auth.uid(), r.updated_by) where id = r.id;
  update public.dup_fusiones set deshecha_el = now() where id = g.id;
  update public.duplicados_revision set estado = 'pendiente', revisada_el = null, actualizada_el = now()
   where ficha_a = least(g.quedar, g.retirar) and ficha_b = greatest(g.quedar, g.retirar);
  return jsonb_build_object('deshecha', g.id, 'quedar', g.quedar, 'retirada', g.retirar);
end $$;

-- ---------- Marcar como distintas (o volver a pendiente) ----------
create or replace function public.dup_decidir(p_par bigint, p_estado text, p_nota text default null)
returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.dup_es_admin() then raise exception 'Solo la cuenta de administración puede revisar duplicados'; end if;
  if p_estado not in ('distintas','pendiente') then raise exception 'Estado no válido'; end if;
  update public.duplicados_revision
     set estado = p_estado, nota = coalesce(p_nota, nota),
         revisada_el = case when p_estado = 'pendiente' then null else now() end, actualizada_el = now()
   where id = p_par;
end $$;

revoke all on function public.dup_es_admin() from public, anon;
revoke all on function public.dup_fusionar(text, text, bigint) from public, anon;
revoke all on function public.dup_deshacer_fusion(bigint) from public, anon;
revoke all on function public.dup_decidir(bigint, text, text) from public, anon;
grant execute on function public.dup_es_admin() to authenticated;
grant execute on function public.dup_fusionar(text, text, bigint) to authenticated;
grant execute on function public.dup_deshacer_fusion(bigint) to authenticated;
grant execute on function public.dup_decidir(bigint, text, text) to authenticated;

select 'Botones del panel de duplicados instalados' as resultado;
