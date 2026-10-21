# TrustLayer: 3-minute demo video script

Story: *"The pipeline broke at 2 AM, and the CFO's dashboard was never wrong."*
Total target: **2:50** (leave 10 s of slack under the 3:00 limit).

## Before you record

- [ ] Exasol running: `exasol status` in WSL shows `database_ready`
- [ ] `python demo.py --hours 12` (prepares a clean state and opens the dashboard)
- [ ] Browser full screen at 1440x900 or larger, zoom 100%, dark or light theme (pick one)
- [ ] In the sidebar, pre-select **unit_change** under *Break it* (Gemini's best diagnosis)
- [ ] Second tab: <http://localhost:8765/badge.svg> (start `python -m trustlayer.badge` first)
- [ ] Third tab: a terminal with `exasol info` already run (shows this is Exasol Personal)
- [ ] Close notifications; hide the `.env` file and anything showing passwords or keys
- [ ] Do one dry run: Gemini sometimes takes 5-10 s, so practise talking over the spinner
- [ ] Record with OBS or the Windows Game Bar (Win+G); 1080p; microphone close to you

## Script

| Time | Screen | Say |
|---|---|---|
| 0:00-0:15 | Dashboard top: trust score **100** | "Every data team knows this moment: the CFO opens a dashboard on Monday, the numbers are wrong, and nobody knows since when. Pipelines fail quietly at 2 AM and dashboards show the damage." |
| 0:15-0:35 | Scroll to blast radius graph | "TrustLayer puts a gate in front of the dashboards. Every hourly batch lands in staging, gets checked inside Exasol Personal, and only then is published. These four dashboards, with their owners, come straight from Exasol's own dependency catalog." |
| 0:35-0:50 | Click **Run next hour** → green banner | "Here's a normal hour: five thousand trips, twelve checks, run inside Exasol in under half a second. Published." |
| 0:50-1:00 | Point at the timeline's dashed line | "The checks don't use fixed thresholds. A Python function running inside Exasol learns what each hour of the week normally looks like, and adapts as traffic grows." |
| 1:00-1:25 | Sidebar: **unit_change** → **Inject into next hour** → red banner | "Now let's break it. Upstream switches amounts from dollars to cents, a classic silent failure. The batch is quarantined. The average fare jumped from twenty-six dollars to over two thousand." |
| 1:25-1:45 | Point at trust score drop, amber dashboards | "The trust score drops, because the dashboards are now an hour behind. But they are not wrong: the CFO still sees correct numbers." |
| 1:45-2:20 | Open the incident; scroll the Gemini report | "TrustLayer then writes the incident report with Gemini. Gemini only sees aggregate evidence computed in Exasol, never raw rows, and it is not told what we broke. It still concludes: a unit conversion error, cents instead of dollars, with the dashboards affected and the SQL to investigate." |
| 2:20-2:35 | Click **Retry hour** → incident turns green, score recovers | "Once upstream is fixed, one click re-runs the hour from source. It passes, the incident closes, trust is back to a hundred." |
| 2:35-2:45 | Badge tab | "Any BI tool can embed this live trust badge, so business users see at a glance whether to believe a number." |
| 2:45-2:55 | README results section or terminal `exasol info` | "Nine and a half million real NYC taxi trips, zero false alarms over ninety-six real hours, all seven failure types caught, all on Exasol Personal on a laptop. TrustLayer: the reason to believe your dashboard." |

## If something goes wrong while recording

- Gemini is slow or busy: keep talking over the spinner; if it falls back to the template report,
  say "and if the AI is unavailable, it still writes a structured report" and move on.
- Trust score not 100 at the start: click **Reset demo** and wait about a minute, or rerun `python demo.py`.
- Want a different failure: `duplicates` and `column_dropped` also produce clear Gemini diagnoses.

## After recording

- Trim to under 3:00, add a title card "TrustLayer · ExaThon India 2026 · Track 04".
- Upload to YouTube as **Unlisted** (or public), check the link in a private window, put it in the
  README and the submission form.
