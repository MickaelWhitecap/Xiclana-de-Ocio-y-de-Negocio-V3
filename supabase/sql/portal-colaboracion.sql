-- Preparación del portal privado de colaboración.
-- No ejecutar hasta aprobar la puesta en marcha de la prueba.
-- Esta tabla no contiene fichas: almacena únicamente hashes de enlaces temporales.

create table if not exists public.listing_access_tokens (
  id uuid primary key default gen_random_uuid(),
  listing_id text not null references public.listings(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id)
);

create index if not exists listing_access_tokens_listing_active_idx
  on public.listing_access_tokens (listing_id)
  where revoked_at is null;

alter table public.listing_access_tokens enable row level security;

revoke all on table public.listing_access_tokens from anon, authenticated;
grant all on table public.listing_access_tokens to service_role;
