"""Testes da agressao vocal (compressao, saturacao e agudos)."""

from __future__ import annotations

import numpy as np
import pytest

from app import audio as A
from app import emotions as E

SR = 24000


def voz(seconds: float = 2.0, f0: float = 130.0, dinamica: bool = True) -> np.ndarray:
    """Sinal parecido com voz: fundamental, formantes e silabas com dinamica."""
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    env = np.clip(np.abs(np.sin(2 * np.pi * 3.5 * t)) ** 1.5, 0.02, 1.0) if dinamica else np.ones_like(t)
    freq = f0 * (1 + 0.05 * np.sin(2 * np.pi * 4 * t))
    fase = 2 * np.pi * np.cumsum(freq) / SR

    x = np.zeros_like(t)
    for n in range(1, 40):
        # Harmonicos moldados por tres formantes, como numa vogal.
        fr = f0 * n
        ganho = sum(a / (1 + ((fr - fc) / bw) ** 2) for a, fc, bw in ((1.0, 700, 130), (0.5, 1200, 160), (0.35, 2600, 220)))
        x += ganho * np.sin(n * fase) / n
    return (x / np.max(np.abs(x)) * env * 0.7).astype(np.float32)


def energia(x: np.ndarray, lo: float, hi: float) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    return float(spec[(freqs >= lo) & (freqs < hi)].sum() / max(spec.sum(), 1e-12))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


# ---------------------------------------------------------------- compressor


def test_compressor_reduz_a_faixa_dinamica():
    """Aproxima o trecho alto do trecho baixo.

    Um compressor com deteccao de nivel atua sobre a dinamica *entre* trechos,
    nao sobre o pico-a-RMS da forma de onda — medir crest factor aqui nao
    descreve o que ele faz.
    """
    alto = voz(1.5, dinamica=False)
    baixo = voz(1.5, dinamica=False) * 0.1  # 20 dB abaixo
    x = np.concatenate([alto, baixo])

    out = A.compress(x, SR, threshold_db=-30.0, ratio=8.0)
    n = len(alto)
    antes = A.lin_to_db(rms(x[:n])) - A.lin_to_db(rms(x[n:]))
    depois = A.lin_to_db(rms(out[:n])) - A.lin_to_db(rms(out[n:]))
    assert antes == pytest.approx(20.0, abs=1.0)
    assert depois < antes - 8.0  # a diferenca entre os trechos encolheu


def test_compressor_com_ratio_1_nao_altera():
    x = voz()
    out = A.compress(x, SR, threshold_db=-30.0, ratio=1.0)
    assert np.allclose(out, x, atol=1e-5)


def test_compressor_nao_mexe_em_sinal_abaixo_do_limiar():
    x = voz() * 0.01  # bem abaixo de -40 dBFS
    out = A.compress(x, SR, threshold_db=-12.0, ratio=8.0)
    assert np.allclose(out, x, atol=1e-6)


def test_compressor_preserva_duracao():
    x = voz(1.7)
    assert len(A.compress(x, SR)) == len(x)


def test_compressor_aceita_audio_vazio():
    assert len(A.compress(np.zeros(0, dtype=np.float32), SR)) == 0


def test_ataque_rapido_segura_mais_que_ataque_lento():
    # Degrau de nivel: o ataque rapido reage antes e deixa passar menos pico.
    x = np.concatenate([np.zeros(2400, dtype=np.float32),
                        (0.9 * np.sin(2 * np.pi * 200 * np.arange(12000) / SR)).astype(np.float32)])
    rapido = A.compress(x, SR, threshold_db=-30.0, ratio=10.0, attack_ms=1.0)
    lento = A.compress(x, SR, threshold_db=-30.0, ratio=10.0, attack_ms=60.0)
    inicio = slice(2400, 2400 + 1200)
    assert np.max(np.abs(rapido[inicio])) < np.max(np.abs(lento[inicio]))


def test_crest_factor_db():
    # Senoide pura: pico/rms = sqrt(2) = 3.01 dB.
    senoide = np.sin(2 * np.pi * 200 * np.arange(SR) / SR).astype(np.float32)
    assert A.crest_factor_db(senoide) == pytest.approx(3.01, abs=0.1)


# ---------------------------------------------------------------- agressao


def test_agressao_zero_e_identidade():
    x = voz()
    assert A.aggression(x, SR, 0.0) is x


def test_agressao_comprime_a_voz():
    """Voz gritada e densa e pressionada: o crest factor cai."""
    x = voz()
    out = A.aggression(x, SR, 0.9)
    assert A.crest_factor_db(out) < A.crest_factor_db(x) - 1.2


def test_agressao_aumenta_a_densidade():
    """Mais RMS para o mesmo pico — e o que faz a voz 'cortar'."""
    x = voz()
    out = A.aggression(x, SR, 0.9)
    assert np.max(np.abs(out)) == pytest.approx(np.max(np.abs(x)), rel=0.02)
    assert rms(out) > rms(x) * 1.15


def test_agressao_joga_energia_nos_agudos():
    """O esforco vocal vive entre 2 e 6 kHz."""
    x = voz()
    assert energia(A.aggression(x, SR, 0.9), 2000, 6000) > energia(x, 2000, 6000) * 1.5


def test_agressao_nao_deixa_ronco_abaixo_da_voz():
    """A saturacao gera energia bem abaixo do fundamental; ela nao pode sobrar.

    Sem o corte apos a distorcao, essa faixa fica com ~1,4% da energia total —
    ronco que suja o grave do PA e desperdica headroom.
    """
    saida = A.aggression(voz(), SR, 0.9)
    assert energia(saida, 0, 60) < 0.001


def test_corte_de_graves_preserva_o_fundamental():
    """O corte tem de ficar longe da voz: uma fundamental grave (85 Hz) nao
    pode ser atenuada pelo filtro."""
    grave = voz(1.5, f0=85.0, dinamica=False)
    saida = A.aggression(grave, SR, 0.9)
    assert energia(saida, 70, 120) > energia(grave, 70, 120) * 0.5


@pytest.mark.parametrize("nivel", [0.2, 0.5, 0.8, 1.0])
def test_agressao_nunca_estoura(nivel):
    assert np.max(np.abs(A.aggression(voz(), SR, nivel))) <= 1.0


@pytest.mark.parametrize("nivel", [0.3, 0.6, 1.0])
def test_agressao_preserva_duracao(nivel):
    x = voz(1.6)
    assert len(A.aggression(x, SR, nivel)) == len(x)


def test_agressao_cresce_com_o_nivel():
    """Mais agressao tem de significar mais agudos, de forma monotona."""
    x = voz()
    valores = [energia(A.aggression(x, SR, n), 2000, 6000) for n in (0.2, 0.5, 0.8)]
    assert valores == sorted(valores)


def test_agressao_com_audio_vazio_ou_mudo():
    assert len(A.aggression(np.zeros(0, dtype=np.float32), SR, 0.8)) == 0
    mudo = np.zeros(SR, dtype=np.float32)
    assert np.all(np.isfinite(A.aggression(mudo, SR, 0.8)))


def test_agressao_nao_produz_nan():
    for nivel in (0.1, 0.5, 1.0):
        assert np.all(np.isfinite(A.aggression(voz(), SR, nivel)))


# ---------------------------------------------------------------- escala de raiva


def test_escala_de_raiva_e_crescente():
    """raivoso -> revoltado -> furioso, cada um mais intenso que o anterior."""
    escala = [E.resolve(e) for e in ("raivoso", "revoltado", "furioso")]
    assert [e.aggression for e in escala] == sorted(e.aggression for e in escala)
    assert [e.speed_mult for e in escala] == sorted(e.speed_mult for e in escala)
    assert [e.volume_delta for e in escala] == sorted(e.volume_delta for e in escala)
    # Raiva aperta as pausas progressivamente.
    assert [e.gap_mult for e in escala] == sorted((e.gap_mult for e in escala), reverse=True)


def test_raivoso_nao_processa_o_sinal():
    """O primeiro degrau e so prosodia: quem quer a voz limpa tem essa opcao."""
    assert E.resolve("raivoso").aggression == 0.0


def test_furioso_e_o_topo_da_escala():
    furioso = E.resolve("furioso")
    assert furioso.aggression >= 0.8
    assert furioso.aggression == max(e.aggression for e in E.EMOTIONS)


def test_aliases_de_muito_raivoso():
    for nome in ("furious", "enraged", "rage", "shouting", "screaming", "muito_raivoso"):
        assert E.resolve(nome).id == "furioso", nome


def test_presets_calmos_nao_tem_agressao():
    for eid in ("neutro", "cansado", "indiferente", "sussurrado", "sarcastico", "sombrio"):
        assert E.resolve(eid).aggression == 0.0, eid


def test_agressao_do_preset_entra_na_configuracao():
    assert E.apply({"params": {}}, "furioso")["aggression"] >= 0.8
    assert E.apply({"params": {}}, "neutro")["aggression"] == 0.0


def test_usuario_sobrepoe_a_agressao_do_preset():
    assert E.apply({"aggression": 0.2, "params": {}}, "furioso")["aggression"] == 0.2


def test_forca_da_emocao_dosa_a_agressao():
    valores = [E.apply({"params": {}}, "furioso", k)["aggression"] for k in (0.0, 0.5, 1.0)]
    assert valores[0] == 0.0 and valores == sorted(valores)
