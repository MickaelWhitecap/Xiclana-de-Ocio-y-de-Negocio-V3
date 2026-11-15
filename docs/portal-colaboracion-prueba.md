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

Antes de probar:
1. Aplicar el SQL de `supabase/sql/portal-colaboracion.sql` al proyecto Supabase.
2. Desplegar las dos Edge Functions con `verify_jwt=true` para `issue-listing-link` y `verify_jwt=false` para `public-listing-portal`.
3. Ejecutar pruebas de aislamiento, expiración, revocación, campos prohibidos, propuesta pendiente y aprobación.
4. Emitir los cinco enlaces solo después de superar esas pruebas.

La función pública debe mantener una lista CORS cerrada a la web de Xiclana y a localhost para desarrollo.
