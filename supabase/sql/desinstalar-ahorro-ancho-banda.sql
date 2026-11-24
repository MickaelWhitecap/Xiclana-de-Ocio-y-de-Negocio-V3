-- Deshace instalar-ahorro-ancho-banda.sql.
-- Los programas siguen funcionando sin estas funciones (vuelven al método antiguo,
-- que gasta mucho más ancho de banda).
drop function if exists public.xiclana_fusionar_catalogo(jsonb, timestamptz);
drop function if exists public.xiclana_limpiar_checkpoint_rad(text);
notify pgrst, 'reload schema';
