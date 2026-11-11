drop policy if exists "Public can read catalog override fields" on public.listing_overrides;
revoke all on table public.listing_overrides from anon;
