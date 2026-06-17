"""Self-contained, offline HTML report for an evaluation run.

Turns stored runs into a single .html file you can open in any browser — no
server, no external assets, no JS dependencies. Honesty rules from the framework
are baked into the rendering:

- every rate is shown WITH its Wilson 95% interval and its n (never a bare number);
- ranks are shown as ranges when the evidence can't separate agents (rank clusters);
- agents with n < 5 are flagged "provisional";
- domains with < 5 tasks render as "insufficient data", never as a number;
- voided (infra-failure) runs are surfaced separately, never counted as losses;
- bimodal score distributions are flagged (the mean is a fiction there).

Pure stdlib (html.escape + string building). No new dependencies.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from afa_kernel.types import RunStatus

from .report import domain_profile, leaderboard, task_aggregate
from .store import RunStore

MIN_RANKED_N = 5            # below this an agent is provisional (framework §6)
MIN_DOMAIN_TASKS = 5        # below this a domain is not displayed (framework §4)


# --------------------------------------------------------------------------- #
# small rendering helpers
# --------------------------------------------------------------------------- #

def _esc(x: object) -> str:
    return html.escape(str(x))


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _heat_color(p: float) -> str:
    """Red (0) -> amber (0.5) -> green (1.0), as a light cell background."""
    hue = 120.0 * max(0.0, min(1.0, p))      # 0=red .. 120=green
    return f"hsl({hue:.0f}, 70%, 88%)"


def _bar_svg(p_hat: float, lo: float, hi: float, *, width: int = 220, height: int = 16) -> str:
    """A horizontal bar: a light Wilson-interval band [lo,hi] with a solid marker
    at p_hat. Pure inline SVG so it renders offline."""
    def x(v: float) -> float:
        return max(0.0, min(1.0, v)) * width
    band_x, band_w = x(lo), max(1.0, x(hi) - x(lo))
    mark = x(p_hat)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" style="vertical-align:middle">'
        f'<rect x="0" y="{height/2-1:.0f}" width="{width}" height="2" fill="#e2e2e2"/>'
        f'<rect x="{band_x:.1f}" y="2" width="{band_w:.1f}" height="{height-4}" '
        f'rx="2" fill="#bcd6f5"/>'
        f'<rect x="{mark-1.5:.1f}" y="0" width="3" height="{height}" fill="#1f6feb"/>'
        f'</svg>'
    )


# --------------------------------------------------------------------------- #
# main entry point
# --------------------------------------------------------------------------- #

def render_report(
    store: RunStore,
    tasks_meta: dict[str, dict],
    *,
    title: str = "AgentForge Arena — Evaluation Report",
    subtitle: str = "",
) -> str:
    """Render a complete HTML report string.

    tasks_meta maps task_id -> {"difficulty": int, "domains": [(domain, weight), ...]}.
    Returns a full standalone HTML document.
    """
    agents = store.agents()
    task_ids = sorted(
        tasks_meta, key=lambda t: (tasks_meta[t].get("difficulty", 99), t)
    )
    task_domains = {t: tasks_meta[t].get("domains", []) for t in tasks_meta}

    board = leaderboard(store)
    # Per (agent, task) aggregate cache for the matrix + cards.
    cell: dict[tuple[str, str], object] = {}
    for a in agents:
        for t in task_ids:
            cell[(a, t)] = task_aggregate(store, a, t)

    parts: list[str] = [_HEAD.format(title=_esc(title))]
    parts.append(f'<h1>{_esc(title)}</h1>')
    if subtitle:
        parts.append(f'<p class="sub">{_esc(subtitle)}</p>')

    parts.append(_leaderboard_html(board))
    parts.append(_matrix_html(agents, task_ids, tasks_meta, cell))
    parts.append(_agents_html(store, agents))
    parts.append(_domains_html(store, agents, task_domains))
    parts.append(_FOOTER)
    parts.append("</body></html>")
    return "\n".join(parts)


def _leaderboard_html(board: Sequence) -> str:
    rows = []
    for e in board:
        if e.provisional or e.rank_low is None:
            rank = '<span class="badge prov">provisional</span>'
        elif e.rank_low == e.rank_high:
            rank = f"{e.rank_low}"
        else:
            rank = f"{e.rank_low}–{e.rank_high}"
        rows.append(
            "<tr>"
            f'<td class="rank">{rank}</td>'
            f'<td class="agent">{_esc(e.agent)}</td>'
            f'<td class="num">{e.n}</td>'
            f'<td class="num">{_pct(e.pass_rate)}</td>'
            f'<td class="num">{e.wilson_low:.3f}</td>'
            f'<td class="bar">{_bar_svg(e.pass_rate, e.wilson_low, e.wilson_high)}</td>'
            "</tr>"
        )
    return (
        '<section><h2>Leaderboard</h2>'
        '<p class="note">Ranked by the conservative lower bound (LCB) of the pass '
        'rate. The blue marker is the observed rate; the shaded band is the 95% '
        'Wilson interval — wider means less certain.</p>'
        '<table class="lb"><thead><tr>'
        '<th>Rank</th><th>Agent</th><th>n</th><th>Pass</th><th>LCB</th>'
        '<th>Rate &amp; 95% interval</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></section>'
    )


def _matrix_html(agents, task_ids, tasks_meta, cell) -> str:
    head = "".join(f"<th>{_esc(a)}</th>" for a in agents)
    rows = []
    for t in task_ids:
        diff = tasks_meta[t].get("difficulty", "")
        cells = []
        for a in agents:
            agg = cell[(a, t)]
            if agg.n_valid == 0:
                cells.append('<td class="cell na" title="no valid runs">—</td>')
                continue
            p = agg.pass_rate
            tip = f"{agg.n_pass}/{agg.n_valid} passed"
            cells.append(
                f'<td class="cell" style="background:{_heat_color(p)}" title="{_esc(tip)}">'
                f'{agg.n_pass}/{agg.n_valid}</td>'
            )
        rows.append(
            f'<tr><td class="tname">{_esc(t)}'
            f'<span class="diff" title="manual difficulty">d{_esc(diff)}</span></td>'
            + "".join(cells) + "</tr>"
        )
    return (
        '<section><h2>Per-task pass rates</h2>'
        '<p class="note">Rows are tasks (easiest at top). Cells show passes / valid '
        'runs, shaded red→green. Watch a strong agent fall off as difficulty rises.</p>'
        '<table class="mx"><thead><tr><th>Task</th>' + head + '</tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody></table></section>'
    )


def _agents_html(store: RunStore, agents) -> str:
    cards = []
    for a in agents:
        recs = store.load_runs(agent=a)
        void = sum(1 for r in recs if r.status is RunStatus.INFRA_FAILURE)
        valid = [r for r in recs if r.status is not RunStatus.INFRA_FAILURE]
        n = len(valid)
        c = sum(1 for r in valid if r.score.functional_pass)
        fails = [r for r in valid if not r.score.functional_pass]
        no_edit = sum(1 for r in fails if r.files_changed == 0)
        wrong = sum(1 for r in fails if r.files_changed > 0)
        rate = (c / n) if n else 0.0
        prov = ' <span class="badge prov">provisional</span>' if n < MIN_RANKED_N else ""
        split = []
        if wrong:
            split.append(f"{wrong} wrong-fix")
        if no_edit:
            split.append(f"{no_edit} no-edit")
        if void:
            split.append(f"{void} voided (infra)")
        split_txt = ", ".join(split) if split else "—"
        cards.append(
            '<div class="card">'
            f'<div class="cardhead">{_esc(a)}{prov}</div>'
            f'<div class="big">{_pct(rate)}</div>'
            f'<div class="cardline">{c}/{n} tasks-runs passed</div>'
            f'<div class="cardline failsplit">failures: {_esc(split_txt)}</div>'
            "</div>"
        )
    return (
        '<section><h2>Per-agent summary</h2>'
        '<p class="note">"wrong-fix" = produced code that failed the hidden tests '
        '(a genuine miss). "no-edit" = produced nothing. "voided" = the model '
        'server was unreachable — excluded from the score, never a loss.</p>'
        '<div class="cards">' + "".join(cards) + '</div></section>'
    )


def _domains_html(store: RunStore, agents, task_domains) -> str:
    # Which domains appear, and how many tasks tag each (any weight).
    domain_task_count: dict[str, int] = {}
    for tags in task_domains.values():
        for dom, _w in tags:
            domain_task_count[dom] = domain_task_count.get(dom, 0) + 1
    domains = sorted(domain_task_count)

    head = "".join(f"<th>{_esc(d)}</th>" for d in domains)
    rows = []
    for a in agents:
        profile = {ds.domain: ds for ds in domain_profile(store, a, task_domains)}
        cells = []
        for d in domains:
            ds = profile.get(d)
            if ds is None or domain_task_count[d] < MIN_DOMAIN_TASKS or not ds.displayable:
                cells.append('<td class="cell na" title="needs >= 5 tasks">insufficient data</td>')
                continue
            tip = f"Wilson [{ds.wilson_low:.2f}, {ds.wilson_high:.2f}], {ds.n_tasks} tasks"
            cells.append(
                f'<td class="cell" style="background:{_heat_color(ds.pooled_pass_rate)}" '
                f'title="{_esc(tip)}">{_pct(ds.pooled_pass_rate)}</td>'
            )
        rows.append(f'<tr><td class="agent">{_esc(a)}</td>' + "".join(cells) + "</tr>")
    return (
        '<section><h2>Domain profile</h2>'
        '<p class="note">A domain needs at least 5 tasks before a score is shown '
        '— otherwise it reads "insufficient data" rather than a misleading number.</p>'
        '<table class="mx"><thead><tr><th>Agent</th>' + head + '</tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody></table></section>'
    )


_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  margin: 0 auto; max-width: 980px; padding: 28px 22px 60px; color: #1b1f24;
  background: #fff; line-height: 1.45; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }}
h2 {{ font-size: 17px; margin: 0 0 8px; }}
.sub {{ color: #6a737d; margin: 0 0 18px; }}
section {{ margin: 26px 0; }}
.note {{ color: #6a737d; font-size: 13px; margin: 0 0 12px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{ padding: 7px 10px; text-align: left; border-bottom: 1px solid #eef0f2; }}
th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .03em; color: #6a737d; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.lb .rank {{ font-weight: 700; width: 64px; }}
.lb .agent, .agent {{ font-weight: 600; }}
.lb .bar {{ width: 230px; }}
.badge {{ font-size: 11px; padding: 1px 7px; border-radius: 10px; font-weight: 600; }}
.badge.prov {{ background: #fff3cd; color: #8a6d00; }}
.mx td.cell {{ text-align: center; font-variant-numeric: tabular-nums; border: 1px solid #fff; }}
.mx td.na {{ color: #9aa0a6; font-style: italic; background: repeating-linear-gradient(
  45deg, #f6f7f8, #f6f7f8 6px, #eff1f3 6px, #eff1f3 12px); font-size: 12px; }}
.mx .tname {{ font-weight: 600; }}
.diff {{ color: #9aa0a6; font-weight: 500; margin-left: 6px; font-size: 12px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }}
.card {{ border: 1px solid #eef0f2; border-radius: 10px; padding: 14px; }}
.cardhead {{ font-weight: 600; margin-bottom: 6px; }}
.big {{ font-size: 28px; font-weight: 700; }}
.cardline {{ color: #6a737d; font-size: 13px; }}
.failsplit {{ margin-top: 4px; }}
footer {{ margin-top: 36px; padding-top: 14px; border-top: 1px solid #eef0f2;
  color: #9aa0a6; font-size: 12px; }}
</style></head><body>"""

_FOOTER = (
    '<footer>Generated by AgentForge Arena. Offline, deterministic scoring '
    '(<code>S = G · T_hidden · (0.85 + 0.15·Q)</code>); ranked by Wilson '
    'lower bound. Numbers are shown with their uncertainty by design — a wide '
    'interval or a "provisional"/"insufficient data" label means trust it less, not more.'
    '</footer>'
)
