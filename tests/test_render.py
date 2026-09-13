"""Testes do pipeline de renderizacao."""

from __future__ import annotations

import json

import numpy as np
import pytest

from app import audio as A
from app.engines import EngineError
from app.render import RenderOptions, VoiceSetting, render_cue, render_script
from app.script_parser import Cue


def fake_setting(**kw) -> VoiceSetting:
    return VoiceSetting(**{"engine": "fake", "voice": "af_heart", **kw})


def cast_for(*speakers, **kw) -> dict[str, VoiceSetting]:
    return {sp: fake_setting(speaker=sp, **kw) for sp in speakers}


# ---------------------------------------------------------------- render_cue


def test_render_cue_produz_audio():
    wav, sr = render_cue(Cue(kind="speech", text="Good evening everyone"), fake_setting(), RenderOptions())
    assert sr == 24000 and len(wav) > 0
    assert wav.dtype == np.float32 and np.max(np.abs(wav)) <= 1.0


def test_velocidade_encurta_o_audio():
    opts = RenderOptions(normalize=False)
    texto = Cue(kind="speech", text="Good evening everyone, welcome to the show")
    lento, sr = render_cue(texto, fake_setting(speed=0.75), opts)
    rapido, _ = render_cue(texto, fake_setting(speed=1.5), opts)
    assert A.duration(lento, sr) > A.duration(rapido, sr) * 1.5


def test_volume_aplica_ganho():
    opts = RenderOptions(normalize=False)
    cue = Cue(kind="speech", text="Testing one two three")
    base, _ = render_cue(cue, fake_setting(), opts)
    alto, _ = render_cue(cue, fake_setting(volume=6.0), opts)
    assert np.max(np.abs(alto)) == pytest.approx(np.max(np.abs(base)) * 2, rel=0.05)


def test_normalizacao_iguala_vozes_diferentes():
    opts = RenderOptions(normalize=True, target_dbfs=-20.0)
    cue = Cue(kind="speech", text="Testing one two three four")
    a, _ = render_cue(cue, fake_setting(voice="af_heart"), opts)
    b, _ = render_cue(cue, fake_setting(voice="am_michael"), opts)
    rms = lambda x: A.lin_to_db(float(np.sqrt(np.mean(x**2))))
    assert abs(rms(a) - rms(b)) < 1.0


def test_pitch_preserva_a_duracao():
    opts = RenderOptions(normalize=False, trim=False)
    cue = Cue(kind="speech", text="Testing the pitch shifting path")
    base, sr = render_cue(cue, fake_setting(), opts)
    grave, _ = render_cue(cue, fake_setting(pitch=-5), opts)
    assert abs(A.duration(grave, sr) - A.duration(base, sr)) < 0.1


def test_texto_vazio_devolve_audio_vazio():
    wav, _ = render_cue(Cue(kind="speech", text="   "), fake_setting(), RenderOptions())
    assert len(wav) == 0


def test_texto_gigante_e_recusado():
    from app import config

    with pytest.raises(EngineError, match="caracteres"):
        render_cue(Cue(kind="speech", text="a" * (config.MAX_CHARS_PER_CUE + 1)), fake_setting(), RenderOptions())


def test_reamostragem_da_saida():
    opts = RenderOptions(sample_rate=48000)
    wav, sr = render_cue(Cue(kind="speech", text="Testing sample rate"), fake_setting(), opts)
    assert sr == 48000 and len(wav) > 0


def test_ajustes_inline_sobrepoem_o_elenco(tmp_path):
    """`(speed=...)` na linha deve vencer a configuracao do falante."""
    script_lento = "[Ana](speed=0.5) Good evening everyone welcome"
    script_rapido = "[Ana](speed=2.0) Good evening everyone welcome"
    opts = RenderOptions(normalize=False, per_line_files=False)
    a = render_script(script_lento, cast_for("Ana", speed=1.0), opts, tmp_path / "a")
    b = render_script(script_rapido, cast_for("Ana", speed=1.0), RenderOptions(normalize=False, per_line_files=False), tmp_path / "b")
    assert a["duration"] > b["duration"] * 2


# ---------------------------------------------------------------- render_script


def test_render_script_gera_mix_e_falas(sample_script, tmp_path):
    out = tmp_path / "show"
    m = render_script(sample_script, cast_for("Announcer", "Singer", "Guitarist"), RenderOptions(), out)

    assert (out / "show.wav").exists()
    assert (out / "manifest.json").exists()
    assert len(m["lines"]) == 4
    assert m["errors"] == []
    for line in m["lines"]:
        assert (out / line["file"]).exists()
        assert line["end"] > line["start"]


def test_manifesto_tem_linha_do_tempo_ordenada(sample_script, tmp_path):
    m = render_script(sample_script, cast_for("Announcer", "Singer", "Guitarist"), RenderOptions(), tmp_path / "s")
    starts = [l["start"] for l in m["lines"]]
    assert starts == sorted(starts)
    assert m["lines"][-1]["end"] <= m["duration"]


def test_pausa_explicita_aumenta_a_duracao(tmp_path):
    opts = lambda: RenderOptions(per_line_files=False, lead_in=0, lead_out=0, normalize=False)
    sem = render_script("[A] one two\n[A] three four", cast_for("A", gap=0.1), opts(), tmp_path / "1")
    com = render_script("[A] one two\n[pause 5]\n[A] three four", cast_for("A", gap=0.1), opts(), tmp_path / "2")
    assert com["duration"] - sem["duration"] == pytest.approx(5.0, abs=0.15)


def test_lead_in_e_lead_out(tmp_path):
    base = render_script("[A] hello there", cast_for("A"), RenderOptions(lead_in=0, lead_out=0, per_line_files=False), tmp_path / "1")
    pad = render_script("[A] hello there", cast_for("A"), RenderOptions(lead_in=2, lead_out=3, per_line_files=False), tmp_path / "2")
    assert pad["duration"] - base["duration"] == pytest.approx(5.0, abs=0.1)


def test_pausa_antes_da_primeira_fala_vira_lead_in(tmp_path):
    opts = RenderOptions(lead_in=0, lead_out=0, per_line_files=False)
    m = render_script("[pause 3]\n[A] hello", cast_for("A"), opts, tmp_path / "p")
    assert m["lines"][0]["start"] == pytest.approx(3.0, abs=0.1)


def test_falante_sem_elenco_usa_o_padrao(tmp_path):
    m = render_script("[Desconhecido] hello there", {}, RenderOptions(per_line_files=False),
                      tmp_path / "d", default_setting=fake_setting())
    assert m["errors"] == [] and len(m["lines"]) == 1


def test_uma_fala_com_erro_nao_derruba_o_show(tmp_path):
    script = "[A] tudo bem aqui\n[A] BOOM falha aqui\n[A] e continua depois"
    m = render_script(script, cast_for("A"), RenderOptions(per_line_files=False), tmp_path / "e")
    assert len(m["lines"]) == 2
    assert len(m["errors"]) == 1 and "proposital" in m["errors"][0]["error"]
    assert m["errors"][0]["line_no"] == 2


def test_todas_as_falas_falhando_levanta_erro(tmp_path):
    with pytest.raises(EngineError, match="Nenhuma fala"):
        render_script("[A] BOOM", cast_for("A"), RenderOptions(), tmp_path / "x")


def test_roteiro_sem_falas_levanta_erro(tmp_path):
    with pytest.raises(EngineError, match="nenhuma fala"):
        render_script("# so um comentario", cast_for("A"), RenderOptions(), tmp_path / "y")


def test_cancelamento_interrompe(tmp_path):
    with pytest.raises(EngineError, match="cancelada"):
        render_script("[A] um\n[A] dois", cast_for("A"), RenderOptions(), tmp_path / "c", cancelled=lambda: True)


def test_progresso_e_reportado(tmp_path):
    eventos = []
    render_script("[A] um dois\n[A] tres quatro", cast_for("A"), RenderOptions(per_line_files=False),
                  tmp_path / "p", progress=lambda c, t, m: eventos.append((c, t)))
    assert eventos and eventos[-1][0] == eventos[-1][1] == 2


def test_per_line_files_desligado(tmp_path):
    out = tmp_path / "nolines"
    m = render_script("[A] hello there", cast_for("A"), RenderOptions(per_line_files=False), out)
    assert "file" not in m["lines"][0]
    assert not (out / "falas").exists()


def test_mp3_sem_ffmpeg_ainda_entrega_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "has_ffmpeg", lambda: False)
    out = tmp_path / "m"
    m = render_script("[A] hello", cast_for("A"), RenderOptions(formats=["mp3"], per_line_files=False), out)
    assert m["files"].get("wav") and (out / "show.wav").exists()
    assert any("ffmpeg" in e["error"] for e in m["errors"])


def test_manifesto_e_json_valido(sample_script, tmp_path):
    out = tmp_path / "j"
    render_script(sample_script, cast_for("Announcer", "Singer", "Guitarist"), RenderOptions(), out)
    data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert data["sample_rate"] == 24000 and data["duration"] > 0


def test_voice_setting_ignora_campos_desconhecidos():
    s = VoiceSetting.from_dict({"voice": "af_bella", "campo_inexistente": 1})
    assert s.voice == "af_bella"


# ------------------------------------------------- regressoes de comportamento


def test_opcoes_nao_sao_mutadas_entre_renderizacoes(tmp_path):
    """Uma pausa inicial ja somou em opts.lead_in e vazava para o render seguinte."""
    opts = RenderOptions(lead_in=0.5, lead_out=0, per_line_files=False)
    a = render_script("[pause 3]\n[A] hello", cast_for("A"), opts, tmp_path / "1")
    assert opts.lead_in == 0.5  # objeto preservado
    b = render_script("[pause 3]\n[A] hello", cast_for("A"), opts, tmp_path / "2")
    assert a["duration"] == pytest.approx(b["duration"], abs=0.01)


def test_precedencia_da_pausa_linha_falante_show(tmp_path):
    """Ajuste da linha > configuracao do falante > padrao do show."""
    def duracao(script, gap_do_falante, gap_do_show):
        opts = RenderOptions(per_line_files=False, lead_in=0, lead_out=0,
                             normalize=False, default_gap=gap_do_show)
        cast = {"A": fake_setting(speaker="A", gap=gap_do_falante)}
        return render_script(script, cast, opts, tmp_path / str(id(script) + hash(gap_do_falante)))["duration"]

    script = "[A] one two\n[A] three four"
    # Sem gap no falante, o padrao do show comanda.
    assert duracao(script, None, 3.0) - duracao(script, None, 0.0) == pytest.approx(3.0, abs=0.1)
    # Com gap no falante, o padrao do show e ignorado.
    assert duracao(script, 0.5, 9.0) - duracao(script, 0.5, 0.0) == pytest.approx(0.0, abs=0.1)


def test_ajuste_de_pausa_na_linha_vence_o_falante(tmp_path):
    opts = lambda: RenderOptions(per_line_files=False, lead_in=0, lead_out=0, normalize=False)
    cast = {"A": fake_setting(speaker="A", gap=0.1)}
    curto = render_script("[A] one two\n[A] three", cast, opts(), tmp_path / "c")
    longo = render_script("[A](gap=4) one two\n[A] three", cast, opts(), tmp_path / "l")
    assert longo["duration"] - curto["duration"] == pytest.approx(3.9, abs=0.15)
