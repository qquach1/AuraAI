"""Look and motion: global CSS plus small HTML components (hero banner, deal ticker,
count-up stat cards, score rings, news cards). Data still comes from the callers; this
module only presents it."""

import html

import streamlit as st

TEAL, BLUE, VIOLET, AMBER, RED, GREEN = "#0D9488", "#2563EB", "#7C3AED", "#D97706", "#DC2626", "#059669"
TYPE_COLORS = {"M&A": BLUE, "Licensing": GREEN, "Partnership": VIOLET, "Regulatory": AMBER,
               "Litigation": RED, "Funding": "#475569"}

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,500,0,0&display=block');

.block-container { padding-top: 3.4rem !important; padding-bottom: 2.5rem !important; max-width: 1380px; }
h1 { letter-spacing: -0.02em; }
[data-testid="stSidebar"] h3 { color: #F8FAFC; letter-spacing: -0.01em; }

/* cards: white, soft shadow, fade in, lift on hover */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {
  background: #FFFFFF; box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 4px 14px rgba(15,23,42,.05);
  transition: transform .18s ease, box-shadow .18s ease; animation: gs-fade-up .45s ease both;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]):hover {
  transform: translateY(-2px); box-shadow: 0 2px 4px rgba(15,23,42,.06), 0 10px 24px rgba(15,23,42,.08);
}

/* tabs as pills */
[data-testid="stTabs"] [role="tablist"] { gap: .45rem; border-bottom: none !important; box-shadow: none !important; }
[data-testid="stTab"] { background: #FFFFFF; border: 1px solid #E2E8F0 !important; border-radius: 999px !important;
  padding: .4rem 1.05rem !important; height: auto !important; transition: background .15s ease, border-color .15s ease; }
[data-testid="stTab"]:hover { border-color: #0D9488 !important; }
[data-testid="stTab"][aria-selected="true"] { background: #0B1533; border-color: #0B1533 !important; }
[data-testid="stTab"][aria-selected="true"] * { color: #FFFFFF !important; }
[data-testid="stTab"]::after, [data-testid="stTab"]::before { display: none !important; }

.gs-icon { font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal; line-height: 1;
  letter-spacing: normal; text-transform: none; white-space: nowrap; direction: ltr; -webkit-font-smoothing: antialiased; }

@keyframes gs-fade-up { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes gs-pulse { 0% { box-shadow: 0 0 0 0 rgba(45,212,191,.7); } 70% { box-shadow: 0 0 0 9px rgba(45,212,191,0); }
  100% { box-shadow: 0 0 0 0 rgba(45,212,191,0); } }
@keyframes gs-scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@keyframes gs-shimmer { from { background-position: 0% 50%; } to { background-position: 100% 50%; } }

/* hero */
.gs-hero { position: relative; overflow: hidden; border-radius: 18px; padding: 22px 26px 0; color: #E2E8F0;
  background: linear-gradient(120deg, #0B1533 0%, #13306B 45%, #0F766E 100%); background-size: 200% 200%;
  animation: gs-shimmer 14s ease-in-out infinite alternate, gs-fade-up .5s ease both; margin-bottom: 14px; }
.gs-hero::after { content: ""; position: absolute; right: -60px; top: -80px; width: 280px; height: 280px; border-radius: 50%;
  background: radial-gradient(circle, rgba(45,212,191,.35), rgba(45,212,191,0) 70%); }
.gs-hero .eyebrow { font-size: .72rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: #5EEAD4; }
.gs-hero h1 { color: #FFFFFF; font-size: 2.1rem; margin: .2rem 0 .25rem; padding: 0; }
.gs-hero .sub { color: #CBD5E1; font-size: .98rem; max-width: 780px; }
.gs-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 16px; position: relative; z-index: 1; }
.gs-chip { background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.18); border-radius: 999px;
  padding: 4px 12px; font-size: .82rem; color: #F1F5F9; }
.gs-chip b { color: #5EEAD4; }
.gs-live { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #2DD4BF; margin-right: 6px;
  animation: gs-pulse 1.8s infinite; vertical-align: middle; }

/* ticker */
.gs-ticker { margin: 0 -26px; border-top: 1px solid rgba(255,255,255,.12); background: rgba(3,7,18,.28);
  overflow: hidden; white-space: nowrap; position: relative; z-index: 1; }
.gs-ticker-label { position: absolute; left: 0; top: 0; bottom: 0; z-index: 2; display: flex; align-items: center;
  padding: 0 14px 0 26px; font-size: .72rem; font-weight: 700; letter-spacing: .1em; color: #5EEAD4;
  background: linear-gradient(90deg, #0B1533 75%, rgba(11,21,51,0)); }
.gs-ticker-track { display: inline-flex; gap: 34px; padding: 9px 0 9px 150px; animation: gs-scroll 70s linear infinite; }
.gs-ticker:hover .gs-ticker-track { animation-play-state: paused; }
.gs-tick { font-size: .84rem; color: #E2E8F0; text-decoration: none; }
.gs-tick:hover { color: #FFFFFF; text-decoration: underline; }
.gs-tick .t { font-weight: 700; margin-right: 6px; }

/* stat cards */
.gs-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 4px 0 10px; }
.gs-stat { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px; padding: 14px 16px; position: relative;
  overflow: hidden; box-shadow: 0 4px 14px rgba(15,23,42,.05); animation: gs-fade-up .5s ease both; }
.gs-stat::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--c); }
.gs-stat .top { display: flex; align-items: center; gap: 10px; }
.gs-stat .ico { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; font-size: 20px;
  color: var(--c); background: color-mix(in srgb, var(--c) 12%, white); }
.gs-stat .lbl { font-size: .8rem; font-weight: 600; color: #475569; }
.gs-stat .val { font-size: 2.1rem; font-weight: 800; color: #0F172A; letter-spacing: -0.02em; margin-top: 6px; line-height: 1.1; }
.gs-stat .cap { font-size: .78rem; color: #64748B; margin-top: 4px; }
.gs-stat .bar { height: 5px; border-radius: 99px; background: #EEF2F7; margin-top: 10px; overflow: hidden; }
.gs-stat .bar span { display: block; height: 100%; border-radius: 99px; background: var(--c); animation: gs-grow 1.3s ease both; }
@keyframes gs-grow { from { width: 0; } }

/* odometer digits: each digit column rolls up to its value */
.gs-odo { display: inline-flex; overflow: hidden; height: 1.15em; line-height: 1.15em; vertical-align: top;
  font-variant-numeric: tabular-nums; }
.gs-odo .d { display: flex; flex-direction: column; animation: gs-roll 1.4s cubic-bezier(.2,.7,.2,1) both; }
.gs-odo .d span { height: 1.15em; }
@keyframes gs-roll { from { transform: translateY(0); } }

/* score ring: a conic gradient that pops in (SVG and @property are stripped by Streamlit) */
.gs-ring { position: relative; flex: none; border-radius: 50%; animation: gs-pop .7s cubic-bezier(.2,.8,.3,1.25) both; }
.gs-ring b { position: absolute; inset: 6px; border-radius: 50%; background: #FFFFFF; display: grid; place-items: center;
  font-weight: 800; color: #0F172A; }
@keyframes gs-pop { from { transform: scale(.55) rotate(-120deg); opacity: 0; } }

/* news card */
.gs-news { border-left: 4px solid var(--c); padding: 2px 0 2px 12px; }
.gs-news .meta { font-size: .78rem; color: #64748B; }
.gs-news .pill { display: inline-block; font-size: .72rem; font-weight: 700; color: var(--c);
  background: color-mix(in srgb, var(--c) 12%, white); border-radius: 999px; padding: 1px 9px; margin-right: 6px; }
.gs-news a.h { display: block; font-weight: 700; color: #0F172A; text-decoration: none; margin: 4px 0 2px; line-height: 1.3; }
.gs-news a.h:hover { color: #0D9488; text-decoration: underline; }
.gs-news .s { font-size: .84rem; color: #475569; }

/* opportunity card header */
.gs-opp { display: flex; gap: 12px; align-items: center; }
.gs-opp .t { font-weight: 700; color: #0F172A; line-height: 1.25; font-size: .95rem; }
.gs-opp .m { font-size: .76rem; color: #64748B; margin-top: 3px; }
.gs-section { display: flex; align-items: baseline; gap: 10px; margin: 18px 0 2px; }
.gs-section h3 { margin: 0; padding: 0; font-size: 1.15rem; }
.gs-section .note { font-size: .8rem; color: #64748B; }
"""


def inject():
    # One style-only call. Note: Streamlit drops any <style> block containing @property,
    # so animations here use plain keyframes (odometer digits, SVG stroke sweeps).
    st.html(f"<style>{CSS}</style>")


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def score_color(score: int) -> str:
    return GREEN if score >= 60 else (AMBER if score >= 40 else RED)


def odometer(value: int, delay_ms: int = 0) -> str:
    """Digits that roll up to the value when the page loads."""
    digits = []
    for k, ch in enumerate(f"{int(value):,}"):
        if not ch.isdigit():
            digits.append(f"<span>{ch}</span>")
            continue
        col = "".join(f"<span>{d}</span>" for d in range(10))
        digits.append(f"<span class='d' style='transform:translateY(-{int(ch) * 1.15:.2f}em);"
                      f"animation-delay:{delay_ms + k * 90}ms'>{col}</span>")
    return f"<span class='gs-odo'>{''.join(digits)}</span>"


def ring(score: int, size: int = 54) -> str:
    """A ring filled to the revival score."""
    s = max(0, min(100, int(score)))
    return (f"<div class='gs-ring' style='width:{size}px;height:{size}px;"
            f"background:conic-gradient({score_color(s)} {s}%, #E8EDF4 0)'>"
            f"<b style='font-size:{size * 0.3:.0f}px'>{s}</b></div>")


def hero(eyebrow: str, title: str, subtitle: str, chips: list[str], ticker: list[dict] | None = None):
    chips_html = "".join(f"<span class='gs-chip'>{c}</span>" for c in chips)
    tick = ""
    if ticker:
        items = "".join(
            f"<a class='gs-tick' href='{_e(i['url'])}' target='_blank' rel='noopener'>"
            f"<span class='t' style='color:{TYPE_COLORS.get(i['type'], TEAL)}'>{_e(i['type'])}</span>{_e(i['headline'])}</a>"
            for i in ticker)
        tick = (f"<div class='gs-ticker'><div class='gs-ticker-label'><span class='gs-live'></span>LIVE DEALS</div>"
                f"<div class='gs-ticker-track'>{items}{items}</div></div>")
    pad = "" if ticker else "<div style='height:6px'></div>"
    st.html(f"<div class='gs-hero'><div class='eyebrow'>{_e(eyebrow)}</div><h1>{_e(title)}</h1>"
            f"<div class='sub'>{_e(subtitle)}</div><div class='gs-chips'>{chips_html}</div>{tick}{pad}</div>")


def stat_cards(cards: list[dict]):
    """cards: label, value (int), caption, icon (Material Symbols name), color, share (0..1 for the bar, optional)."""
    parts = []
    for k, c in enumerate(cards):
        bar = (f"<div class='bar'><span style='width:{max(2, min(100, round(c['share'] * 100)))}%'></span></div>"
               if c.get("share") is not None else "")
        parts.append(f"<div class='gs-stat' style='--c:{c['color']};animation-delay:{k * 70}ms'>"
                     f"<div class='top'><div class='ico gs-icon'>{_e(c['icon'])}</div><div class='lbl'>{_e(c['label'])}</div></div>"
                     f"<div class='val'>{odometer(c['value'], k * 120)}</div><div class='cap'>{_e(c['caption'])}</div>{bar}</div>")
    st.html(f"<div class='gs-stats'>{''.join(parts)}</div>")


def section(title: str, note: str = ""):
    st.html(f"<div class='gs-section'><h3>{_e(title)}</h3><span class='note'>{_e(note)}</span></div>")


def news_card(i: dict, when: str, compact: bool = False):
    c = TYPE_COLORS.get(i["type"], TEAL)
    summary = "" if compact else f"<div class='s'>{_e(i['summary'])}</div>"
    who = "" if compact else (f"<div class='meta' style='margin-top:4px'>{_e(', '.join(i['companies']))}"
                              f"{' · ' if i['companies'] else ''}Source: {_e(i['source'])}</div>")
    st.html(f"<div class='gs-news' style='--c:{c}'><div class='meta'><span class='pill'>{_e(i['type'])}</span>"
            f"{_e(when)} · {_e(i['field_label'])}</div>"
            f"<a class='h' href='{_e(i['url'])}' target='_blank' rel='noopener'>{_e(i['headline'])}</a>{summary}{who}</div>")


def card_title(icon: str, title: str, color: str, note: str = ""):
    """Colored icon + title at the top of a card."""
    sub = f"<div style='font-size:.76rem;color:#64748B;margin-top:2px'>{_e(note)}</div>" if note else ""
    st.html(f"<div style='display:flex;gap:10px;align-items:center;margin-bottom:4px'>"
            f"<div class='gs-icon' style='width:32px;height:32px;border-radius:9px;display:grid;place-items:center;"
            f"font-size:19px;color:{color};background:color-mix(in srgb,{color} 12%,white)'>{_e(icon)}</div>"
            f"<div><div style='font-weight:700;color:#0F172A'>{_e(title)}</div>{sub}</div></div>")


def opp_header(score: int, title: str, meta: str):
    st.html(f"<div class='gs-opp'>{ring(score, 50)}<div><div class='t'>{_e(title)}</div>"
            f"<div class='m'>{_e(meta)}</div></div></div>")
