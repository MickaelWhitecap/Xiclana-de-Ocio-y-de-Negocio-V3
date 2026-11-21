-- =====================================================================
-- VIGILANCIA DE FICHAS DUPLICADAS · Xiclana de Ocio y de Negocio
-- 21-nov-2026
--
-- Qué hace (sin coste: todo funciona dentro de la base de datos):
--   1. Guarda para cada ficha sus "huellas": nombre limpio, teléfonos,
--      correos, web, calle, número y coordenadas.
--   2. BARRERA: cada ficha nueva que entre (importación, alta manual,
--      portal...) se compara con las que ya hay.
--        · Si es casi seguro un duplicado, entra OCULTA (no publicada) y
--          con la nota «posible_duplicado_de».
--        · Si es probable o dudoso, entra normal pero queda en la lista
--          de revisión.
--        · Si su identificador ya se fusionó o se borró antes, NO entra
--          (así las importaciones no resucitan fichas retiradas).
--   3. LISTA DE REVISIÓN: tabla duplicados_revision con cada pareja
--      sospechosa, sus puntos y los motivos. Lo que se marque como
--      «distintas» no vuelve a salir.
--   4. REVISIÓN DIARIA: a las 04:45 (hora de Madrid) repasa todo el
--      catálogo y añade las parejas nuevas a la lista.
--
-- No cambia ni borra ninguna ficha existente.
-- Para deshacerlo todo: desinstalar-vigilancia-duplicados.sql
--
-- Pegar ENTERO en Supabase > SQL Editor y pulsar Run.
-- =====================================================================

-- ---------- 1. Tablas ----------

create table if not exists public.dup_huellas (
  id text primary key,
  nn text not null default '',          -- nombre limpio (minúsculas, sin acentos)
  tokens text[] not null default '{}',  -- palabras del nombre
  tels text[] not null default '{}',    -- teléfonos (9 cifras)
  mails text[] not null default '{}',
  webs text[] not null default '{}',    -- dominio de la web
  calle text[] not null default '{}',   -- palabras de la calle
  num text,                             -- número de la calle
  lat double precision,
  lon double precision,
  activa boolean not null default true,
  actualizada timestamptz not null default now()
);
create index if not exists dup_huellas_tokens_idx on public.dup_huellas using gin (tokens);
create index if not exists dup_huellas_tels_idx on public.dup_huellas using gin (tels);
create index if not exists dup_huellas_mails_idx on public.dup_huellas using gin (mails);
create index if not exists dup_huellas_webs_idx on public.dup_huellas using gin (webs);
create index if not exists dup_huellas_nn_idx on public.dup_huellas (nn);
create index if not exists dup_huellas_pos_idx on public.dup_huellas (lat, lon);

-- Cuántas fichas usan cada palabra del nombre (para dar más peso a las raras).
create table if not exists public.dup_pesos (
  t text primary key,
  df integer not null
);

-- Identificadores que no deben volver a entrar (fusionados o borrados).
create table if not exists public.dup_vetadas (
  id text primary key,
  motivo text not null,
  absorbida_en text,
  fecha timestamptz not null default now()
);

-- Altas frenadas por la barrera (para poder revisarlas).
create table if not exists public.dup_bloqueos (
  id bigserial primary key,
  ficha_id text not null,
  nombre text,
  motivo text not null,
  datos jsonb,
  fecha timestamptz not null default now()
);

-- Lista de parejas sospechosas.
create table if not exists public.duplicados_revision (
  id bigserial primary key,
  ficha_a text not null,
  ficha_b text not null,
  puntos integer not null,
  clase text not null check (clase in ('casi seguro','probable','dudoso')),
  motivos text not null,
  estado text not null default 'pendiente' check (estado in ('pendiente','fusionadas','distintas','cerrada')),
  detectada_el timestamptz not null default now(),
  actualizada_el timestamptz not null default now(),
  revisada_el timestamptz,
  nota text,
  constraint duplicados_revision_orden check (ficha_a < ficha_b),
  constraint duplicados_revision_unica unique (ficha_a, ficha_b)
);
create index if not exists duplicados_revision_estado_idx on public.duplicados_revision (estado, puntos desc);

-- Registro de cada revisión completa.
create table if not exists public.dup_ejecuciones (
  id bigserial primary key,
  fecha timestamptz not null default now(),
  fichas integer,
  parejas_nuevas integer,
  pendientes integer,
  casi_seguras integer,
  segundos numeric
);

-- Solo el administrador puede leerlas y cambiarlas desde la web.
alter table public.dup_huellas enable row level security;
alter table public.dup_pesos enable row level security;
alter table public.dup_vetadas enable row level security;
alter table public.dup_bloqueos enable row level security;
alter table public.duplicados_revision enable row level security;
alter table public.dup_ejecuciones enable row level security;
revoke all on public.dup_huellas, public.dup_pesos, public.dup_vetadas, public.dup_bloqueos,
              public.duplicados_revision, public.dup_ejecuciones from anon, authenticated;
grant select on public.dup_vetadas, public.dup_bloqueos, public.duplicados_revision, public.dup_ejecuciones to authenticated;
grant update (estado, revisada_el, nota) on public.duplicados_revision to authenticated;

drop policy if exists "Xiclana admin lee duplicados" on public.duplicados_revision;
create policy "Xiclana admin lee duplicados" on public.duplicados_revision for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
drop policy if exists "Xiclana admin revisa duplicados" on public.duplicados_revision;
create policy "Xiclana admin revisa duplicados" on public.duplicados_revision for update to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid)
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
drop policy if exists "Xiclana admin lee vetadas" on public.dup_vetadas;
create policy "Xiclana admin lee vetadas" on public.dup_vetadas for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
drop policy if exists "Xiclana admin lee bloqueos" on public.dup_bloqueos;
create policy "Xiclana admin lee bloqueos" on public.dup_bloqueos for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
drop policy if exists "Xiclana admin lee ejecuciones" on public.dup_ejecuciones;
create policy "Xiclana admin lee ejecuciones" on public.dup_ejecuciones for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);

-- ---------- 2. Huellas de una ficha ----------

create or replace function public.dup_limpiar(t text) returns text
language sql immutable  set search_path = public as $$
  select trim(regexp_replace(
    translate(lower(coalesce(t,'')),'áéíóúàèìòùäëïöüâêîôûñç','aeiouaeiouaeiouaeiounc'),
    '[^a-z0-9]+',' ','g'))
$$;

create or replace function public.dup_calcular_huellas(p_id text, d jsonb, p_activa boolean default true)
returns public.dup_huellas
language plpgsql immutable  set search_path = public as $$
declare
  h public.dup_huellas;
  ad text;
  la text; lo text;
begin
  h.id := p_id;
  h.nn := public.dup_limpiar(d->>'n');
  h.tokens := array(
    select distinct t from regexp_split_to_table(h.nn,' ') t
    where length(t) >= 2
      and t not in ('de','la','el','los','las','del','y','en','the','and','of','al','sl','sa','slu','cb','chiclana','frontera'));
  h.tels := array(
    select distinct right(m[1],9)
    from regexp_matches(regexp_replace(coalesce(d->>'p',''),'[\s\.\-\(\)]','','g'),'(?:\+?34|0034)?([6789]\d{8})','g') m);
  h.mails := array(
    select distinct m[1]
    from regexp_matches(lower(coalesce(d->>'e','')),'([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]+)','g') m);
  h.webs := array(
    select x from (select regexp_replace(regexp_replace(lower(coalesce(d->>'w','')),'^\s*https?://(www\.)?',''),'[/:?#\s].*$','') x) z
    where x like '%.%'
      and x !~ '(facebook|instagram|google|goo\.gl|booking|tripadvisor|linktr|wa\.me|whatsapp|twitter|x\.com|youtube|tiktok|wixsite|blogspot|business\.site|negocio\.site|yelp|thefork|eltenedor|just-eat|glovo)');
  ad := regexp_replace(regexp_replace(
          translate(lower(coalesce(d->>'a','')),'áéíóúàèìòùäëïöüâêîôûñç','aeiouaeiouaeiouaeiounc'),
          'chiclana.*$',''), '\m11\d\d\d\M','','g');
  h.num := substring(ad from '\m(\d{1,4})\M');
  h.calle := array(
    select distinct t from regexp_split_to_table(
      regexp_replace(split_part(regexp_replace(ad,'\m\d{1,4}\M','#'),'#',1),'[^a-z]+',' ','g'),' ') t
    where length(t) >= 3
      and t not in ('calle','avenida','avda','carretera','ctra','plaza','camino','urbanizacion','urb','paseo',
                    'travesia','poligono','pol','industrial','ind','local','bajo','centro','comercial','del',
                    'los','las','la','el','de','sin','numero','edificio','esquina'));
  la := d->>'lat'; lo := d->>'lon';
  h.lat := case when la ~ '^-?\d+(\.\d+)?$' then la::double precision end;
  h.lon := case when lo ~ '^-?\d+(\.\d+)?$' then lo::double precision end;
  h.activa := p_activa;
  h.actualizada := now();
  return h;
end $$;

-- ---------- 3. Comparar dos fichas: puntos y motivos ----------
-- Puntos (se suman):
--   mismo teléfono +3 (si lo comparten muchas fichas, +1)
--   mismo correo   +3 (si lo comparten muchas fichas, +1)
--   misma web      +2 (si la comparten muchas fichas, 0: suele ser una cadena)
--   («muchas»: 3 o más; o 5 o más si los nombres se parecen)
--   (lo de contacto suma como mucho 5)
--   (un fijo de fuera de la provincia, como 902 o 91, se toma como centralita de cadena)
--   nombre igual o casi igual +3, uno dentro del otro o parecido +2, algo parecido +1,
--   nada parecido -2 (y entonces, sin un contacto propio en común, como mucho «dudoso»)
--   misma calle y número +2, misma calle +1, calle o número distintos -1
--   a menos de 30 m +2, a menos de 100 m +1
--   los dos tienen teléfono y no coincide ninguno -1
--   nombre de cadena (3 o más fichas se llaman igual) -2
-- 6 o más: casi seguro · 4 o 5: probable · 3: dudoso
-- (dos fichas con el mismo nombre exacto que no es de cadena salen siempre, al menos como dudosas)

create or replace function public.dup_comparar(a public.dup_huellas, b public.dup_huellas,
  out puntos integer, out clase text, out motivos text)
language plpgsql stable  set search_path = public as $$
declare
  n_total numeric;
  sa numeric := 0; sb numeric := 0; sh numeric := 0;
  sim numeric := 0;
  igual boolean;
  pc integer := 0;
  m text[] := '{}';
  f integer;
  v text;
  dist numeric;
  ambas_dir boolean; misma_calle boolean; mismo_num boolean; otro_num boolean;
  cadena boolean := false;
  contiene boolean := false;
  fuerte boolean := false;   -- comparten un teléfono o correo propio (no de cadena)
  p_nombre integer;
begin
  select greatest(coalesce(max(df),1),1) into n_total from public.dup_pesos where t = '#total';

  select coalesce(sum(ln(n_total / greatest(coalesce(p.df,1),1))),0) into sa
    from unnest(a.tokens) u(t) left join public.dup_pesos p on p.t = u.t;
  select coalesce(sum(ln(n_total / greatest(coalesce(p.df,1),1))),0) into sb
    from unnest(b.tokens) u(t) left join public.dup_pesos p on p.t = u.t;
  select coalesce(sum(ln(n_total / greatest(coalesce(p.df,1),1))),0) into sh
    from (select unnest(a.tokens) intersect select unnest(b.tokens)) x(t) left join public.dup_pesos p on p.t = x.t;

  -- sim: parecido de los dos nombres completos.
  -- contiene: un nombre está dentro del otro y comparten una palabra rara
  -- ("Garola" / "Agricentro Garola"); cuenta algo menos que un nombre igual.
  if sa + sb > 0 then sim := 2 * sh / (sa + sb); end if;
  contiene := sh >= 6.5 and least(sa,sb) > 0 and sh / least(sa,sb) >= 0.8;
  igual := a.nn <> '' and a.nn = b.nn;
  if igual then
    select count(*) >= 3 into cadena from public.dup_huellas where activa and nn = a.nn;
  end if;

  -- Nombre
  p_nombre := case when igual or sim >= 0.8 then 3 when contiene or sim >= 0.6 then 2 when sim >= 0.4 then 1
                   when sim < 0.2 then -2 else 0 end;

  -- Contacto. Un dato que comparten muchas fichas (cadenas, hoteles con varios
  -- restaurantes, el Ayuntamiento) cuenta poco, salvo que los nombres se parezcan
  -- y sean pocas fichas (el mismo negocio repetido 3 o 4 veces).
  foreach v in array (select coalesce(array_agg(x),'{}') from (select unnest(a.tels) intersect select unnest(b.tels)) s(x)) loop
    select count(*) into f from public.dup_huellas where activa and tels @> array[v];
    -- Un fijo de fuera de la provincia (902, 91...) suele ser la centralita de una cadena.
    if v ~ '^[89]' and v !~ '^(956|856)' then f := greatest(f, 99); end if;
    if 'mismo teléfono' = any(m) then null;
    elsif f <= 2 or (f <= 4 and p_nombre >= 2) then pc := pc + 3; fuerte := true; m := m || 'mismo teléfono'::text;
    elsif f >= 99 then pc := pc + 1; m := m || 'mismo teléfono (centralita de cadena)'::text;
    else pc := pc + 1; m := m || ('mismo teléfono (lo comparten ' || f || ' fichas)'); end if;
  end loop;
  foreach v in array (select coalesce(array_agg(x),'{}') from (select unnest(a.mails) intersect select unnest(b.mails)) s(x)) loop
    select count(*) into f from public.dup_huellas where activa and mails @> array[v];
    if f <= 2 or (f <= 4 and p_nombre >= 2) then pc := pc + 3; fuerte := true; m := m || 'mismo correo'::text;
    else pc := pc + 1; m := m || ('mismo correo (lo comparten ' || f || ' fichas)'); end if;
  end loop;
  foreach v in array (select coalesce(array_agg(x),'{}') from (select unnest(a.webs) intersect select unnest(b.webs)) s(x)) loop
    select count(*) into f from public.dup_huellas where activa and webs @> array[v];
    if f <= 2 or (f <= 4 and p_nombre >= 2) then pc := pc + 2; m := m || 'misma web'::text;
    else m := m || ('misma web (la comparten ' || f || ' fichas)'); end if;
  end loop;
  puntos := least(pc, 5) + p_nombre;
  m := m || case when igual then 'mismo nombre'
                 when p_nombre > 0 then 'nombre parecido (' || round(sim*100) || ' %)'
                 when p_nombre < 0 then 'nombre distinto'
                 else 'nombre poco parecido (' || round(sim*100) || ' %)' end;

  -- Dirección
  ambas_dir := cardinality(a.calle) > 0 and cardinality(b.calle) > 0;
  misma_calle := ambas_dir and (a.calle <@ b.calle or b.calle <@ a.calle);
  mismo_num := a.num is not null and b.num is not null and a.num = b.num;
  otro_num := a.num is not null and b.num is not null and a.num <> b.num;
  if misma_calle and mismo_num then puntos := puntos + 2; m := m || 'misma dirección'::text;
  elsif misma_calle and not otro_num then puntos := puntos + 1; m := m || 'misma calle'::text;
  elsif ambas_dir then puntos := puntos - 1; m := m || case when misma_calle then 'otro número de la calle' else 'otra calle' end;
  end if;

  -- Distancia (las coordenadas de algunas fuentes son poco precisas: lejos no resta)
  if a.lat is not null and b.lat is not null then
    dist := 6371000 * 2 * asin(sqrt(power(sin(radians(b.lat-a.lat)/2),2)
            + cos(radians(a.lat))*cos(radians(b.lat))*power(sin(radians(b.lon-a.lon)/2),2)));
    if dist < 30 then puntos := puntos + 2; elsif dist < 100 then puntos := puntos + 1; end if;
    m := m || ('a ' || case when dist < 1000 then round(dist)::text || ' m' else round(dist/1000.0,1)::text || ' km' end);
  end if;

  if cardinality(a.tels) > 0 and cardinality(b.tels) > 0 and not (a.tels && b.tels) then
    puntos := puntos - 1; m := m || 'teléfonos distintos'::text;
  end if;
  if cadena then puntos := puntos - 2; m := m || 'nombre de cadena'::text; end if;
  -- Nombres que no se parecen y sin un contacto propio en común: como mucho «dudoso»
  -- (p. ej. dos negocios distintos en el mismo edificio o centro comercial).
  if p_nombre <= 0 and not fuerte then puntos := least(puntos, 3); end if;

  clase := case when puntos >= 6 then 'casi seguro' when puntos >= 4 then 'probable'
                when puntos >= 3 or (igual and not cadena) then 'dudoso' end;
  motivos := array_to_string(m, ' · ');
end $$;

-- ---------- 4. Buscar parecidas a una ficha ----------

-- solo_mayores: en la revisión completa cada pareja se mira una sola vez.
create or replace function public.dup_buscar(h public.dup_huellas, solo_mayores boolean default false)
returns table (otra text, puntos integer, clase text, motivos text)
language plpgsql stable  set search_path = public as $$
declare raras text[];
begin
  select coalesce(array_agg(u.t),'{}') into raras from unnest(h.tokens) u(t)
    left join public.dup_pesos p on p.t = u.t where coalesce(p.df,1) <= 25;
  return query
  with cand as materialized (
    select o.* from public.dup_huellas o where o.activa and o.id <> h.id and o.tokens && raras
    union select o.* from public.dup_huellas o where o.activa and o.id <> h.id and o.tels && h.tels
    union select o.* from public.dup_huellas o where o.activa and o.id <> h.id and o.mails && h.mails
    union select o.* from public.dup_huellas o where o.activa and o.id <> h.id and o.webs && h.webs
    union select o.* from public.dup_huellas o where o.activa and o.id <> h.id and h.nn <> '' and o.nn = h.nn
    -- cerca (unos 50 m) y con alguna palabra del nombre en común, aunque sea corriente ("Bar", "Farmacia")
    union select o.* from public.dup_huellas o where o.activa and o.id <> h.id and h.lat is not null
          and o.lat between h.lat - 0.0005 and h.lat + 0.0005 and o.lon between h.lon - 0.0006 and h.lon + 0.0006
          and o.tokens && h.tokens)
  select c.id, r.puntos, r.clase, r.motivos
  from cand c, lateral public.dup_comparar(h, c::public.dup_huellas) r
  where r.clase is not null and (not solo_mayores or c.id > h.id);
end $$;

-- Guarda en la lista las parejas de una ficha (sin tocar las ya decididas).
create or replace function public.dup_anotar(h public.dup_huellas, solo_mayores boolean default false)
returns integer
language plpgsql  set search_path = public as $$
declare n integer;
begin
  with r as (select * from public.dup_buscar(h, solo_mayores)),
  ins as (
    insert into public.duplicados_revision (ficha_a, ficha_b, puntos, clase, motivos)
    select least(h.id, r.otra), greatest(h.id, r.otra), r.puntos, r.clase, r.motivos from r
    on conflict (ficha_a, ficha_b) do update
      set puntos = excluded.puntos, clase = excluded.clase, motivos = excluded.motivos, actualizada_el = now()
      , estado = 'pendiente'
      where duplicados_revision.estado in ('pendiente','cerrada')
    returning (xmax = 0) nueva)
  select count(*) filter (where nueva) into n from ins;
  return n;
end $$;

-- ---------- 5. Barrera en la tabla de fichas ----------

create or replace function public.dup_barrera_antes()
returns trigger
language plpgsql security definer set search_path = public as $$
declare
  h public.dup_huellas;
  mejor record;
  absorbida text;
begin
  -- Escape para scripts de deshacer: set local xiclana.saltar_vigilancia = 'si';
  if coalesce(current_setting('xiclana.saltar_vigilancia', true),'') = 'si' then return new; end if;
  -- Si la ficha ya existe, es una actualización (upsert): no se frena.
  if exists (select 1 from public.listings where id = new.id) then return new; end if;
  if coalesce(new.is_deleted,false) then return new; end if;

  -- ¿Se fusionó o se borró antes?
  select l.id into absorbida from public.listings l
   where not l.is_deleted and l.data->'ids_alternativos' ? new.id limit 1;
  if absorbida is null then
    select coalesce(absorbida_en, '(borrada)') into absorbida from public.dup_vetadas where id = new.id;
  end if;
  if absorbida is not null and coalesce(new.data->>'alta_confirmada','') <> 'si' then
    insert into public.dup_bloqueos (ficha_id, nombre, motivo, datos)
    values (new.id, new.data->>'n', 'ya se fusionó o se retiró antes (' || absorbida || ')', new.data);
    return null;   -- no entra
  end if;

  if coalesce(new.data->>'alta_confirmada','') = 'si' then return new; end if;

  h := public.dup_calcular_huellas(new.id, new.data);
  select * into mejor from public.dup_buscar(h) order by puntos desc limit 1;
  if mejor.otra is not null and mejor.clase = 'casi seguro' then
    new.is_published := false;
    new.data := new.data || jsonb_build_object(
      'posible_duplicado_de', mejor.otra,
      'posible_duplicado_motivos', mejor.motivos,
      'posible_duplicado_fecha', to_char(now() at time zone 'Europe/Madrid','YYYY-MM-DD HH24:MI'));
    insert into public.dup_bloqueos (ficha_id, nombre, motivo, datos)
    values (new.id, new.data->>'n', 'entra oculta: casi seguro duplicado de ' || mejor.otra || ' (' || mejor.motivos || ')', null);
  end if;
  return new;
end $$;

create or replace function public.dup_barrera_despues()
returns trigger
language plpgsql security definer set search_path = public as $$
declare h public.dup_huellas;
begin
  if tg_op = 'DELETE' then
    update public.dup_huellas set activa = false where id = old.id;
    insert into public.dup_vetadas (id, motivo) values (old.id, 'borrada') on conflict (id) do nothing;
    return old;
  end if;
  h := public.dup_calcular_huellas(new.id, new.data, not coalesce(new.is_deleted,false));
  insert into public.dup_huellas values (h.*)
    on conflict (id) do update set nn = excluded.nn, tokens = excluded.tokens, tels = excluded.tels,
      mails = excluded.mails, webs = excluded.webs, calle = excluded.calle, num = excluded.num,
      lat = excluded.lat, lon = excluded.lon, activa = excluded.activa, actualizada = now();
  if coalesce(new.is_deleted,false) then
    insert into public.dup_vetadas (id, motivo, absorbida_en)
    values (new.id, 'retirada', new.data->>'fusionada_en') on conflict (id) do nothing;
    update public.duplicados_revision set estado = 'cerrada', actualizada_el = now()
     where estado = 'pendiente' and (ficha_a = new.id or ficha_b = new.id);
  else
    delete from public.dup_vetadas where id = new.id;  -- restaurada desde la papelera
    if tg_op = 'INSERT' or new.data is distinct from old.data then
      perform public.dup_anotar(h);
    end if;
  end if;
  return new;
end $$;

drop trigger if exists dup_barrera_antes on public.listings;
create trigger dup_barrera_antes before insert on public.listings
  for each row execute function public.dup_barrera_antes();
drop trigger if exists dup_barrera_despues on public.listings;
create trigger dup_barrera_despues after insert or update of data, is_deleted or delete on public.listings
  for each row execute function public.dup_barrera_despues();

-- ---------- 6. Revisión completa (diaria) ----------

create or replace function public.dup_revisar_todo()
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  t0 timestamptz := clock_timestamp();
  h public.dup_huellas;
  nuevas integer := 0;
  r jsonb;
begin
  -- Rehacer huellas de todas las fichas
  insert into public.dup_huellas
    select (public.dup_calcular_huellas(l.id, l.data, not l.is_deleted)).* from public.listings l
  on conflict (id) do update set nn = excluded.nn, tokens = excluded.tokens, tels = excluded.tels,
      mails = excluded.mails, webs = excluded.webs, calle = excluded.calle, num = excluded.num,
      lat = excluded.lat, lon = excluded.lon, activa = excluded.activa, actualizada = now();
  update public.dup_huellas set activa = false where not exists (select 1 from public.listings l where l.id = dup_huellas.id);

  -- Pesos de las palabras
  delete from public.dup_pesos;
  insert into public.dup_pesos select u.t, count(*) from public.dup_huellas, unnest(tokens) u(t) where activa group by u.t;
  insert into public.dup_pesos values ('#total', (select count(*) from public.dup_huellas where activa));

  -- Comparar cada ficha con sus parecidas
  for h in select * from public.dup_huellas where activa order by id loop
    nuevas := nuevas + public.dup_anotar(h, true);
  end loop;

  -- Cerrar parejas pendientes en las que una ficha ya no está
  update public.duplicados_revision d set estado = 'cerrada', actualizada_el = now()
   where estado = 'pendiente' and exists (select 1 from public.dup_huellas x where x.id in (d.ficha_a, d.ficha_b) and not x.activa);

  insert into public.dup_ejecuciones (fichas, parejas_nuevas, pendientes, casi_seguras, segundos)
  select (select count(*) from public.dup_huellas where activa), nuevas,
         count(*) filter (where estado='pendiente'),
         count(*) filter (where estado='pendiente' and clase='casi seguro'),
         round(extract(epoch from clock_timestamp() - t0)::numeric, 1)
    from public.duplicados_revision
  returning jsonb_build_object('fichas', fichas, 'parejas_nuevas', parejas_nuevas, 'pendientes', pendientes,
                               'casi_seguras', casi_seguras, 'segundos', segundos) into r;
  return r;
end $$;

revoke all on function public.dup_revisar_todo() from public, anon, authenticated;
revoke all on function public.dup_barrera_antes() from public, anon, authenticated;
revoke all on function public.dup_barrera_despues() from public, anon, authenticated;
revoke all on function public.dup_anotar(public.dup_huellas, boolean) from public, anon, authenticated;

-- ---------- 7. Datos iniciales ----------

-- Fichas ya retiradas que no deben volver: las 81 de la papelera vaciada el 20-nov
-- y las fusionadas (aparecen en ids_alternativos de la ficha que se quedó).
insert into public.dup_vetadas (id, motivo, absorbida_en)
  select id, 'papelera vaciada el 20-nov-2026', data->>'fusionada_en' from public.listings_copia_papelera_20261120
  on conflict (id) do nothing;
insert into public.dup_vetadas (id, motivo, absorbida_en)
  select x, 'fusionada', l.id from public.listings l, jsonb_array_elements_text(
    case when jsonb_typeof(l.data->'ids_alternativos')='array' then l.data->'ids_alternativos' else '[]' end) x
  where not l.is_deleted
  on conflict (id) do nothing;

-- Primera revisión completa (tarda unos segundos)
select public.dup_revisar_todo() as resultado;

-- ---------- 8. Revisión automática diaria (pg_cron, gratuito en Supabase) ----------
create extension if not exists pg_cron with schema pg_catalog;
select cron.unschedule(jobid) from cron.job where jobname = 'revisar-duplicados';
select cron.schedule('revisar-duplicados', '45 3 * * *', $$select public.dup_revisar_todo()$$);
-- 03:45 UTC = 04:45 en Madrid en invierno (05:45 en verano).

-- ---------- 9. Resumen ----------
select clase, count(*) as parejas
from public.duplicados_revision where estado = 'pendiente'
group by clase order by min(case clase when 'casi seguro' then 1 when 'probable' then 2 else 3 end);
