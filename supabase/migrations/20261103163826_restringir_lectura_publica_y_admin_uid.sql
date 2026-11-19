-- Limita la lectura de datos administrativos al usuario administrador.
-- El catálogo público se sirve desde fichas_completas.json; publicidad conserva lectura anónima.
revoke select on table public.listing_overrides, public.listing_categories from anon;

drop policy if exists "Public can read listing overrides" on public.listing_overrides;
drop policy if exists "Public can read listing categories" on public.listing_categories;

create policy "Only Xiclana admin can read overrides"
  on public.listing_overrides for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
create policy "Only Xiclana admin can read listing categories"
  on public.listing_categories for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);

drop policy if exists "Only Xiclana admin can delete advertising slots" on public.advertising_slots;
drop policy if exists "Only Xiclana admin can insert advertising slots" on public.advertising_slots;
drop policy if exists "Only Xiclana admin can update advertising slots" on public.advertising_slots;
drop policy if exists "Only Xiclana admin can delete listing categories" on public.listing_categories;
drop policy if exists "Only Xiclana admin can insert listing categories" on public.listing_categories;
drop policy if exists "Only Xiclana admin can update listing categories" on public.listing_categories;
drop policy if exists "Only Xiclana admin can delete overrides" on public.listing_overrides;
drop policy if exists "Only Xiclana admin can insert overrides" on public.listing_overrides;
drop policy if exists "Only Xiclana admin can update overrides" on public.listing_overrides;
drop policy if exists "Xiclana admin can delete proposals" on public.listing_proposals;
drop policy if exists "Xiclana admin can insert proposals" on public.listing_proposals;
drop policy if exists "Xiclana admin can read proposals" on public.listing_proposals;
drop policy if exists "Xiclana admin can update proposals" on public.listing_proposals;

create policy "Xiclana admin can delete advertising slots"
  on public.advertising_slots for delete to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
create policy "Xiclana admin can insert advertising slots"
  on public.advertising_slots for insert to authenticated
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and updated_by = (select auth.uid()));
create policy "Xiclana admin can update advertising slots"
  on public.advertising_slots for update to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid)
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and updated_by = (select auth.uid()));

create policy "Xiclana admin can delete listing categories"
  on public.listing_categories for delete to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
create policy "Xiclana admin can insert listing categories"
  on public.listing_categories for insert to authenticated
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and created_by = (select auth.uid()));
create policy "Xiclana admin can update listing categories"
  on public.listing_categories for update to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid)
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and created_by = (select auth.uid()));

create policy "Xiclana admin can delete overrides"
  on public.listing_overrides for delete to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
create policy "Xiclana admin can insert overrides"
  on public.listing_overrides for insert to authenticated
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and updated_by = (select auth.uid()));
create policy "Xiclana admin can update overrides"
  on public.listing_overrides for update to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid)
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and updated_by = (select auth.uid()));

create policy "Xiclana admin can delete proposals"
  on public.listing_proposals for delete to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
create policy "Xiclana admin can insert proposals"
  on public.listing_proposals for insert to authenticated
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid and created_by = (select auth.uid()));
create policy "Xiclana admin can read proposals"
  on public.listing_proposals for select to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
create policy "Xiclana admin can update proposals"
  on public.listing_proposals for update to authenticated
  using ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid)
  with check ((select auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);
