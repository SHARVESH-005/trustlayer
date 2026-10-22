"""TrustLayer dashboard. Run: streamlit run app/dashboard.py"""
import html
import sys
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trustlayer import baseline, chaos, lineage, pipeline, report  # noqa: E402
from trustlayer.db import connect  # noqa: E402
from trustlayer.schema import TRIPS, create_all  # noqa: E402

st.set_page_config(page_title="TrustLayer", page_icon="🛡️", layout="wide")

GREEN, AMBER, RED, BLUE, MUTED = "#2FBF71", "#F2A33A", "#F25C54", "#4C8DFF", "#8FA0BA"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
html, body, .stApp, .stMarkdown, button, input, textarea, select, label { font-family: 'Inter', sans-serif !important; }
[data-testid="stToolbar"], [data-testid="stDecoration"], footer { display: none !important; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1380px; }
section[data-testid="stSidebar"] { background: #0E1626; border-right: 1px solid #1E2A40; }
.tl-brand { display:flex; align-items:center; gap:14px; margin-bottom:6px; }
.tl-brand h1 { font-size:2.1rem; font-weight:800; letter-spacing:-0.02em; margin:0; padding:0; color:#E6EAF2; }
.tl-logo { width:42px; height:42px; border-radius:12px; background:linear-gradient(135deg,#4C8DFF,#2FBF71);
  display:flex; align-items:center; justify-content:center; font-size:22px; }
.tl-tag { color:#8FA0BA; font-size:1rem; margin:0 0 26px 0; }
.tl-tag b { color:#E6EAF2; font-weight:600; }
.tl-eyebrow { font-family:'JetBrains Mono',monospace; font-size:.72rem; letter-spacing:.14em; color:#4C8DFF;
  text-transform:uppercase; margin:34px 0 4px 0; }
.tl-h2 { font-size:1.35rem; font-weight:700; color:#E6EAF2; margin:0 0 14px 0; }
.tl-card { background:#121B2E; border:1px solid #22304A; border-radius:16px; padding:18px 20px; }
.tl-grid { display:grid; grid-template-columns: 1.55fr 1fr 1fr 1fr 1fr; gap:14px; }
.tl-hero { display:flex; align-items:center; gap:20px; }
.tl-hero .label { color:#8FA0BA; font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; }
.tl-hero .state { font-size:1.6rem; font-weight:800; margin:2px 0; }
.tl-hero .sub { color:#B4C0D3; font-size:.92rem; line-height:1.35; }
.tl-kpi .label { color:#8FA0BA; font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; }
.tl-kpi .value { font-size:2.1rem; font-weight:700; color:#E6EAF2; margin-top:6px; line-height:1.1; }
.tl-kpi .note { color:#8FA0BA; font-size:.85rem; margin-top:4px; }
.tl-banner { border-radius:14px; padding:16px 20px; margin-top:16px; border:1px solid; }
.tl-banner .title { font-weight:700; font-size:1.05rem; }
.tl-banner .meta { color:#B4C0D3; font-size:.9rem; margin-top:4px; }
.tl-banner ul { margin:10px 0 0 0; padding-left:20px; color:#E6EAF2; font-size:.95rem; }
.tl-chip { display:inline-block; font-family:'JetBrains Mono',monospace; font-size:.78rem; padding:2px 8px;
  border-radius:999px; background:#1A2540; color:#B4C0D3; margin-right:6px; }
.tl-flow { display:grid; grid-template-columns: 1fr 34px 1.15fr 34px 1fr 34px 1.75fr; align-items:center; gap:0; }
.tl-node { background:#121B2E; border:1px solid #22304A; border-radius:14px; padding:16px; }
.tl-node .name { font-family:'JetBrains Mono',monospace; font-weight:600; font-size:.95rem; color:#E6EAF2; }
.tl-node .desc { color:#8FA0BA; font-size:.85rem; margin-top:4px; line-height:1.35; }
.tl-node.exa { background:linear-gradient(160deg,#16264A,#121B2E); border-color:#33507F; }
.tl-node.cur { border-color:#2FBF71; }
.tl-arrow { text-align:center; color:#4C6A99; font-size:1.4rem; }
.tl-dash { display:flex; flex-direction:column; gap:8px; }
.tl-dcard { background:#121B2E; border:1px solid #22304A; border-radius:12px; padding:10px 14px;
  display:flex; justify-content:space-between; align-items:center; gap:10px; }
.tl-dcard .n { font-weight:600; color:#E6EAF2; font-size:.95rem; }
.tl-dcard .o { color:#8FA0BA; font-size:.78rem; font-family:'JetBrains Mono',monospace; }
.tl-pill { font-size:.75rem; font-weight:600; padding:3px 10px; border-radius:999px; white-space:nowrap; }
.tl-quar { margin-top:10px; display:grid; grid-template-columns: 1fr 34px 1.15fr 34px 1fr 34px 1.75fr; }
.tl-foot { color:#8FA0BA; font-size:.82rem; margin-top:12px; }
.tl-foot code { color:#B4C0D3; }
div[data-testid="stExpander"] { border:1px solid #22304A; border-radius:14px; background:#121B2E; }
</style>
"""


@st.cache_resource
def conn():
    return connect()


def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    stmt = conn().execute(sql, params)
    return pd.DataFrame(stmt.fetchall(), columns=stmt.column_names())


def esc(text) -> str:
    return html.escape(str(text))


def md(text: str) -> str:
    """Streamlit markdown treats $...$ as LaTeX; money amounts must stay literal."""
    return text.replace("$", r"\$")


def show(markup: str) -> None:
    # No leading spaces: indented lines would render as markdown code blocks.
    st.markdown("\n".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


def heading(eyebrow: str, title: str) -> None:
    show(f"<div class='tl-eyebrow'>{eyebrow}</div><div class='tl-h2'>{title}</div>")


def ring(score: float, color: str) -> str:
    c = 2 * 3.14159 * 46
    filled = c * max(0.0, min(score, 100.0)) / 100
    return f"""<svg width="112" height="112" viewBox="0 0 112 112" aria-label="trust score {score:.0f}">
<circle cx="56" cy="56" r="46" fill="none" stroke="#1E2A40" stroke-width="10"/>
<circle cx="56" cy="56" r="46" fill="none" stroke="{color}" stroke-width="10" stroke-linecap="round"
stroke-dasharray="{filled:.1f} {c:.1f}" transform="rotate(-90 56 56)"/>
<text x="56" y="64" text-anchor="middle" font-family="Inter, sans-serif" font-size="30" font-weight="800"
fill="#E6EAF2">{score:.0f}</text></svg>"""


show(CSS)

# ---------- sidebar: drive the pipeline ----------
with st.sidebar:
    st.markdown("### ⚙️ Pipeline")
    st.caption("Each run lands one hour of NYC taxi trips in staging, checks it inside Exasol, "
               "then publishes or quarantines it.")
    if st.button("▶  Run next hour", width="stretch", type="primary"):
        st.session_state.outcome = pipeline.run_batch(conn())
    hours = st.number_input("Hours to replay", 1, 48, 6)
    if st.button(f"⏩  Replay {hours} hours", width="stretch"):
        with st.spinner("Replaying..."):
            for _ in range(int(hours)):
                st.session_state.outcome = pipeline.run_batch(conn())

    st.divider()
    st.markdown("### 💥 Break it")
    scenario = st.selectbox("Upstream failure", sorted(chaos.SCENARIOS),
                            format_func=lambda s: chaos.SCENARIOS[s][0])
    st.caption(f"Scenario: `{scenario}`")
    if st.button("Inject into next hour", width="stretch"):
        outcome = pipeline.run_batch(conn(), scenario=scenario)
        st.session_state.outcome = outcome
        if outcome.incident_id:
            with st.spinner("Gemini is writing the incident report..."):
                report.generate(conn(), outcome.incident_id)

    st.divider()
    if st.button("↺  Reset demo (~1 min)", width="stretch"):
        with st.spinner("Rebuilding schemas, publishing history, learning baselines..."):
            create_all(conn(), reset=True, freshness_sla_minutes=120)  # pauses while presenting don't count
            pipeline.backfill(conn())
            baseline.learn(conn())
        st.session_state.pop("outcome", None)

# ---------- header ----------
show("""<div class='tl-brand'><div class='tl-logo'>🛡️</div><h1>TrustLayer</h1></div>
<p class='tl-tag'>Stops broken data before it reaches a dashboard. Every check runs inside <b>Exasol Personal</b>.</p>""")

trust = query("SELECT * FROM TRUSTLAYER.TRUST_SCORES WHERE TABLE_NAME = {t}", {"t": TRIPS})
if trust.empty:
    st.warning("No pipeline yet. Use **Reset demo** in the sidebar.")
    st.stop()
t = trust.iloc[0]
score = float(t.TRUST_SCORE)
missing = int(t.MISSING_HOURS)
open_incidents = int(t.OPEN_INCIDENTS)
last_hour = query("""SELECT MAX(BATCH_START) AS H FROM TRUSTLAYER.LOAD_LOG
                     WHERE TABLE_NAME = {t} AND STATUS = 'PROMOTED'""", {"t": TRIPS}).H[0]
held = query("SELECT NVL(SUM(ROWS_QUARANTINED), 0) AS N FROM TRUSTLAYER.INCIDENTS WHERE STATUS = 'OPEN'").N[0]

if score >= 90 and missing == 0:
    color, state = GREEN, "Trusted"
elif score >= 60:
    color, state = AMBER, "At risk"
else:
    color, state = RED, "Untrusted"
sub = ("Dashboards show complete, checked data." if missing == 0
       else f"Dashboards are correct but {missing} hour{'s' if missing != 1 else ''} behind.")
last = pd.Timestamp(last_hour) if last_hour else None

show(f"""<div class='tl-grid'>
<div class='tl-card tl-hero'>{ring(score, color)}
<div><div class='label'>Data trust</div><div class='state' style='color:{color}'>{state}</div>
<div class='sub'>{sub}</div></div></div>
<div class='tl-card tl-kpi'><div class='label'>Last published</div>
<div class='value'>{last.strftime('%H:00') if last is not None else '—'}</div>
<div class='note'>{last.strftime('%a %d %b %Y') if last is not None else 'nothing yet'}</div></div>
<div class='tl-card tl-kpi'><div class='label'>Missing hours</div>
<div class='value' style='color:{AMBER if missing else "#E6EAF2"}'>{missing}</div>
<div class='note'>blocked, not yet re-run</div></div>
<div class='tl-card tl-kpi'><div class='label'>Open incidents</div>
<div class='value' style='color:{RED if open_incidents else "#E6EAF2"}'>{open_incidents}</div>
<div class='note'>{int(held):,} rows held</div></div>
<div class='tl-card tl-kpi'><div class='label'>Batch quality</div>
<div class='value'>{float(t.QUALITY_SCORE):.0f}</div>
<div class='note'>last published batch</div></div>
</div>""")

# ---------- last action ----------
o = st.session_state.get("outcome")
if o:
    failed = [r for r in o.results if r.status == "FAIL"]
    warned = [r for r in o.results if r.status == "WARN"]
    tone, bg = (RED, "#2A1418") if failed else (GREEN, "#11261C")
    title = ("⛔ Batch quarantined: dashboards kept the last good data" if failed
             else "✅ Batch published to dashboards")
    chips = [f"{o.batch_start:%d %b %H:00}", f"{o.rows:,} rows",
             f"{len(o.results)} checks in Exasol · {o.check_seconds * 1000:.0f} ms"]
    if o.chaos:
        chips.append(f"injected: {o.chaos}")
    items = "".join(
        f"<li><b>{esc(r.check)}{' · ' + esc(r.column) if r.column else ''}</b>: {esc(r.details)}</li>"
        for r in (failed or warned))
    show(f"""<div class='tl-banner' style='border-color:{tone};background:{bg}'>
<div class='title' style='color:{tone}'>{title}</div>
<div class='meta'>{''.join(f"<span class='tl-chip'>{esc(c)}</span>" for c in chips)}</div>
{f'<ul>{items}</ul>' if items else ''}</div>""")

# ---------- pipeline and blast radius ----------
impact = lineage.affected(conn(), TRIPS)
heading("Blast radius", "How data reaches your dashboards")
depth = {v["view"]: v["depth"] for v in impact["views"]}
cards = []
for d in impact["dashboards"]:
    pill = (f"<span class='tl-pill' style='background:#3A2A12;color:{AMBER}'>Protected · {missing} h behind</span>"
            if missing else f"<span class='tl-pill' style='background:#123222;color:{GREEN}'>Up to date</span>")
    via = " via DAILY_REVENUE" if depth.get(d["view"], 1) > 1 else ""
    cards.append(f"""<div class='tl-dcard'><div><div class='n'>{esc(d['dashboard'])}</div>
<div class='o'>{esc(d['owner'])} · {esc(d['view'])}{via}</div></div>{pill}</div>""")
quar_border, quar_bg = (RED, "#2A1418") if open_incidents else ("#22304A", "#121B2E")
show(f"""<div class='tl-flow'>
<div class='tl-node'><div class='name'>STAGE</div><div class='desc'>hourly batch lands here first</div></div>
<div class='tl-arrow'>→</div>
<div class='tl-node exa'><div class='name'>12 checks · Exasol</div>
<div class='desc'>volume, distribution, completeness, schema drift, uniqueness, validity</div></div>
<div class='tl-arrow' style='color:{GREEN}'>→</div>
<div class='tl-node cur'><div class='name'>CURATED</div><div class='desc'>only checked data; marts read this</div></div>
<div class='tl-arrow'>→</div>
<div class='tl-dash'>{''.join(cards)}</div>
</div>
<div class='tl-quar'><div></div><div></div>
<div class='tl-node' style='border-color:{quar_border};background:{quar_bg}'>
<div class='name' style='color:{RED if open_incidents else "#E6EAF2"}'>↳ fail → QUARANTINE</div>
<div class='desc'>{f"{int(held):,} rows held from {open_incidents} batch{'es' if open_incidents != 1 else ''}"
                   if open_incidents else "nothing held"}</div></div></div>
<div class='tl-foot'>Lineage is read live from Exasol’s <code>EXA_DBA_DEPENDENCIES</code> catalog.
Embed the live badge in any BI tool: <code>python -m trustlayer.badge</code> →
<code>http://localhost:8765/badge.svg</code></div>""")

# ---------- incidents ----------
heading("Incidents", "What broke and why")
incidents = query("""SELECT i.INCIDENT_ID, i.TITLE, i.SEVERITY, i.STATUS, i.ROWS_QUARANTINED, i.OPENED_AT,
                            i.REPORT, i.REPORT_SOURCE, l.CHAOS
                     FROM TRUSTLAYER.INCIDENTS i JOIN TRUSTLAYER.LOAD_LOG l ON l.BATCH_ID = i.BATCH_ID
                     ORDER BY i.OPENED_AT DESC LIMIT 10""")
if incidents.empty:
    show("<div class='tl-card' style='color:#8FA0BA'>No incidents. Use <b style='color:#E6EAF2'>Break it</b> "
         "in the sidebar to inject an upstream failure.</div>")
for idx, inc in incidents.iterrows():
    icon = "🔴" if inc.STATUS == "OPEN" else "🟢"
    status = "open" if inc.STATUS == "OPEN" else "resolved"
    with st.expander(f"{icon}  {inc.TITLE}  ·  {inc.SEVERITY}  ·  {int(inc.ROWS_QUARANTINED):,} rows held  ·  {status}",
                     expanded=(idx == 0 and inc.STATUS == "OPEN")):
        a, b = st.columns([5, 1])
        with b:
            if inc.STATUS == "OPEN" and st.button("↻ Retry hour", key=f"retry-{inc.INCIDENT_ID}", type="primary",
                                                  help="Re-run this hour from source after the upstream fix"):
                st.session_state.outcome = pipeline.retry(conn(), inc.INCIDENT_ID)
                st.rerun()
            if not inc.REPORT and st.button("Explain", key=f"explain-{inc.INCIDENT_ID}"):
                with st.spinner("Asking Gemini..."):
                    report.generate(conn(), inc.INCIDENT_ID)
                st.rerun()
            if inc.CHAOS:
                st.caption(f"Ground truth, hidden from Gemini: `{inc.CHAOS}`")
        with a:
            if inc.REPORT:
                source = "✨ Gemini" if str(inc.REPORT_SOURCE).startswith("gemini") else "Template"
                st.caption(f"{source} · {inc.REPORT_SOURCE}")
                st.markdown(md(inc.REPORT))
            else:
                st.caption("No report yet.")

# ---------- batch timeline ----------
heading("Timeline", "Every batch against what normal looks like")
batches = query("""
    SELECT l.BATCH_START, l.STATUS, l.ROW_COUNT, h.HEALTH_SCORE, v.EXPECTED, l.CHAOS
    FROM TRUSTLAYER.LOAD_LOG l
    LEFT JOIN TRUSTLAYER.BATCH_HEALTH h ON h.BATCH_ID = l.BATCH_ID
    LEFT JOIN TRUSTLAYER.CHECK_RESULTS v ON v.BATCH_ID = l.BATCH_ID AND v.CHECK_NAME = 'volume'
    WHERE l.TABLE_NAME = {t} AND l.BATCH_ID NOT LIKE 'backfill-%'
    ORDER BY l.STARTED_AT DESC LIMIT 72""", {"t": TRIPS})
if not batches.empty:
    batches["BATCH_START"] = pd.to_datetime(batches.BATCH_START)
    batches["ROW_COUNT"] = batches.ROW_COUNT.astype(float)
    batches["EXPECTED"] = batches.EXPECTED.astype(float)
    batches["Status"] = batches.STATUS.map({"PROMOTED": "Published", "QUARANTINED": "Quarantined",
                                            "FAILED": "Failed"}).fillna(batches.STATUS)
    hour = alt.X("yearmonthdatehours(BATCH_START):T", title=None,  # time unit: bars fill their hour
                 axis=alt.Axis(format="%H:00", labelAngle=0, labelOverlap=True))
    bars = alt.Chart(batches).mark_bar(opacity=0.9, cornerRadiusTopLeft=3, cornerRadiusTopRight=3,
                                       width=alt.RelativeBandSize(0.8)).encode(
        x=hour,
        y=alt.Y("ROW_COUNT:Q", title="Trips per hour"),
        color=alt.Color("Status:N", title=None,
                        scale=alt.Scale(domain=["Published", "Quarantined", "Failed"], range=[GREEN, RED, MUTED]),
                        legend=alt.Legend(orient="top", direction="horizontal")),
        tooltip=[alt.Tooltip("BATCH_START:T", title="Hour", format="%d %b %H:00"), "Status",
                 alt.Tooltip("ROW_COUNT:Q", title="Rows", format=","),
                 alt.Tooltip("EXPECTED:Q", title="Expected", format=",.0f"),
                 alt.Tooltip("HEALTH_SCORE:Q", title="Health"), alt.Tooltip("CHAOS:N", title="Injected")],
    )
    expected = alt.Chart(batches).mark_line(color=BLUE, strokeDash=[5, 4], strokeWidth=2).encode(
        x=alt.X("yearmonthdatehours(BATCH_START):T", bandPosition=0.5), y="EXPECTED:Q")
    chart = (bars + expected).properties(height=280).configure(background="transparent").configure_view(
        strokeWidth=0).configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor="#1E2A40",
                                      domainColor="#22304A", tickColor="#22304A", labelFont="Inter",
                                      titleFont="Inter").configure_legend(labelColor="#B4C0D3", labelFont="Inter")
    st.altair_chart(chart, width="stretch")
    show("<div class='tl-foot'>Dashed line: expected trips from the baseline learned inside Exasol, "
         "scaled to current traffic.</div>")

# ---------- exasol facts ----------
st.write("")
with st.expander("Under the hood: Exasol"):
    facts = query(f"""SELECT (SELECT COUNT(*) FROM RAW.YELLOW_TRIPS) AS RAW_ROWS,
                             (SELECT COUNT(*) FROM {TRIPS}) AS CURATED_ROWS,
                             (SELECT COUNT(*) FROM QUARANTINE.YELLOW_TRIPS) AS QUARANTINED_ROWS,
                             (SELECT MAX(BASELINE_METHOD) FROM TRUSTLAYER.BASELINE
                              WHERE BASELINE_METHOD LIKE 'python%' OR BASELINE_METHOD LIKE 'sql_median%')
                                 AS BASELINE_METHOD""")
    st.dataframe(facts, hide_index=True, width="stretch")
    t0 = time.perf_counter()
    n = conn().execute(f"SELECT COUNT(DISTINCT PULOCATIONID || '-' || DOLOCATIONID) FROM {TRIPS}").fetchval()
    st.caption(f"Live: distinct pickup→dropoff zone pairs over all curated trips = {n:,} "
               f"in {time.perf_counter() - t0:.2f}s.")
