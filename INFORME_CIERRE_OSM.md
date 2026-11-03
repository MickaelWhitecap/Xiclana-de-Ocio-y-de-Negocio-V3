# Informe de cierre de la explotación inicial de OpenStreetMap

**Proyecto:** Xiclana de Ocio y de Negocio V3  
**Ámbito:** municipio de Chiclana de la Frontera  
**Relación municipal OSM:** 346951  
**Área Overpass:** 3600346951

## 1. Extracción de referencia

La extracción inicial verificada e inmutable quedó guardada en `v3/fichas_completas.json` y contiene **132.875 objetos OSM**.

- Fecha de la extracción inicial: 2 de noviembre de 2026, 19:13:24 UTC.
- Extracción de comprobación: 3 de noviembre de 2026, 20:00:00 UTC.
- Objetos en la comprobación: **132.878**.
- Distribución: 117.220 nodos, 15.459 vías y 199 relaciones.
- Objetos con etiquetas: 19.187.
- Objetos con nombre: 4.661.
- Vías con geometría completa: 15.459.
- IDs duplicados en la respuesta: **0**.
- Tamaño de la extracción actual: 77.756.896 bytes.
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

El proceso detectó:

- **77 fichas dadas de baja** que OSM vuelve a reconocer y que pueden proponerse para recuperación.
- **35 nuevas candidatas únicas**.
- **2 candidatas manuales** que ya estaban pendientes.
- **114 propuestas en total** para revisión: 112 automáticas y 2 manuales.
- **0 fichas publicadas automáticamente**.

Administración carga `osm_candidatas_pendientes.json` y `propuestas_direcciones_osm.json`. La publicación de V3 copia ambos ficheros al sitio. La aprobación o el rechazo requiere una decisión expresa del administrador; las bajas no se reactivan automáticamente.

## 5. Direcciones: límite real de los datos OSM

En el catálogo había 554 fichas activas sin dirección:

- 541 tenían identificador OSM.
- Los 541 identificadores estaban presentes en la extracción.
- 13 no tenían identificador OSM.
- Solo se obtuvo **1 propuesta de dirección postal explícita** a partir de etiquetas OSM.
- Los otros **540 objetos no contienen etiquetas postales utilizables**.
- No se sobrescribió ninguna dirección existente.
- No se publicó ninguna dirección automáticamente.

Esto significa que la extracción ha recuperado toda la información postal que esos objetos contienen, pero OSM no proporciona una dirección postal explícita para 540 de ellos. Para completar esas fichas habrá que recurrir a otras fuentes públicas y mantener las propuestas pendientes de aprobación. El piloto de 50 fichas de mayor impacto es el siguiente trabajo de enriquecimiento.

## 6. Actualización semanal

El workflow `.github/workflows/auditoria-osm-municipal.yml` queda configurado para ejecutarse automáticamente los **lunes a las 04:30 UTC** (05:30 en España durante el horario de invierno). También conserva la ejecución manual para cuando se solicite expresamente.

Se ha eliminado el disparador automático por cambios de código: modificar un script o workflow ya no debe provocar una consulta extraordinaria a Overpass. La siguiente ejecución automática está prevista para el lunes 9 de noviembre de 2026.

## Conclusión

La explotación inicial de OSM queda cerrada para el ámbito y la fecha de la extracción de referencia: el conjunto de 132.875 objetos está conservado, identificado y contrastado; no se detectaron IDs duplicados; las novedades se presentan como propuestas y ninguna se publica sin aprobación.

Esta certificación acredita el contenido devuelto por OSM para el ámbito municipal y la fecha consultada. No afirma que OSM contenga todos los establecimientos que existen físicamente en Chiclana.
