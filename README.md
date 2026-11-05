# Xiclana de Ocio y de NegOcio — V3

V3 utiliza un único fichero JSON maestro: `v3/fichas_completas.json`. Contiene las fichas del directorio, las candidatas pendientes de revisión, la configuración publicitaria y los informes de consolidación. El proceso de publicación no lee ni genera catálogos JSON auxiliares.

- Web pública: https://mickaelwhitecap.github.io/Xiclana-de-Ocio-y-de-Negocio-V3/
- Administración: https://mickaelwhitecap.github.io/Xiclana-de-Ocio-y-de-Negocio-V3/admin.html

Cada publicación valida el catálogo maestro y sincroniza las modificaciones administrativas vigentes de Supabase antes de generar la web pública. También regenera el informe de integridad y comprueba IDs, bajas y candidatas automáticas sin aprobación.

Las candidatas de revisión no se publican automáticamente como fichas verificadas. La ampliación desde OpenStreetMap escribe las nuevas fichas en el catálogo maestro. La recuperación de direcciones utiliza exclusivamente la extracción archivada y genera propuestas pendientes, sin nuevas consultas a Overpass ni publicación automática.

- `v3/propuestas-enriquecimiento-contacto.json`: propuestas pendientes de aprobación para enriquecer fichas que ya disponen de correo electrónico. No modifica el catálogo público.
