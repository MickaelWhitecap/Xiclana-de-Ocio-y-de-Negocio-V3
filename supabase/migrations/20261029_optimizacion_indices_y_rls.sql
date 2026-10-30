-- Preparado para revisión; NO se ha ejecutado en Supabase.
-- Optimiza las cinco claves foráneas sin alterar datos ni permisos funcionales.
create index if not exists advertising_slots_updated_by_idx
  on public.advertising_slots (updated_by);
create index if not exists listing_categories_created_by_idx
  on public.listing_categories (created_by);
create index if not exists listing_overrides_updated_by_idx
  on public.listing_overrides (updated_by);
create index if not exists listing_proposals_created_by_idx
  on public.listing_proposals (created_by);
create index if not exists listing_proposals_reviewed_by_idx
  on public.listing_proposals (reviewed_by);

-- Sustituye las llamadas RLS por subconsultas escalares para evitar reevaluación por fila.
alter policy "Only Xiclana admin can delete advertising slots"
  on public.advertising_slots
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com');

alter policy "Only Xiclana admin can insert advertising slots"
  on public.advertising_slots
  with check (
    (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
    and updated_by = (select auth.uid())
  );

alter policy "Only Xiclana admin can update advertising slots"
  on public.advertising_slots
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
  with check (
    (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
    and updated_by = (select auth.uid())
  );

alter policy "Only Xiclana admin can delete listing categories"
  on public.listing_categories
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com');

alter policy "Only Xiclana admin can insert listing categories"
  on public.listing_categories
  with check (
    (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
    and created_by = (select auth.uid())
  );

alter policy "Only Xiclana admin can update listing categories"
  on public.listing_categories
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
  with check (
    (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
    and created_by = (select auth.uid())
  );

alter policy "Only Xiclana admin can delete overrides"
  on public.listing_overrides
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com');

alter policy "Only Xiclana admin can insert overrides"
  on public.listing_overrides
  with check (
    (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
    and updated_by = (select auth.uid())
  );

alter policy "Only Xiclana admin can update overrides"
  on public.listing_overrides
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
  with check (
    (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
    and updated_by = (select auth.uid())
  );

alter policy "Xiclana admin can delete proposals"
  on public.listing_proposals
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com');

alter policy "Xiclana admin can insert proposals"
  on public.listing_proposals
  with check (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com');

alter policy "Xiclana admin can read proposals"
  on public.listing_proposals
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com');

alter policy "Xiclana admin can update proposals"
  on public.listing_proposals
  using (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com')
  with check (((select auth.jwt()) ->> 'email') = 'surferomc@gmail.com');
