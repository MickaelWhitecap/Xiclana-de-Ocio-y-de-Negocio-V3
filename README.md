# Xiclana de Ocio y de Negocio — V3

V3 utiliza **Supabase como fuente única de datos operativa**. La web pública, Administración y los procesos automáticos trabajan sobre el mismo proyecto Supabase.

- Web pública: https://mickaelwhitecap.github.io/Xiclana-de-Ocio-y-de-Negocio-V3/
- Administración: https://mickaelwhitecap.github.io/Xiclana-de-Ocio-y-de-Negocio-V3/admin.html

## Arquitectura de datos

- **`public.listings`**: fuente maestra única de las fichas. Contiene los datos de cada establecimiento y sus estados de publicación, baja y verificación. Crear, editar, publicar, ocultar o restaurar una ficha se realiza sobre esta tabla.
- **`public.site_settings`**, registro `id='catalogo'`: metadatos generales del directorio, destacados y propuestas de revisión RAD/OSM. No es un segundo catálogo. La columna `data` conserva los metadatos administrativos; `public_data` contiene únicamente `actualizado` y `destacados`, se mantiene mediante un trigger y es la única información de esta tabla legible por el rol público.
- **`public.listing_categories`**, **`public.listing_proposals`** y **`public.advertising_slots`**: tablas auxiliares para categorías, propuestas administrativas y publicidad. No sustituyen ni duplican la fuente maestra `public.listings`.
- **`public.web_stats_daily`**: contadores diarios anónimos (visitas a la web, vistas y clics de cada espacio publicitario). No guarda cookies, IP ni datos del visitante; la web pública solo puede sumar mediante la función `registrar_evento_web` y solo el administrador puede leer las cifras, en el panel «Visitas y resultados de los anuncios».
- **`public.listing_overrides`**: tabla histórica conservada, sin uso operativo. La compatibilidad de Administración redirige las llamadas antiguas a `public.listings`; no se deben crear ni sincronizar datos en esta tabla.

### Papel de los ficheros JSON

`v3/fichas_completas.json` es el fichero conservado de la migración inicial. **No es el catálogo operativo**: la web, Administración y las actualizaciones ordinarias no lo consultan ni lo regeneran.

RAD y OSM exportan temporalmente los datos de Supabase para trabajar. Esas exportaciones son copias de trabajo, no fuentes alternativas:

- RAD puede completar campos autorizados en fichas publicadas, activas y verificadas, respetando los datos existentes y los cambios concurrentes. Las nuevas candidatas y el informe RAD se guardan como metadatos en `public.site_settings`.
- OSM guarda candidatas y propuestas de direcciones como metadatos pendientes en `public.site_settings`. No publica fichas ni aplica direcciones por sí solo.
- Las candidatas y propuestas requieren revisión y aprobación manual desde Administración.

La herramienta `v3/catalogo_supabase.py` permite exportar una copia temporal y sincronizar únicamente los cambios autorizados. Ejemplo:

```bash
export SUPABASE_SECRET_KEY="..."
python v3/catalogo_supabase.py export --output /tmp/xiclana-catalogo.json
```

`v3/migrar_catalogo_supabase.py` se conserva exclusivamente para la migración inicial. Está protegida para impedir una reimportación accidental y no debe utilizarse en las actualizaciones ordinarias.

## Publicación y copias de seguridad

- El workflow de publicación prepara la web sin incluir el catálogo JSON. La web consulta Supabase y la publicación comprueba que las tablas centrales responden.
- Administración lee y escribe las fichas en `public.listings` y utiliza el JSON administrativo de `public.site_settings`. La web pública solo puede leer `id` y `public_data` de esa tabla.
- Las copias de seguridad se generan desde Supabase: incluyen los volcados SQL, una exportación JSON auxiliar para validar el número e integridad de las fichas y una copia cifrada del código. La exportación JSON no sustituye la restauración de la base de datos.
- La restauración y sus límites están descritos en [RECUPERACION_XICLANA.md](RECUPERACION_XICLANA.md).

**Regla de mantenimiento:** una sola fuente maestra para las fichas: `public.listings`. Ningún JSON local ni tabla auxiliar debe convertirse en un catálogo paralelo.
