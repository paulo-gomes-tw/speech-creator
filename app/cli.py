"""Linha de comando, para renderizar um roteiro sem abrir o navegador.

    python -m app.cli roteiro.txt -o show.wav
    python -m app.cli roteiro.txt --voice bm_george --speed 1.1 --mp3
    python -m app.cli --list-voices --lang a
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from . import config
from .engines import EngineError, get_engine
from .render import RenderOptions, VoiceSetting, render_script
from .script_parser import parse_script
from .voices import KOKORO_VOICES, LANGUAGES


def _list_voices(lang: str | None) -> int:
    voices = [v for v in KOKORO_VOICES if not lang or v.lang == lang]
    if not voices:
        print(f"Nenhuma voz para o idioma '{lang}'.", file=sys.stderr)
        return 1
    atual = None
    for v in sorted(voices, key=lambda v: (v.lang, v.gender, v.id)):
        if v.lang != atual:
            atual = v.lang
            meta = LANGUAGES.get(v.lang, {})
            print(f"\n{meta.get('flag', '')} {meta.get('name', v.lang)}  (codigo '{v.lang}')")
        print(f"  {v.id:<16} {v.name:<12} {v.gender:<10} nota {v.quality}")
    print(f"\n{len(voices)} vozes. Misture com 'af_heart:0.6+af_bella:0.4'.")
    return 0


def _build_cast(parsed, args) -> dict[str, VoiceSetting]:
    """Monta o elenco a partir do --cast (JSON) ou do --voice aplicado a todos."""
    cast: dict[str, VoiceSetting] = {}
    if args.cast:
        raw = json.loads(Path(args.cast).read_text(encoding="utf-8"))
        for name, data in raw.items():
            setting = VoiceSetting.from_dict(data)
            setting.speaker = name
            cast[name] = setting

    for speaker in parsed.speakers:
        if speaker not in cast:
            cast[speaker] = VoiceSetting(
                speaker=speaker, engine=args.engine, voice=args.voice,
                speed=args.speed, pitch=args.pitch, gap=args.gap,
            )
    return cast


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="speech-creator",
        description="Gera o audio de um roteiro de show com vozes de IA.",
    )
    p.add_argument("script", nargs="?", help="arquivo de roteiro (.txt). Use '-' para ler da entrada padrao.")
    p.add_argument("-o", "--output", default="show.wav", help="arquivo de saida (padrao: show.wav)")
    p.add_argument("--engine", default="kokoro", help="motor de sintese (padrao: kokoro)")
    p.add_argument("--voice", default="af_heart", help="voz padrao para falantes sem elenco definido")
    p.add_argument("--cast", help="JSON com a configuracao por falante")
    p.add_argument("--speed", type=float, default=1.0, help="velocidade (padrao: 1.0)")
    p.add_argument("--pitch", type=float, default=0.0, help="tom em semitons (padrao: 0)")
    p.add_argument("--gap", type=float, default=0.6, help="pausa entre falas em segundos (padrao: 0.6)")
    p.add_argument("--lead-in", type=float, default=0.5, help="silencio no inicio")
    p.add_argument("--lead-out", type=float, default=1.0, help="silencio no fim")
    p.add_argument("--mp3", action="store_true", help="gerar tambem MP3 (requer ffmpeg)")
    p.add_argument("--no-normalize", action="store_true", help="nao igualar o volume entre as falas")
    p.add_argument("--no-lines", action="store_true", help="nao gerar um arquivo por fala")
    p.add_argument("--list-voices", action="store_true", help="listar as vozes disponiveis e sair")
    p.add_argument("--lang", help="filtrar as vozes por idioma (a, b, p, e, f, i, h, j, z)")
    args = p.parse_args(argv)

    if args.list_voices:
        return _list_voices(args.lang)

    if not args.script:
        p.error("informe o arquivo de roteiro (ou use --list-voices)")

    text = sys.stdin.read() if args.script == "-" else Path(args.script).read_text(encoding="utf-8")
    parsed = parse_script(text)
    for warning in parsed.warnings:
        print(f"aviso: {warning}", file=sys.stderr)

    engine = get_engine(args.engine)
    if not engine.is_available():
        print(f"erro: motor '{args.engine}' nao instalado.\n  {engine.install_hint}", file=sys.stderr)
        return 1

    out_path = Path(args.output).resolve()
    opts = RenderOptions(
        normalize=not args.no_normalize,
        lead_in=args.lead_in, lead_out=args.lead_out, default_gap=args.gap,
        formats=["wav", "mp3"] if args.mp3 else ["wav"],
        per_line_files=not args.no_lines,
    )

    config.ensure_dirs()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Renderiza num diretorio temporario e so entao move para o destino final,
    # para nunca sobrescrever um arquivo do usuario com um nome intermediario.
    tmp = tempfile.mkdtemp(prefix="speech-creator-")
    out_dir = Path(tmp)

    total = parsed.stats()["lines"]
    print(f"Gerando {total} falas de {len(parsed.speakers)} falantes...", file=sys.stderr)

    def progress(current: int, _total: int, message: str) -> None:
        print(f"  [{current}/{total}] {message}", file=sys.stderr)

    try:
        manifest = render_script(text, _build_cast(parsed, args), opts, out_dir, progress=progress)
    except EngineError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    try:
        for fmt, rel in manifest["files"].items():
            destino = out_path if fmt == "wav" else out_path.with_suffix(f".{fmt}")
            shutil.move(str(out_dir / rel), str(destino))
            print(f"\nPronto: {destino}  ({manifest['duration']}s)", file=sys.stderr)

        linhas_dir = out_dir / "falas"
        if opts.per_line_files and linhas_dir.is_dir():
            destino_linhas = out_path.parent / f"{out_path.stem}_falas"
            if destino_linhas.exists():
                shutil.rmtree(destino_linhas)
            shutil.move(str(linhas_dir), str(destino_linhas))
            print(f"Falas individuais em: {destino_linhas}", file=sys.stderr)

        shutil.move(str(out_dir / "manifest.json"), str(out_path.with_suffix(".json")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for err in manifest["errors"]:
        print(f"aviso: linha {err['line_no']}: {err['error']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
