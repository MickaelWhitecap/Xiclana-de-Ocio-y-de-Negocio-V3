# Xiclana de Ocio y de NegOcio — V3

V3 utiliza un único fichero JSON maestro: `v3/fichas_completas.json`. Contiene las fichas del directorio, las candidatas pendientes de revisión, la configuración publicitaria y los informes de consolidación. El proceso de publicación no lee ni genera catálogos JSON auxiliares.

- Web pública: https://mickaelwhitecap.github.io/Xiclana-de-Ocio-y-de-Negocio-V3/
- Administración: https://mickaelwhitecap.github.io/Xiclana-de-Ocio-y-de-Negocio-V3/admin.html

Cada publicación valida el catálogo maestro y sincroniza las modificaciones administrativas vigentes de Supabase antes de generar la web pública. También regenera el informe de integridad y comprueba IDs, bajas y candidatas automáticas sin aprobación.

Las candidatas de revisión no se publican automáticamente como fichas verificadas. La ampliación desde OpenStreetMap escribe las nuevas fichas en el catálogo maestro. La recuperación de direcciones no vuelve a consultar Overpass: combina la extracción OSM archivada con fuentes oficiales externas y genera propuestas pendientes; ninguna se publica sin aprobación manual.

- `v3/propuestas-enriquecimiento-contacto.json`: propuestas pendientes de aprobación para enriquecer fichas que ya disponen de correo electrónico. No modifica el catálogo público.


## Fuente única de datos de Xiclana V3

La única fuente de verdad de las fichas es **Supabase `public.listings`**.

- `public.listings`: fichas, datos, publicación y papelera. Es la única tabla que se debe consultar o modificar para crear, editar, publicar, ocultar o restaurar establecimientos.
- `public.site_settings`: metadatos generales del directorio, destacados y listas de propuestas pendientes. No es un segundo catálogo de fichas.
- `public.listing_proposals`: cola de propuestas privadas pendientes de aprobación. Una propuesta no es una ficha publicada; al aprobarla, Administración crea el registro correspondiente en `public.listings`.
- `public.listing_categories` y `public.advertising_slots`: datos auxiliares de categorías y publicidad.
- `public.listing_overrides`: tabla histórica retirada. No debe volver a utilizarse como fuente de datos ni como mecanismo de sincronización.

### Papel de fichas_completas.json

`v3/fichas_completas.json` queda como **archivo histórico de la migración**, no como fuente de datos. No se debe editar, regenerar ni integrar en `main` para actualizar el directorio. Tampoco se incluye en la web pública.

Para obtener una copia de trabajo o una exportación legible del estado actual:

```bash
export SUPABASE_SECRET_KEY="..."
python v3/catalogo_supabase.py export --output /tmp/xiclana-catalogo.json
```

La exportación es de solo lectura sobre las fichas. Los procesos RAD y OSM pueden utilizarla como copia temporal de trabajo; únicamente sincronizan sus propuestas y metadatos permitidos en `public.site_settings`. No escriben fichas en el JSON ni modifican automáticamente los registros de `public.listings`.

### Actualizaciones y copias de seguridad

- La publicación web lee directamente `public.listings`.
- Administración escribe directamente en `public.listings`.
- RAD y OSM leen una exportación temporal de Supabase. RAD puede completar únicamente campos vacíos y añadir contactos alternativos en fichas activas con estado **Verificada**, sin sobrescribir valores existentes ni cambiar su publicación. OSM guarda propuestas de fichas y direcciones para aprobación manual.
- Las copias de seguridad se generan desde la base de datos y se cifran. El JSON de respaldo, si se genera, es una exportación de Supabase.
- `v3/migrar_catalogo_supabase.py` se conserva exclusivamente como herramienta histórica de migración inicial; no debe ejecutarse para actualizaciones ordinarias.

**Regla de mantenimiento:** ningún proceso automático puede escribir fichas en `v3/fichas_completas.json` ni utilizarlo como catálogo operativo.
