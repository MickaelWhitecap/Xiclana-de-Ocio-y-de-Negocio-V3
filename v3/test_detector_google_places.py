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


def test_palabras_frecuentes_pesan_poco():
    nombres = ["Inmobiliaria Alameda", "Inmobiliaria Sol", "Inmobiliaria Mar", "Inmobiliaria Luz",
               "Umami La Barrosa", "Telepizza Barrosa", "Barrosa Playa", "Hotel Barrosa",
               "Playa Sol", "Playa Mar", "Playa Luz", "Kiosko Playa"]
    D.preparar_pesos(nombres)
    try:
        assert D.peso({"inmobiliaria"}) < D.peso({"gaviota"})
        # Comparten dos palabras frecuentes, pero el nombre propio es distinto.
        assert D.parecido("Umami Playa Barrosa", "Telepizza Playa Barrosa") < 0.5
        # Mismo nombre propio con palabras de relleno distintas: sigue siendo el mismo.
        assert D.parecido("Umami Barrosa", "Umami") >= 0.5
    finally:
        D.PESOS, D.PESO_DESCONOCIDA = {}, 1.0


def test_restaurante_no_se_confunde_con_farmacia():
    # Caso Greda (23-nov-2026): solo compartían el nombre del barrio.
    assert D.parecido("Greda - Restaurante en La Barrosa", "Farmacia La Barrosa") < 0.5
    assert not D.familias_compatibles("restaurant", "Farmacia")
    fichas = [{"id": "f1", "nombres": ["Greda"], "a": "", "c": "Farmacia", "lat": None, "lon": None}]
    lugar = {"nombre": "Greda", "tipo": "restaurant", "lat": 36.39, "lon": -6.17}
    assert D.buscar_en_catalogo(lugar, fichas) == ("falta", None)


def test_familias_de_negocio():
    assert D.familia("barber_shop") == "belleza"
    assert D.familia("ice_cream_shop") == "comida"
    assert D.familia("Servicio público") == ""
    assert D.familias_compatibles("restaurant", "Bar")
    assert D.familias_compatibles("restaurant", "Servicios y negocios")
    assert not D.familias_compatibles("hair_care", "Restaurante")


def test_nombres_de_zona_no_cuentan():
    assert D.parecido("Umami La Barrosa", "Taller La Barrosa") == 0.0
    assert D.parecido("Los Quintos Sancti Petri", "Los Quintos") == 1.0


def test_supermercados_y_cafeterias_de_overture():
    # Avisado al revisar Overture (23-nov-2026): no deben salir como «falta».
    assert D.familias_compatibles("food_and_beverage_store", "Supermercado")
    assert D.familias_compatibles("coffee_shop", "Cafetería")
    assert D.familia("fast_food_restaurant") == "comida"
    assert not D.familias_compatibles("food_and_beverage_store", "Farmacia")
