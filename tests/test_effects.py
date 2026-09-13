"""Testes dos efeitos de voz."""

from __future__ import annotations

import numpy as np
import pytest

from app import audio as A
from app import effects as FX

SR = 24000


def voz(seconds: float = 1.0, f0: float = 140.0, vibrato: bool = True) -> np.ndarray:
    """Sinal parecido com voz: fundamental com harmonicos e leve vibrato."""
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    freq = f0 * (1 + 0.03 * np.sin(2 * np.pi * 5 * t)) if vibrato else np.full_like(t, f0)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return (0.4 * np.sin(phase) + 0.2 * np.sin(2 * phase) + 0.1 * np.sin(3 * phase)).astype(np.float32)


def ruido(seconds: float = 1.0, seed: int = 7) -> np.ndarray:
    """Ruido branco: tem energia em todas as faixas, entao revela o que um
    filtro corta. Um sinal de voz sintetica nao serve — ele ja nasce sem
    agudos, e a comparacao mede so ruido numerico."""
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(SR * seconds)) * 0.2).astype(np.float32)


def banda_energia(x: np.ndarray, lo: float, hi: float) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    return float(spec[(freqs >= lo) & (freqs < hi)].sum() / max(spec.sum(), 1e-12))


def f0_autocorr(x: np.ndarray) -> float:
    seg = x.astype(np.float64) - np.mean(x)
    ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
    lo, hi = int(SR / 400), int(SR / 60)
    return SR / (lo + int(np.argmax(ac[lo:hi])))


@pytest.mark.parametrize("efeito", [e.id for e in FX.EFFECTS])
def test_todo_efeito_produz_audio_valido(efeito):
    out = FX.apply(voz(), SR, efeito)
    assert len(out) > 0
    assert out.dtype == np.float32
    assert np.all(np.isfinite(out))
    assert np.max(np.abs(out)) <= 1.0


@pytest.mark.parametrize("efeito", [e.id for e in FX.EFFECTS])
def test_duracao_e_praticamente_preservada(efeito):
    x = voz(1.5)
    out = FX.apply(x, SR, efeito)
    assert abs(len(out) - len(x)) / len(x) < 0.05


def test_nenhum_nao_altera():
    x = voz()
    assert FX.apply(x, SR, "nenhum") is x


def test_intensidade_zero_nao_altera():
    x = voz()
    assert FX.apply(x, SR, "robo", 0.0) is x


def test_robo_achata_a_entonacao():
    """A marca do efeito: o tom percebido para de acompanhar a entrada."""
    grave, agudo = voz(1.2, f0=110, vibrato=False), voz(1.2, f0=260, vibrato=False)
    assert abs(f0_autocorr(grave) - f0_autocorr(agudo)) > 80  # entrada varia

    r_grave = A.robotize(grave, SR)
    r_agudo = A.robotize(agudo, SR)
    assert abs(f0_autocorr(r_grave) - f0_autocorr(r_agudo)) < 5  # saida trava


def test_robo_trava_na_grade_de_frequencia():
    """A fase zerada concentra a energia em multiplos de sr/hop."""
    grade = SR / 256
    out = A.robotize(voz(1.5), SR)
    spec = np.abs(np.fft.rfft(out * np.hanning(len(out)))) ** 2
    freqs = np.fft.rfftfreq(len(out), 1 / SR)
    faixa = (freqs > 50) & (freqs < 3000)
    dist = np.abs(freqs[faixa] / grade - np.round(freqs[faixa] / grade))
    na_grade = spec[faixa][dist < 0.12].sum() / spec[faixa].sum()
    assert na_grade > 0.85


def test_intensidade_maior_afasta_mais_do_original():
    x = voz()
    def distancia(nivel):
        out = FX.apply(x, SR, "robo", nivel)
        n = min(len(out), len(x))
        return float(np.sqrt(np.mean((out[:n] - x[:n]) ** 2)))
    assert distancia(0.9) > distancia(0.3)


def test_telefone_corta_graves_e_agudos():
    x = ruido()
    out = FX.apply(x, SR, "telefone", 1.0)
    assert banda_energia(out, 0, 250) < banda_energia(x, 0, 250) * 0.3
    assert banda_energia(out, 4500, 12000) < banda_energia(x, 4500, 12000) * 0.3
    # A faixa util da linha telefonica sobrevive.
    assert banda_energia(out, 300, 3400) > banda_energia(x, 300, 3400) * 2


def test_megafone_concentra_na_faixa_media():
    x = ruido()
    out = FX.apply(x, SR, "megafone", 1.0)
    assert banda_energia(out, 500, 4000) > banda_energia(x, 500, 4000) * 1.5
    assert banda_energia(out, 0, 300) < banda_energia(x, 0, 300) * 0.5


def test_bandpass_deixa_passar_so_a_faixa_pedida():
    x = ruido()
    out = A.bandpass(x, SR, 800.0, 2000.0, poles=2)
    assert banda_energia(out, 800, 2000) > 0.6
    assert banda_energia(out, 0, 400) < 0.05
    assert banda_energia(out, 4000, 12000) < 0.05


def test_radio_adiciona_chiado():
    """Com o sinal em silencio, so o ruido do efeito deve sobrar."""
    mudo = np.zeros(SR, dtype=np.float32)
    out = FX.apply(mudo, SR, "radio", 1.0)
    assert float(np.sqrt(np.mean(out**2))) > 0.0


def test_coro_engrossa_sem_mudar_o_tom():
    x = voz(1.2, vibrato=False)
    out = FX.apply(x, SR, "coro", 1.0)
    assert abs(f0_autocorr(out) - f0_autocorr(x)) < 8


def test_lofi_reduz_a_resolucao():
    out = A.bitcrush(voz(), SR, bits=4, downsample=1)
    assert len(np.unique(out)) < len(np.unique(voz())) / 10


def test_aliases():
    assert FX.resolve("robot").id == "robo"
    assert FX.resolve("megaphone").id == "megafone"
    assert FX.resolve("PHONE").id == "telefone"


def test_desconhecido_cai_em_nenhum():
    assert FX.resolve("inexistente").id == "nenhum"
    assert FX.resolve(None).id == "nenhum"


def test_audio_vazio_nao_quebra():
    vazio = np.zeros(0, dtype=np.float32)
    for efeito in [e.id for e in FX.EFFECTS]:
        assert len(FX.apply(vazio, SR, efeito)) == 0


def test_catalogo_tem_descricao_e_padrao():
    for item in FX.catalog():
        assert item["name"] and item["description"]
        assert 0.0 <= item["default_amount"] <= 1.0
