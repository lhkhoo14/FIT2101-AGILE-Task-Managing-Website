"""
Chart helpers for the sprint dashboard: burndown data/SVG and effort-breakdown pie SVG.

Pure Python (no pyscript imports) so it can be shared with the browser code and
unit-tested outside it. Dates are ISO strings ("YYYY-MM-DD").
"""
import math
from datetime import date, timedelta
from html import escape

COLUMN_ORDER = ["backlog", "active", "review", "completed"]
BRAND = "#4747D4"
PIE_COLORS = [
    "#4747D4", "#f59e0b", "#10b981", "#ef4444", "#06b6d4",
    "#8b5cf6", "#ec4899", "#84cc16", "#f97316", "#64748b",
]
UNASSIGNED = "Unassigned"


def parse_iso(value):
    """ISO string -> date, or None when missing/invalid."""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def format_day(day, with_year=False):
    text = f"{day.strftime('%b')} {day.day}"
    return f"{text}, {day.year}" if with_year else text


# ---------------------------------------------------------------- burndown
def burndown_series(sprint, state, today):
    """
    Day-by-day burndown for a sprint, or None for legacy sprints with no dates.

    Returns {"start", "end", "total", "completed", "days": [...]} where every day is
    {"date", "ideal", "remaining", "completed"}; remaining/completed are None for days
    that have not happened yet.
    """
    start, end = parse_iso(sprint.get("start_date")), parse_iso(sprint.get("end_date"))
    if start is None or end is None or end < start:
        return None

    state = state or {}
    tasks = [task for column in COLUMN_ORDER for task in state.get(column, []) or []]
    total = len(tasks)
    done_dates = [
        parse_iso(task.get("completed_at")) or start
        for task in (state.get("completed", []) or [])
    ]

    # The chart stops at today while the sprint runs, or at the end/ended date once over.
    if sprint.get("status") == "ended":
        ended_at = parse_iso(sprint.get("ended_at"))
        last_day = min(end, ended_at) if ended_at else end
        last_day = max(last_day, start)
    else:
        last_day = min(end, max(today, start))

    span = (end - start).days
    days = []
    for offset in range(span + 1):
        day = start + timedelta(days=offset)
        ideal = total * (span - offset) / span if span else 0
        if day <= last_day:
            completed = sum(1 for d in done_dates if d <= day)
            remaining = total - completed
        else:
            completed = remaining = None
        days.append({"date": day.isoformat(), "ideal": ideal,
                     "remaining": remaining, "completed": completed})

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total": total,
        "completed": len(done_dates),
        "days": days,
    }


def _y_ticks(maximum):
    step = max(1, math.ceil(maximum / 5))
    return list(range(0, maximum + step, step))


def burndown_svg(series):
    """Render the burndown series as a responsive inline SVG line chart."""
    width, height = 640, 340
    left, right, top, bottom = 48, 20, 20, 56
    plot_w, plot_h = width - left - right, height - top - bottom
    days = series["days"]
    n = len(days)
    ticks = _y_ticks(max(series["total"], 1))
    y_max = ticks[-1]

    def x_at(i):
        return left + (plot_w / 2 if n == 1 else plot_w * i / (n - 1))

    def y_at(value):
        return top + plot_h * (1 - value / y_max)

    parts = [
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Burndown chart" xmlns="http://www.w3.org/2000/svg">'
    ]

    for tick in ticks:  # horizontal grid + y labels
        y = y_at(tick)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#e2e8f0" stroke-width="1"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="#666">{tick}</text>')

    label_every = max(1, math.ceil(n / 8))  # x labels, always including the last day
    for i, day in enumerate(days):
        if i % label_every == 0 or i == n - 1:
            label = format_day(parse_iso(day["date"]))
            parts.append(f'<text x="{x_at(i):.1f}" y="{height - bottom + 18}" text-anchor="middle" font-size="11" fill="#666">{escape(label)}</text>')

    parts.append(f'<text x="14" y="{top + plot_h / 2:.1f}" text-anchor="middle" font-size="11" fill="#666" '
                 f'transform="rotate(-90 14 {top + plot_h / 2:.1f})">Tasks remaining</text>')

    ideal_pts = " ".join(f"{x_at(i):.1f},{y_at(d['ideal']):.1f}" for i, d in enumerate(days))
    parts.append(f'<polyline points="{ideal_pts}" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="6 5"/>')

    actual = [(i, d) for i, d in enumerate(days) if d["remaining"] is not None]
    if len(actual) > 1:
        pts = " ".join(f"{x_at(i):.1f},{y_at(d['remaining']):.1f}" for i, d in actual)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{BRAND}" stroke-width="3" stroke-linejoin="round"/>')
    for i, d in actual:
        tip = (f"{format_day(parse_iso(d['date']), True)}: {d['remaining']} remaining, "
               f"{d['completed']} of {series['total']} completed")
        parts.append(f'<circle cx="{x_at(i):.1f}" cy="{y_at(d["remaining"]):.1f}" r="4.5" fill="{BRAND}" '
                     f'stroke="#fff" stroke-width="1.5"><title>{escape(tip)}</title></circle>')

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------- effort breakdown
def effort_counts(states):
    """
    Count completed tasks per member across any number of kanban states.
    Returns [(name, count)] sorted by count (desc) then name; unassigned tasks are grouped.
    """
    counts = {}
    for state in states:
        for task in (state or {}).get("completed", []) or []:
            name = str(task.get("assignee") or "").strip() or UNASSIGNED
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))


def pie_svg(counts):
    """Render [(name, count)] as an inline SVG pie chart (empty string if no data)."""
    total = sum(count for _, count in counts)
    if total == 0:
        return ""
    size, cx, cy, radius = 320, 160, 160, 140
    parts = [f'<svg class="chart-svg pie-svg" viewBox="0 0 {size} {size}" role="img" '
             f'aria-label="Completed tasks per member" xmlns="http://www.w3.org/2000/svg">']

    def point(angle, r):
        return cx + r * math.sin(angle), cy - r * math.cos(angle)

    angle = 0.0
    for index, (name, count) in enumerate(counts):
        color = PIE_COLORS[index % len(PIE_COLORS)]
        share = count / total
        tip = escape(f"{name}: {count} task{'s' if count != 1 else ''} ({share * 100:.0f}%)")
        if len(counts) == 1:
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{color}"><title>{tip}</title></circle>')
        else:
            sweep = share * 2 * math.pi
            x1, y1 = point(angle, radius)
            x2, y2 = point(angle + sweep, radius)
            large = 1 if sweep > math.pi else 0
            parts.append(
                f'<path d="M{cx},{cy} L{x1:.2f},{y1:.2f} A{radius},{radius} 0 {large} 1 {x2:.2f},{y2:.2f} Z" '
                f'fill="{color}" stroke="#fff" stroke-width="2"><title>{tip}</title></path>'
            )
        if share >= 0.06:
            lx, ly = point(angle + share * math.pi, radius * 0.62)
            parts.append(f'<text x="{lx:.1f}" y="{ly + 5:.1f}" text-anchor="middle" font-size="14" '
                         f'font-weight="700" fill="#fff" pointer-events="none">{share * 100:.0f}%</text>')
        angle += share * 2 * math.pi
    parts.append("</svg>")
    return "".join(parts)


def pie_legend_html(counts):
    total = sum(count for _, count in counts)
    rows = []
    for index, (name, count) in enumerate(counts):
        color = PIE_COLORS[index % len(PIE_COLORS)]
        rows.append(
            f'<li class="pie-legend-row"><span class="pie-swatch" style="background:{color}"></span>'
            f'<span class="pie-legend-name">{escape(name)}</span>'
            f'<span class="pie-legend-count">{count} task{"s" if count != 1 else ""} '
            f'· {count / total * 100:.0f}%</span></li>'
        )
    return "".join(rows)
