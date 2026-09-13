# 🎙️ Speech Creator

Gerador de speeches e diálogos com vozes de IA, feito para montar as falas de
um show ao vivo. Você escreve o roteiro, distribui as vozes entre os
personagens e recebe o áudio pronto — a mixagem completa e cada fala separada,
para montar no seu DAW.

Roda **100% local**, com modelo **gratuito** e licença que permite uso
comercial (inclusive em show pago).

---

## Como funciona

```
[Announcer](speed=0.95, pitch=-3) Ladies and gentlemen... please welcome Voltage!
[pause 2]
[Singer] Good evening! How are you feeling tonight?
[Guitarist](speed=1.1) This next one is off the new record.
```

↓

`show.wav` — mixado, com as pausas certas e volume equalizado entre as vozes
`falas/001_Announcer.wav`, `falas/002_Singer.wav`, … — cada fala isolada

---

## Instalação

**Requisito de sistema:** `espeak-ng` (converte texto em fonemas).

| Sistema | Comando |
|---|---|
| macOS | `brew install espeak-ng` |
| Ubuntu/Debian | `sudo apt install espeak-ng` |
| Windows | `winget install espeak-ng` |

Opcional: `ffmpeg` para exportar MP3 (sem ele, o WAV continua funcionando).

Depois:

```bash
git clone <este-repositorio>
cd speech-creator
./run.sh            # Linux/macOS  — cria o venv, instala tudo e sobe o servidor
.\run.ps1           # Windows
```

Abra **http://127.0.0.1:8000**.

Na primeira geração o modelo (~330 MB) é baixado automaticamente do
HuggingFace e fica em cache. **Depois disso a aplicação roda offline.**

---

## O modelo de voz

**[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** — licença Apache 2.0.

| | |
|---|---|
| Vozes | **54**, em 9 idiomas |
| Inglês | **28 vozes** (20 americanas, 8 britânicas) |
| Tamanho | 82M parâmetros, ~330 MB |
| Hardware | roda em CPU, mais rápido que tempo real |
| Custo | gratuito, sem chave de API, sem limite de uso |
| Licença | Apache 2.0 — **uso comercial liberado** |

É o melhor custo-benefício hoje para esse caso: modelos maiores (XTTS, Bark)
são mais lentos e têm licenças restritas para uso comercial; modelos menores
(Piper) têm qualidade bem inferior.

### Vozes em inglês com melhor nota

| Voz | Sotaque | Gênero | Nota |
|---|---|---|---|
| `af_heart` | americano | feminina | **A** |
| `af_bella` | americano | feminina | **A-** |
| `bf_emma` | britânico | feminina | **B-** |
| `af_nicole` | americano | feminina | B- |
| `am_fenrir`, `am_michael`, `am_puck` | americano | masculina | C+ |
| `bm_george`, `bm_fable` | britânico | masculina | C |

Lista completa: `python -m app.cli --list-voices`

---

## Variedade de vozes

Três recursos multiplicam as 28 vozes em inglês num elenco bem maior:

**1. Mistura de vozes.** Some duas vozes do mesmo idioma com pesos — o
resultado é uma voz nova, que não é nenhuma das duas:

```
af_heart:0.6+af_bella:0.4
```

**2. Tom (pitch).** Deslocamento em semitons preservando a duração e a
naturalidade (phase vocoder, não o efeito "esquilo"). `-4` semitons em cima de
`am_michael` já soa como outra pessoa.

**3. Timbre.** Controles de corpo (graves) e brilho (agudos) para diferenciar
um narrador grave e encorpado de um MC estridente.

Combinando os três, cada voz base vira dezenas de personagens distintos.

### Clonagem de voz (opcional)

Para usar a voz de alguém da banda:

```bash
pip install chatterbox-tts
```

Envie uma amostra de 7 a 20 segundos na aba **Projetos**, e escolha o motor
Chatterbox no elenco. Licença MIT, também gratuito.

> ⚠️ Clone apenas vozes de quem autorizou.

---

## Sintaxe do roteiro

| Escrita | Efeito |
|---|---|
| `[Singer] texto` | uma fala do falante `Singer` |
| `[Singer]` sozinho numa linha | abre um bloco: as linhas seguintes viram **uma** fala |
| `[pause 2]` | 2 segundos de silêncio (`[pausa 2]` também funciona) |
| `# comentário` | ignorado |
| `[Singer](speed=1.1) texto` | ajuste só nesta linha |

Ajustes aceitos em `( )`, em inglês ou português:

| Ajuste | Alias | Faixa | O que faz |
|---|---|---|---|
| `speed` | `velocidade` | 0.3 – 3.0 | velocidade da fala |
| `pitch` | `tom` | -24 – 24 | tom em semitons |
| `volume` | — | -40 – 12 | ganho em dB |
| `gap` | `pausa` | 0 – 60 | pausa depois desta fala |
| `warmth` | `calor` | -18 – 18 | graves |
| `brightness` | `brilho` | -18 – 18 | agudos |

---

## Interface

| Aba | Para quê |
|---|---|
| **Roteiro** | escrever o texto e ajustar a mixagem do show |
| **Elenco** | voz e tratamento de cada falante, com prévia instantânea |
| **Vozes** | ouvir as 54 vozes, com filtro por idioma e gênero |
| **Saída** | progresso da geração, player, download do mix e de cada fala |
| **Projetos** | salvar/abrir roteiros e enviar amostras para clonagem |

O volume é equalizado entre as falas automaticamente (normalização RMS), então
uma voz não sai gritando e a outra sussurrando no PA.

---

## Linha de comando

Para gerar em lote, sem abrir o navegador:

```bash
python -m app.cli roteiro.txt -o show.wav
python -m app.cli roteiro.txt --voice bm_george --speed 1.1 --mp3
python -m app.cli roteiro.txt --cast elenco.json -o show.wav
python -m app.cli --list-voices --lang a
```

`elenco.json`:

```json
{
  "Announcer": { "voice": "am_michael", "pitch": -3, "speed": 0.95 },
  "Singer":    { "voice": "af_heart" },
  "Guitarist": { "voice": "af_heart:0.6+af_bella:0.4", "brightness": 3 }
}
```

---

## Estrutura

```
app/
  main.py            API HTTP + serve a interface
  cli.py             linha de comando
  script_parser.py   roteiro -> lista de falas
  render.py          pipeline: síntese + pós-processamento + mixagem
  audio.py           DSP (pitch, EQ, normalização, montagem) em numpy
  jobs.py            fila de renderização com progresso
  projects.py        persistência em JSON
  voices.py          catálogo das 54 vozes
  engines/           kokoro_engine.py, chatterbox_engine.py, base.py
web/                 interface (HTML/CSS/JS puro, sem build)
tests/               117 testes
data/                projetos, saídas e amostras (não versionado)
```

Para adicionar outro motor de TTS, implemente `Engine` em `app/engines/base.py`
e registre em `app/engines/__init__.py`.

---

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes usam um motor falso, então rodam em segundos e **não precisam baixar
o modelo**.

---

## Configuração

| Variável | Padrão | Para quê |
|---|---|---|
| `SPEECH_CREATOR_DATA` | `./data` | onde ficam projetos e saídas |
| `SPEECH_CREATOR_DEVICE` | `cpu` | use `cuda` se tiver GPU NVIDIA |
| `SPEECH_CREATOR_WORKERS` | `1` | renderizações simultâneas |
| `PORT` | `8000` | porta do servidor |

---

## Licenças

| Componente | Licença | Uso comercial |
|---|---|---|
| Kokoro-82M | Apache 2.0 | ✅ |
| Chatterbox (opcional) | MIT | ✅ |
| Esta aplicação | MIT | ✅ |
