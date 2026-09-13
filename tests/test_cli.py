"""Testes da linha de comando."""

from __future__ import annotations

import json

import pytest

from app.cli import main


def test_lista_vozes(capsys):
    assert main(["--list-voices"]) == 0
    out = capsys.readouterr().out
    assert "af_heart" in out and "54 vozes" in out


def test_lista_vozes_por_idioma(capsys):
    assert main(["--list-voices", "--lang", "a"]) == 0
    out = capsys.readouterr().out
    assert "af_heart" in out and "pf_dora" not in out


def test_idioma_inexistente(capsys):
    assert main(["--list-voices", "--lang", "q"]) == 1


def test_render_completo(tmp_path, capsys):
    roteiro = tmp_path / "r.txt"
    roteiro.write_text("[Announcer] Welcome to the show\n[pause 1]\n[Singer] Good evening!", encoding="utf-8")
    saida = tmp_path / "show.wav"

    cast = tmp_path / "cast.json"
    cast.write_text(json.dumps({
        "Announcer": {"engine": "fake", "voice": "am_michael", "pitch": -3},
        "Singer": {"engine": "fake", "voice": "af_heart"},
    }), encoding="utf-8")

    assert main([str(roteiro), "-o", str(saida), "--cast", str(cast)]) == 0
    assert saida.exists() and saida.stat().st_size > 1000

    falas = sorted((tmp_path / "show_falas").glob("*.wav"))
    assert [f.name for f in falas] == ["001_Announcer.wav", "002_Singer.wav"]
    assert (tmp_path / "show.json").exists()  # manifesto ao lado do mix
    assert "Pronto" in capsys.readouterr().err


def test_nao_sobrescreve_arquivo_existente(tmp_path):
    """A renderizacao passa por um diretorio temporario, entao nada no destino
    e destruido por um nome de arquivo intermediario."""
    roteiro = tmp_path / "r.txt"
    roteiro.write_text("[A] hello there", encoding="utf-8")
    vizinho = tmp_path / "show.wav"
    vizinho.write_text("nao me apague", encoding="utf-8")

    assert main([str(roteiro), "-o", str(tmp_path / "mix.wav"), "--engine", "fake", "--no-lines"]) == 0
    assert vizinho.read_text(encoding="utf-8") == "nao me apague"
    assert (tmp_path / "mix.wav").exists()


def test_voz_unica_para_todos(tmp_path):
    roteiro = tmp_path / "r.txt"
    roteiro.write_text("[A] one two three\n[B] four five six", encoding="utf-8")
    saida = tmp_path / "out.wav"
    assert main([str(roteiro), "-o", str(saida), "--engine", "fake", "--no-lines"]) == 0
    assert saida.exists()


def test_motor_indisponivel(tmp_path, capsys):
    roteiro = tmp_path / "r.txt"
    roteiro.write_text("[A] hello", encoding="utf-8")
    assert main([str(roteiro), "--engine", "chatterbox"]) == 1
    assert "nao instalado" in capsys.readouterr().err


def test_sem_argumentos_falha():
    with pytest.raises(SystemExit):
        main([])


def test_stdin(tmp_path, monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("[A] hello from stdin"))
    saida = tmp_path / "s.wav"
    assert main(["-", "-o", str(saida), "--engine", "fake", "--no-lines"]) == 0
    assert saida.exists()
