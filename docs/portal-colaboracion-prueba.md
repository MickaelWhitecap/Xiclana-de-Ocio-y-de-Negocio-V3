# Portal privado para completar fichas — prueba controlada

## Alcance

- Página independiente: `v3/completar-ficha.html`.
- Cada enlace da acceso a una sola ficha publicada.
- El enlace caduca a los 30 días y se puede revocar desde Administración.
- El código aleatorio tiene 256 bits de entropía; solo se guarda su hash.
- El visitante puede proponer cambios en dirección, teléfono, correo, web, horario, dato destacado y descripción.
- Nombre, tipo, categoría, coordenadas y estado de verificación quedan reservados a Administración.
- Los cambios se guardan como propuestas privadas en `public.listing_proposals`; nunca se escriben directamente en `public.listings`.
- La aprobación administrativa aplica únicamente los campos permitidos a la ficha existente. No crea otra ficha.

## Seguridad

- El navegador nunca recibe una clave secreta.
- La función pública valida el token y determina en servidor el ID de ficha asociado. No acepta un ID enviado por el visitante.
- La tabla de tokens tiene RLS y no concede acceso a `anon` ni `authenticated`; solo las Edge Functions usan la clave secreta.
- La emisión y revocación exigen sesión de la cuenta administradora autorizada.
- La función pública solo devuelve los campos de ficha necesarios para el formulario.

## Puesta en marcha pendiente

Este código está en una rama de prueba. No se han desplegado funciones, creado tablas, emitido enlaces, enviado correos ni modificado fichas del catálogo.

La función pública mantiene una lista CORS cerrada a la web de Xiclana y a localhost para desarrollo, y admite como máximo 3 propuestas pendientes por ficha.

### 1. Preparar la base de datos

Abrir el editor SQL del proyecto Supabase y ejecutar `supabase/sql/portal-colaboracion.sql`. Revisar las dos consultas de verificación del final: `rls` debe ser `true` y no debe aparecer ningún permiso para `anon` ni `authenticated`.

### 2. Desplegar las Edge Functions

```bash
supabase login
supabase link --project-ref pewfqucupmbkgamwvaic
supabase functions deploy issue-listing-link
supabase functions deploy public-listing-portal --no-verify-jwt
```

`issue-listing-link` conserva la verificación JWT (solo la cuenta administradora). `public-listing-portal` no la usa porque el establecimiento no tiene cuenta: el token del enlace es la credencial.

### 3. Publicar la página

Al fusionar en `main`, el workflow de publicación copia `completar-ficha.html` a GitHub Pages. Para probar antes de fusionar, servir `v3/` en local (`python -m http.server 5500` dentro de `v3/`) y abrir `http://localhost:5500/completar-ficha.html?token=…`.

### 4. Pruebas manuales (con una ficha de prueba)

| # | Prueba | Resultado esperado |
|---|--------|--------------------|
| 1 | En Administración, abrir una ficha y pulsar «Generar enlace» | Aparece un enlace `…/completar-ficha.html?token=…` |
| 2 | Abrir el enlace | Se ven nombre, categoría y los campos actuales de esa ficha |
| 3 | Cambiar el teléfono y enviar | «Propuesta recibida». La web pública no cambia |
| 4 | En Administración → Propuestas | Aparece «Actualización de ficha»; «Ver cambios propuestos» muestra `antes → después` |
| 5 | Aprobar | Solo cambia el teléfono de esa ficha; no se crea otra ficha |
| 6 | Enviar sin cambios | «No hay cambios nuevos que enviar» |
| 7 | Enviar 4 propuestas sin revisarlas | La cuarta se rechaza (máximo 3 pendientes) |
| 8 | Vaciar la descripción y enviar | La propuesta muestra «(borrar)»; al aprobar, la descripción queda vacía |
| 9 | Pulsar «Generar enlace» otra vez | El enlace anterior deja de funcionar |
| 10 | Pulsar «Revocar enlace» | El enlace actual deja de funcionar |
| 11 | Modificar un carácter del token en la URL | «El enlace no es válido…» |

### 5. Pruebas de seguridad con curl

```bash
URL=https://pewfqucupmbkgamwvaic.supabase.co/functions/v1/public-listing-portal
KEY=sb_publishable_troU61xihB4HKtmy93x6kQ_c05Ob5RK
TOKEN=...   # el token de un enlace de prueba

# Campo prohibido (nombre): debe responder 400
curl -s -X POST "$URL" -H "apikey: $KEY" -H "Content-Type: application/json" \
  -d '{"token":"'"$TOKEN"'","action":"submit","fields":{"n":"Otro nombre"}}'

# Origen no autorizado: debe responder 403
curl -s -X POST "$URL" -H "apikey: $KEY" -H "Origin: https://ejemplo.com" -H "Content-Type: application/json" \
  -d '{"token":"'"$TOKEN"'","action":"read"}'

# La tabla de tokens no es legible con la clave pública: debe devolver error o lista vacía
curl -s "https://pewfqucupmbkgamwvaic.supabase.co/rest/v1/listing_access_tokens?select=*" -H "apikey: $KEY"

# Emitir enlace sin sesión administrativa: debe responder 401
curl -s -X POST https://pewfqucupmbkgamwvaic.supabase.co/functions/v1/issue-listing-link \
  -H "apikey: $KEY" -H "Content-Type: application/json" -d '{"action":"issue","listing_id":"x"}'
```

Para probar la caducidad sin esperar 30 días, en el editor SQL:
`update public.listing_access_tokens set expires_at = now() - interval '1 minute' where listing_id = '<id de prueba>';` y comprobar que el enlace se rechaza.

### 6. Después de las pruebas

Emitir los cinco enlaces reales solo cuando todas las pruebas anteriores hayan salido bien.
