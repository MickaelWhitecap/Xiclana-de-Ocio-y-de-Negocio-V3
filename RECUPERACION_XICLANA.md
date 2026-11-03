# Recuperación de Xiclana V3

## Copia automática

El workflow **Copia de seguridad cifrada de Supabase y Xiclana V3** se ejecuta diariamente a las 03:30 UTC.

Solo debe utilizarse una copia cuyo workflow de GitHub Actions haya terminado en verde. El artefacto se conserva durante **14 días**. Conviene descargar periódicamente una copia y guardarla fuera de GitHub.

Cada artefacto contiene cinco ficheros cifrados:

- `schema.sql.enc`: estructura de las tablas propias de Xiclana y sus políticas.
- `roles.sql.enc`: configuración de roles de PostgreSQL.
- `data.sql.enc`: datos del esquema `public`.
- `fichas_completas.json.gz.enc`: catálogo maestro completo, incluida la referencia histórica de OSM.
- `xiclana-v3-source.zip.enc`: código, workflows y recursos del repositorio; el catálogo maestro se excluye de este ZIP porque se guarda por separado.

El cifrado utiliza AES-256-CBC con PBKDF2 y 600.000 iteraciones. La frase de paso está únicamente en el secreto `BACKUP_PASSPHRASE` de GitHub Actions.

## Prueba automática de restauración

Cada copia se descifra y se restaura en un PostgreSQL 17 temporal de GitHub Actions, sin conexión de escritura a Supabase de producción.

La prueba verifica:

1. Integridad del ZIP del código.
2. Descompresión y lectura JSON del catálogo maestro.
3. Restauración del esquema y de los datos propios de Xiclana.
4. Existencia de las cuatro tablas principales y recuento de sus registros.

La prueba crea una tabla `auth.users` mínima y registros de ID ficticios únicamente en la base temporal, para satisfacer las claves foráneas de Xiclana. **No restaura cuentas ni credenciales de Supabase Auth.**

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

5. Restaurar los datos SQL en una base Supabase de destino preparada para la recuperación:

```bash
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f roles.sql
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f schema.sql
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f data.sql
```

6. Recuperar el código descomprimiendo `xiclana-v3-source.zip` y colocar `fichas_completas.json` en `v3/fichas_completas.json`.
7. Si se utiliza otro proyecto Supabase, actualizar su URL y clave pública en la configuración de V3 y los secretos de GitHub Actions.

## Límites importantes

- El volcado de datos incluye el esquema `public`, no las tablas gestionadas de Supabase Auth ni Storage.
- Si se restaura en el mismo proyecto Supabase y sus cuentas Auth siguen existiendo, se conservan las referencias de usuario.
- Si se reconstruye en un proyecto Supabase nuevo, hay que recrear la cuenta administradora y resolver las referencias de usuario y las políticas RLS antes de dar el sistema por operativo. La prueba automática no simula una migración de cuentas Auth.
- No ejecutar los comandos de restauración sobre producción sin una copia previa y un plan de sustitución de las tablas existentes. La prueba automática se realiza siempre en una base temporal.

Todo el procedimiento utiliza el repositorio, GitHub Actions y el proyecto Supabase ya existente; no requiere contratar otro servicio.
