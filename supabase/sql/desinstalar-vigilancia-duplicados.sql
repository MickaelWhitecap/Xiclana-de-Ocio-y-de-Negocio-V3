-- =====================================================================
-- DESHACER la vigilancia de fichas duplicadas (21-nov-2026)
-- Quita la barrera, la revisión diaria y las tablas de apoyo.
-- Las fichas que la barrera dejó ocultas por "posible duplicado" se vuelven a publicar.
-- Ojo: se pierde la lista de parejas revisadas (incluidas las marcadas como «distintas»).
-- Pegar ENTERO en Supabase > SQL Editor y pulsar Run.
-- =====================================================================

-- 1. Volver a publicar las fichas que entraron ocultas por la barrera
update public.listings
   set is_published = true,
       data = data - 'posible_duplicado_de' - 'posible_duplicado_motivos' - 'posible_duplicado_fecha'
 where data ? 'posible_duplicado_de' and not is_deleted;

-- 2. Quitar la barrera
drop trigger if exists dup_barrera_antes on public.listings;
drop trigger if exists dup_barrera_despues on public.listings;

-- 3. Quitar la revisión diaria
select cron.unschedule(jobid) from cron.job where jobname = 'revisar-duplicados';

-- 4. Quitar funciones y tablas
drop function if exists public.dup_revisar_todo();
drop function if exists public.dup_barrera_antes();
drop function if exists public.dup_barrera_despues();
drop function if exists public.dup_anotar(public.dup_huellas, boolean);
drop function if exists public.dup_buscar(public.dup_huellas, boolean);
drop function if exists public.dup_comparar(public.dup_huellas, public.dup_huellas);
drop function if exists public.dup_calcular_huellas(text, jsonb, boolean);
drop function if exists public.dup_limpiar(text);
drop table if exists public.dup_ejecuciones, public.duplicados_revision, public.dup_bloqueos,
                     public.dup_vetadas, public.dup_pesos, public.dup_huellas;

select 'Vigilancia de duplicados desinstalada' as resultado;
