# Procedimiento único de captación de datos

Este es el único procedimiento para encontrar el ocio y el negocio de Chiclana y
completar sus fichas. Cada fallo que hemos tenido deja aquí una regla y un
control para que no se repita. Si un fallo nuevo aparece, se añade su lección al
final y su control a la tabla, en el mismo cambio que lo arregla.

Los siete datos que buscamos en cada ficha: **dirección, teléfono, correo, web,
horario, descripción y redes**. El contador de completitud (Administración >
Contador de datos) mide el resultado.

## Las cinco fases (siempre en este orden)

| Fase | Qué hace | Herramienta | Cuándo corre |
|---|---|---|---|
| 1. Detectar | Saber qué negocios existen (solo pistas: nombre, calle, tipo) | Overture Maps (`/captacion-datos/scripts`), OSM (`auditoria-osm-municipal.yml`), detector de Google en el cupo gratis (`detector_google_places.py`), visitas de Miguel, «Añadir un sitio» | Overture y OSM cada mes; Google solo con cupo |
| 2. Comparar y dar de alta | Cruzar pistas con el catálogo; revisar **también** los «dudosos» | `cmp.py`, detector (familias y palabras de zona), barrera de duplicados en la base de datos | Cada vez que llega una lista |
| 3. Buscar la web propia | A cada ficha **sin web** se le busca su web | `buscar_web_propia.py` (`buscar-web-propia.yml`) | Lunes y jueves 03:53 |
| 4. Leer la web propia | A cada ficha **con web** se le leen los huecos y se verifica | `rastreo_fichas_con_web.py` + `leer_web_propia.py` (`rastreo-fichas-con-web.yml`) | Lunes y jueves 04:23 |
| 5. Vigilar | Encontrar errores y duplicados nuevos | `auditoria_revisar()` (pg_cron 04:15 UTC), vigilancia de duplicados (03:45 UTC), contador | Cada día |

La fase 3 va antes que la 4: una ficha a la que se le encuentra web se lee en la
misma pasada, y la fase 4 relee lo que haya quedado.

## Reglas que no se saltan

1. **Simular antes de escribir.** Toda tanda nueva se ejecuta primero en modo
   simular y se revisa una muestra real antes de guardar nada. Ninguna tanda
   masiva sin muestra revisada.
2. **Solo rellenar huecos.** Nunca se cambia un dato que ya existe. Lo descartado
   se guarda en un campo `*_descartada` o `*_anterior`, no se borra.
3. **Toda escritura deja rastro** en `fuentes_datos` (fuente, fecha y campos) y
   tiene una forma de deshacerla (copia en una tabla o SQL de deshacer).
4. **Una web se acepta solo si es del negocio**: el texto la nombra, nombra
   Chiclana (o coincide el teléfono) y no es una cadena, un portal ni un dominio
   compartido por varias fichas.
5. **Google y los directorios son solo pista.** No se copian sus datos. Los datos
   de la ficha salen de la web del propio negocio, de fuentes abiertas o del
   propio negocio a través del portal.
6. **Gasto cero.** Siempre dentro del cupo gratis (tope del script: 4.000 Nearby
   al mes). Nunca se usa el crédito de prueba.
7. **Respetar robots.txt y los bloqueos.** El robot se identifica como
   `Xiclana-RAD`. Si una web lo bloquea, no se esquiva.
8. **Solo la V3** (repo V3 y Supabase `pewfqucupmbkgamwvaic`).
9. **Medir antes y después** con el contador de completitud en cada tanda.

## Lecciones (fallos reales y su control)

| Fecha | Caso | Qué falló | Control que lo evita |
|---|---|---|---|
| 19-nov | todociudad.es | 67 fichas con la portada de un directorio como «web» | Lista `HOSTS_NO_PROPIOS`; dominios compartidos por 3 o más fichas no son web propia |
| 20-nov | Cantina de Santa Mónica | Solo está en Google e Instagram: ninguna fuente la tenía | Detector de Google como pista + visitas; campo `r` (redes) |
| 21-nov | Venta Bonilla | Ficha con web que nadie leyó (el ciclo RAD fijaba la lista al empezar y se canceló) | Fase 4 con estado propio (`lectura_web_propia`): toda ficha con web se intenta y se reintenta a los 30 días |
| 21-nov | Primera tanda de lectura | Basura (cookies, textos legales, teléfonos sueltos, webs de cadenas) | `leer_web_propia.py`: solo datos con forma clara, máximo 2 teléfonos, filtros de texto |
| 21-nov | Segunda tanda | Redes del diseñador de la plantilla, web de otro negocio | `perfil_relacionado`, `identifica_negocio`; regla 1 (simular) |
| 21-nov | Duplicados de Overture | El mismo negocio dado de alta dos veces | Barrera de duplicados en la base de datos + revisión diaria |
| 23-nov | Cadenas borradas | «Mismo nombre + misma web» borró 11 locales reales de cadenas | Las cadenas no se fusionan por nombre y web; `alta_confirmada` |
| 23-nov | Greda (alta) | Marcado «dudoso» por parecerse a «Farmacia La Barrosa»; nadie revisó los dudosos | Palabras de zona no cuentan; familias de negocio; **los dudosos se revisan siempre** |
| 26-nov | Greda (datos) | Dado de alta sin web; la fase 4 solo trabaja con fichas que ya tienen web | Fase 3 (`buscar_web_propia.py`): toda ficha sin web se busca y se reintenta a los 60 días |
| 26-nov | Bubble TAI | Web de una franquicia aceptada como propia | `parece_cadena`: webs que nombran muchas ciudades o franquicias se rechazan |
| 26-nov | Ohana, «Costa de la Luz» | Un alquiler vacacional y una villa aceptados como restaurante y hotel: la «calle» coincidía solo por «Barrosa» y «bar» casaba dentro de «Barrosa» | Las palabras de zona no cuentan como calle; la categoría debe ser palabra entera; nombres solo de zona no se buscan |
| 26-nov | BigMat, Don Gatto | Correo de plantilla (`info@website.com`) y descripción mal descodificada | Correos de plantilla y textos con «�» se descartan |

## Comprobación de un sitio notorio

Cuando falte un sitio conocido (o tenga la ficha vacía), se comprueba en este
orden y se anota la causa en la tabla de lecciones:

1. ¿Está en `listings`, en la papelera o fusionado? (`ids_alternativos`)
2. ¿Lo tenía alguna fuente (Overture, OSM, detector)? ¿Como «falta» o como «dudoso»?
3. Si está, ¿tiene web? Si no, ¿qué dijo la fase 3 (`busqueda_web_propia` en
   `site_settings.catalogo`)? Si tiene web, ¿qué dijo la fase 4
   (`lectura_web_propia`)?
4. Arreglar la causa en el script de la fase que falló, con una prueba en su
   `--self-test`, y añadir la lección aquí.
