"""Auditoria das pausas: cada controle tem de aparecer no audio final.

Estes testes medem o silencio real no WAV gerado, e nao os numeros que o
manifesto declara — a pergunta e se o audio que sai do programa respeita o que
foi pedido.
"""

from __future__ import annotations

import numpy as np
import pytest

from app import audio as A
from app.render import RenderOptions, VoiceSetting, render_script

SR = 24000


def fx(**kw) -> VoiceSetting:
    return VoiceSetting(engine="fake", voice="af_heart", **kw)


def opts(**kw) -> RenderOptions:
    base = {"per_line_files": False, "lead_in": 0.0, "lead_out": 0.0, "normalize": False}
    return RenderOptions(**{**base, **kw})


def blocos_de_silencio(path, minimo: float = 0.05) -> list[float]:
    """Duracao de cada trecho mudo do WAV, em segundos."""
    x, sr = A.read_audio(path)
    quadro = int(sr * 0.01)
    quadros = x[: len(x) // quadro * quadro].reshape(-1, quadro)
    energia = np.sqrt(np.mean(quadros**2, axis=1))
    mudo = energia < max(energia.max() * 0.02, 1e-5)

    blocos, i = [], 0
    while i < len(mudo):
        if mudo[i]:
            j = i
            while j < len(mudo) and mudo[j]:
                j += 1
            dur = (j - i) * 0.01
            if dur >= minimo:
                blocos.append(round(dur, 2))
            i = j
        else:
            i += 1
    return blocos


def renderiza(tmp_path, script, cast, options, nome="s") -> list[float]:
    render_script(script, cast, options, tmp_path / nome)
    return blocos_de_silencio(tmp_path / nome / "show.wav")


DUAS_FALAS = "[A] hello there friend\n[A] second line here"


# ---------------------------------------------------------------- basicos


@pytest.mark.parametrize("lead_in,lead_out", [(0.0, 0.0), (1.0, 2.0), (2.5, 0.5)])
def test_lead_in_e_lead_out(tmp_path, lead_in, lead_out):
    silencios = renderiza(tmp_path, "[A] hello there", {"A": fx(gap=0.5)},
                          opts(lead_in=lead_in, lead_out=lead_out))
    for esperado in (lead_in, lead_out):
        if esperado > 0.05:
            assert any(abs(s - esperado) < 0.08 for s in silencios), (esperado, silencios)


@pytest.mark.parametrize("gap", [0.3, 1.0, 2.5])
def test_pausa_padrao_do_show(tmp_path, gap):
    """Falante sem pausa propria herda a do show."""
    silencios = renderiza(tmp_path, DUAS_FALAS, {"A": fx(gap=None)}, opts(default_gap=gap))
    assert any(abs(s - gap) < 0.08 for s in silencios), silencios


@pytest.mark.parametrize("gap", [0.2, 1.5])
def test_pausa_do_falante_vence_a_do_show(tmp_path, gap):
    silencios = renderiza(tmp_path, DUAS_FALAS, {"A": fx(gap=gap)}, opts(default_gap=9.0))
    assert any(abs(s - gap) < 0.08 for s in silencios), silencios


def test_pausa_da_linha_vence_a_do_falante(tmp_path):
    silencios = renderiza(tmp_path, "[A](gap=3) hello there friend\n[A] second line here",
                          {"A": fx(gap=0.2)}, opts())
    assert any(abs(s - 3.0) < 0.1 for s in silencios), silencios


# ---------------------------------------------------------------- [pause N]


@pytest.mark.parametrize("segundos", [1.0, 2.5, 4.0])
def test_marcador_de_pausa_vale_o_tempo_declarado(tmp_path, segundos):
    """Regressao: `[pause N]` somava-se a pausa automatica, entao `[pause 1]`
    com gap 0.5 rendia 1.5s de silencio."""
    silencios = renderiza(tmp_path, f"[A] hello there friend\n[pause {segundos}]\n[A] second line here",
                          {"A": fx(gap=0.5)}, opts())
    assert any(abs(s - segundos) < 0.1 for s in silencios), silencios
    assert not any(abs(s - (segundos + 0.5)) < 0.05 for s in silencios), silencios


def test_marcadores_seguidos_se_acumulam(tmp_path):
    silencios = renderiza(tmp_path, "[A] hello there friend\n[pause 1]\n[pause 2]\n[A] second line here",
                          {"A": fx(gap=0.5)}, opts())
    assert any(abs(s - 3.0) < 0.12 for s in silencios), silencios


def test_pausa_antes_da_primeira_fala_vira_silencio_inicial(tmp_path):
    silencios = renderiza(tmp_path, "[pause 2]\n[A] hello there friend", {"A": fx(gap=0.5)}, opts())
    assert any(abs(s - 2.0) < 0.1 for s in silencios), silencios


# ---------------------------------------------------------------- emocao


@pytest.mark.parametrize("emocao,mult", [("neutro", 1.0), ("raivoso", 0.65), ("cansado", 1.5)])
def test_emocao_molda_a_pausa_do_falante(tmp_path, emocao, mult):
    silencios = renderiza(tmp_path, DUAS_FALAS, {"A": fx(gap=1.0, emotion=emocao)}, opts())
    assert any(abs(s - mult) < 0.1 for s in silencios), (emocao, silencios)


@pytest.mark.parametrize("emocao,mult", [("neutro", 1.0), ("raivoso", 0.65), ("cansado", 1.5)])
def test_emocao_molda_tambem_a_pausa_herdada(tmp_path, emocao, mult):
    """Regressao: o gap_mult so era aplicado quando o falante tinha pausa
    propria. Como a interface cria todo falante herdando a pausa do show, o
    ajuste de pausa da emocao nunca acontecia na pratica."""
    silencios = renderiza(tmp_path, DUAS_FALAS, {"A": fx(gap=None, emotion=emocao)},
                          opts(default_gap=1.0))
    assert any(abs(s - mult) < 0.1 for s in silencios), (emocao, silencios)


def test_forca_da_emocao_dosa_a_pausa(tmp_path):
    cheio = renderiza(tmp_path, DUAS_FALAS, {"A": fx(gap=None, emotion="cansado", emotion_intensity=1.0)},
                      opts(default_gap=1.0), "cheio")
    meio = renderiza(tmp_path, DUAS_FALAS, {"A": fx(gap=None, emotion="cansado", emotion_intensity=0.5)},
                     opts(default_gap=1.0), "meio")
    zero = renderiza(tmp_path, DUAS_FALAS, {"A": fx(gap=None, emotion="cansado", emotion_intensity=0.0)},
                     opts(default_gap=1.0), "zero")
    assert any(abs(s - 1.50) < 0.1 for s in cheio), cheio
    assert any(abs(s - 1.25) < 0.1 for s in meio), meio
    assert any(abs(s - 1.00) < 0.1 for s in zero), zero


def test_marcador_explicito_ignora_a_emocao(tmp_path):
    """Quem escreve `[pause 3]` quer 3 segundos, nao 3 vezes o multiplicador."""
    silencios = renderiza(tmp_path, "[A] hello there friend\n[pause 3]\n[A] second line here",
                          {"A": fx(gap=1.0, emotion="cansado")}, opts())
    assert any(abs(s - 3.0) < 0.12 for s in silencios), silencios


# ---------------------------------------------------------------- manifesto


def test_manifesto_bate_com_o_audio(tmp_path):
    """Os tempos declarados tem de corresponder ao arquivo entregue."""
    m = render_script("[A] hello there friend\n[pause 2]\n[A] second line here",
                      {"A": fx(gap=0.5)}, opts(lead_in=1.0, lead_out=1.5), tmp_path / "m")
    x, sr = A.read_audio(tmp_path / "m" / "show.wav")
    assert A.duration(x, sr) == pytest.approx(m["duration"], abs=0.02)
    assert m["lines"][0]["start"] == pytest.approx(1.0, abs=0.05)
    # Fim da 1a fala + os 2s do marcador = inicio da 2a.
    assert m["lines"][1]["start"] - m["lines"][0]["end"] == pytest.approx(2.0, abs=0.05)


# ---------------------------------------------------------------- previa


def test_previa_bate_com_o_audio_renderizado(tmp_path):
    """A linha do tempo mostrada na interface tem de prever o audio real."""
    from app.render import timeline

    script = ("[A] hello there friend\n[pause 2]\n[A] second line here\n"
              "[B](gap=1.5) third line here\n[A] fourth line here")
    cast = {"A": fx(gap=None, emotion="cansado"), "B": fx(gap=0.4)}
    options = opts(default_gap=1.0)

    previsto = timeline(script, cast, options)
    m = render_script(script, cast, options, tmp_path / "p")

    assert [l["speaker"] for l in previsto] == [l["speaker"] for l in m["lines"]]
    # A pausa prevista tem de aparecer entre o fim de uma fala e o inicio da seguinte.
    for i in range(len(m["lines"]) - 1):
        real = m["lines"][i + 1]["start"] - m["lines"][i]["end"]
        assert real == pytest.approx(previsto[i]["gap"], abs=0.03), i


def test_previa_explica_a_origem_de_cada_pausa():
    from app.render import timeline

    script = "[A] first line here\n[pause 3]\n[A] second line\n[B](gap=2) third line\n[A] last line"
    previsto = timeline(script, {"A": fx(gap=None), "B": fx(gap=0.5)}, opts(default_gap=0.8))
    assert previsto[0]["source"] == "marcador [pause]" and previsto[0]["gap"] == 3.0
    assert previsto[1]["source"] == "padrão do show" and previsto[1]["gap"] == 0.8
    assert previsto[2]["source"] == "ajuste da linha" and previsto[2]["gap"] == 2.0
    assert previsto[-1]["gap"] == 0.0  # depois da ultima fala nao ha pausa


def test_previa_mostra_o_multiplicador_do_tom():
    from app.render import timeline

    previsto = timeline(DUAS_FALAS, {"A": fx(gap=None, emotion="cansado")}, opts(default_gap=1.0))
    assert previsto[0]["gap"] == pytest.approx(1.5, abs=0.01)
    assert "Cansado" in previsto[0]["source"]
