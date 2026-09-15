"""Testes do pipeline de renderizacao."""

from __future__ import annotations

import json

import numpy as np
import pytest

from app import audio as A
from app import config, emotions, prosody
from app.engines import EngineError
from app.render import (
    RenderOptions,
    VoiceSetting,
    _emotion_from_script,
    _resolve,
    _with_emotion,
    render_cue,
    render_script,
)
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
    baixo, _ = render_cue(cue, fake_setting(volume=-6.0), opts)
    assert np.max(np.abs(baixo)) == pytest.approx(np.max(np.abs(base)) / 2, rel=0.05)


def test_limitador_segura_ganho_excessivo():
    """O ganho nao pode estourar: as falas soltas sao gravadas antes do
    limitador do mix, entao cada uma leva o seu."""
    opts = RenderOptions(normalize=False)
    cue = Cue(kind="speech", text="Testing one two three")
    base, _ = render_cue(cue, fake_setting(), opts)
    alto, _ = render_cue(cue, fake_setting(volume=12.0), opts)

    assert np.max(np.abs(alto)) <= 1.0
    # Mais alto que o original, mas bem abaixo dos 4x que o ganho pediria.
    assert np.max(np.abs(base)) < np.max(np.abs(alto)) < np.max(np.abs(base)) * 4


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


def test_emocao_da_linha_sobrepoe_os_params_do_falante():
    """`(emotion=...)` tambem manda nos params nativos do motor."""
    falante = fake_setting(speaker="Ana", params={"exaggeration": 0.9, "cfg_weight": 0.55})

    herdado = _resolve(falante, {})
    assert herdado.params["exaggeration"] == 0.9

    do_roteiro = _resolve(falante, {"emotion": "revoltado"})
    assert do_roteiro.params["exaggeration"] == emotions.resolve("revoltado").exaggeration
    assert do_roteiro.params["cfg_weight"] == emotions.resolve("revoltado").cfg_weight


def test_params_do_motor_na_linha_vencem_o_preset():
    falante = fake_setting(speaker="Ana", params={"exaggeration": 0.9})
    s = _resolve(falante, {"emotion": "raivoso", "exaggeration": 0.4, "temperature": 1.2})
    assert s.params["exaggeration"] == 0.4   # nem o falante nem o preset
    assert s.params["temperature"] == 1.2
    assert s.params["cfg_weight"] == emotions.resolve("raivoso").cfg_weight


def test_amostra_da_linha_e_resolvida_na_pasta_de_amostras():
    falante = fake_setting(speaker="Ana", ref_audio="/qualquer/padrao.wav")
    s = _resolve(falante, {"ref_audio": "voz_cansada.wav"})
    assert s.ref_audio == str(config.REFS_DIR.resolve() / "voz_cansada.wav")


def test_amostra_que_escapa_da_pasta_e_descartada():
    """Defesa em profundidade: o parser ja recusa, isto cobre uso programatico."""
    falante = fake_setting(speaker="Ana", ref_audio="/qualquer/padrao.wav")
    s = _resolve(falante, {"ref_audio": "../../../etc/passwd"})
    assert s.ref_audio == "/qualquer/padrao.wav"


def test_tag_de_tom_sobrepoe_os_params_so_no_trecho_marcado():
    """`<tom>` vale para o seu trecho; o resto da fala fica com o falante."""
    falante = fake_setting(speaker="Ana", params={"exaggeration": 0.9})
    texto = "When did you realize <sombrio>you were following its decisions?"

    cue = Cue(kind="speech", speaker="Ana", text=texto)
    resultado = {}
    for span in prosody.split_spans(texto, falante.emotion, falante.emotion_intensity):
        forcar = _emotion_from_script(cue, span.emotion, falante)
        resultado[span.emotion] = _with_emotion(falante, {}, span.emotion, span.intensity, forcar)

    assert resultado["neutro"].params["exaggeration"] == 0.9
    assert resultado["sombrio"].params["exaggeration"] == emotions.resolve("sombrio").exaggeration


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


# ------------------------------------------------------ tom de voz e efeitos


def test_emocao_do_falante_muda_a_entrega(tmp_path):
    opts = RenderOptions(normalize=False, trim=False, per_line_files=False, lead_in=0, lead_out=0)
    cue = Cue(kind="speech", text="You call that loud enough for me")
    neutro, sr = render_cue(cue, fake_setting(emotion="neutro"), opts)
    raiva, _ = render_cue(cue, fake_setting(emotion="raivoso"), opts)
    cansado, _ = render_cue(cue, fake_setting(emotion="cansado"), opts)
    # Raiva acelera, cansaco arrasta.
    assert A.duration(raiva, sr) < A.duration(neutro, sr) < A.duration(cansado, sr)


def test_emocao_na_linha_vence_a_do_falante(tmp_path):
    opts = RenderOptions(normalize=False, per_line_files=False, lead_in=0, lead_out=0)
    cast = {"A": fake_setting(speaker="A", emotion="cansado")}
    lento = render_script("[A] one two three four five", cast, opts, tmp_path / "1")
    rapido = render_script("[A](emotion=raivoso) one two three four five", cast,
                           RenderOptions(normalize=False, per_line_files=False, lead_in=0, lead_out=0),
                           tmp_path / "2")
    assert rapido["duration"] < lento["duration"]


def test_ajuste_numerico_vence_a_emocao():
    """(speed=...) e absoluto e ignora o multiplicador do preset.

    O resto do preset (fraseado, pontuacao, volume) continua valendo: travar a
    velocidade nao e o mesmo que desligar a emocao.
    """
    from app.render import _resolve

    raiva = _resolve(fake_setting(), {"emotion": "raivoso", "speed": 1.0})
    cansaco = _resolve(fake_setting(), {"emotion": "cansado", "speed": 1.0})
    assert raiva.speed == 1.0 and cansaco.speed == 1.0
    assert raiva.volume > cansaco.volume  # o preset ainda diferencia os dois


def test_intensidade_dosa_a_emocao():
    from app.render import _resolve

    cheio = _resolve(fake_setting(emotion="cansado", emotion_intensity=1.0), {})
    meio = _resolve(fake_setting(emotion="cansado", emotion_intensity=0.5), {})
    zero = _resolve(fake_setting(emotion="cansado", emotion_intensity=0.0), {})
    assert cheio.speed < meio.speed < zero.speed
    assert zero.speed == 1.0 and zero.volume == 0.0  # intensidade 0 = sem efeito


def test_preset_nunca_altera_o_tom():
    """A regressao que motivou a reescrita: mexer no pitch arrastava os
    formantes e descaracterizava a voz."""
    from app.render import _resolve

    for emocao in [e.id for e in __import__("app.emotions", fromlist=["x"]).EMOTIONS]:
        resolvido = _resolve(fake_setting(pitch=-3.0), {"emotion": emocao})
        assert resolvido.pitch == -3.0, emocao


def test_emocao_preserva_o_timbre_do_personagem(tmp_path):
    """O preset e relativo: um personagem grave nao vira agudo com raiva."""
    from app.render import _resolve

    grave = _resolve(fake_setting(pitch=-6.0), {"emotion": "raivoso"})
    agudo = _resolve(fake_setting(pitch=4.0), {"emotion": "raivoso"})
    assert grave.pitch < 0 and grave.pitch < agudo.pitch


def test_efeito_altera_o_audio(tmp_path):
    opts = RenderOptions(normalize=False, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="Systems online initiating sequence")
    limpo, sr = render_cue(cue, fake_setting(), opts)
    robo, _ = render_cue(cue, fake_setting(effect="robo"), opts)
    n = min(len(limpo), len(robo))
    assert float(np.sqrt(np.mean((robo[:n] - limpo[:n]) ** 2))) > 0.01


def test_efeito_na_linha(tmp_path):
    opts = RenderOptions(per_line_files=False)
    m = render_script("[A](effect=telefone, intensidade=0.9) hello there", cast_for("A"), opts, tmp_path / "e")
    assert m["errors"] == [] and m["lines"][0]["effect"] == "telefone"


def test_manifesto_registra_tom_e_efeito(tmp_path):
    cast = {"A": fake_setting(speaker="A", emotion="sombrio", effect="megafone")}
    m = render_script("[A] hello there", cast, RenderOptions(per_line_files=False), tmp_path / "m")
    assert m["lines"][0]["emotion"] == "sombrio"
    assert m["lines"][0]["effect"] == "megafone"


def test_emocao_desconhecida_nao_derruba_a_renderizacao(tmp_path):
    cast = {"A": fake_setting(speaker="A", emotion="inexistente")}
    m = render_script("[A] hello there", cast, RenderOptions(per_line_files=False), tmp_path / "x")
    assert m["errors"] == [] and m["lines"][0]["emotion"] == "neutro"


def test_efeito_nao_estoura_o_volume(tmp_path):
    opts = RenderOptions(per_line_files=False)
    for efeito in ("robo", "megafone", "radio", "alienigena", "coro"):
        wav, _ = render_cue(Cue(kind="speech", text="Testing the effect chain"),
                            fake_setting(effect=efeito), opts)
        assert np.max(np.abs(wav)) <= 1.0, efeito


def test_previa_e_renderizacao_aplicam_a_emocao_igualmente(tmp_path):
    """Regressao: a emocao so era aplicada dentro de render_script, entao o
    botao "Ouvir" (que chama render_cue direto) ignorava o preset."""
    opts = RenderOptions(normalize=False, trim=False, per_line_files=False, lead_in=0, lead_out=0)
    cue = Cue(kind="speech", text="You call that loud enough for me")

    neutro, sr = render_cue(cue, fake_setting(emotion="neutro"), opts)
    raiva, _ = render_cue(cue, fake_setting(emotion="raivoso"), opts)
    assert A.duration(raiva, sr) < A.duration(neutro, sr)

    # E o mesmo resultado pelo caminho completo.
    cast = {"A": fake_setting(speaker="A", emotion="raivoso")}
    via_script = render_script("[A] You call that loud enough for me", cast,
                               RenderOptions(normalize=False, trim=False, per_line_files=False,
                                             lead_in=0, lead_out=0),
                               tmp_path / "s")
    assert via_script["duration"] == pytest.approx(A.duration(raiva, sr), rel=0.02)


def test_emocao_nao_e_aplicada_duas_vezes(tmp_path):
    """render_script resolve para metadados e render_cue resolve para sintetizar;
    os deltas nao podem se acumular."""
    opts = lambda: RenderOptions(normalize=False, trim=False, per_line_files=False, lead_in=0, lead_out=0)
    cast = {"A": fake_setting(speaker="A", emotion="cansado")}
    m = render_script("[A] one two three four", cast, opts(), tmp_path / "d")

    direto, sr = render_cue(Cue(kind="speech", text="one two three four"),
                            fake_setting(emotion="cansado"), opts())
    assert m["duration"] == pytest.approx(A.duration(direto, sr), rel=0.02)


# ------------------------------------------------- tom por trecho da fala


def test_trecho_com_tom_proprio_muda_a_fala(tmp_path):
    opts = lambda: RenderOptions(normalize=False, trim=False, per_line_files=False,
                                 lead_in=0, lead_out=0)
    cast = cast_for("A")
    com = render_script("[A] Good evening everyone! <cansado>and I am so tired now.",
                        cast, opts(), tmp_path / "com")
    sem = render_script("[A] Good evening everyone! and I am so tired now.",
                        cast, opts(), tmp_path / "sem")
    assert com["duration"] > sem["duration"]  # o trecho cansado arrasta


def test_cada_trecho_recebe_o_seu_preset(tmp_path):
    """Raiva acelera e cansaco arrasta dentro da MESMA fala."""
    opts = lambda: RenderOptions(normalize=False, trim=False, per_line_files=False,
                                 lead_in=0, lead_out=0)
    rapido = render_script("[A] <raivoso>Get up on your feet right now everyone!",
                           cast_for("A"), opts(), tmp_path / "r")
    lento = render_script("[A] <cansado>Get up on your feet right now everyone!",
                          cast_for("A"), opts(), tmp_path / "l")
    assert rapido["duration"] < lento["duration"]


def test_tag_desconhecida_nao_e_falada_como_tom(tmp_path):
    m = render_script("[A] I love you <3 always", cast_for("A"),
                      RenderOptions(per_line_files=False), tmp_path / "t")
    assert m["errors"] == []


def test_ajuste_da_linha_vale_para_todos_os_trechos():
    """`speed=` na linha e absoluto: nenhum trecho escapa dele."""
    from app.render import _with_emotion

    base = fake_setting()
    for emocao in ("neutro", "raivoso", "cansado"):
        assert _with_emotion(base, {"speed": 1.0}, emocao, 1.0).speed == 1.0


def test_trechos_nao_quebram_a_fala_sem_tag(tmp_path):
    """Sem tags, o resultado tem de ser identico ao de antes do recurso."""
    opts = lambda: RenderOptions(normalize=False, trim=False, per_line_files=False,
                                 lead_in=0, lead_out=0)
    a = render_script("[A] Good evening everyone, welcome to the show tonight.",
                      cast_for("A"), opts(), tmp_path / "a")
    b = render_script("[A] Good evening everyone, welcome to the show tonight.",
                      {"A": fake_setting(speaker="A", emotion="neutro")}, opts(), tmp_path / "b")
    assert a["duration"] == pytest.approx(b["duration"], abs=0.01)


# ------------------------------------------------- o tom precisa ser audivel


def _rms_db(x) -> float:
    return A.lin_to_db(float(np.sqrt(np.mean(x**2))))


def test_volume_do_tom_sobrevive_a_normalizacao():
    """Regressao: `rms_normalize` rodava depois do ganho do preset e zerava o
    volume de todas as emocoes. Como "Igualar volume" vem ligado por padrao na
    interface, sussurrado e revoltado saiam exatamente no mesmo nivel."""
    opts = RenderOptions(normalize=True, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="We drove eight hours to get here tonight")

    alto, _ = render_cue(cue, fake_setting(emotion="revoltado"), opts)
    normal, _ = render_cue(cue, fake_setting(emotion="neutro"), opts)
    baixo, _ = render_cue(cue, fake_setting(emotion="sussurrado"), opts)

    assert _rms_db(alto) > _rms_db(normal) + 3.0
    assert _rms_db(baixo) < _rms_db(normal) - 5.0


def test_igualar_volume_continua_emparelhando_vozes():
    """A normalizacao nao pode ter deixado de fazer o seu trabalho: duas vozes
    no mesmo tom ainda precisam sair no mesmo nivel."""
    opts = RenderOptions(normalize=True, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="We drove eight hours to get here tonight")
    a, _ = render_cue(cue, fake_setting(voice="af_heart"), opts)
    b, _ = render_cue(cue, fake_setting(voice="am_michael"), opts)
    assert abs(_rms_db(a) - _rms_db(b)) < 1.0


def test_diferenca_entre_tons_e_grande_o_bastante_para_ouvir():
    """Nao basta ser diferente: precisa ser *perceptivelmente* diferente.

    Uma versao anterior mudava so ~8% na velocidade, o que passava num teste de
    desigualdade mas nao se ouvia como emocao.
    """
    opts = lambda: RenderOptions(normalize=True, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="We drove eight hours to get here, so you better be loud tonight.")

    raiva, sr = render_cue(cue, fake_setting(emotion="raivoso"), opts())
    cansado, _ = render_cue(cue, fake_setting(emotion="cansado"), opts())

    dur_raiva, dur_cansado = A.duration(raiva, sr), A.duration(cansado, sr)
    assert dur_cansado > dur_raiva * 1.4, (dur_raiva, dur_cansado)
    assert _rms_db(raiva) > _rms_db(cansado) + 5.0


@pytest.mark.parametrize("emocao", ["raivoso", "revoltado", "cansado", "indiferente",
                                    "animado", "sombrio", "sarcastico", "sussurrado", "epico"])
def test_todo_preset_muda_algo_de_forma_mensuravel(emocao):
    opts = lambda: RenderOptions(normalize=True, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="We drove eight hours to get here, so you better be loud tonight.")

    neutro, sr = render_cue(cue, fake_setting(emotion="neutro"), opts())
    alvo, _ = render_cue(cue, fake_setting(emotion=emocao), opts())

    dur = abs(A.duration(alvo, sr) - A.duration(neutro, sr)) / A.duration(neutro, sr)
    vol = abs(_rms_db(alvo) - _rms_db(neutro))
    # Pelo menos 8% de diferenca de duracao ou 2 dB de nivel.
    assert dur > 0.08 or vol > 2.0, (emocao, round(dur, 3), round(vol, 2))


def test_nada_estoura_o_teto_com_preset_alto():
    opts = RenderOptions(normalize=True, trim=False, per_line_files=False)
    for emocao in ("revoltado", "raivoso", "animado", "epico"):
        wav, _ = render_cue(Cue(kind="speech", text="Get up on your feet right now"),
                            fake_setting(emotion=emocao, volume=6.0), opts)
        assert np.max(np.abs(wav)) <= 1.0, emocao


def test_escala_de_raiva_e_audivel_no_pipeline(tmp_path):
    """raivoso -> revoltado -> furioso, medido no audio que sai."""
    opts = lambda: RenderOptions(normalize=True, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="Get up on your feet right now, I said move!")

    saidas = {}
    for emocao in ("neutro", "raivoso", "revoltado", "furioso"):
        wav, sr = render_cue(cue, fake_setting(emotion=emocao), opts())
        saidas[emocao] = (A.duration(wav, sr), _rms_db(wav), A.crest_factor_db(wav))

    # Cada degrau e mais rapido e mais alto que o anterior.
    duracoes = [saidas[e][0] for e in ("neutro", "raivoso", "revoltado", "furioso")]
    niveis = [saidas[e][1] for e in ("neutro", "raivoso", "revoltado", "furioso")]
    assert duracoes == sorted(duracoes, reverse=True), duracoes
    assert niveis == sorted(niveis), niveis

    # Furioso tem de ser inconfundivel ao lado do neutro.
    assert saidas["furioso"][1] > saidas["neutro"][1] + 5.0


def _mordida(x: np.ndarray, sr: int = 24000) -> float:
    """Fracao da energia entre 2 e 6 kHz — onde vive o esforco vocal.

    E a medida certa para agressao: mais confiavel que crest factor, que aqui
    e mascarado pela normalizacao e pelo limitador do fim da cadeia.
    """
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    return float(spec[(freqs >= 2000) & (freqs < 6000)].sum() / max(spec.sum(), 1e-12))


def test_agressao_so_age_nos_presets_que_pedem():
    """Raivoso e so prosodia; furioso processa o sinal."""
    opts = lambda: RenderOptions(normalize=True, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="Get up on your feet right now")

    limpo, sr = render_cue(cue, fake_setting(emotion="raivoso"), opts())
    bruto, _ = render_cue(cue, fake_setting(emotion="furioso"), opts())
    assert _mordida(bruto, sr) > _mordida(limpo, sr) * 3.0


def test_agressividade_manual_em_qualquer_tom():
    """O controle e independente: da para esgoelar sem escolher um preset."""
    opts = lambda: RenderOptions(normalize=True, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="Get up on your feet right now")

    normal, sr = render_cue(cue, fake_setting(emotion="neutro"), opts())
    forcada, _ = render_cue(cue, fake_setting(emotion="neutro", aggression=0.9), opts())
    assert _mordida(forcada, sr) > _mordida(normal, sr) * 3.0


def test_mordida_cresce_ao_longo_da_escala():
    opts = lambda: RenderOptions(normalize=True, trim=False, per_line_files=False)
    cue = Cue(kind="speech", text="Get up on your feet right now, I said move!")
    valores = [_mordida(render_cue(cue, fake_setting(emotion=e), opts())[0])
               for e in ("neutro", "raivoso", "revoltado", "furioso")]
    assert valores == sorted(valores), valores
    assert valores[-1] > valores[0] * 4.0


def test_agressao_na_linha_e_na_tag(tmp_path):
    m = render_script("[A](agressividade=0.8) Get up now\n[A] <furioso>I said move!",
                      cast_for("A"), RenderOptions(per_line_files=False), tmp_path / "a")
    assert m["errors"] == []
    assert len(m["lines"]) == 2


# ------------------------------------- nada impronunciavel chega ao modelo


def _textos_sintetizados(cue: Cue, setting: VoiceSetting, monkeypatch) -> list[str]:
    from app.engines import get_engine

    engine = get_engine("fake")
    vistos: list[str] = []
    original = engine.synth

    def espiao(req):
        vistos.append(req.text)
        return original(req)

    monkeypatch.setattr(engine, "synth", espiao)
    render_cue(cue, setting, RenderOptions())
    return vistos


def test_modelo_nunca_recebe_texto_sem_fonema(monkeypatch):
    """Sem nada para pronunciar o modelo inventa som: balbucio ou letra solta."""
    cue = Cue(kind="speech", text="Listen to me right now. ... Are you still there?")
    for texto in _textos_sintetizados(cue, fake_setting(), monkeypatch):
        assert prosody.has_speech(texto)


def test_modelo_nao_recebe_fragmento_curto(monkeypatch):
    """Fragmento solto e a outra metade da mesma alucinacao."""
    cue = Cue(kind="speech", text="Hey, you, over there, listen up now!")
    for texto in _textos_sintetizados(cue, fake_setting(), monkeypatch):
        assert len(texto) >= prosody.MIN_CLAUSE_CHARS
