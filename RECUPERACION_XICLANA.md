# Recuperación de Xiclana V3

## Fuente maestra y principio de recuperación

La fuente maestra de las fichas es **Supabase `public.listings`**. Los metadatos del directorio y las propuestas pendientes se conservan en **`public.site_settings`**, registro `id='catalogo'`.

La recuperación operativa se hace restaurando la base de datos desde los volcados SQL. El fichero `fichas_completas.json.gz.enc` incluido en la copia es una exportación auxiliar de Supabase para comprobar la integridad y el recuento de fichas; **no debe copiarse a `v3/fichas_completas.json` ni utilizarse como catálogo operativo**.

## Copia automática

El workflow **Copia de seguridad cifrada de Supabase y Xiclana V3** se ejecuta diariamente a las 03:30 UTC.

Solo debe utilizarse una copia cuyo workflow de GitHub Actions haya terminado en verde. El artefacto se conserva durante **14 días**. Conviene descargar periódicamente una copia y guardarla fuera de GitHub.

Cada artefacto contiene cinco ficheros cifrados:

- `schema.sql.enc`: estructura de las tablas y objetos incluidos en el volcado de Supabase.
- `roles.sql.enc`: configuración de roles de PostgreSQL.
- `data.sql.enc`: datos del esquema `public`.
- `fichas_completas.json.gz.enc`: exportación auxiliar de las fichas obtenidas desde `public.listings`, comprimida y cifrada.
- `xiclana-v3-source.zip.enc`: código, workflows y recursos del repositorio; excluye el JSON histórico del catálogo.

El cifrado utiliza AES-256-CBC con PBKDF2 y 600.000 iteraciones. La frase de paso está únicamente en el secreto `BACKUP_PASSPHRASE` de GitHub Actions.

## Prueba automática de restauración

Cada copia se descifra y se restaura en un PostgreSQL 17 temporal de GitHub Actions, sin conexión de escritura a Supabase de producción.

La prueba verifica:

1. Integridad del ZIP del código.
2. Descompresión y lectura de la exportación JSON auxiliar, con IDs únicos y procedencia `Supabase public.listings`.
3. Restauración del esquema y de los datos SQL.
4. Existencia de las dos tablas centrales, `public.listings` y `public.site_settings`.
5. Coincidencia entre el número de registros restaurados en `public.listings` y el número de fichas de la exportación auxiliar.

Las tablas auxiliares incluidas en los volcados se restauran junto con el esquema `public`; no son catálogos alternativos. La prueba crea una tabla `auth.users` mínima y registros de ID ficticios únicamente en la base temporal, para satisfacer las claves foráneas de Xiclana. **No restaura cuentas ni credenciales de Supabase Auth.**

## Recuperación manual

1. En GitHub, abrir **Actions**, seleccionar la última ejecución verde del workflow de copias y descargar su artefacto.
2. Descomprimir el ZIP y situarse en la carpeta que contiene los cinco ficheros cifrados.
3. Definir la frase de paso en una variable de entorno local, sin escribirla en el repositorio ni compartirla:

```bash
export BACKUP_PASSPHRASE='LA_FRASE_DE_PASO'
```

4. Descifrar los ficheros:

```bash
for f in schema.sql roles.sql data.sql; do
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 \
    -in "$f.enc" -out "$f" -pass env:BACKUP_PASSPHRASE
done

openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 \
  -in fichas_completas.json.gz.enc -out fichas_completas.json.gz \
  -pass env:BACKUP_PASSPHRASE

gzip -t fichas_completas.json.gz
gzip -dc fichas_completas.json.gz > fichas_completas.json

openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 \
  -in xiclana-v3-source.zip.enc -out xiclana-v3-source.zip \
  -pass env:BACKUP_PASSPHRASE

unzip -t xiclana-v3-source.zip
```

5. Preparar una base Supabase de destino para la recuperación. Restaurar los roles, el esquema y los datos SQL:

```bash
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f roles.sql
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f schema.sql
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f data.sql
```

6. Comprobar que existen `public.listings` y `public.site_settings`, y que el recuento de `public.listings` corresponde al de la exportación auxiliar. La exportación JSON sirve para esta comprobación; no se importa ni se copia al repositorio para reconstruir el catálogo.
7. Recuperar el código descomprimiendo `xiclana-v3-source.zip` en una copia de trabajo del repositorio.
8. Si se utiliza otro proyecto Supabase, actualizar la URL y la clave pública en la configuración de V3 y los secretos correspondientes de GitHub Actions. Comprobar también los permisos de Administración antes de reabrir el servicio.

## Límites importantes

- El volcado de datos incluye el esquema `public`, no las tablas gestionadas de Supabase Auth ni Storage.
- Si se restaura en el mismo proyecto Supabase y sus cuentas Auth siguen existiendo, se conservan las referencias de usuario.
- Si se reconstruye en un proyecto Supabase nuevo, hay que recrear la cuenta administradora y resolver las referencias de usuario y las políticas RLS antes de dar el sistema por operativo. La prueba automática no simula una migración de cuentas Auth.
- No ejecutar los comandos de restauración sobre producción sin una copia previa y un plan de sustitución de las tablas existentes. La prueba automática se realiza siempre en una base temporal.
- No ejecutar `v3/migrar_catalogo_supabase.py` como método de recuperación o actualización ordinaria: es una herramienta histórica de migración inicial.

Todo el procedimiento utiliza el repositorio, GitHub Actions y el proyecto Supabase ya existente; no requiere contratar otro servicio.
