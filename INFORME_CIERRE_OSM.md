# Informe histórico de cierre de la explotación inicial de OpenStreetMap

**Proyecto:** Xiclana de Ocio y de Negocio V3  
**Ámbito:** municipio de Chiclana de la Frontera  
**Relación municipal OSM:** 346951  
**Área Overpass:** 3600346951

> Este documento conserva los resultados de la extracción y auditoría iniciales, no el estado operativo actual del catálogo. Las cifras siguientes corresponden a las consultas fechadas en noviembre de 2026. La fuente maestra vigente de las fichas es Supabase `public.listings`; las propuestas pendientes se guardan en `public.site_settings`. Los resultados detallados de cada ejecución semanal se conservan como artefactos de GitHub Actions.

## 1. Extracción de referencia

La extracción inicial verificada de referencia contenía **132.875 objetos OSM**.

- Fecha de la extracción inicial: 2 de noviembre de 2026, 19:13:24 UTC.
- Extracción de comprobación: 3 de noviembre de 2026, 20:00:00 UTC.
- Objetos en la comprobación: **132.878**.
- Distribución: 117.220 nodos, 15.459 vías y 199 relaciones.
- Objetos con etiquetas: 19.187.
- Objetos con nombre: 4.661.
- Vías con geometría completa: 15.459.
- IDs duplicados en la respuesta: **0**.
- Tamaño de la extracción de referencia: 77.756.896 bytes.
- SHA-256: `6b19dcf1034782dfff1f745d6ea32207f7efe483241e8e8e074b578c14e7beaf`.

## 2. Comparación con la extracción inicial

| Resultado | Cantidad |
|---|---:|
| Objetos nuevos | 3 |
| Objetos con cambios de contenido | 17 |
| Objetos eliminados de OSM | 0 |
| Cambios solo de metadatos | 0 |

Los tres objetos nuevos son dos nodos y una relación. Los 17 objetos modificados son 16 relaciones y una vía.

La comparación se realiza contra la extracción inicial inmutable. Por tanto, estos cambios son acumulados desde la extracción de referencia, no un diff exclusivo entre dos lunes consecutivos.

## 3. Clasificación de objetos sin ficha coincidente

Se detectaron **3.194 objetos OSM con nombre** que no tenían una ficha candidata coincidente en el catálogo.

| Clasificación | Cantidad |
|---|---:|
| Vías/carreteras (`highway`) | 2.706 |
| Sin coordenadas utilizables | 70 |
| Otros objetos con nombre y coordenadas | 418 |
| **Total** | **3.194** |

De los 418 restantes, 36 pasaron los filtros de relevancia del directorio. Se agrupó un duplicado entre candidatas, quedando **35 nuevas candidatas únicas**.

Por tanto, la cifra de 3.194 no representa objetos sin coordenadas: solo 70 carecían de coordenadas utilizables.

## 4. Propuestas para Administración

En aquella ejecución se detectaron:

- **77 fichas dadas de baja** que OSM volvía a reconocer y que podían proponerse para recuperación.
- **35 nuevas candidatas únicas**.
- **2 candidatas manuales** que ya estaban pendientes.
- **114 propuestas en total** para revisión: 112 automáticas y 2 manuales.
- **0 fichas publicadas automáticamente**.

El flujo operativo vigente exporta una copia temporal desde Supabase, genera las propuestas y las guarda como metadatos en `public.site_settings`. Administración las consulta desde Supabase. La aprobación o el rechazo requiere una decisión expresa; las bajas no se reactivan automáticamente. Los ficheros JSON generados durante una auditoría son resultados de trabajo o artefactos, no una base de datos paralela.

## 5. Direcciones: límite real de los datos OSM

En el catálogo consultado entonces había 554 fichas activas sin dirección:

- 541 tenían identificador OSM.
- Los 541 identificadores estaban presentes en la extracción.
- 13 no tenían identificador OSM.
- Solo se obtuvo **1 propuesta de dirección postal explícita** a partir de etiquetas OSM.
- Los otros **540 objetos no contienen etiquetas postales utilizables**.
- No se sobrescribió ninguna dirección existente.
- No se publicó ninguna dirección automáticamente.

Esto significa que la extracción recuperó toda la información postal que esos objetos contenían, pero OSM no proporcionaba una dirección postal explícita para 540 de ellos. Para completar esas fichas se necesitan otras fuentes y las propuestas deben seguir pendientes de aprobación.

## 6. Actualización semanal

En el momento de redactar este informe, el workflow `.github/workflows/auditoria-osm-municipal.yml` estaba configurado para ejecutarse los lunes a las 04:30 UTC, con ejecución manual disponible. Se había eliminado el disparador automático por cambios de código para evitar consultas extraordinarias a Overpass al modificar scripts o workflows.

La configuración horaria de este apartado es una referencia histórica del cierre inicial. Para conocer la programación vigente hay que consultar el propio workflow en la rama `main`.

## Conclusión

La explotación inicial de OSM quedó cerrada para el ámbito y las fechas de las consultas de referencia: el conjunto de objetos recuperados se conservó, identificó y contrastó; no se detectaron IDs duplicados; las novedades se presentaron como propuestas y ninguna se publicó sin aprobación.

Esta conclusión acredita el contenido devuelto por OSM para el ámbito municipal y las fechas consultadas. No afirma que OSM contenga todos los establecimientos que existen físicamente en Chiclana.
