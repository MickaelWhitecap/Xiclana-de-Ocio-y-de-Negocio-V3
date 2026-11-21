-- Agenda de eventos de Chiclana (21-nov-2026).
-- La web pública lee los eventos publicados que no han terminado.
-- Solo el administrador puede crear, cambiar o borrar eventos.

create table if not exists public.eventos (
  id uuid primary key default gen_random_uuid(),
  titulo text not null check (length(titulo) between 2 and 180),
  fecha_inicio date not null,
  fecha_fin date check (fecha_fin is null or fecha_fin >= fecha_inicio),
  hora text check (hora is null or length(hora) <= 60),
  lugar text check (lugar is null or length(lugar) <= 240),
  listing_id text,
  categoria text not null default 'Otros' check (categoria in ('Música','Teatro y danza','Fiestas y tradiciones','Deporte','Exposiciones','Infantil','Gastronomía','Mercadillos y ferias','Rutas y naturaleza','Otros')),
  descripcion text check (descripcion is null or length(descripcion) <= 1000),
  precio text check (precio is null or length(precio) <= 80),
  enlace text check (enlace is null or enlace ~ '^https?://'),
  fuente text check (fuente is null or length(fuente) <= 240),
  publicado boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  updated_by uuid
);

comment on table public.eventos is 'Agenda de eventos de Chiclana. Texto propio; la fuente indica de dónde se tomó la fecha y el lugar.';
create index if not exists eventos_fechas_idx on public.eventos (fecha_inicio, fecha_fin) where publicado;

alter table public.eventos enable row level security;
revoke all on table public.eventos from anon, authenticated;
grant select on table public.eventos to anon, authenticated;
grant insert, update, delete on table public.eventos to authenticated;

drop policy if exists "Public can read upcoming events" on public.eventos;
create policy "Public can read upcoming events"
  on public.eventos for select to anon, authenticated
  using (publicado and coalesce(fecha_fin, fecha_inicio) >= (now() at time zone 'Europe/Madrid')::date - 1);

drop policy if exists "Xiclana admin can read all events" on public.eventos;
create policy "Xiclana admin can read all events"
  on public.eventos for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);

drop policy if exists "Xiclana admin can insert events" on public.eventos;
create policy "Xiclana admin can insert events"
  on public.eventos for insert to authenticated
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and updated_by = (select auth.uid()));

drop policy if exists "Xiclana admin can update events" on public.eventos;
create policy "Xiclana admin can update events"
  on public.eventos for update to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid)
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and updated_by = (select auth.uid()));

drop policy if exists "Xiclana admin can delete events" on public.eventos;
create policy "Xiclana admin can delete events"
  on public.eventos for delete to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
