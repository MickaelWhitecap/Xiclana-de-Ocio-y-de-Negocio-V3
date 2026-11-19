-- Preparación del portal privado de colaboración (PR #41).
-- No ejecutar hasta aprobar la puesta en marcha de la prueba.
-- Esta tabla no contiene fichas: almacena únicamente hashes de enlaces temporales.
-- Se puede ejecutar más de una vez sin efectos duplicados.

-- 0. Comprobaciones previas (solo lectura). Deben devolver:
--    listings.id -> text, y listing_proposals con las columnas usadas por el portal.
select table_name, column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and ((table_name = 'listings' and column_name in ('id', 'data', 'is_published', 'is_deleted'))
    or (table_name = 'listing_proposals' and column_name in ('fields', 'status', 'source_name', 'source_url', 'source_checked_at', 'notes', 'created_by')))
order by table_name, column_name;

-- 1. Tabla de enlaces privados.
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

create index if not exists listing_access_tokens_created_by_idx
  on public.listing_access_tokens (created_by);

alter table public.listing_access_tokens enable row level security;

revoke all on table public.listing_access_tokens from anon, authenticated;
grant all on table public.listing_access_tokens to service_role;

-- 2. Las propuestas del portal las inserta la Edge Function sin usuario asociado.
--    Si created_by fuera obligatorio, la inserción fallaría; se permite vacío.
--    Las políticas RLS existentes siguen exigiendo created_by = auth.uid() a las cuentas con sesión.
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'listing_proposals'
      and column_name = 'created_by' and is_nullable = 'NO'
  ) then
    alter table public.listing_proposals alter column created_by drop not null;
    raise notice 'listing_proposals.created_by ahora admite valores vacíos.';
  end if;
end $$;

-- 3. Índice para contar rápidamente las propuestas pendientes de cada ficha.
create index if not exists listing_proposals_pending_update_target_idx
  on public.listing_proposals ((fields->>'_xiclana_update_target_id'))
  where status = 'pending';

-- 4. Verificación posterior (solo lectura). Esperado: rls = true y ninguna fila para anon/authenticated.
select relname, relrowsecurity as rls
from pg_class where oid = 'public.listing_access_tokens'::regclass;

select grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public' and table_name = 'listing_access_tokens'
  and grantee in ('anon', 'authenticated');

-- Marcha atrás (solo si se abandona la prueba; borra todos los enlaces emitidos):
-- drop index if exists public.listing_proposals_pending_update_target_idx;
-- drop table if exists public.listing_access_tokens;
