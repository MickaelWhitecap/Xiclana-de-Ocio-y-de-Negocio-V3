-- El sincronizador del catálogo necesita leer los campos publicados de overrides.
-- Se limita el acceso anónimo a las columnas que consume v3/actualizar.py;
-- updated_by y cualquier otra columna interna siguen fuera del alcance de anon.
grant select (listing_id, fields, is_new, verified_at, updated_at)
  on table public.listing_overrides to anon;

create policy "Public can read catalog override fields"
  on public.listing_overrides for select to anon
  using (true);
