"""TrustLayer dashboard. Run: streamlit run app/dashboard.py"""
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


@st.cache_resource
def conn():
    return connect()


def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    stmt = conn().execute(sql, params)
    return pd.DataFrame(stmt.fetchall(), columns=stmt.column_names())


def score_color(score: float) -> str:
    return "#1a7f37" if score >= 90 else "#bf8700" if score >= 60 else "#cf222e"


def md(text: str) -> str:
    """Streamlit markdown treats $...$ as LaTeX; money amounts must stay literal."""
    return text.replace("$", r"\$")


# ---------- sidebar: drive the pipeline ----------
with st.sidebar:
    st.header("Pipeline controls")
    st.caption("Each run lands one hour of NYC taxi trips in staging, checks it inside Exasol, "
               "then publishes or quarantines it.")
    if st.button("Run next hour", width="stretch", type="primary"):
        st.session_state.outcome = pipeline.run_batch(conn())
    hours = st.number_input("Hours to replay", 1, 48, 6)
    if st.button(f"Replay {hours} hours", width="stretch"):
        with st.spinner("Replaying..."):
            for _ in range(int(hours)):
                st.session_state.outcome = pipeline.run_batch(conn())

    st.divider()
    st.subheader("Break it")
    scenario = st.selectbox("Upstream failure", sorted(chaos.SCENARIOS),
                            format_func=lambda s: f"{s}: {chaos.SCENARIOS[s][0]}")
    if st.button("Inject into next hour", width="stretch"):
        outcome = pipeline.run_batch(conn(), scenario=scenario)
        st.session_state.outcome = outcome
        if outcome.incident_id:
            with st.spinner("Writing incident report..."):
                report.generate(conn(), outcome.incident_id)

    st.divider()
    if st.button("Reset demo (~1 min)", width="stretch"):
        with st.spinner("Rebuilding schemas, publishing history, learning baselines..."):
            create_all(conn(), reset=True)
            pipeline.backfill(conn())
            baseline.learn(conn())
        st.session_state.pop("outcome", None)

# ---------- header: trust score ----------
st.title("🛡️ TrustLayer")
st.caption("Stops broken data before it reaches a dashboard. Every check runs inside **Exasol Personal**.")

trust = query("SELECT * FROM TRUSTLAYER.TRUST_SCORES WHERE TABLE_NAME = {t}", {"t": TRIPS})
if trust.empty:
    st.warning("No pipeline yet. Use **Reset demo** in the sidebar.")
    st.stop()
t = trust.iloc[0]
score = float(t.TRUST_SCORE)
last_hour = query("""SELECT MAX(BATCH_START) AS H FROM TRUSTLAYER.LOAD_LOG
                     WHERE TABLE_NAME = {t} AND STATUS = 'PROMOTED'""", {"t": TRIPS}).H[0]

c1, c2, c3, c4, c5 = st.columns(5)
c1.markdown(f"<div style='font-size:0.9rem;opacity:.75'>Trust score</div>"
            f"<div style='font-size:3rem;font-weight:700;color:{score_color(score)};line-height:1'>"
            f"{score:.0f}</div>", unsafe_allow_html=True)
c2.metric("Last published hour", pd.Timestamp(last_hour).strftime("%d %b %H:00") if last_hour else "none")
c3.metric("Missing hours", int(t.MISSING_HOURS), help="Blocked hours not yet re-run successfully")
c4.metric("Open incidents", int(t.OPEN_INCIDENTS))
c5.metric("Batch quality", f"{float(t.QUALITY_SCORE):.0f}")

# ---------- last action ----------
o = st.session_state.get("outcome")
if o:
    failed = [r for r in o.results if r.status == "FAIL"]
    warned = [r for r in o.results if r.status == "WARN"]
    head = (f"**{o.batch_start:%Y-%m-%d %H:00}** · {o.rows:,} rows · "
            f"{len(o.results)} checks in Exasol in **{o.check_seconds:.2f}s**")
    if o.chaos:
        head += f" · injected: `{o.chaos}`"
    if failed:
        st.error(f"⛔ Batch QUARANTINED: dashboards kept the last good data. {head}")
        for r in failed:
            st.markdown(md(f"- **{r.check}**{' (' + r.column + ')' if r.column else ''}: {r.details}"))
    else:
        st.success(f"✅ Batch PUBLISHED. {head}")
        for r in warned:
            st.markdown(md(f"- ⚠️ {r.check}{' (' + r.column + ')' if r.column else ''}: {r.details}"))

st.divider()

# ---------- blast radius ----------
left, right = st.columns([3, 2])
impact = lineage.affected(conn(), TRIPS)
at_risk = int(t.MISSING_HOURS) > 0
with left:
    st.subheader("Blast radius")
    st.caption("From Exasol's dependency catalog (EXA_DBA_DEPENDENCIES) plus the dashboard registry.")
    edge = "#cf222e" if at_risk else "#8c959f"
    lines = ["digraph G { rankdir=LR; bgcolor=transparent; nodesep=0.25; ranksep=0.45;",
             "node [shape=box, style=\"rounded,filled\", fontname=Helvetica, fontsize=16, "
             "fillcolor=\"#f6f8fa\", color=\"#8c959f\", fontcolor=\"#1f2328\"];",
             "edge [color=\"#8c959f\", fontcolor=\"#8c959f\", fontname=Helvetica, fontsize=13];",
             f'"QUARANTINE" [label="QUARANTINE\\nblocked batches", fillcolor="{"#ffebe9" if at_risk else "#f6f8fa"}"];',
             f'"{TRIPS}" [fillcolor="#ddf4ff"];',
             f'"STAGE" -> "{TRIPS}" [label="pass"]; "STAGE" -> "QUARANTINE" [label="fail", color="{edge}"];']
    edges = lineage.dependency_edges(conn())
    names = {TRIPS} | {v["view"] for v in impact["views"]}
    for parent in names:
        for child in edges.get(parent, []):
            lines.append(f'"{parent}" -> "{child}";')
    for d in impact["dashboards"]:
        label = f"{d['dashboard']}\\n{d['owner']}"
        fill = "#fff8c5" if at_risk else "#dafbe1"
        lines.append(f'"{label}" [shape=note, fillcolor="{fill}"]; "{d["view"]}" -> "{label}";')
    lines.append("}")
    st.graphviz_chart("\n".join(lines), width="stretch")
with right:
    st.subheader("Protected dashboards")
    status = f"Correct, missing {int(t.MISSING_HOURS)} h" if at_risk else "Up to date"
    st.dataframe(pd.DataFrame([{"Dashboard": d["dashboard"], "Owner": d["owner"], "Reads": d["view"],
                                "Status": status} for d in impact["dashboards"]]),
                 hide_index=True, width="stretch")
    st.caption("Badge for any BI tool: `python -m trustlayer.badge` → http://localhost:8765/badge.svg")

# ---------- incidents ----------
st.divider()
st.subheader("Incidents")
incidents = query("""SELECT i.INCIDENT_ID, i.TITLE, i.SEVERITY, i.STATUS, i.ROWS_QUARANTINED, i.OPENED_AT,
                            i.REPORT, i.REPORT_SOURCE, l.CHAOS
                     FROM TRUSTLAYER.INCIDENTS i JOIN TRUSTLAYER.LOAD_LOG l ON l.BATCH_ID = i.BATCH_ID
                     ORDER BY i.OPENED_AT DESC LIMIT 10""")
if incidents.empty:
    st.info("No incidents. Try **Break it** in the sidebar.")
for idx, inc in incidents.iterrows():
    icon = "🔴" if inc.STATUS == "OPEN" else "🟢"
    with st.expander(f"{icon} {inc.TITLE} · {inc.SEVERITY} · {int(inc.ROWS_QUARANTINED):,} rows held",
                     expanded=(idx == 0 and inc.STATUS == "OPEN")):
        a, b = st.columns([4, 1])
        with b:
            if inc.STATUS == "OPEN" and st.button("Retry hour", key=f"retry-{inc.INCIDENT_ID}",
                                                  help="Re-run this hour from source after the upstream fix"):
                st.session_state.outcome = pipeline.retry(conn(), inc.INCIDENT_ID)
                st.rerun()
            if not inc.REPORT and st.button("Explain", key=f"explain-{inc.INCIDENT_ID}"):
                with st.spinner("Asking Gemini..."):
                    report.generate(conn(), inc.INCIDENT_ID)
                st.rerun()
            if inc.CHAOS:
                st.caption(f"Ground truth (not shown to Gemini): `{inc.CHAOS}`")
        with a:
            if inc.REPORT:
                st.caption(f"Report source: {inc.REPORT_SOURCE}")
                st.markdown(md(inc.REPORT))
            else:
                st.caption("No report yet.")

# ---------- batch timeline ----------
st.divider()
st.subheader("Batch timeline")
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
    bars = alt.Chart(batches).mark_bar(opacity=0.85).encode(
        x=alt.X("BATCH_START:T", title="Batch hour (simulated)"),
        y=alt.Y("ROW_COUNT:Q", title="Rows"),
        color=alt.Color("STATUS:N", scale=alt.Scale(domain=["PROMOTED", "QUARANTINED", "FAILED"],
                                                    range=["#2da44e", "#cf222e", "#8c959f"])),
        tooltip=["BATCH_START:T", "STATUS", "ROW_COUNT", "EXPECTED", "HEALTH_SCORE", "CHAOS"],
    )
    expected = alt.Chart(batches).mark_line(color="#0969da", strokeDash=[4, 3]).encode(
        x="BATCH_START:T", y=alt.Y("EXPECTED:Q"))
    st.altair_chart((bars + expected).properties(height=260), width="stretch")
    st.caption("Dashed line: expected rows from the learned baseline, scaled to current traffic.")

# ---------- exasol facts ----------
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
