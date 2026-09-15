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

## Tom de voz (emoção)

Dez presets: **neutro, raivoso, revoltado, indiferente, cansado, animado,
sombrio, sarcástico, sussurrado, épico**.

```
[MC](emotion=raivoso) You call that loud?!
[Roadie](emocao=cansado, forca=0.6) Two more shows this week.
```

**Como funciona — e por que não distorce.** Emoção na fala é ritmo, ênfase e
fraseado, não deslocamento de frequência. Então os presets agem **antes da
síntese**, mudando o que o modelo recebe:

| Lever | O que faz |
|---|---|
| velocidade | parâmetro nativo do Kokoro — o modelo re-sintetiza, sem artefato |
| contorno | cada oração vai com a sua velocidade (acelerar, perder fôlego) |
| respiro | silêncio entre as orações |
| pontuação | reescrita que o G2P repassa ao modelo e muda a entonação |
| volume | ganho limpo |

Exemplo real do que o modelo recebe, para
`"We drove eight hours to get here, so you better be loud tonight."`:

```
RAIVOSO    1.05x  We drove eight hours to get here.
           1.15x  So you better be loud tonight!          (respiro 0.0s)

CANSADO    0.95x  We drove eight hours to get here,
           0.77x  so you better be loud tonight...        (respiro 0.3s)

ÉPICO      0.90x  We drove eight hours to get here,
           0.86x  so you better be loud tonight.          (respiro 0.45s)
```

**Nenhum preset mexe no tom (pitch).** Deslocar o tom com phase vocoder arrasta
os formantes junto, e formante é o que define a identidade de uma voz — o
resultado não soa como a mesma pessoa com raiva, soa como voz distorcida. Pelo
mesmo motivo o EQ dos presets é limitado a ±2 dB. O controle de pitch continua
disponível como ajuste manual, para quem quiser pagar esse preço
conscientemente.

A **força da emoção** (0 a 100%, ou `forca=` no roteiro) dosa o quanto o preset
pesa. Em 0% o preset não tem efeito nenhum.

Os presets são **relativos**: um personagem configurado grave continua grave.

Para emoção atuada de verdade, use o motor **Chatterbox** com uma amostra de
referência já falada naquela emoção — ele copia a entrega do áudio. Nesse caso
o preset também ajusta `exaggeration` e `cfg_weight`.

> **Quem vence.** Um tom escrito no roteiro — `emotion=` na linha ou uma tag
> `<tom>` — sobrescreve o `exaggeration` e o `cfg_weight` configurados no
> falante: a indicação mais específica manda. Já o tom herdado do próprio
> falante respeita esses valores, senão os sliders da interface nunca teriam
> efeito. Numa fala com tags, cada trecho decide sozinho: o texto sem tag
> continua com os valores do falante.

> **"Igualar volume" e os presets.** A normalização acontece *antes* dos ganhos
> deliberados (seu slider de volume e o do preset). Ela existe para emparelhar
> vozes diferentes, não para apagar dinâmica proposital — aplicada depois, ela
> zerava o volume de todas as emoções, e sussurrado saía no mesmo nível de
> revoltado.

O painel de **linha do tempo** (aba Roteiro) mostra a velocidade e o volume
efetivos de cada fala e de cada trecho. Se aparecer `1.00x` sem ganho, aquele
preset não está fazendo nada ali.

### Raiva e agressividade

Escala de três degraus:

| Preset | O que faz |
|---|---|
| `raivoso` | rápido e cortado — **só prosódia**, sinal intacto |
| `revoltado` | mais rápido e alto, voz já começando a forçar |
| `furioso` | **muito raivoso**: gritado e esgoelado |

```
[Singer](emotion=furioso) I said get up right now!
[Singer] Normal again. <furioso>MOVE!<neutro> Thanks.
```

**Por que aqui o sinal é processado.** O Kokoro não grita — as vozes são
embeddings fixos, sem esforço vocal, tensão de prega ou fonação pressionada.
Nenhuma manipulação de velocidade produz isso. O que dá para fazer é
reproduzir os *correlatos acústicos* do grito, que são exatamente o que um
técnico de som faz para um vocal cortar:

- **compressão forte** — voz gritada é densa e pressionada;
- **saturação** — o esforço vocal gera harmônicos;
- **energia em 2–5 kHz** — onde vive a agressividade;
- **corte de graves** antes e depois da distorção.

Ao contrário do deslocamento de tom, nada disso mexe nos formantes: continua
sendo a mesma voz, só que esgoelada.

Medido no áudio final, com "Igualar volume" ligado:

| | duração | nível | energia 2–6 kHz |
|---|---|---|---|
| neutro | 3,07 s | −20,0 dB | 0,0103 |
| raivoso | 2,60 s | −15,5 dB | 0,0116 |
| revoltado | 2,48 s | −14,0 dB | 0,0353 |
| furioso | 2,36 s | −12,5 dB | **0,0624** |

A **agressividade** também é um controle independente (0 a 100%, ou
`agressividade=0.8` no roteiro): dá para esgoelar qualquer voz sem escolher um
preset de raiva, ou suavizar o `furioso` se ficar demais.

### Trocar de tom no meio da fala

Uma tag `<tom>` troca o tom dali em diante, até a próxima tag ou o fim da fala.
Não há tag de fechamento — numa fala há muito mais trocas do que pares, e
esquecer de fechar seria o erro mais comum:

```
[Singer] We drove eight hours to get here. <raivoso>So you better be loud!<neutro> Thanks for coming.
```

Cada trecho recebe o preset inteiro: velocidade, contorno, respiro, pontuação e
volume próprios. A normalização é da fala inteira, então as diferenças de
volume entre os trechos sobrevivem.

Dá para dosar por trecho: `<raivoso:0.4>`. Uma tag cujo nome não seja um tom
conhecido fica como texto literal (um `<3` numa letra não some), e o roteiro
avisa se parecer erro de digitação.

## Efeitos de voz

Processamento de sinal — determinístico, sai idêntico em qualquer motor:

| Efeito | Som |
|---|---|
| `robo` | robô clássico de ficção: a entonação vira zumbido metálico |
| `androide` | sintético mas articulado, bom para falas longas |
| `vocoder` | robô cantado, mais grave e saturado |
| `megafone` | PA de arena, alto-falante esgoelado |
| `radio` | transmissão AM com chiado |
| `telefone` | faixa estreita de linha telefônica |
| `alienigena` | timbre fora do humano |
| `lofi` | sampler de 8 bits |
| `coro` | várias vozes desafinadas em uníssono |

```
[Computer](effect=robo) Systems online.
[PA](efeito=megafone, intensidade=0.9) Last call.
```

O `robo` usa robotização por fase zerada na STFT: sem a fase original, a
energia trava numa grade harmônica fixa de 93,75 Hz, substituindo a entonação
por um zumbido constante — e preservando os formantes, então o texto continua
inteligível.

Cada efeito tem uma **intensidade** de 0 a 100%, que mistura sinal limpo e
processado.

## Pausas

| Controle | Onde | O que faz |
|---|---|---|
| silêncio no início / fim | ajustes do show | antes da primeira e depois da última fala |
| pausa padrão entre falas | ajustes do show | usada por quem não definiu a sua |
| pausa depois | por falante | sobrepõe o padrão do show |
| `(gap=2)` / `(pausa=2)` | na linha | sobrepõe o falante |
| `[pause 2]` | no roteiro | **vale exatamente 2 segundos** ali |
| preset de tom | automático | multiplica a pausa herdada (raiva aperta, cansaço alonga) |

`[pause N]` **substitui** a pausa automática em vez de somar-se a ela: quem
escreve o marcador está declarando o tempo que quer. Marcadores seguidos se
acumulam (`[pause 1]` + `[pause 2]` = 3 s).

A aba **Roteiro** tem um painel de **linha do tempo** que mostra a pausa
calculada depois de cada fala e de onde ela veio — conferível antes de gerar.
Ele é calculado pelo mesmo código que renderiza o áudio (`effective_gap()` em
`app/render.py`), então não diverge do resultado.

## Precedência dos ajustes

Do mais fraco para o mais forte:

1. **configuração do falante** — o timbre do personagem
2. **preset de emoção** — aplicado como *delta* sobre ela
3. **ajustes numéricos na linha** — absolutos, vencem tudo

```
[MC](emotion=raivoso, speed=1.0) ...
```
→ pega a raiva (tom, volume, brilho), mas a velocidade fica travada em 1.0.

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
| `emotion` | `emocao` | nome | preset de tom de voz |
| `emotion_intensity` | `forca` | 0 – 1 | o quanto o preset pesa |
| `aggression` | `agressividade` | 0 – 1 | grito/esgoelamento |
| `effect` | `efeito` | nome | efeito de voz |
| `effect_amount` | `intensidade` | 0 – 1 | intensidade do efeito |

---

## Interface

| Aba | Para quê |
|---|---|
| **Roteiro** | escrever o texto e ajustar a mixagem do show |
| **Elenco** | voz, tom de voz, efeito e tratamento de cada falante, com prévia instantânea |
| **Vozes** | ouvir as 54 vozes, com filtro por idioma e gênero |
| **Saída** | progresso da geração, player, download do mix e de cada fala |
| **Projetos** | criar, abrir, duplicar, renomear, exportar/importar e amostras para clonagem |

O volume é equalizado entre as falas automaticamente (normalização RMS), então
uma voz não sai gritando e a outra sussurrando no PA.

---

## Projetos

Cada projeto guarda roteiro, elenco e ajustes num arquivo em
`data/projects/<id>.json`.

| Ação | O que faz |
|---|---|
| **Novo projeto** | começa do zero, com um roteiro inicial em vez de página em branco |
| **Salvar** | grava no projeto aberto |
| **Salvar como…** | grava numa cópia nova, sem tocar no original |
| **Duplicar** | copia um projeto salvo, independente do original |
| **Renomear** | muda só o nome |
| **Exportar** | baixa o `.json` — versionável no git ou enviável para a banda |
| **Importar** | traz um `.json` exportado, sempre como projeto novo |
| **Excluir** | apaga (sem desfazer) |

O cabeçalho mostra o projeto aberto e marca com `•` quando há alterações não
salvas. Criar, abrir ou fechar a aba com trabalho pendente pede confirmação.

O formato exportado é o mesmo do arquivo salvo, então não há conversão em
nenhuma direção. Importar nunca reaproveita o `id` do arquivo — importar duas
vezes gera dois projetos em vez de sobrescrever um existente.

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
  projects.py        projetos: criar, duplicar, renomear, importar/exportar
  voices.py          catálogo das 54 vozes
  emotions.py        presets de prosódia (tom de voz)
  prosody.py         fraseado: orações, contorno de velocidade, pontuação
  effects.py         efeitos de voz (robô, megafone, rádio...)
  engines/           kokoro_engine.py, chatterbox_engine.py, base.py
web/                 interface (HTML/CSS/JS puro, sem build)
tests/               388 testes
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
