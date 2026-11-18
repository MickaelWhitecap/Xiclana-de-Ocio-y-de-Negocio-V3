#!/usr/bin/env python3
"""Pruebas unitarias sin llamadas de red para CartoCiudad."""
import unittest

import geocodificar_cartociudad as geo


class CartoCiudadTests(unittest.TestCase):
    def test_municipio_exige_codigo_o_nombre_exactos(self):
        self.assertTrue(geo.es_chiclana({"muni": "Chiclana de la Frontera", "muniCode": "11015"}))
        self.assertTrue(geo.es_chiclana({"muni": "Chiclana de la Frontera"}))
        self.assertFalse(geo.es_chiclana({"muni": "San Fernando", "muniCode": "11031"}))
        self.assertFalse(geo.es_chiclana({"muni": "Chiclana de la Frontera", "muniCode": "11031"}))
        self.assertFalse(geo.es_chiclana({"muni": "Chiclana de la Frontera", "muniCode": "11015", "provinceCode": "29"}))

    def test_solo_extrae_geometrias_puntuales(self):
        lat, lon = geo.coordinates_from_point({"lat": 36.42, "lng": -6.15})
        self.assertAlmostEqual(lat, 36.42)
        self.assertAlmostEqual(lon, -6.15)
        lat, lon = geo.coordinates_from_point({"geom": "POINT(-6.15 36.42)"})
        self.assertAlmostEqual(lat, 36.42)
        self.assertAlmostEqual(lon, -6.15)
        self.assertEqual(geo.coordinates_from_point({"geom": "LINESTRING(-6.15 36.42,-6.16 36.43)"}), (None, None))
        self.assertEqual(geo.coordinates_from_point({"geometry": {"type": "LineString", "coordinates": [[-6.1, 36.4]]}}), (None, None))

    def test_unifica_respuestas_cartociudad(self):
        sample = {"results": [{"id": "1", "type": "portal"}]}
        self.assertEqual(len(geo.unpack_records(sample)), 1)
        feature = {
            "type": "Feature",
            "properties": {"id": "2", "type": "portal"},
            "geometry": {"type": "Point", "coordinates": [-6.15, 36.42]},
        }
        self.assertEqual(
            geo.coordinates_from_point(geo.as_properties(feature)),
            (36.42, -6.15),
        )

    def test_compara_numero_de_portal_y_direccion(self):
        source = "Calle Ancha, número 12, 11130 Chiclana de la Frontera"
        candidate = {
            "address": "CALLE ANCHA, 12", "type": "portal", "portalNumber": 12,
            "lat": 36.42, "lng": -6.15, "muni": "Chiclana de la Frontera",
            "muniCode": "11015", "provinceCode": "11",
        }
        features = geo.candidate_features(source, candidate)
        self.assertTrue(features["es_chiclana"])
        self.assertTrue(features["numero_coincide"])
        self.assertGreaterEqual(features["similaridad_direccion"], 0.65)

    def test_numero_distinto_no_es_alta_coincidencia(self):
        source = "Calle Ancha 12, Chiclana de la Frontera"
        candidate = {
            "address": "CALLE ANCHA, 14", "type": "portal", "portalNumber": 14,
            "lat": 36.42, "lng": -6.15, "muni": "Chiclana de la Frontera",
            "muniCode": "11015",
        }
        features = geo.candidate_features(source, candidate)
        self.assertFalse(features["numero_coincide"])

    def test_numero_y_codigo_postal(self):
        self.assertEqual(
            geo.extract_house_number("Avda. de los Descubrimientos, nº 22, 11130 Chiclana"),
            "22",
        )

    def test_rechaza_direcciones_vagas(self):
        self.assertFalse(geo.direccion_especifica("Centro"))
        self.assertFalse(geo.direccion_especifica("Casco histórico"))
        self.assertFalse(geo.direccion_especifica("Chiclana"))
        self.assertFalse(geo.direccion_especifica("E-mail:"))
        self.assertTrue(geo.direccion_especifica("C. San Alejandro, 24, 11130 Chiclana de la Frontera"))
        self.assertTrue(geo.direccion_especifica("Calle Nueva, 20"))

    def test_normaliza_abreviaturas_y_prepara_busqueda_alternativa(self):
        self.assertEqual(
            geo.limpiar_direccion_busqueda("C. San Alejandro, 24, 11130 Chiclana de la Frontera, Cádiz"),
            "Calle San Alejandro 24",
        )
        variants = geo.variantes_consulta("Av. del Mueble, 46B, 11130 Chiclana de la Frontera")
        self.assertEqual(variants[0], "Avenida del Mueble 46B")
        self.assertEqual(variants[1], "Avenida del Mueble")

    def test_preserva_andalucia_en_nombres_de_calles(self):
        source = "Plaza de Andalucía, 1, 11130 Chiclana de la Frontera, Cádiz"
        candidate_wrong = "CALLE PLAZA (DE LA 1, Chiclana de la Frontera"
        candidate_right = "PLAZA ANDALUCIA (DE), 1, Chiclana de la Frontera"
        self.assertLess(geo.similarity_address(source, candidate_wrong), 0.65)
        self.assertGreaterEqual(geo.similarity_address(source, candidate_right), 0.80)
        self.assertEqual(
            geo.limpiar_direccion_busqueda(source),
            "Plaza de Andalucía 1",
        )

    def test_caja_geografica_solo_como_control(self):
        self.assertTrue(geo.in_sanity_bounds(36.42, -6.15))
        self.assertFalse(geo.in_sanity_bounds(40.42, -3.70))


if __name__ == "__main__":
    unittest.main()
