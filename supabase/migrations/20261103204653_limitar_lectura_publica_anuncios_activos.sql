-- La web pública solo necesita leer anuncios activos y dentro de su periodo.
-- El administrador autenticado conserva acceso completo mediante su política UID.

DROP POLICY IF EXISTS "Public can read advertising slots" ON public.advertising_slots;

CREATE POLICY "Public can read active advertising slots"
ON public.advertising_slots
FOR SELECT
TO anon
USING (
  status = 'active'
  AND (starts_at IS NULL OR starts_at <= now())
  AND (ends_at IS NULL OR ends_at >= now())
);

CREATE POLICY "Xiclana admin can read advertising slots"
ON public.advertising_slots
FOR SELECT
TO authenticated
USING ((SELECT auth.uid()) = '2ebd10a1-fbae-454b-a12b-e1692f1eed17'::uuid);

REVOKE SELECT ON TABLE public.advertising_slots FROM anon;

GRANT SELECT (
  slot_id,
  listing_name,
  phone,
  location,
  promotion,
  hook_text,
  image_url,
  target_url,
  status,
  starts_at,
  ends_at
) ON TABLE public.advertising_slots TO anon;
