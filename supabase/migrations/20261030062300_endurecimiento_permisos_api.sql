-- Aplicada en Supabase el 2026-10-30.
-- Endurece los privilegios de API: anon solo lectura de datos públicos;
-- authenticated mantiene operaciones sujetas a las políticas RLS.
revoke all privileges on table
  public.advertising_slots,
  public.listing_categories,
  public.listing_overrides,
  public.listing_proposals
from anon, authenticated;

grant select on table
  public.advertising_slots,
  public.listing_categories,
  public.listing_overrides
to anon;

grant select, insert, update, delete on table
  public.advertising_slots,
  public.listing_categories,
  public.listing_overrides,
  public.listing_proposals
to authenticated;
