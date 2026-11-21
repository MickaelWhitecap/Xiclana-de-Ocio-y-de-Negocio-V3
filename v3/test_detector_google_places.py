import detector_google_places as D


def test_mismo_tipo_de_local_con_nombre_distinto_no_es_el_mismo():
    assert D.parecido("Venta Bonilla", "Venta Zacarías bar cervecería") < 0.5
    assert D.parecido("Venta Bonilla", "Venta Agustín") < 0.5


def test_nombres_equivalentes_siguen_coincidiendo():
    assert D.parecido("El Sitio", "Bar el Sitio") == 1.0
    assert D.parecido("Restaurante Zurga", "Zurga") == 1.0
    assert D.parecido("Mesón La Cabaña Ibérica", "La Cabaña Ibérica") == 1.0


def test_una_palabra_suelta_no_basta():
    assert D.parecido("Cantina Plaza de Abastos", "Farmacia La Plaza") < 0.5
