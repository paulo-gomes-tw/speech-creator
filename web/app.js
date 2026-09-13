/* Speech Creator - interface. Sem build: JS puro, carregado direto. */

const state = {
  voices: [],
  languages: {},
  engines: [],
  emotions: [],
  effects: [],
  cast: {},          // falante -> configuracao
  speakers: [],
  job: null,
  poll: null,
  projectId: null,
  ffmpeg: false,
  previewAudio: null,
};

const EXAMPLE = `# Roteiro de exemplo - abertura do show
# [Falante] texto | [pause 2] | ajustes: (speed=) (emotion=) (effect=)
# Trocar de tom no meio da fala: <raivoso> ... <neutro> ...

[Announcer](emotion=epico) Ladies and gentlemen... please welcome to the stage... Voltage!

[pause 2]

[Singer](emotion=animado) Good evening! How are you feeling tonight?
[Singer] We drove eight hours to get here. <raivoso>So you better be loud!<neutro> Thanks for coming.

[pause 1]

[Computer](effect=robo) Systems online. Initiating sequence.

[Guitarist](emotion=indiferente) This next one is off the new record.

[Announcer](emotion=sombrio, effect=megafone) Static Line.

[pause 1.5]

[Singer](emotion=revoltado) One, two, three, four!`;

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- utilidades

function toast(msg, isError = false) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "show" + (isError ? " error" : "");
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = ""), 3600);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body && !(options.body instanceof FormData)
      ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  if (!res.ok) {
    let detail = `Erro ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

// ---------------------------------------------------------------- navegacao

document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    tab.classList.add("active");
    $("view-" + tab.dataset.view).classList.add("active");
    if (tab.dataset.view === "projetos") { loadProjects(); loadRefs(); }
  };
});

// ---------------------------------------------------------------- roteiro

let parseTimer = null;

$("script").addEventListener("input", () => {
  clearTimeout(parseTimer);
  parseTimer = setTimeout(parseScript, 350);
});

async function parseScript() {
  const script = $("script").value;
  if (!script.trim()) {
    $("script-stats").innerHTML = "";
    $("speaker-chips").innerHTML = '<span class="empty">Escreva o roteiro para ver os falantes.</span>';
    return;
  }
  try {
    const cleanCast = {};
    for (const [k, v] of Object.entries(state.cast)) { const { _open, ...rest } = v; cleanCast[k] = rest; }
    const r = await api("/api/parse", {
      method: "POST",
      body: JSON.stringify({ script, cast: cleanCast, options: collectOptions() }),
    });
    const s = r.stats;
    $("script-stats").innerHTML =
      `<span><b>${s.lines}</b> falas</span>` +
      `<span><b>${s.pauses}</b> pausas</span>` +
      `<span><b>${s.words}</b> palavras</span>` +
      `<span>~<b>${fmtTime(s.estimated_seconds)}</b> estimado</span>`;

    state.speakers = r.speakers;
    syncCast(r.speakers);

    $("speaker-chips").innerHTML = r.speakers.length
      ? r.speakers.map((sp) => {
          const c = state.cast[sp];
          return `<span class="badge b" title="${esc(c?.voice || "")}">${esc(sp)}</span>`;
        }).join("")
      : '<span class="empty">Nenhum falante detectado.</span>';

    renderTimeline(r.timeline);
    if (r.warnings.length) toast(r.warnings[0]);
  } catch (e) {
    toast(e.message, true);
  }
}

// Mantem o elenco alinhado com os falantes do roteiro, preservando ajustes.
function syncCast(speakers) {
  const defaults = ["af_heart", "am_michael", "bf_emma", "am_fenrir", "af_bella", "bm_george", "af_nicole", "am_puck"];
  speakers.forEach((sp, i) => {
    if (!state.cast[sp]) {
      state.cast[sp] = {
        speaker: sp, engine: "kokoro", voice: defaults[i % defaults.length],
        ref_audio: null, speed: 1, pitch: 0, volume: 0, gap: null,
        warmth: 0, brightness: 0, emotion: "neutro", emotion_intensity: 1,
        effect: "nenhum", effect_amount: null, params: {},
      };
    }
  });
  renderCast();
}

$("btn-example").onclick = () => { $("script").value = EXAMPLE; parseScript(); };
$("btn-clear").onclick = () => {
  if (confirm("Limpar o roteiro?")) { $("script").value = ""; parseScript(); }
};

// A linha do tempo vem pronta do servidor, calculada pelo mesmo codigo que
// renderiza — reimplementar a precedencia aqui divergiria do audio gerado.
function renderTimeline(linhas) {
  if (!linhas || !linhas.length) {
    $("timeline").innerHTML = '<div class="empty">Sem falas.</div>';
    return;
  }
  const total = linhas.reduce((a, l) => a + l.gap, 0);
  $("timeline").innerHTML = linhas.map((l, i) => `
    <div class="line-item">
      <span class="idx">${String(i + 1).padStart(2, "0")}</span>
      <div>
        <div class="who">${esc(l.speaker)}${l.emotion && l.emotion !== "neutro" ? ` <span class="badge b">${esc(l.emotion)}</span>` : ""}</div>
        <div class="txt">${esc(l.text.slice(0, 70))}${l.text.length > 70 ? "…" : ""}</div>
      </div>
      <div style="text-align:right">
        <div class="who">${l.gap.toFixed(2)}s</div>
        <div class="txt">${esc(l.source)}</div>
      </div>
    </div>`).join("") +
    `<div class="stats" style="margin-top:10px"><span>Silêncio somado entre falas: <b>${total.toFixed(1)}s</b></span></div>`;
}

// ---------------------------------------------------------------- elenco

const effectDefault = (id) => state.effects.find((e) => e.id === id)?.default_amount ?? 0.75;

// Pausa padrao do show, usada pelos falantes que nao definiram a sua.
const showGap = () => parseFloat($("opt-gap").value);

function voiceLabel(id) {
  if (!id) return "";
  return id.split("+").map((part) => {
    const [name] = part.split(":");
    const v = state.voices.find((x) => x.id === name.trim());
    return v ? `${v.flag} ${v.name}` : name;
  }).join(" + ");
}

function renderCast() {
  const host = $("cast-list");
  if (!state.speakers.length) {
    host.innerHTML = '<div class="empty">Escreva o roteiro primeiro — os falantes aparecem aqui.</div>';
    return;
  }

  host.innerHTML = state.speakers.map((sp) => {
    const c = state.cast[sp];
    const collapsed = c._open ? "" : "collapsed";
    return `
    <div class="speaker ${collapsed}" data-sp="${esc(sp)}">
      <div class="speaker-head" data-toggle="${esc(sp)}">
        <span class="caret">▾</span>
        <span class="name">${esc(sp)}</span>
        <span class="meta">${esc(voiceLabel(c.voice))}</span>
        ${c.emotion && c.emotion !== "neutro" ? `<span class="badge b">${esc(state.emotions.find((e) => e.id === c.emotion)?.name || c.emotion)}</span>` : ""}
        ${c.effect && c.effect !== "nenhum" ? `<span class="badge">${esc(state.effects.find((e) => e.id === c.effect)?.name || c.effect)}</span>` : ""}
        <div class="spacer" style="flex:1"></div>
        <button class="small" data-preview="${esc(sp)}">▶ Ouvir</button>
      </div>
      <div class="speaker-body">
        <div class="two" style="margin-top:12px">
          <label class="field">
            <span>Motor</span>
            <select data-f="engine" data-sp="${esc(sp)}">
              ${state.engines.map((e) => `<option value="${e.id}" ${c.engine === e.id ? "selected" : ""} ${e.available ? "" : "disabled"}>${esc(e.name)}${e.available ? "" : " (não instalado)"}</option>`).join("")}
            </select>
          </label>
          ${c.engine === "chatterbox" ? `
          <label class="field">
            <span>Amostra de referência</span>
            <select data-f="ref_audio" data-sp="${esc(sp)}">
              <option value="">— escolha uma amostra —</option>
              ${(state.refs || []).map((r) => `<option value="${esc(r.path)}" ${c.ref_audio === r.path ? "selected" : ""}>${esc(r.name)}</option>`).join("")}
            </select>
          </label>` : `
          <label class="field">
            <span>Voz</span>
            <select data-f="voice" data-sp="${esc(sp)}">
              ${state.voices.map((v) => `<option value="${v.id}" ${c.voice === v.id ? "selected" : ""}>${v.flag} ${esc(v.name)} · ${esc(v.language)} · ${esc(v.gender)} · nota ${esc(v.quality)}</option>`).join("")}
              ${c.voice.includes("+") ? `<option value="${esc(c.voice)}" selected>🎚️ Mistura: ${esc(c.voice)}</option>` : ""}
            </select>
          </label>`}
        </div>

        ${c.engine === "kokoro" ? `
        <label class="field">
          <span>Mistura de vozes (opcional) — some duas vozes do mesmo idioma</span>
          <div class="row">
            <input data-f="voice" data-sp="${esc(sp)}" data-raw="1" value="${esc(c.voice)}"
                   placeholder="af_heart:0.6+af_bella:0.4" style="flex:1;font-family:ui-monospace,monospace">
            <button class="small ghost" data-blend="${esc(sp)}">Sugerir</button>
          </div>
        </label>` : `
        <div class="three">
          <label class="field">
            <span>Expressividade <b class="slider-val">${(c.params?.exaggeration ?? 0.5).toFixed(2)}</b></span>
            <input type="range" data-p="exaggeration" data-sp="${esc(sp)}" min="0.25" max="2" step="0.05" value="${c.params?.exaggeration ?? 0.5}">
          </label>
          <label class="field">
            <span>Aderência (cfg) <b class="slider-val">${(c.params?.cfg_weight ?? 0.5).toFixed(2)}</b></span>
            <input type="range" data-p="cfg_weight" data-sp="${esc(sp)}" min="0" max="1" step="0.05" value="${c.params?.cfg_weight ?? 0.5}">
          </label>
          <label class="field">
            <span>Idioma</span>
            <input data-p="language_id" data-sp="${esc(sp)}" value="${esc(c.params?.language_id ?? "en")}" placeholder="en">
          </label>
        </div>`}

        <div class="four">
          <label class="field">
            <span>Tom de voz</span>
            <select data-f="emotion" data-sp="${esc(sp)}">
              ${state.emotions.map((e) => `<option value="${e.id}" ${c.emotion === e.id ? "selected" : ""} title="${esc(e.description)}">${esc(e.name)}</option>`).join("")}
            </select>
            <div class="hint" style="margin:6px 0 0">${esc(state.emotions.find((e) => e.id === c.emotion)?.description || "")}</div>
          </label>
          <label class="field">
            <span>Força da emoção <b class="slider-val">${Math.round((c.emotion_intensity ?? 1) * 100)}%</b></span>
            <input type="range" data-f="emotion_intensity" data-sp="${esc(sp)}" min="0" max="1" step="0.05"
                   value="${c.emotion_intensity ?? 1}" ${c.emotion === "neutro" ? "disabled" : ""}>
          </label>
          <label class="field">
            <span>Efeito</span>
            <select data-f="effect" data-sp="${esc(sp)}">
              ${state.effects.map((e) => `<option value="${e.id}" ${c.effect === e.id ? "selected" : ""} title="${esc(e.description)}">${esc(e.name)}</option>`).join("")}
            </select>
          </label>
          <label class="field">
            <span>Intensidade do efeito <b class="slider-val">${((c.effect_amount ?? effectDefault(c.effect)) * 100).toFixed(0)}%</b></span>
            <input type="range" data-f="effect_amount" data-sp="${esc(sp)}" min="0" max="1" step="0.05"
                   value="${c.effect_amount ?? effectDefault(c.effect)}" ${c.effect === "nenhum" ? "disabled" : ""}>
          </label>
        </div>

        <div class="three">
          <label class="field">
            <span>Velocidade <b class="slider-val">${(+c.speed).toFixed(2)}x</b></span>
            <input type="range" data-f="speed" data-sp="${esc(sp)}" min="0.5" max="2" step="0.05" value="${c.speed}">
          </label>
          <label class="field">
            <span>Tom <b class="slider-val">${c.pitch > 0 ? "+" : ""}${(+c.pitch).toFixed(1)} st</b></span>
            <input type="range" data-f="pitch" data-sp="${esc(sp)}" min="-12" max="12" step="0.5" value="${c.pitch}">
          </label>
          <label class="field">
            <span>Volume <b class="slider-val">${c.volume > 0 ? "+" : ""}${(+c.volume).toFixed(1)} dB</b></span>
            <input type="range" data-f="volume" data-sp="${esc(sp)}" min="-20" max="10" step="0.5" value="${c.volume}">
          </label>
        </div>

        <div class="three">
          <label class="field">
            <span>Corpo (graves) <b class="slider-val">${c.warmth > 0 ? "+" : ""}${(+c.warmth).toFixed(1)} dB</b></span>
            <input type="range" data-f="warmth" data-sp="${esc(sp)}" min="-12" max="12" step="0.5" value="${c.warmth}">
          </label>
          <label class="field">
            <span>Brilho (agudos) <b class="slider-val">${c.brightness > 0 ? "+" : ""}${(+c.brightness).toFixed(1)} dB</b></span>
            <input type="range" data-f="brightness" data-sp="${esc(sp)}" min="-12" max="12" step="0.5" value="${c.brightness}">
          </label>
          <label class="field">
            <span>
              Pausa depois
              <b class="slider-val">${(c.gap ?? showGap()).toFixed(2)}s${c.gap === null ? " (padrão)" : ""}</b>
            </span>
            <div class="row tight">
              <input type="range" data-f="gap" data-sp="${esc(sp)}" min="0" max="5" step="0.05"
                     value="${c.gap ?? showGap()}" style="flex:1">
              <button class="small ghost" data-resetgap="${esc(sp)}" title="Voltar ao padrão do show">↺</button>
            </div>
          </label>
        </div>
      </div>
    </div>`;
  }).join("");

  host.querySelectorAll("[data-toggle]").forEach((el) => {
    el.onclick = (ev) => {
      if (ev.target.dataset.preview) return;
      const sp = el.dataset.toggle;
      state.cast[sp]._open = !state.cast[sp]._open;
      renderCast();
    };
  });

  host.querySelectorAll("[data-preview]").forEach((btn) => {
    btn.onclick = (ev) => { ev.stopPropagation(); previewSpeaker(btn.dataset.preview, btn); };
  });

  host.querySelectorAll("[data-resetgap]").forEach((btn) => {
    btn.onclick = () => {
      state.cast[btn.dataset.resetgap].gap = null;
      renderCast();
      toast("Pausa voltou ao padrão do show.");
    };
  });

  host.querySelectorAll("[data-blend]").forEach((btn) => {
    btn.onclick = () => {
      const sp = btn.dataset.blend;
      const c = state.cast[sp];
      const lang = (c.voice.split("+")[0].split(":")[0] || "af_heart")[0];
      const same = state.voices.filter((v) => v.lang === lang);
      if (same.length < 2) return toast("Esse idioma não tem vozes suficientes para misturar.", true);
      const a = same[Math.floor(Math.random() * same.length)];
      let b = same[Math.floor(Math.random() * same.length)];
      while (b.id === a.id) b = same[Math.floor(Math.random() * same.length)];
      const w = (0.3 + Math.random() * 0.4).toFixed(2);
      c.voice = `${a.id}:${w}+${b.id}:${(1 - w).toFixed(2)}`;
      renderCast();
      toast(`Mistura: ${c.voice}`);
    };
  });

  // Um handler unico para todos os campos do elenco.
  host.querySelectorAll("[data-f], [data-p]").forEach((el) => {
    const ev = el.type === "range" ? "input" : "change";
    el.addEventListener(ev, () => {
      const c = state.cast[el.dataset.sp];
      const raw = el.value;
      const value = el.type === "range" ? parseFloat(raw) : raw;
      if (el.dataset.p) {
        c.params = c.params || {};
        c.params[el.dataset.p] = el.type === "range" ? value : raw;
      } else {
        c[el.dataset.f] = value === "" && el.dataset.f === "ref_audio" ? null : value;
        // Cada efeito tem a sua intensidade natural; trocar reinicia o slider.
        if (el.dataset.f === "effect") c.effect_amount = null;
        parseScript();  // pausa e tom mudam a linha do tempo
      }
      if (el.type === "range") {
        const label = el.parentElement.querySelector(".slider-val");
        if (label) {
          const f = el.dataset.f || el.dataset.p;
          const unit = { speed: "x", pitch: " st", volume: " dB", warmth: " dB", brightness: " dB", gap: "s" }[f] || "";
          const sign = value > 0 && ["pitch", "volume", "warmth", "brightness"].includes(f) ? "+" : "";
          label.textContent = `${sign}${value.toFixed(2).replace(/0$/, "")}${unit}`;
        }
      } else {
        renderCast();  // trocar motor ou voz muda o formulario
      }
    });
  });
}

async function previewSpeaker(sp, btn) {
  const c = state.cast[sp];
  const original = btn.textContent;
  btn.textContent = "⏳ ...";
  btn.disabled = true;
  try {
    const res = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: $("preview-text").value, setting: c, options: collectOptions() }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || "Falha na prévia");
    playBlob(await res.blob());
    toast(`Prévia de ${sp}`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
}

function playBlob(blob) {
  if (state.previewAudio) {
    state.previewAudio.pause();
    URL.revokeObjectURL(state.previewAudio.src);
  }
  const audio = new Audio(URL.createObjectURL(blob));
  state.previewAudio = audio;
  audio.play();
}

// ---------------------------------------------------------------- vozes

function renderVoices() {
  const lang = $("voice-lang").value;
  const gender = $("voice-gender").value;
  const list = state.voices.filter((v) => (!lang || v.lang === lang) && (!gender || v.gender === gender));

  $("voice-grid").innerHTML = list.length ? list.map((v) => `
    <div class="voice" data-voice="${v.id}">
      <div class="top">
        <span class="vname">${v.flag} ${esc(v.name)}</span>
        <span class="badge ${v.quality.startsWith("A") ? "a" : v.quality.startsWith("B") ? "b" : ""}">${esc(v.quality)}</span>
      </div>
      <div class="vmeta">${esc(v.language)} · ${esc(v.gender)}</div>
      <div class="vid">${v.id}</div>
      ${v.needs_extra ? `<div class="vmeta" style="color:var(--accent-2)">requer ${esc(v.needs_extra)}</div>` : ""}
    </div>`).join("") : '<div class="empty">Nenhuma voz com esses filtros.</div>';

  $("voice-grid").querySelectorAll("[data-voice]").forEach((el) => {
    el.onclick = async () => {
      document.querySelectorAll(".voice").forEach((v) => v.classList.remove("selected"));
      el.classList.add("selected");
      el.style.opacity = ".5";
      try {
        const res = await fetch("/api/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: $("preview-text").value,
            setting: { engine: "kokoro", voice: el.dataset.voice, speed: 1 },
          }),
        });
        if (!res.ok) throw new Error((await res.json()).detail || "Falha na prévia");
        playBlob(await res.blob());
      } catch (e) {
        toast(e.message, true);
      } finally {
        el.style.opacity = "1";
      }
    };
  });
}

$("voice-lang").onchange = renderVoices;
$("voice-gender").onchange = renderVoices;

// ---------------------------------------------------------------- render

function collectOptions() {
  const formats = [];
  if ($("fmt-wav").checked) formats.push("wav");
  if ($("fmt-mp3").checked) formats.push("mp3");
  return {
    normalize: $("opt-normalize").checked,
    trim: $("opt-trim").checked,
    limit: $("opt-limit").checked,
    target_dbfs: parseFloat($("opt-target").value),
    lead_in: parseFloat($("opt-leadin").value),
    lead_out: parseFloat($("opt-leadout").value),
    default_gap: parseFloat($("opt-gap").value),
    per_line_files: $("opt-perline").checked,
    formats: formats.length ? formats : ["wav"],
  };
}

$("btn-render").onclick = async () => {
  const script = $("script").value.trim();
  if (!script) return toast("O roteiro está vazio.", true);

  document.querySelector('[data-view="saida"]').click();
  $("btn-render").disabled = true;
  try {
    const cleanCast = {};
    for (const [k, v] of Object.entries(state.cast)) {
      const { _open, ...rest } = v;
      cleanCast[k] = rest;
    }
    state.job = await api("/api/render", {
      method: "POST",
      body: JSON.stringify({ script, cast: cleanCast, options: collectOptions(), name: $("opt-name").value }),
    });
    pollJob();
  } catch (e) {
    toast(e.message, true);
    $("btn-render").disabled = false;
  }
};

function pollJob() {
  clearInterval(state.poll);
  state.poll = setInterval(async () => {
    try {
      state.job = await api(`/api/jobs/${state.job.id}`);
      renderJob();
      if (["done", "error", "cancelled"].includes(state.job.status)) {
        clearInterval(state.poll);
        $("btn-render").disabled = false;
      }
    } catch (e) {
      clearInterval(state.poll);
      $("btn-render").disabled = false;
      toast(e.message, true);
    }
  }, 700);
  renderJob();
}

function renderJob() {
  const j = state.job;
  if (!j) return;
  const pct = Math.round(j.progress * 100);

  let html = `
    <div class="row" style="margin-bottom:6px">
      <b>${esc(j.title)}</b>
      <span class="badge ${j.status === "done" ? "a" : j.status === "error" ? "" : "b"}">${esc(j.status)}</span>
      <div class="spacer" style="flex:1"></div>
      <span class="stats"><span><b>${j.current}</b>/${j.total} falas</span><span><b>${j.elapsed}s</b></span></span>
    </div>
    <div class="progress-track"><div class="progress-bar" style="width:${pct}%"></div></div>
    <div class="hint" style="color:var(--muted)">${esc(j.message || "")}</div>`;

  if (j.status === "running" || j.status === "queued") {
    html += `<div class="row" style="margin-top:10px"><button class="small danger" onclick="cancelJob()">Cancelar</button></div>`;
  }

  if (j.status === "error") {
    html += `<div class="msg error" style="margin-top:12px">${esc(j.error)}</div>`;
  }

  if (j.manifest) {
    const m = j.manifest;
    html += `<div class="msg ok" style="margin-top:12px">
      Pronto: <b>${fmtTime(m.duration)}</b> de áudio, ${m.lines.length} falas, ${m.sample_rate} Hz.
    </div>`;

    if (m.files.wav) html += `<audio controls src="/api/jobs/${j.id}/file/${m.files.wav}"></audio>`;

    html += `<div class="row" style="margin-top:10px">`;
    for (const [fmt, _] of Object.entries(m.files)) {
      html += `<a href="/api/jobs/${j.id}/download?format=${fmt}" download><button class="primary">⬇ Baixar ${fmt.toUpperCase()}</button></a>`;
    }
    html += `<a href="/api/jobs/${j.id}/file/manifest.json" target="_blank"><button class="ghost">Ver manifesto</button></a></div>`;

    if (m.errors.length) {
      html += `<div class="msg warn" style="margin-top:12px"><b>${m.errors.length} aviso(s):</b><br>` +
        m.errors.map((e) => `Linha ${e.line_no}${e.speaker ? " (" + esc(e.speaker) + ")" : ""}: ${esc(e.error)}`).join("<br>") + `</div>`;
    }

    renderJobLines(j, m);
  }

  $("job-area").innerHTML = html;
}

function renderJobLines(job, m) {
  if (!m.lines.length || !m.lines[0].file) { $("job-lines-card").style.display = "none"; return; }
  $("job-lines-card").style.display = "";
  $("job-lines").innerHTML = m.lines.map((l, i) => `
    <div class="line-item">
      <span class="idx">${String(i + 1).padStart(2, "0")}</span>
      <div>
        <div class="who">${esc(l.speaker)} <span class="badge">${esc(l.voice)}</span></div>
        <div class="txt">${esc(l.text.slice(0, 120))}${l.text.length > 120 ? "…" : ""}</div>
      </div>
      <div class="row tight">
        <span class="idx">${l.duration}s</span>
        <button class="small" onclick="new Audio('/api/jobs/${job.id}/file/${l.file}').play()">▶</button>
        <a href="/api/jobs/${job.id}/file/${l.file}" download><button class="small ghost">⬇</button></a>
      </div>
    </div>`).join("");
}

async function cancelJob() {
  try { await api(`/api/jobs/${state.job.id}/cancel`, { method: "POST" }); toast("Cancelando..."); }
  catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- projetos

$("btn-save").onclick = async () => {
  const cleanCast = {};
  for (const [k, v] of Object.entries(state.cast)) { const { _open, ...rest } = v; cleanCast[k] = rest; }
  try {
    const saved = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        id: state.projectId, name: $("opt-name").value,
        script: $("script").value, cast: cleanCast, options: collectOptions(),
      }),
    });
    state.projectId = saved.id;
    toast(`Projeto "${saved.name}" salvo.`);
    loadProjects();
  } catch (e) { toast(e.message, true); }
};

$("btn-refresh-projects").onclick = loadProjects;

async function loadProjects() {
  try {
    const { projects } = await api("/api/projects");
    $("project-list").innerHTML = projects.length ? projects.map((p) => `
      <div class="proj-item">
        <div style="flex:1">
          <div class="pname">${esc(p.name)}</div>
          <div class="pmeta">${p.speakers.length} falantes · ${p.characters} caracteres · ${new Date(p.updated_at * 1000).toLocaleString("pt-BR")}</div>
        </div>
        <button class="small" onclick="openProject('${p.id}')">Abrir</button>
        <button class="small danger" onclick="deleteProject('${p.id}')">Excluir</button>
      </div>`).join("") : '<div class="empty">Nenhum projeto salvo ainda.</div>';
  } catch (e) { toast(e.message, true); }
}

async function openProject(id) {
  try {
    const p = await api(`/api/projects/${id}`);
    state.projectId = p.id;
    $("opt-name").value = p.name;
    $("script").value = p.script;
    state.cast = p.cast || {};
    applyOptions(p.options || {});
    await parseScript();
    document.querySelector('[data-view="roteiro"]').click();
    toast(`Projeto "${p.name}" aberto.`);
  } catch (e) { toast(e.message, true); }
}

async function deleteProject(id) {
  if (!confirm("Excluir este projeto?")) return;
  try {
    await api(`/api/projects/${id}`, { method: "DELETE" });
    if (state.projectId === id) state.projectId = null;
    loadProjects();
    toast("Projeto excluído.");
  } catch (e) { toast(e.message, true); }
}

function applyOptions(o) {
  const map = {
    normalize: "opt-normalize", trim: "opt-trim", limit: "opt-limit",
    per_line_files: "opt-perline",
  };
  for (const [k, id] of Object.entries(map)) if (o[k] !== undefined) $(id).checked = o[k];
  const ranges = { target_dbfs: "opt-target", lead_in: "opt-leadin", lead_out: "opt-leadout", default_gap: "opt-gap" };
  for (const [k, id] of Object.entries(ranges)) if (o[k] !== undefined) { $(id).value = o[k]; $(id).dispatchEvent(new Event("input")); }
  if (o.formats) { $("fmt-wav").checked = o.formats.includes("wav"); $("fmt-mp3").checked = o.formats.includes("mp3"); }
}

// ---------------------------------------------------------------- amostras

$("btn-upload-ref").onclick = async () => {
  const file = $("ref-file").files[0];
  if (!file) return toast("Escolha um arquivo primeiro.", true);
  const fd = new FormData();
  fd.append("file", file);
  try {
    await api("/api/refs", { method: "POST", body: fd });
    toast("Amostra enviada.");
    $("ref-file").value = "";
    loadRefs();
  } catch (e) { toast(e.message, true); }
};

async function loadRefs() {
  try {
    const { refs } = await api("/api/refs");
    state.refs = refs;
    $("ref-list").innerHTML = refs.length ? refs.map((r) => `
      <div class="proj-item">
        <div style="flex:1">
          <div class="pname">${esc(r.name)}</div>
          <div class="pmeta">${(r.size / 1024).toFixed(0)} KB</div>
        </div>
        <button class="small danger" onclick="deleteRef('${esc(r.name)}')">Excluir</button>
      </div>`).join("") : '<div class="empty">Nenhuma amostra enviada.</div>';
  } catch (e) { toast(e.message, true); }
}

async function deleteRef(name) {
  try { await api(`/api/refs/${encodeURIComponent(name)}`, { method: "DELETE" }); loadRefs(); toast("Amostra excluída."); }
  catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- sliders globais

[["opt-leadin", "v-leadin", "s"], ["opt-leadout", "v-leadout", "s"],
 ["opt-gap", "v-gap", "s"], ["opt-target", "v-target", " dB"]].forEach(([input, out, unit]) => {
  $(input).addEventListener("input", () => {
    $(out).textContent = (unit === " dB" ? $(input).value : (+$(input).value).toFixed(1)) + unit;
    if (input === "opt-gap") parseScript();
  });
});

// ---------------------------------------------------------------- boot

async function boot() {
  try {
    const health = await api("/api/health");
    state.ffmpeg = health.ffmpeg;
    $("mp3-note").textContent = health.ffmpeg ? "" : "requer ffmpeg";
    if (!health.ffmpeg) $("fmt-mp3").disabled = true;

    const { engines } = await api("/api/engines");
    state.engines = engines;
    const ready = engines.filter((e) => e.available);
    const status = $("engine-status");
    status.textContent = ready.length ? `${ready.map((e) => e.name).join(", ")} pronto` : "nenhum motor instalado";
    status.className = "badge " + (ready.length ? "a" : "");

    const [{ emotions }, { effects }] = await Promise.all([
      api("/api/emotions"), api("/api/effects"),
    ]);
    state.emotions = emotions;
    state.effects = effects;

    const { voices, languages } = await api("/api/voices?engine=kokoro");
    state.voices = voices;
    state.languages = languages;

    const langs = [...new Set(voices.map((v) => v.lang))];
    $("voice-lang").innerHTML = '<option value="">Todos os idiomas</option>' +
      langs.map((l) => `<option value="${l}" ${l === "a" ? "selected" : ""}>${languages[l]?.flag || ""} ${esc(languages[l]?.name || l)}</option>`).join("");

    renderVoices();
    await loadRefs();
  } catch (e) {
    toast("Falha ao carregar: " + e.message, true);
  }

  $("script").value = EXAMPLE;
  await parseScript();
}

boot();
