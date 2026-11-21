-- DESHACER los botones del panel de duplicados (21-nov-2026).
-- Quita las funciones de fusionar / deshacer / marcar como distintas.
-- No toca las fichas: las fusiones ya hechas se quedan como están
-- (si quieres deshacer alguna, hazlo ANTES desde Administración o con
--  select public.dup_deshacer_fusion(<número de registro>); ).
-- La tabla dup_fusiones (copias de antes de cada fusión) se conserva.
-- Pegar ENTERO en Supabase > SQL Editor y pulsar Run.

drop function if exists public.dup_decidir(bigint, text, text);
drop function if exists public.dup_deshacer_fusion(bigint);
drop function if exists public.dup_fusionar(text, text, bigint);
drop function if exists public.dup_es_admin();
drop function if exists public.dup_contacto_igual(text, text, text);

select 'Botones del panel de duplicados quitados' as resultado;
