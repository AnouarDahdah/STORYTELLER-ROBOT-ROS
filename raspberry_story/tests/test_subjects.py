"""Test di ``subjects.resolve_subject``: le soglie 50%/55% richieste per i comandi 1/2."""

from __future__ import annotations

from imaginarium.subjects import resolve_subject

MIN_MAIN = 0.55
MIN_SUB = 0.50


def _resolve(subject_map, **kwargs):
    defaults = dict(
        main_class="vehicle",
        main_confidence=0.9,
        sub_class="treno",
        sub_confidence=0.9,
        subject_map=subject_map,
        min_main_confidence=MIN_MAIN,
        min_sub_confidence=MIN_SUB,
    )
    defaults.update(kwargs)
    return resolve_subject(**defaults)


class TestSottoclasseSicura:
    def test_sottoclasse_coperta_sopra_soglia(self, subject_map):
        result = _resolve(subject_map, sub_confidence=0.50)
        assert result.tier == "sottoclasse"
        assert result.pool_key == "treno"

    def test_sottoclasse_non_coperta_scende_alla_classe(self, subject_map):
        """'macchinina' non e' in subject_map: deve ricadere sul bucket di 'vehicle'."""
        result = _resolve(subject_map, sub_class="macchinina")
        assert result.tier == "classe_principale"
        assert result.pool_key == "veicolo giocattolo"


class TestSottoclasseIncerta:
    def test_appena_sotto_la_soglia_usa_la_classe_principale(self, subject_map):
        result = _resolve(subject_map, sub_confidence=0.4999)
        assert result.tier == "classe_principale"
        assert result.pool_key == "veicolo giocattolo"

    def test_nessuna_sottoclasse_usa_la_classe_principale(self, subject_map):
        result = _resolve(subject_map, sub_class=None, sub_confidence=None)
        assert result.tier == "classe_principale"
        assert result.pool_key == "veicolo giocattolo"


class TestClassePrincipaleIncerta:
    def test_sotto_soglia_usa_il_fallback_finale(self, subject_map):
        result = _resolve(subject_map, main_confidence=0.5499)
        assert result.tier == "generico"
        assert result.pool_key == "gioco di imitazione"

    def test_al_limite_esatto_non_e_generico(self, subject_map):
        """La soglia e' un '<', non un '<=': 0.55 esatto e' già sufficiente."""
        result = _resolve(subject_map, main_confidence=0.55)
        assert result.tier != "generico"


class TestClassePrincipaleSenzaBucket:
    def test_ricade_sul_fallback_finale(self, subject_map):
        result = _resolve(
            subject_map,
            main_class="classe_mai_vista",
            sub_class=None,
            sub_confidence=None,
        )
        assert result.tier == "generico"
        assert result.pool_key == subject_map.final_fallback_subject
