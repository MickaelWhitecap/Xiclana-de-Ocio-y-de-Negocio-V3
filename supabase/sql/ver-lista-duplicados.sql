-- Ver la lista de parejas sospechosas (no cambia nada).
-- Pegar en Supabase > SQL Editor y pulsar Run. Sale ordenada de más a menos segura.
-- Para ver solo una clase, cambia el final: where d.estado = 'pendiente' and d.clase = 'casi seguro'

select d.id as n,
       d.clase,
       d.puntos,
       a.data->>'n' as nombre_1,
       b.data->>'n' as nombre_2,
       d.motivos,
       a.data->>'a' as direccion_1,
       b.data->>'a' as direccion_2,
       a.data->>'p' as telefono_1,
       b.data->>'p' as telefono_2,
       d.ficha_a, d.ficha_b
from public.duplicados_revision d
join public.listings a on a.id = d.ficha_a
join public.listings b on b.id = d.ficha_b
where d.estado = 'pendiente'
order by d.puntos desc, d.id;

-- Fichas que la barrera ha frenado o dejado ocultas:
-- select fecha, ficha_id, nombre, motivo from public.dup_bloqueos order by fecha desc;

-- Última revisión diaria:
-- select * from public.dup_ejecuciones order by fecha desc limit 5;
