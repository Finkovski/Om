# Om_1_0.py — Om meditation coach (Guided + Self-guided), 4 phases, auto-TTS, auto-phases, chat, PDF certificate
# Run:
# panel serve Om_1_0.py --address=0.0.0.0 --port=8704 --allow-websocket-origin='*'

import io
import os
import base64
import textwrap
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import panel as pn
from panel.template import FastListTemplate
pn.extension(notifications=True)

# ---------- .env & API ----------
from dotenv import load_dotenv
load_dotenv(override=True)
if not os.getenv("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY missing. Put it in .env or export before serving.")

from openai import OpenAI
client = OpenAI()

# ---------- Cross-version helper ----------
def call_soon(ms: int, fn):
    """Run `fn` after ~ms milliseconds, across Panel/Bokeh versions."""
    add_to = getattr(pn.state, "add_timeout_callback", None)
    if callable(add_to):
        add_to(fn, timeout=ms)
    else:
        pn.state.curdoc.add_timeout_callback(fn, ms)

# ---------- Personas / intents ----------
PERSONAS: Dict[str, Dict] = {
    "Self-guided (silent, user-led)": {
        "style": "Silent prompts only. No voice. You lead your own pace.",
        "voice": None,                    # <- important: skip TTS
        "label": "Self-guided",
        "mode": "self",
    },
    "Sage Arjun (guru, talkative, he/him)": {
        "style": "Warm, guru-like, gentle metaphors, kind encouragement, patient rhythm.",
        "voice": "verse",
        "label": "Sage Arjun",
        "mode": "guided",
    },
    "Sage Mira (guru, talkative, she/her)": {
        "style": "Nurturing, soothing cadence, ocean and moonlight imagery, soft compassion.",
        "voice": "coral",
        "label": "Sage Mira",
        "mode": "guided",
    },
    "Coach Theo (concise instructor, he/him)": {
        "style": "Concise instructor, minimal words, crisp steps, neutral tone.",
        "voice": "alloy",
        "label": "Coach Theo",
        "mode": "guided",
    },
    "Coach Ana (concise instructor, she/her)": {
        "style": "Clear pacing, pragmatic, supportive, minimal commentary.",
        "voice": "shimmer",
        "label": "Coach Ana",
        "mode": "guided",
    },
    "Zorblax (alien/gorilla guide)": {
        "style": "Playful non-human guide. Friendly, soft hums (hrrr, mmm), whimsical imagery.",
        "voice": "ash",
        "label": "Zorblax",
        "mode": "guided",
    },
}
INTENTS = ["stress relief", "sleep", "focus", "self-compassion", "resilience"]
DEFAULT_MANTRA = {
    "stress relief": "I am safe; I can soften.",
    "sleep": "Rest is here.",
    "focus": "Steady and clear.",
    "self-compassion": "May I be kind.",
    "resilience": "I can meet this.",
}
PHASES = [
    ("Opening & Intention",    "Welcome, posture, centering breath. Name intent and introduce the mantra."),
    ("Breath & Mantra",        "Guide a calm breath cadence and weave in the mantra for 1–2 minutes."),
    ("Body Scan & Kind Wish",  "Soft scan from head to toe; invite a kind wish using the mantra."),
    ("Closing & Integration",  "Gently return. Offer one simple action to carry the calm into the day."),
]
SAFETY = "Gentle reminder: pause or stop if any discomfort arises."

# ---------- State ----------
default_persona_key = list(PERSONAS.keys())[0]  # Self-guided first
state = {
    "persona": default_persona_key,
    "voice": PERSONAS[default_persona_key]["voice"],
    "mode":  PERSONAS[default_persona_key]["mode"],  # "guided" | "self"
    "intent": INTENTS[0],
    "mantra": DEFAULT_MANTRA[INTENTS[0]],
    "mantra_customized": False,     # NEW: track if user edited mantra
    "minutes": 10,
    "chat": [],                     # [{"role": "user"/"assistant", "content": "..."}]
    "start_at": None,
    "end_at": None,
    "phase_i": 0,
    "phase_marks": [],              # seconds at which to auto-advance (for phases 1..3)
}

# ---------- OpenAI helpers ----------
def llm_reply(chat: List[Dict], sys_prompt: str) -> str:
    messages = [{"role": "system", "content": sys_prompt}] + chat
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.5,
        max_tokens=400,
        messages=messages,
    )
    return resp.choices[0].message.content.strip()

def tts_mp3(text: str, voice: str) -> bytes:
    if not text.strip() or not voice:
        return b""
    audio = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=voice,
        input=text,
    )
    return audio.read()

# ---------- UI helpers ----------
def bubble(role: str, text: str, title: str = None) -> pn.Column:
    if role == "assistant":
        who = PERSONAS.get(state["persona"], {}).get("label", "Guide")
        header = f"**{who}**"
        bg = "rgba(66,133,244,.12)"
        bd = "1px solid rgba(66,133,244,.35)"
    else:
        header = "**You**"
        bg = "rgba(255,255,255,.06)"
        bd = "1px solid rgba(255,255,255,.14)"

    header_md = pn.pane.Markdown(header, styles={"opacity": "0.85", "margin": "0 0 4px 0"})
    body_md = pn.pane.Markdown(
        text if not title else f"### {title}\n\n{text}",
        styles={
            "white-space": "pre-wrap",
            "line-height": "1.55",
            "background": bg,
            "border": bd,
            "border-radius": "14px",
            "padding": "10px 12px",
            "color": "#eaeef5",
        },
        sizing_mode="stretch_width",
    )
    return pn.Column(header_md, body_md, styles={"margin": "8px 0"})

def audio_player_from_mp3(mp3_bytes: bytes) -> pn.pane.HTML:
    # Hidden audio, no controls, still autoplays
    if not mp3_bytes:
        return pn.pane.HTML("")
    b64 = base64.b64encode(mp3_bytes).decode("utf-8")
    html = (
        '<audio id="tts_audio" autoplay style="display:none">'
        f'<source src="data:audio/mpeg;base64,{b64}"></audio>'
        "<script>"
        "var a = document.getElementById('tts_audio');"
        "if (a) { let p=a.play(); if (p!==undefined) { p.catch(e=>console.log('Autoplay blocked', e)); } }"
        "</script>"
    )
    return pn.pane.HTML(html, sizing_mode="stretch_width")

def system_prompt() -> str:
    return (
        "You are a compassionate meditation teacher.\n"
        f"Persona: {state['persona']} — style: {PERSONAS[state['persona']]['style']}\n"
        f"Intent: {state['intent']}; mantra: \"{state['mantra']}\".\n"
        f"{SAFETY}\n"
        "Keep replies brief (3–7 short sentences), invitational, sensory, kind. Avoid medical advice.\n"
        "End with a gentle check-in question."
    )

def phase_prompt(i:int) -> str:
    title, goals = PHASES[i]
    return (
        f"Phase: {title}\n"
        f"Goals: {goals}\n"
        f"Use the mantra \"{state['mantra']}\" naturally.\n"
        "2–6 short sentences; warm tone; invite breath cues.\n"
    )

def _fmt(sec:int)->str:
    m,s = divmod(max(0, sec),60); return f"{m:02d}:{s:02d}"

# ---------- Self-guided text ----------
def self_guided_text(i:int) -> str:
    m = state["mantra"]
    if i == 0:
        return (
            "• Find a comfortable seat. Lengthen your spine, soften shoulders.\n"
            f"• Set intention for this session. Mantra: “{m}”.\n"
            "• Take 3 relaxed breaths—slow in, slower out.\n"
            "• When ready, continue."
        )
    if i == 1:
        return (
            f"• Breathe in for 4, out for 6. Whisper your mantra: “{m}”.\n"
            "• Let distractions drift by; kindly return to breath and mantra.\n"
            "• Continue for a minute or two, at your own pace."
        )
    if i == 2:
        return (
            "• Gentle body scan: crown → forehead → jaw → shoulders → torso → hips → legs → feet.\n"
            "• Wherever there is tension, soften slightly.\n"
            f"• Offer a kind wish to yourself with the mantra: “{m}”."
        )
    return (
        "• Deepen the breath. Notice calm and steadiness.\n"
        "• Choose one small action to carry this feeling into your day.\n"
        "• When ready, gently open the eyes. Thank yourself for practicing."
    )

# ---------- Steps 1–3 ----------
persona_select = pn.widgets.Select(name="Guide", options=list(PERSONAS.keys()),
                                   value=state["persona"], width=360)
s1_next = pn.widgets.Button(name="Continue", button_type="primary", width=160)
def _s1(_):
    key = persona_select.value
    state["persona"]=key
    state["voice"]=PERSONAS[key]["voice"]
    state["mode"]=PERSONAS[key].get("mode","guided")
    show_step(2)
s1_next.on_click(_s1)
step1 = pn.Column(pn.Row(persona_select), pn.Row(s1_next), sizing_mode="stretch_width")

intent_select = pn.widgets.Select(name="Intent", options=INTENTS, value=state["intent"], width=220)
mantra_input  = pn.widgets.TextInput(name="Mantra", value=state["mantra"], width=400)

def _intent_changed(_):
    """If user didn't customize mantra, switch to default of the new intent."""
    state["intent"] = intent_select.value
    if not state["mantra_customized"]:
        mantra_input.value = DEFAULT_MANTRA[intent_select.value]
intent_select.param.watch(_intent_changed, "value")

def _mantra_edited(event):
    """Track if user changed mantra away from the default of current intent."""
    current_default = DEFAULT_MANTRA.get(state["intent"], "")
    new = (event.new or "").strip()
    state["mantra_customized"] = (new != current_default)
    state["mantra"] = new or current_default
mantra_input.param.watch(_mantra_edited, "value")

s2_next = pn.widgets.Button(name="Continue", button_type="primary", width=160)
def _s2(_):
    # Ensure state has the latest UI selections
    state["intent"] = intent_select.value
    state["mantra"] = mantra_input.value.strip() or DEFAULT_MANTRA[intent_select.value]
    show_step(3)
s2_next.on_click(_s2)
step2 = pn.Column(pn.Row(intent_select, mantra_input), pn.Row(s2_next), sizing_mode="stretch_width")

duration_slider = pn.widgets.IntSlider(name="Session length (minutes)", start=5, end=45, step=1,
                                       value=state["minutes"], width=360)
s3_next = pn.widgets.Button(name="Continue", button_type="primary", width=160)
def _s3(_):
    state["minutes"]=int(duration_slider.value)
    show_step(4)
s3_next.on_click(_s3)
step3 = pn.Column(pn.Row(duration_slider), pn.Row(s3_next), sizing_mode="stretch_width")

# ---------- Step 4: Live session ----------
chat_box    = pn.Column(sizing_mode="stretch_width", max_height=460, scroll=True, styles={"overflow-y":"auto"})
audio_out   = pn.pane.HTML("", sizing_mode="stretch_width")   # hidden audio HTML lives here
user_input  = pn.widgets.TextInput(placeholder="Type here… (press Enter to send)", sizing_mode="stretch_width")
send_btn    = pn.widgets.Button(name="Send", button_type="primary", width=80)
timer_label = pn.pane.Markdown("00:00 / 00:00", styles={"text-align":"right","opacity":"0.75"})
start_btn   = pn.widgets.Button(name="Start session", button_type="primary", width=140)
repeat_btn  = pn.widgets.Button(name="Repeat", button_type="default", width=90)
next_btn    = pn.widgets.Button(name="Next phase →", button_type="primary", width=120)
cert_btn    = pn.widgets.FileDownload(
    label="Download certificate (PDF)",
    filename="om_certificate.pdf",
    button_type="primary",
    disabled=True,
    visible=False,
    width=220,
)

input_row   = pn.Row(user_input, send_btn, sizing_mode="stretch_width")
controls    = pn.Row(start_btn, repeat_btn, next_btn, cert_btn, sizing_mode="stretch_width")
timer_row   = pn.Row(pn.Spacer(), timer_label, sizing_mode="stretch_width")
step4       = pn.Column(chat_box, audio_out, input_row, controls, timer_row, sizing_mode="stretch_both")

current_step = {"i":1}
container = pn.Column()

def show_step(i:int):
    i = max(1, min(4, i)); current_step["i"]=i
    container.objects = [step1 if i==1 else step2 if i==2 else step3 if i==3 else step4]

# ---------- Session logic ----------
tick_cb = None

def _set_timer(running:bool):
    global tick_cb
    if running and tick_cb is None:
        tick_cb = pn.state.add_periodic_callback(_tick, period=1000)
    elif not running and tick_cb is not None:
        tick_cb.stop(); tick_cb=None

def _fmt_total():
    return int((state["end_at"] - state["start_at"]).total_seconds())

def _tick():
    if not state["start_at"] or not state["end_at"]:
        return
    now = datetime.now(timezone.utc)
    if now >= state["end_at"]:
        _set_timer(False)
        total = _fmt_total()
        timer_label.object = f"{_fmt(total)} / {_fmt(total)}"
        next_btn.disabled = True
        _on_session_finished()
        return

    elapsed = int((now - state["start_at"]).total_seconds())
    total   = _fmt_total()
    timer_label.object = f"{_fmt(elapsed)} / {_fmt(total)}"

    # Auto advance at phase marks (for phases 1..3)
    if state["phase_i"] < len(PHASES)-1:
        marks = state.get("phase_marks", [])
        if state["phase_i"] < len(marks) and elapsed >= marks[state["phase_i"]]:
            _next(auto=True)

def append_user(txt:str):
    state["chat"].append({"role":"user","content":txt})
    chat_box.append(bubble("user", txt))
    if hasattr(chat_box, "scroll_to_bottom"): chat_box.scroll_to_bottom()

def _speak_text(text: str):
    # Skip when persona has no voice (Self-guided)
    if not state.get("voice"):
        return
    try:
        mp3 = tts_mp3(text, state["voice"])
        audio_out.object = audio_player_from_mp3(mp3).object
        call_soon(50, lambda: audio_out.param.trigger("object"))
    except Exception as e:
        pn.state.notifications.error(f"TTS error: {e}")

def append_assistant(txt:str, title:str=None, speak=True):
    state["chat"].append({"role":"assistant","content":txt})
    chat_box.append(bubble("assistant", txt, title=title))
    if hasattr(chat_box, "scroll_to_bottom"): chat_box.scroll_to_bottom()
    if speak:
        _speak_text(txt)

def _send_text(text: str):
    if not text.strip():
        return
    append_user(text.strip())
    if state["mode"] == "guided":
        try:
            reply = llm_reply(state["chat"][-12:], system_prompt())
            append_assistant(reply, speak=True)
        except Exception as e:
            pn.state.notifications.error(f"LLM error: {e}")

def _send_clicked(_=None):
    txt = (user_input.value or "")
    user_input.value = ""     # clear field immediately
    _send_text(txt)

send_btn.on_click(_send_clicked)

def _send_on_enter(event):
    """
    Reliable Enter-to-send:
    When TextInput commits (Enter), Bokeh updates 'value' to the newly typed text.
    We send 'event.new' and then clear the field.
    """
    new_val = (event.new or "").strip()
    old_val = (event.old or "").strip()
    # If new text appeared (Enter), fire once
    if new_val and new_val != old_val:
        user_input.value = ""  # clear UI
        _send_text(new_val)

user_input.param.watch(_send_on_enter, "value")

def _generate_phase(i:int):
    title, _ = PHASES[i]
    if state["mode"] == "self":
        txt = self_guided_text(i)
        append_assistant(txt, title=title, speak=False)
        return
    try:
        reply = llm_reply([{"role":"user", "content": phase_prompt(i)}], system_prompt())
        append_assistant(reply, title=title, speak=True)
    except Exception as e:
        pn.state.notifications.error(f"Phase error: {e}")

def _start(_=None):
    total = int(duration_slider.value) * 60
    state["minutes"] = int(duration_slider.value)
    state["start_at"] = datetime.now(timezone.utc)
    state["end_at"]   = state["start_at"] + timedelta(seconds=total)
    timer_label.object = f"00:00 / {_fmt(total)}"
    state["phase_i"] = 0
    state["chat"].clear()
    chat_box.objects = []
    audio_out.object = ""
    next_btn.disabled = False

    # Hide/disable certificate whenever we restart
    cert_btn.visible = False
    cert_btn.disabled = True
    try:
        cert_btn.data = None
    except Exception:
        pass

    # Build auto phase schedule (equal quarters): thresholds for when to MOVE TO next phase
    q = total / 4.0
    state["phase_marks"] = [int(q*1), int(q*2), int(q*3)]  # elapsed seconds

    _set_timer(True)
    _generate_phase(0)

start_btn.on_click(_start)

def _repeat(_=None):
    if state["mode"] == "self":
        pn.state.notifications.info("Self-guided mode: no voice to repeat.")
        return
    for m in reversed(state["chat"]):
        if m["role"]=="assistant":
            _speak_text(m["content"])
            return
    pn.state.notifications.info("Nothing to repeat yet.")
repeat_btn.on_click(_repeat)

def _next(_=None, auto: bool=False):
    i = state["phase_i"]
    if i >= len(PHASES)-1:
        next_btn.disabled = True
        if not auto:
            pn.state.notifications.info("All phases complete.")
        return
    state["phase_i"] = i + 1
    _generate_phase(state["phase_i"])
    if state["phase_i"] >= len(PHASES)-1:
        next_btn.disabled = True
next_btn.on_click(_next)

# ---------- Certificate (personalized full-page) ----------
import io, textwrap
from datetime import datetime

# Try ReportLab; fall back to tiny PDF writer
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    _CERT_HAS_RL = True
except Exception:
    _CERT_HAS_RL = False

def _norm_quotes(s: str) -> str:
    repl = {"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "…": "...", "\u00a0": " "}
    return "".join(repl.get(ch, ch) for ch in s)

def _wrap_lines(text: str, width: int = 95):
    lines = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, width=width) or [""])
    return lines

def _generate_certificate_note() -> str:
    """Personal note from the selected guide, adapted to the session/chat."""
    who_label = PERSONAS.get(state.get("persona", ""), {}).get("label", "Your guide")
    style     = PERSONAS.get(state.get("persona", ""), {}).get("style", "Warm and grounded.")
    intent    = state.get("intent", "—")
    mantra    = state.get("mantra", "—")
    minutes   = state.get("minutes", 10)

    # Use the last few turns so the note can reference the session
    hist = state.get("chat", [])[-10:]
    def _fmt(m):
        role = m.get('role', '')
        content = (m.get('content', '') or '')
        content = " ".join(content.splitlines()).strip()  # remove newlines safely
        return f"{role}: {content}"

    history_txt = "\n".join(_fmt(m) for m in hist)

    try:
        sys = (
            f"You are {who_label}, a meditation guide. Style: {style}\n"
            "Write a warm, encouraging ONE-PAGE note (≈180–220 words) to the practitioner, "
            "reflecting their session sincerely and concretely. Use second person. "
            "Weave in their intent and mantra naturally. Offer 2–3 gentle suggestions for the next day. "
            "No markdown; plain text only; no medical claims."
        )
        prompt = (
            f"Session metadata:\n- Intent: {intent}\n- Mantra: {mantra}\n- Duration: {minutes} minutes\n\n"
            f"Recent conversation (latest last):\n{history_txt}\n\nWrite the full note now."
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.6,
            max_tokens=500,
            messages=[{"role":"system","content":sys},{"role":"user","content":prompt}],
        )
        note = resp.choices[0].message.content.strip()
    except Exception:
        # Friendly fallback if API hiccups
        note = (
            f"Dear friend,\n\n"
            f"Today you practiced with the intention of {intent.lower()}. Let your mantra—“{mantra}”—"
            f"stay close as the day unfolds. When attention wanders, return kindly to breath.\n\n"
            f"Over the next day, try three simple things: pause for three soft breaths between tasks; "
            f"scan the body before sleep; name one thing you appreciate as you stand up after sitting.\n\n"
            f"Thank you for showing up with courage. May your practice stay gentle and real.\n\n"
            f"With gratitude,\n{who_label}"
        )
    return _norm_quotes(note)

def _simple_pdf_bytes_fullpage(title: str, subtitle: str, body: str) -> bytes:
    """Tiny built-in PDF (no ReportLab) — single page Helvetica."""
    def esc(s): return s.replace("\\","\\\\").replace("(","\\(").replace(")","\\)")
    W, H = (595, 842)  # A4 pts
    left, top, bottom = 48, 800, 48
    lines = []
    # title
    lines += ["BT", "/F1 20 Tf", f"{left} {top} Td", f"({esc(title)}) Tj", "ET"]
    y = top - 28
    # subtitle
    lines += ["BT", "/F1 11 Tf", f"{left} {y} Td", f"({esc(subtitle)}) Tj", "ET"]
    y -= 18
    # divider is omitted in this tiny writer
    for ln in _wrap_lines(body, width=92):
        if y <= bottom + 16: break
        lines += ["BT", "/F1 12 Tf", f"{left} {y} Td", f"({esc(ln)}) Tj", "ET"]
        y -= 16
    contents = "\n".join(lines).encode("latin-1","ignore")
    stream = b"<< /Length %d >>\nstream\n" % len(contents) + contents + b"\nendstream\n"
    obj1 = b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    obj2 = b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    obj3 = b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
    obj4 = b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
    obj5 = b"5 0 obj " + stream + b"endobj\n"
    parts = [b"%PDF-1.4\n", obj1, obj2, obj3, obj4, obj5]
    offsets, buf = [], b""
    for p in parts: offsets.append(len(buf)); buf += p
    xref_pos = len(buf)
    xref = ["xref","0 6","0000000000 65535 f "] + [f"{off:010d} 00000 n " for off in offsets]
    trailer = "trailer << /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref_pos) + "\n%%EOF\n"
    return buf + ("\n".join(xref) + "\n" + trailer).encode("latin-1","ignore")

def build_certificate_pdf() -> bytes:
    """Public: called by the FileDownload button."""
    who_label = PERSONAS.get(state.get("persona",""),{}).get("label","Your guide")
    intent  = state.get("intent","—")
    mantra  = state.get("mantra","—")
    minutes = state.get("minutes",10)
    date_str = datetime.now().strftime("%B %d, %Y")

    title = "Om — Participation Certificate"
    subtitle = f"{who_label}  •  {date_str}  •  {minutes} min  •  Intent: {intent}  •  Mantra: “{mantra}”"
    body = _generate_certificate_note()

    if not _CERT_HAS_RL:
        return _simple_pdf_bytes_fullpage(title, subtitle, body)

    # Nice one-page layout with ReportLab
    bio = io.BytesIO()
    c = canvas.Canvas(bio, pagesize=A4)
    W, H = A4
    margin = 18 * mm
    left = margin; right = margin; top = H - margin; bottom = margin

    # background + title
    c.setFillColorRGB(0.08, 0.09, 0.11); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 24); c.drawString(left, top, _norm_quotes(title))
    y = top - 30

    c.setFont("Helvetica", 11); c.drawString(left, y, _norm_quotes(subtitle)); y -= 16
    c.setLineWidth(0.6); c.line(left, y, W - right, y); y -= 16

    c.setFont("Helvetica", 12)
    for ln in _wrap_lines(body, width=95):
        if y <= bottom + 16: break
        c.drawString(left, y, _norm_quotes(ln)); y -= 16

    y -= 10; c.setLineWidth(0.4); c.line(left, y, left + 55*mm, y); y -= 12
    c.setFont("Helvetica-Oblique", 11); c.drawString(left, y, _norm_quotes(who_label))

    c.showPage(); c.save()
    return bio.getvalue()


# ---------- Template (with soft mandala background) ----------
CSS = """
:root{--fg:#eaeef5;--card:rgba(17,18,21,.78)}
.bk-body, body { background:#0b0b0c !important; color:var(--fg); position:relative; }
body::before{
  content:"";
  position:fixed; inset:0; pointer-events:none; z-index:-1;
  background:
    radial-gradient(circle at 20% 25%, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.00) 35%),
    radial-gradient(circle at 80% 75%, rgba(66,133,244,0.08) 0%, rgba(66,133,244,0.00) 40%),
    radial-gradient(circle at 50% 50%, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.00) 45%);
  filter: blur(2px);
}
.card { background:var(--card); border:1px solid rgba(255,255,255,.10); border-radius:16px; padding:14px; }
"""

tmpl = FastListTemplate(title="Om", theme="dark",
                        header_background="rgba(10,10,11,0.85)", header_color="#f5f6f7")
tmpl.header.append(pn.pane.HTML(f"<style>{CSS}</style>"))
tmpl.main.append(pn.Column(container, css_classes=["card"], sizing_mode="stretch_both"))

# Boot
show_step(1)
tmpl.servable()

if __name__ == "__main__":
    pn.serve(tmpl, address="0.0.0.0", port=8913, show=True)

# =====================  Om_1.0 — PATCH (auto-chained TTS + working certificate)  =====================
# Paste this AT THE END of your existing Om_1.0.py (no other edits needed).

# ----- imports used by the patch (safe to re-import) -----
import io, base64, textwrap
try:
    import panel as pn  # already in Om_1.0
except Exception:
    pass

# --------------------------- AUTO-CHAINED TTS (never interrupt) ---------------------------
def _om10_audio_player_from_mp3(mp3_bytes: bytes):
    """
    Creates (or reuses) one hidden <audio> element in the page and enqueues mp3 clips
    so the coach never interrupts themself.
    """
    if not mp3_bytes:
        return pn.pane.HTML("")
    b64 = base64.b64encode(mp3_bytes).decode("utf-8")
    html = (
        "<div id=\"om_tts_inject\"></div>"
        "<script>(function(){"
        "try{"
        "  if(!window.omTTS){"
        "    const audio = document.createElement('audio');"
        "    audio.id = 'om_tts_audio';"
        "    audio.style.display = 'none';"
        "    audio.autoplay = false;"
        "    document.body.appendChild(audio);"
        "    const q = [];"
        "    let playing = false;"
        "    function next(){"
        "      if(q.length===0){ playing=false; return; }"
        "      const b64 = q.shift();"
        "      audio.src = 'data:audio/mpeg;base64,' + b64;"
        "      playing = true;"
        "      const p = audio.play();"
        "      if(p!==undefined){ p.catch(e=>console.log('Autoplay blocked', e)); }"
        "    }"
        "    audio.addEventListener('ended', ()=>{ playing=false; next(); });"
        "    audio.addEventListener('error',  ()=>{ playing=false; next(); });"
        "    window.omTTS = {"
        "      enqueue: function(b){ q.push(b); if(!playing){ next(); } },"
        "      stop: function(){ try{ audio.pause(); }catch(e){} playing=false; q.length=0; audio.removeAttribute('src'); },"
        "      _queue: q, _next: next, _audio: audio"
        "    };"
        "  }"
        "  window.omTTS.enqueue('%s');"
        "}catch(e){ console.log('TTS enqueue error', e); }"
        "})();</script>"
    ) % b64
    return pn.pane.HTML(html, sizing_mode="stretch_width")

def _om10_audio_stop_html():
    return pn.pane.HTML("<script>try{ if(window.omTTS){ window.omTTS.stop(); } }catch(e){}</script>")

# Monkeypatch _speak_text to enqueue instead of interrupting
try:
    _om10__orig_speak = _speak_text  # keep original for fallback
except NameError:
    _om10__orig_speak = None

def _speak_text(text: str):
    # Uses global 'state', 'tts_mp3', and 'audio_out' already present in Om_1.0
    try:
        if not text or not text.strip():
            return
        voice = None
        try:
            voice = state.get("voice")
        except Exception:
            pass
        if not voice:
            # If there's no voice configured, defer to any original (text-only) behavior if existed
            if _om10__orig_speak:
                return _om10__orig_speak(text)
            return
        mp3 = tts_mp3(text, voice)
        # ENQUEUE (never interrupts)
        audio_out.object = _om10_audio_player_from_mp3(mp3).object
        try:
            audio_out.param.trigger("object")
        except Exception:
            pass
    except Exception as e:
        try:
            pn.state.notifications.error(f"TTS error: {e}")
        except Exception:
            print("TTS error:", e)

# Also clear any pending TTS when a new session starts (wrap your _start if it exists)
try:
    _om10__orig_start = _start
    def _start(*a, **k):
        try:
            audio_out.object = _om10_audio_stop_html().object
        except Exception:
            pass
        return _om10__orig_start(*a, **k)
except NameError:
    pass

# ===== FINAL OVERRIDE: full-page personalized certificate (wins last) =====
import io, textwrap
from datetime import datetime

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    _CERT_HAS_RL = True
except Exception:
    _CERT_HAS_RL = False

def _final_norm_quotes(s: str) -> str:
    repl = {"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "…": "...", "\u00a0": " "}
    return "".join(repl.get(ch, ch) for ch in s)

def _final_wrap_lines(text: str, width: int = 95):
    lines = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(para, width=width) or [""])
    return lines

def _final_generate_note() -> str:
    who_label = PERSONAS.get(state.get("persona", ""), {}).get("label", "Your guide")
    style     = PERSONAS.get(state.get("persona", ""), {}).get("style", "Warm and grounded.")
    intent    = state.get("intent", "—")
    mantra    = state.get("mantra", "—")
    minutes   = state.get("minutes", 10)

    hist = state.get("chat", [])[-12:]
    def _fmt(m):
        role = m.get('role', '')
        content = (m.get('content', '') or '')
        content = " ".join(content.splitlines()).strip()
        return f"{role}: {content}"
    history_txt = "\n".join(_fmt(m) for m in hist)

    try:
        sys = (
            f"You are {who_label}, a meditation guide. Style: {style}\n"
            "Write a warm, encouraging ONE-PAGE note for the practitioner.\n"
            "IMPORTANT: Minimum 180 words, target 220–260 words. Plain text only.\n"
            "Reflect the actual session; use second person; weave in intent and mantra; "
            "offer 2–3 gentle suggestions for the next day; avoid medical claims."
        )
        prompt = (
            f"Session metadata:\n- Intent: {intent}\n- Mantra: {mantra}\n- Duration: {minutes} minutes\n\n"
            f"Recent conversation (latest last):\n{history_txt}\n\n"
            "Write the full note now."
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.7,
            max_tokens=650,   # allow a longer page
            messages=[{"role":"system","content":sys},{"role":"user","content":prompt}],
        )
        note = resp.choices[0].message.content.strip()
    except Exception:
        note = (
            f"Dear friend,\n\n"
            f"Today you practiced with the intention of {intent.lower()}. Let your mantra—“{mantra}”—"
            f"stay close as the day unfolds. When attention wanders, return kindly to breath. "
            f"Notice small places to soften the jaw and shoulders, and let the exhale be a touch longer.\n\n"
            f"Over the next day, try three simple things: pause for three soft breaths between tasks; "
            f"before sleep, scan the body from crown to feet; and after sitting, name one thing you appreciate. "
            f"Let these be gentle, low-effort invitations, not rules.\n\n"
            f"Thank you for showing up with courage. May your practice stay steady and kind.\n\n"
            f"With gratitude,\n{who_label}"
        )
    return _final_norm_quotes(note)

def _final_simple_pdf(title: str, subtitle: str, body: str) -> bytes:
    def esc(s): return s.replace("\\","\\\\").replace("(","\\(").replace(")","\\)")
    W, H = (595, 842)
    left, top, bottom = 48, 800, 48
    lines = []
    lines += ["BT", "/F1 20 Tf", f"{left} {top} Td", f"({esc(title)}) Tj", "ET"]
    y = top - 28
    lines += ["BT", "/F1 11 Tf", f"{left} {y} Td", f"({esc(subtitle)}) Tj", "ET"]
    y -= 18
    for ln in _final_wrap_lines(body, width=92):
        if y <= bottom + 16: break
        lines += ["BT", "/F1 12 Tf", f"{left} {y} Td", f"({esc(ln)}) Tj", "ET"]
        y -= 16
    contents = "\n".join(lines).encode("latin-1","ignore")
    stream = b"<< /Length %d >>\nstream\n" % len(contents) + contents + b"\nendstream\n"
    obj1 = b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    obj2 = b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    obj3 = b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
    obj4 = b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
    obj5 = b"5 0 obj " + stream + b"endobj\n"
    parts = [b"%PDF-1.4\n", obj1, obj2, obj3, obj4, obj5]
    offsets, buf = [], b""
    for p in parts: offsets.append(len(buf)); buf += p
    xref_pos = len(buf)
    xref = ["xref","0 6","0000000000 65535 f "] + [f"{off:010d} 00000 n " for off in offsets]
    trailer = "trailer << /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref_pos) + "\n%%EOF\n"
    return buf + ("\n".join(xref) + "\n" + trailer).encode("latin-1","ignore")

def _fullpage_build_certificate_pdf() -> bytes:
    who_label = PERSONAS.get(state.get("persona",""),{}).get("label","Your guide")
    intent  = state.get("intent","—")
    mantra  = state.get("mantra","—")
    minutes = state.get("minutes",10)
    date_str = datetime.now().strftime("%B %d, %Y")

    title = "Om — Participation Certificate"
    subtitle = f"{who_label}  •  {date_str}  •  {minutes} min  •  Intent: {intent}  •  Mantra: “{mantra}”"
    body = _final_generate_note()

    if not _CERT_HAS_RL:
        return _final_simple_pdf(title, subtitle, body)

    bio = io.BytesIO()
    c = canvas.Canvas(bio, pagesize=A4)
    W, H = A4
    margin = 18 * mm
    left = margin; right = margin; top = H - margin; bottom = margin

    c.setFillColorRGB(0.08, 0.09, 0.11); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 24); c.drawString(left, top, _final_norm_quotes(title))
    y = top - 30

    c.setFont("Helvetica", 11); c.drawString(left, y, _final_norm_quotes(subtitle)); y -= 16
    c.setLineWidth(0.6); c.line(left, y, W - right, y); y -= 16

    c.setFont("Helvetica", 12)
    for ln in _final_wrap_lines(body, width=95):
        if y <= bottom + 16: break
        c.drawString(left, y, _final_norm_quotes(ln)); y -= 16

    y -= 10; c.setLineWidth(0.4); c.line(left, y, left + 55*mm, y); y -= 12
    c.setFont("Helvetica-Oblique", 11); c.drawString(left, y, _final_norm_quotes(who_label))

    c.showPage(); c.save()
    return bio.getvalue()

# Make this the version your app uses (overrides earlier/shorter one)
build_certificate_pdf = _fullpage_build_certificate_pdf
# ============================================================================

# ===== CERT BUTTON: wire + show at session finish (drop-in, paste at end) =====
import io

def _cert_file():
    pdf = build_certificate_pdf()
    bio = io.BytesIO(pdf); bio.seek(0)
    try: bio.name = "om_certificate.pdf"
    except Exception: pass
    return bio

def _cert_show_button():
    # Support both old/new Panel: set callback and also prefill .file
    try: cert_btn.callback = _cert_file
    except Exception: pass
    try: cert_btn.file = _cert_file()
    except Exception: pass
    try: cert_btn.filename = "om_certificate.pdf"
    except Exception: pass
    try: cert_btn.embed = False
    except Exception: pass
    cert_btn.visible = True
    cert_btn.disabled = False
    try: cert_btn.param.trigger("file")
    except Exception: pass

# Preserve any previous finish handler if it exists (it likely doesn't now)
try:
    _prev_finish = _on_session_finished
except NameError:
    _prev_finish = None

def _on_session_finished(*args, **kwargs):
    if _prev_finish:
        try: _prev_finish(*args, **kwargs)
        except Exception: pass
    pn.state.notifications.info("Session completed. You can download your certificate.")
    _cert_show_button()
# ============================================================================== 

# ==================== Om_1_0.py — Agent-backed report/certificate (drop-in) ====================
# Paste this block AT THE VERY END of Om_1_0.py. No other edits needed.

import os, json
try:
    import requests
except Exception:
    requests = None  # we'll fall back if requests is missing

# Point to your agent (override via env if deployed elsewhere)
OM_REPORT_AGENT_URL = os.getenv("OM_REPORT_AGENT_URL", "http://localhost:8088/report")

def _agent_build_certificate_pdf() -> bytes:
    """
    Calls the external report agent to get a PDF.
    Raises on error so we can fall back cleanly.
    """
    if requests is None:
        raise RuntimeError("`requests` is not installed")

    who_map = PERSONAS.get(state.get("persona",""), {})
    payload = {
        "persona_label": who_map.get("label", "Your guide"),
        "persona_style": who_map.get("style", "Warm and grounded."),
        "intent": state.get("intent", "—"),
        "mantra": state.get("mantra", "—"),
        "minutes": int(state.get("minutes", 10) or 10),
        "chat": [
            {"role": str(m.get("role","")), "content": str(m.get("content",""))}
            for m in state.get("chat", [])
        ],
        "format": "pdf",
    }

    r = requests.post(OM_REPORT_AGENT_URL, json=payload, timeout=45)
    ct = (r.headers.get("content-type") or "").lower()
    if r.status_code == 200 and "application/pdf" in ct:
        return r.content
    raise RuntimeError(f"Agent responded {r.status_code}: {r.text[:200]}")

# Keep a reference to your existing local builder for fallback
try:
    _LOCAL_PDF_BUILDER = build_certificate_pdf
except NameError:
    try:
        _LOCAL_PDF_BUILDER = _fullpage_build_certificate_pdf
    except NameError:
        # Minimal tiny-PDF fallback if neither exists
        def _LOCAL_PDF_BUILDER():
            body = "Om — Participation Certificate\n\nThe external report agent was unavailable.\n"
            # tiny one-page PDF
            def esc(s): return s.replace("\\","\\\\").replace("(","\\(").replace(")","\\)")
            W,H = (595,842); L, T, B = 48, 800, 48
            parts=[]; y=T
            parts += ["BT","/F1 20 Tf",f"{L} {y} Td","(Om — Participation Certificate) Tj","ET"]; y-=28
            for ln in body.splitlines():
                parts += ["BT","/F1 12 Tf",f"{L} {y} Td",f"({esc(ln)}) Tj","ET"]; y-=16
            b = "\n".join(parts).encode("latin-1","ignore")
            stream = b"<< /Length %d >>\nstream\n" % len(b) + b + b"\nendstream\n"
            o1=b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
            o2=b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            o3=b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
            o4=b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
            o5=b"5 0 obj "+stream+b"endobj\n"
            parts=[b"%PDF-1.4\n",o1,o2,o3,o4,o5]; offs=[]; buf=b""
            for p in parts: offs.append(len(buf)); buf+=p
            xref=len(buf)
            x=["xref","0 6","0000000000 65535 f "]+[f"{o:010d} 00000 n " for o in offs]
            trailer=f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
            return buf+("\n".join(x)+"\n"+trailer).encode("latin-1","ignore")

# FINAL OVERRIDE: always try the agent first; on any error, use local builder
def build_certificate_pdf() -> bytes:  # <- your FileDownload already calls this
    try:
        return _agent_build_certificate_pdf()
    except Exception as e:
        try:
            pn.state.notifications.warn(f"Report agent unavailable, using local certificate. ({e})")
        except Exception:
            pass
        return _LOCAL_PDF_BUILDER()
# ==================== /Agent-backed report/certificate ====================
