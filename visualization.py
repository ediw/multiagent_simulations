"""Visualization module for the multi-agent mail-processing simulator.

Produces interactive HTML charts (plotly) and static PNG exports (kaleido).
All outputs are written to an ``output/`` directory.

Usage::

    from main import SimulationConfig, run_single_experiment, run_monte_carlo
    from visualization import SimulationVisualizer

    summary, sim = run_single_experiment(SimulationConfig(), return_sim=True)
    viz = SimulationVisualizer(sim)
    viz.plot_all()              # generates every chart

    mc, sims = run_monte_carlo(5, return_sims=True)
    viz.plot_monte_carlo_comparison(sims)
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import networkx as nx
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from models import AgentType, CaseStatus, TimeseriesSnapshot
from simulator import MultiAgentMailSimulator
from export import export_all

_BASE_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# Active output directory — set by SimulationVisualizer or CLI.
_OUTPUT_DIR: str = os.path.join(_BASE_OUTPUT, "default")


def _ensure_output_dir() -> None:
    os.makedirs(_OUTPUT_DIR, exist_ok=True)


# Ordered chart names + display labels used for the navigation menu.
CHART_REGISTRY: List[Tuple[str, str]] = [
    ("01_network_topology", "Network topology"),
    ("02_input_parameters", "Input parameters"),
    ("03_queue_evolution", "Queue evolution"),
    ("04_case_status", "Case status"),
    ("05_fatigue_heatmap", "Fatigue heatmap"),
    ("06_trust_evolution", "Trust evolution"),
    ("07_routing_sankey", "Routing Sankey"),
    ("08_metrics_dashboard", "Metrics dashboard"),
    ("09_monte_carlo", "Monte Carlo"),
    ("10_effective_thermodynamics", "Thermodynamics"),
    ("10w_warm_thermodynamics", "Warm thermo"),
    ("11_operational_health", "Operational health"),
    ("12_warm_start_trend", "Warm-start trend"),
]


# Module-level agent roster HTML — set once by SimulationVisualizer.
_AGENT_PANEL_HTML: str = ""


def _build_agent_panel(sim: "MultiAgentMailSimulator") -> str:
    """Build a collapsible HTML panel with the full agent roster."""
    header_style = (
        "background:#3366CC;color:#fff;padding:4px 8px;font-weight:600;"
        "font-size:12px;position:sticky;top:0;z-index:1"
    )
    cell_style = "padding:3px 7px;font-size:11px;border-bottom:1px solid #eee;white-space:nowrap"
    cols = [
        "ID", "Type", "Accuracy", "Confidence", "Avg svc time",
        "Queue cap", "Cost/action", "Split prop.", "Esc. thr.",
        "Rework thr.", "Fatigue +", "Recovery",
    ]
    # Build skills sub-columns dynamically
    all_skills: set = set()
    for a in sim.agents.values():
        all_skills.update(a.skills.keys())
    skill_cols = sorted(all_skills)
    cols += [f"Skill: {s}" for s in skill_cols]

    header_cells = "".join(f'<th style="{header_style}">{c}</th>' for c in cols)
    rows_html = ""
    for aid in sorted(sim.agents.keys()):
        a = sim.agents[aid]
        atype = a.agent_type.value
        color = AGENT_TYPE_COLORS.get(atype, "#888")
        type_badge = (
            f'<span style="background:{color};color:#fff;padding:1px 6px;'
            f'border-radius:3px;font-size:10px">{atype}</span>'
        )
        vals = [
            aid, type_badge,
            f"{a.base_accuracy:.2f}", f"{a.base_confidence:.2f}",
            f"{a.avg_service_time:.1f}", str(a.queue_capacity),
            f"{a.cost_per_action:.2f}", f"{a.split_propensity:.2f}",
            f"{a.escalation_threshold:.2f}", f"{a.rework_threshold:.2f}",
            f"{a.fatigue_increase:.3f}", f"{a.fatigue_recovery:.3f}",
        ]
        vals += [f"{a.skills.get(s, 0.0):.2f}" for s in skill_cols]
        cells = "".join(f'<td style="{cell_style}">{v}</td>' for v in vals)
        rows_html += f'<tr data-agent-type="{atype}">{cells}</tr>'

    # Collect unique agent types for filter buttons
    agent_types_sorted = sorted({a.agent_type.value for a in sim.agents.values()})
    filter_buttons = ""
    btn_base = (
        "padding:4px 10px;border:1px solid #ccc;border-radius:4px;"
        "cursor:pointer;font-size:11px;font-family:sans-serif;"
        "transition:all .15s"
    )
    filter_buttons += (
        f'<button class="agent-filter-btn agent-filter-active" '
        f'data-filter="all" style="{btn_base};background:#636EFA;color:#fff;'
        f'border-color:#636EFA">All</button> '
    )
    for atype in agent_types_sorted:
        color = AGENT_TYPE_COLORS.get(atype, "#888")
        filter_buttons += (
            f'<button class="agent-filter-btn" data-filter="{atype}" '
            f'style="{btn_base};background:#fff;color:{color};border-color:{color}">'
            f'{atype}</button> '
        )

    filter_bar = (
        '<div style="padding:6px 0;display:flex;gap:5px;flex-wrap:wrap;'
        'align-items:center">'
        '<span style="font-size:12px;font-weight:600;margin-right:4px">'
        'Filter:</span>'
        f'{filter_buttons}'
        '</div>'
    )

    filter_script = (
        '<script>'
        '(function(){'
        'var btns=document.querySelectorAll(".agent-filter-btn");'
        'var rows=document.querySelectorAll("tr[data-agent-type]");'
        'btns.forEach(function(b){'
        'b.addEventListener("click",function(){'
        'var f=b.getAttribute("data-filter");'
        'btns.forEach(function(x){'
        'x.classList.remove("agent-filter-active");'
        'x.style.fontWeight="normal";'
        '});'
        'b.classList.add("agent-filter-active");'
        'b.style.fontWeight="700";'
        'rows.forEach(function(r){'
        'if(f==="all"||r.getAttribute("data-agent-type")===f)'
        '{r.style.display="";}else{r.style.display="none";}'
        '});'
        '});'
        '});'
        '})();'
        '</script>'
    )

    table = (
        '<table style="border-collapse:collapse;width:100%;font-family:monospace">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
    )
    return (
        '<details style="font-family:sans-serif;font-size:13px;margin:0;'
        'border-bottom:1px solid #ddd;background:#fdfdfe">'
        '<summary style="padding:6px 16px;cursor:pointer;user-select:none;'
        'color:#636EFA;font-weight:600">'
        f'\U0001F465 Agent roster ({len(sim.agents)} agents)</summary>'
        f'<div style="padding:4px 8px">{filter_bar}'
        f'<div style="max-height:340px;overflow:auto">{table}</div></div>'
        f"{filter_script}"
        "</details>"
    )


def _nav_html(current_name: str) -> str:
    """Build an HTML navigation bar highlighting the current chart."""
    items: List[str] = []
    for fname, label in CHART_REGISTRY:
        if fname == current_name:
            items.append(
                f'<span style="padding:6px 14px;background:#636EFA;color:#fff;'
                f'border-radius:4px;font-weight:600">{label}</span>'
            )
        else:
            items.append(
                f'<a href="{fname}.html" style="padding:6px 14px;color:#636EFA;'
                f'text-decoration:none;border:1px solid #ddd;border-radius:4px">{label}</a>'
            )
    bar = " ".join(items)
    return (
        '<div style="position:sticky;top:0;z-index:9999;background:#f8f9fa;'
        'padding:10px 16px;display:flex;flex-wrap:wrap;gap:6px;'
        'align-items:center;border-bottom:1px solid #ddd;font-family:sans-serif;font-size:13px">'
        '<strong style="margin-right:10px">Charts:</strong>'
        f'{bar}</div>'
    )


def _save(fig: go.Figure, name: str, width: int = 1400, height: int = 800) -> None:
    _ensure_output_dir()
    html_path = os.path.join(_OUTPUT_DIR, f"{name}.html")
    # Write HTML with navigation menu injected after <body>
    raw_html = fig.to_html(full_html=True, include_plotlyjs=True)
    nav = _nav_html(name)
    raw_html = raw_html.replace("<body>", f"<body>{nav}{_AGENT_PANEL_HTML}", 1)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(raw_html)
    print(f"  saved {html_path}")


# ── colour palette ──────────────────────────────────────────────────
AGENT_TYPE_COLORS: Dict[str, str] = {
    "intake": "#636EFA",
    "context": "#EF553B",
    "extraction": "#00CC96",
    "validation": "#AB63FA",
    "resolver": "#FFA15A",
    "human": "#19D3F3",
    "memory": "#FF6692",
}


# ====================================================================
# 1.  Network topology  (side-by-side: initial vs final)
# ====================================================================

def _build_nx_graph(
    edges: Dict[str, Dict],
    agents: Dict,
    trust_scores: Dict[str, float],
) -> nx.DiGraph:
    """Build a networkx DiGraph with node / edge attributes."""
    G = nx.DiGraph()
    for aid, agent in agents.items():
        G.add_node(aid, agent_type=agent.agent_type.value)
    for src, neighbors in edges.items():
        for dst in neighbors:
            key = f"{src}->{dst}"
            G.add_edge(src, dst, trust=trust_scores.get(key, 0.5))
    return G


def _plot_network_panel(
    G: nx.DiGraph,
    pos: Dict[str, Tuple[float, float]],
    title: str,
) -> go.Figure:
    # Collect trust values to compute adaptive scale
    trust_values = [d.get("trust", 0.5) for _, _, d in G.edges(data=True)]
    t_min = min(trust_values) if trust_values else 0.5
    t_max = max(trust_values) if trust_values else 0.5
    t_range = t_max - t_min if t_max > t_min else 1e-6  # avoid division by zero

    # Draw each edge with trust mapped to width + colour (scaled to actual range)
    edge_traces = []
    for u, v, data in G.edges(data=True):
        trust = data.get("trust", 0.5)
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        # Normalize to [0, 1] within this panel's actual trust range
        t_norm = (trust - t_min) / t_range
        # Width: 0.3 → 3.5
        width = 0.3 + 3.2 * t_norm
        # Colour: red (low) → yellow (mid) → green (high)
        r = int(220 * (1.0 - t_norm))
        g = int(60 + 180 * t_norm)
        b = 60
        color = f"rgba({r},{g},{b},0.6)"
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None], mode="lines",
            line=dict(width=width, color=color),
            hoverinfo="text",
            hovertext=f"{u}→{v}  trust={trust:.3f}",
            showlegend=False,
        ))

    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_colors = [AGENT_TYPE_COLORS.get(G.nodes[n].get("agent_type", ""), "#888") for n in G.nodes()]
    node_text = list(G.nodes())

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=12, color=node_colors, line=dict(width=1, color="white")),
        text=node_text, textposition="top center", textfont=dict(size=7),
        hoverinfo="text",
    )

    # Invisible colorbar trace to show trust scale
    colorbar_trace = go.Scatter(
        x=[None], y=[None], mode="markers",
        marker=dict(
            size=0.1,
            color=[t_min, t_max],
            colorscale=[[0, f"rgba(220,60,60,0.8)"], [1, f"rgba(0,240,60,0.8)"]],
            colorbar=dict(
                title=f"trust [{t_min:.3f} – {t_max:.3f}]",
                thickness=12, len=0.6, x=1.02,
            ),
            showscale=True,
        ),
        showlegend=False,
        hoverinfo="none",
    )

    fig = go.Figure(data=edge_traces + [node_trace, colorbar_trace])
    fig.update_layout(
        title=title, showlegend=False,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


def plot_network(sim: MultiAgentMailSimulator) -> None:
    """Network topology (initial vs final) + edge analytics."""
    edges = sim.graph.all_edges()
    initial_trust = sim.initial_graph_snapshot
    final_trust = sim.graph.snapshot_trust()

    G_init = _build_nx_graph(edges, sim.agents, initial_trust)
    G_final = _build_nx_graph(edges, sim.agents, final_trust)

    pos = nx.spring_layout(G_init, seed=42, k=2.0)

    fig = make_subplots(
        rows=2, cols=3,
        subplot_titles=[
            "Initial trust network", "Final trust network", "Top-10 edges (by traffic)",
            "A. Trust updates per used edge",
            "B. Traffic concentration (top-k edges)",
            "C. Node degree distribution",
        ],
        specs=[
            [{"type": "scatter"}, {"type": "scatter"}, {"type": "scatter"}],
            [{"type": "bar"}, {"type": "bar"}, {"type": "bar"}],
        ],
        row_heights=[0.55, 0.45],
        horizontal_spacing=0.06,
        vertical_spacing=0.12,
    )

    # --- row 1: network panels (span cols 1-2, col 3 empty) ---
    fig_init = _plot_network_panel(G_init, pos, "")
    fig_final = _plot_network_panel(G_final, pos, "")

    for trace in fig_init.data:
        fig.add_trace(trace, row=1, col=1)
    for trace in fig_final.data:
        fig.add_trace(trace, row=1, col=2)

    for col in (1, 2):
        fig.update_xaxes(visible=False, row=1, col=col)
        fig.update_yaxes(visible=False, row=1, col=col)
    fig.update_xaxes(visible=False, row=1, col=3)
    fig.update_yaxes(visible=False, row=1, col=3)

    # Legend for agent types (place in col 3 area)
    for atype, color in AGENT_TYPE_COLORS.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color=color),
            name=atype, showlegend=True,
        ))

    # --- row 1, col 3: Top-10 edges by traffic volume ---
    rc = sim.metrics.routing_counts
    if rc:
        sorted_edges = sorted(rc.items(), key=lambda x: x[1], reverse=True)
        top10 = set(e for e, _ in sorted_edges[:10])
        max_count = sorted_edges[0][1] if sorted_edges else 1

        # Draw all edges in faint grey first
        for u, v, data in G_final.edges(data=True):
            key = f"{u}->{v}"
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            if key not in top10:
                fig.add_trace(go.Scatter(
                    x=[x0, x1, None], y=[y0, y1, None], mode="lines",
                    line=dict(width=0.4, color="rgba(200,200,200,0.35)"),
                    hoverinfo="skip", showlegend=False,
                ), row=1, col=3)

        # Draw top-10 edges highlighted with rank labels
        rank = 0
        for edge_key, count in sorted_edges[:10]:
            rank += 1
            src, dst = edge_key.split("->")
            if src not in pos or dst not in pos:
                continue
            x0, y0 = pos[src]
            x1, y1 = pos[dst]
            # Width proportional to count
            width = 1.5 + 4.5 * (count / max_count)
            # Colour from gold (#1) → orange → red-ish (#10)
            t_norm = (rank - 1) / 9.0
            r_c = int(255 - 80 * t_norm)
            g_c = int(180 - 120 * t_norm)
            b_c = int(30 + 30 * t_norm)
            color = f"rgba({r_c},{g_c},{b_c},0.85)"
            fig.add_trace(go.Scatter(
                x=[x0, x1, None], y=[y0, y1, None], mode="lines",
                line=dict(width=width, color=color),
                hoverinfo="text",
                hovertext=f"#{rank} {edge_key}  traffic={count}",
                showlegend=False,
            ), row=1, col=3)
            # Rank label at midpoint
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            fig.add_trace(go.Scatter(
                x=[mx], y=[my], mode="text",
                text=[f"<b>#{rank}</b>"],
                textfont=dict(size=9, color=color),
                hoverinfo="text",
                hovertext=f"#{rank} {edge_key}  traffic={count}",
                showlegend=False,
            ), row=1, col=3)

        # Nodes
        node_x = [pos[n][0] for n in G_final.nodes()]
        node_y = [pos[n][1] for n in G_final.nodes()]
        node_colors = [AGENT_TYPE_COLORS.get(G_final.nodes[n].get("agent_type", ""), "#888") for n in G_final.nodes()]
        node_text = list(G_final.nodes())
        fig.add_trace(go.Scatter(
            x=node_x, y=node_y, mode="markers+text",
            marker=dict(size=12, color=node_colors, line=dict(width=1, color="white")),
            text=node_text, textposition="top center", textfont=dict(size=7),
            hoverinfo="text", showlegend=False,
        ), row=1, col=3)

    # --- row 2, col 1: A. Trust updates per used edge (histogram) ---
    rc = sim.metrics.routing_counts
    if rc:
        counts = sorted(rc.values(), reverse=True)
        fig.add_trace(go.Histogram(
            x=counts, nbinsx=25,
            marker_color="#636EFA",
            showlegend=False,
        ), row=2, col=1)
        fig.update_xaxes(title_text="updates per edge", row=2, col=1)
        fig.update_yaxes(title_text="# edges", row=2, col=1)

    # --- row 2, col 2: B. Traffic concentration (top-k) ---
    if rc:
        sorted_edges = sorted(rc.items(), key=lambda x: x[1], reverse=True)
        total_traffic = sum(rc.values())
        top_k_values = [10, 20, 30, 50]
        cumulative_pcts = []
        labels = []
        for k in top_k_values:
            top_k_sum = sum(v for _, v in sorted_edges[:k])
            pct = 100.0 * top_k_sum / total_traffic if total_traffic > 0 else 0
            cumulative_pcts.append(pct)
            labels.append(f"top-{k}")

        bar_colors = ["#EF553B" if p > 80 else "#FFA15A" if p > 60 else "#00CC96" for p in cumulative_pcts]
        fig.add_trace(go.Bar(
            x=labels, y=cumulative_pcts,
            marker_color=bar_colors,
            text=[f"{p:.1f}%" for p in cumulative_pcts],
            textposition="auto",
            showlegend=False,
        ), row=2, col=2)
        fig.update_yaxes(title_text="% of total traffic", range=[0, 105], row=2, col=2)

    # --- row 2, col 3: C. Degree distribution ---
    G_undir = G_final.to_undirected()
    degrees = [d for _, d in G_undir.degree()]
    if degrees:
        fig.add_trace(go.Histogram(
            x=degrees, nbinsx=max(5, max(degrees) - min(degrees) + 1),
            marker_color="#AB63FA",
            showlegend=False,
        ), row=2, col=3)
        avg_deg = sum(degrees) / len(degrees)
        fig.add_vline(
            x=avg_deg, line_dash="dash", line_color="red",
            annotation_text=f"avg={avg_deg:.1f}",
            row=2, col=3,
        )
        fig.update_xaxes(title_text="degree", row=2, col=3)
        fig.update_yaxes(title_text="# agents", row=2, col=3)

    fig.update_layout(
        title="Agent network topology — trust before & after simulation",
        height=1000, width=1600,
    )
    _save(fig, "01_network_topology", width=1600, height=1000)


# ====================================================================
# 2.  Input parameters dashboard
# ====================================================================

def plot_input_parameters(sim: MultiAgentMailSimulator) -> None:
    cfg = sim.config
    params = {
        "duration (min)": cfg.duration,
        "arrival_rate/hr": cfg.arrival_rate_per_hour,
        "max_rework": cfg.max_rework,
        "split_threshold": cfg.split_threshold,
        "merge_min_quality": cfg.merge_min_quality,
        "human_resolve_mean": cfg.human_resolution_time_mean,
        "burst_multiplier": cfg.burst_multiplier,
        "failure_duration": cfg.failure_duration,
        "seed": cfg.seed,
    }

    fig = make_subplots(
        rows=1, cols=2,
        column_widths=[0.45, 0.55],
        specs=[[{"type": "table"}, {"type": "bar"}]],
    )

    # Table
    fig.add_trace(go.Table(
        header=dict(values=["Parameter", "Value"], fill_color="#3366CC", font=dict(color="white")),
        cells=dict(
            values=[list(params.keys()), [f"{v}" for v in params.values()]],
            fill_color="lavender",
        ),
    ), row=1, col=1)

    # Agent counts by type
    type_counts: Dict[str, int] = defaultdict(int)
    for a in sim.agents.values():
        type_counts[a.agent_type.value] += 1
    types = list(type_counts.keys())
    counts = list(type_counts.values())
    colors = [AGENT_TYPE_COLORS.get(t, "#888") for t in types]

    fig.add_trace(go.Bar(
        x=types, y=counts, marker_color=colors,
        text=counts, textposition="outside", name="Agents",
    ), row=1, col=2)

    fig.update_layout(title="Simulation input parameters & agent fleet", height=500, showlegend=False)
    _save(fig, "02_input_parameters", height=500)


# ====================================================================
# 3.  Queue evolution (timeseries) — aggregated by AgentType
# ====================================================================

def plot_queue_evolution(sim: MultiAgentMailSimulator) -> None:
    ts = sim.metrics.timeseries
    if not ts:
        print("  [skip] no timeseries data for queue evolution")
        return

    timestamps = [s.timestamp for s in ts]
    agent_types = sorted({at.value for at in AgentType})

    fig = go.Figure()
    for atype in agent_types:
        values = [s.queue_lengths_by_type.get(atype, 0) for s in ts]
        fig.add_trace(go.Scatter(
            x=timestamps, y=values, mode="lines",
            name=atype,
            line=dict(color=AGENT_TYPE_COLORS.get(atype, "#888")),
            stackgroup="one",
        ))

    fig.update_layout(
        title="Queue depth over time (stacked by agent type)",
        xaxis_title="Simulation time (min)",
        yaxis_title="Total items in queues",
        height=550,
    )
    _save(fig, "03_queue_evolution", height=550)


# ====================================================================
# 4.  Case status (area chart) — open / closed / escalated
# ====================================================================

def plot_case_status(sim: MultiAgentMailSimulator) -> None:
    ts = sim.metrics.timeseries
    if not ts:
        print("  [skip] no timeseries data for case status")
        return

    timestamps = [s.timestamp for s in ts]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=[s.cumulative_open for s in ts],
        mode="lines", name="Open / active", fill="tozeroy",
        line=dict(color="#636EFA"),
    ))
    fig.add_trace(go.Scatter(
        x=timestamps, y=[s.cumulative_closed for s in ts],
        mode="lines", name="Closed (cumulative)",
        line=dict(color="#00CC96"),
    ))
    fig.add_trace(go.Scatter(
        x=timestamps, y=[s.cumulative_escalated for s in ts],
        mode="lines", name="Escalated (cumulative)",
        line=dict(color="#EF553B"),
    ))
    fig.update_layout(
        title="Case status over time",
        xaxis_title="Simulation time (min)",
        yaxis_title="Count",
        height=500,
    )
    _save(fig, "04_case_status", height=500)


# ====================================================================
# 5.  Fatigue heatmap
# ====================================================================

def plot_fatigue_evolution(sim: MultiAgentMailSimulator) -> None:
    ts = sim.metrics.timeseries
    if not ts:
        print("  [skip] no timeseries data for fatigue")
        return

    agent_ids = sorted(sim.agents.keys())
    timestamps = [s.timestamp for s in ts]
    z = [[s.fatigue_levels.get(aid, 0.0) for s in ts] for aid in agent_ids]

    fig = go.Figure(data=go.Heatmap(
        z=z, x=timestamps, y=agent_ids,
        colorscale="YlOrRd", colorbar_title="Fatigue",
        zmin=0, zmax=1,
    ))
    fig.update_layout(
        title="Agent fatigue heatmap over time",
        xaxis_title="Simulation time (min)",
        yaxis_title="Agent",
        height=max(500, 18 * len(agent_ids)),
    )
    _save(fig, "05_fatigue_heatmap", height=max(500, 18 * len(agent_ids)))


# ====================================================================
# 6.  Trust evolution — top-N most-changed edges
# ====================================================================

def plot_trust_evolution(
    sim: MultiAgentMailSimulator,
    top_n: int = 15,
) -> None:
    ts = sim.metrics.timeseries
    if not ts:
        print("  [skip] no timeseries data for trust")
        return

    # Collect all edge keys that appear in any snapshot
    all_keys: set = set()
    for s in ts:
        all_keys.update(s.trust_scores.keys())

    # Compute magnitude of change for each edge
    changes: Dict[str, float] = {}
    for key in all_keys:
        values = [s.trust_scores.get(key) for s in ts]
        present = [v for v in values if v is not None]
        if len(present) >= 2:
            changes[key] = abs(present[-1] - present[0])
        else:
            changes[key] = 0.0

    # Pick top N most-changed
    top_keys = sorted(changes, key=changes.get, reverse=True)[:top_n]

    timestamps = [s.timestamp for s in ts]
    fig = go.Figure()
    for key in top_keys:
        values = [s.trust_scores.get(key) for s in ts]
        fig.add_trace(go.Scatter(
            x=timestamps, y=values, mode="lines", name=key,
        ))

    fig.update_layout(
        title=f"Trust evolution — top {top_n} most-changed edges",
        xaxis_title="Simulation time (min)",
        yaxis_title="Trust score",
        height=600,
        legend=dict(font=dict(size=9)),
    )
    _save(fig, "06_trust_evolution", height=600)


# ====================================================================
# 7.  Routing Sankey diagram
# ====================================================================

def plot_routing_sankey(sim: MultiAgentMailSimulator) -> None:
    rc = sim.metrics.routing_counts
    if not rc:
        print("  [skip] no routing counts for sankey")
        return

    # Collect unique node labels
    labels: List[str] = []
    label_idx: Dict[str, int] = {}
    for route in rc:
        src, dst = route.split("->")
        for n in (src, dst):
            if n not in label_idx:
                label_idx[n] = len(labels)
                labels.append(n)

    sources, targets, values = [], [], []
    for route, count in rc.items():
        src, dst = route.split("->")
        sources.append(label_idx[src])
        targets.append(label_idx[dst])
        values.append(count)

    node_colors = []
    for lbl in labels:
        if lbl in sim.agents:
            node_colors.append(AGENT_TYPE_COLORS.get(sim.agents[lbl].agent_type.value, "#888"))
        else:
            node_colors.append("#888888")

    fig = go.Figure(data=[go.Sankey(
        node=dict(pad=15, thickness=20, label=labels, color=node_colors),
        link=dict(source=sources, target=targets, value=values),
    )])
    fig.update_layout(title="Routing flow (Sankey)", height=700, width=1400)
    _save(fig, "07_routing_sankey", width=1400, height=700)


# ====================================================================
# 8.  Metrics dashboard — summary KPIs
# ====================================================================

def plot_metrics_dashboard(sim: MultiAgentMailSimulator) -> None:
    summary = sim.metrics.summary()

    fig = make_subplots(
        rows=2, cols=3,
        subplot_titles=[
            "Lead time distribution",
            "Quality distribution",
            "Agent utilization",
            "Queue imbalance by type",
            "Key KPIs",
            "Routing entropy",
        ],
        specs=[
            [{"type": "histogram"}, {"type": "histogram"}, {"type": "bar"}],
            [{"type": "bar"}, {"type": "table"}, {"type": "indicator"}],
        ],
        vertical_spacing=0.14,
        horizontal_spacing=0.08,
    )

    # 1. Lead time histogram
    fig.add_trace(go.Histogram(
        x=sim.metrics.lead_times, nbinsx=30, name="Lead time",
        marker_color="#636EFA",
    ), row=1, col=1)

    # 2. Quality histogram
    fig.add_trace(go.Histogram(
        x=sim.metrics.quality_scores, nbinsx=20, name="Quality",
        marker_color="#00CC96",
    ), row=1, col=2)

    # 3. Agent utilization (busy_time / duration)
    agent_ids = sorted(sim.agents.keys())
    utils = [sim.metrics.agent_busy_time.get(a, 0.0) / sim.config.duration for a in agent_ids]
    colors = [AGENT_TYPE_COLORS.get(sim.agents[a].agent_type.value, "#888") for a in agent_ids]
    fig.add_trace(go.Bar(
        x=agent_ids, y=utils, marker_color=colors, name="Utilization",
    ), row=1, col=3)

    # 4. Queue imbalance by type
    type_means: Dict[str, float] = defaultdict(list)
    for aid, samples in sim.metrics.queue_samples.items():
        if samples:
            atype = sim.agents[aid].agent_type.value
            type_means[atype].append(sum(samples) / len(samples))
    types_sorted = sorted(type_means.keys())
    means = [sum(type_means[t]) / len(type_means[t]) if type_means[t] else 0 for t in types_sorted]
    fig.add_trace(go.Bar(
        x=types_sorted, y=means,
        marker_color=[AGENT_TYPE_COLORS.get(t, "#888") for t in types_sorted],
        name="Avg queue",
    ), row=2, col=1)

    # 5. KPI table
    kpi_names = ["closed_cases", "mean_lead_time", "avg_quality", "escalation_rate", "sla_breaches", "false_closures"]
    kpi_vals = [f"{summary.get(k, 0):.2f}" for k in kpi_names]
    fig.add_trace(go.Table(
        header=dict(values=["KPI", "Value"], fill_color="#3366CC", font=dict(color="white")),
        cells=dict(values=[kpi_names, kpi_vals], fill_color="lavender"),
    ), row=2, col=2)

    # 6. Routing entropy indicator
    fig.add_trace(go.Indicator(
        mode="gauge+number",
        value=summary.get("routing_entropy", 0.0),
        title=dict(text="Routing entropy"),
        gauge=dict(axis=dict(range=[0, 5]), bar=dict(color="#636EFA")),
    ), row=2, col=3)

    fig.update_layout(title="Simulation metrics dashboard", height=900, showlegend=False)
    _save(fig, "08_metrics_dashboard", height=900)


# ====================================================================
# 9.  Monte Carlo comparison — box plots across runs
# ====================================================================

def plot_monte_carlo_comparison(
    sims: List[MultiAgentMailSimulator],
    label: str = "",
) -> None:
    if not sims:
        print("  [skip] no sims for monte-carlo comparison")
        return

    metrics_keys = [
        "closed_cases", "mean_lead_time", "avg_quality",
        "escalation_rate", "avg_handoffs_per_case", "avg_cost_per_case",
    ]
    summaries = [s.metrics.summary() for s in sims]

    fig = make_subplots(rows=2, cols=3, subplot_titles=metrics_keys)
    for idx, key in enumerate(metrics_keys):
        row = idx // 3 + 1
        col = idx % 3 + 1
        vals = [s[key] for s in summaries]
        fig.add_trace(go.Box(y=vals, name=key, boxpoints="all"), row=row, col=col)

    suffix = f" ({label})" if label else ""
    fig.update_layout(
        title=f"Monte Carlo comparison — {len(sims)} runs{suffix}",
        height=700, showlegend=False,
    )
    name = f"09_monte_carlo_{label}" if label else "09_monte_carlo"
    _save(fig, name, height=700)


# ====================================================================
# 10.  Effective thermodynamic quantities over time
#      Single-run trace + optional MC ensemble bands
# ====================================================================

_THERMO_FIELDS = [
    ("T_eff (temperature)", "effective_temperature", "#EF553B"),
    ("U_eff (internal energy)", "effective_internal_energy", "#636EFA"),
    ("S_eff (entropy)", "effective_entropy", "#00CC96"),
    ("F_eff (free energy)", "effective_free_energy", "#AB63FA"),
]


def _hex_fill(hex_color: str, alpha: float) -> str:
    """Convert #RRGGBB to rgba(r,g,b,alpha)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def plot_effective_thermodynamics(
    sim: MultiAgentMailSimulator,
    mc_sims: Optional[List[MultiAgentMailSimulator]] = None,
) -> None:
    ts = sim.metrics.timeseries
    if not ts:
        print("  [skip] no timeseries data for thermodynamics")
        return

    timestamps = [s.timestamp for s in ts]

    # Prepare MC ensemble data if available
    all_ts = [s.metrics.timeseries for s in (mc_sims or []) if s.metrics.timeseries]
    has_ensemble = len(all_ts) >= 2
    if has_ensemble:
        mc_len = min(len(t) for t in all_ts)
        mc_times = [all_ts[0][i].timestamp for i in range(mc_len)]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[f[0] for f in _THERMO_FIELDS],
        horizontal_spacing=0.08,
        vertical_spacing=0.12,
    )

    for idx, (label, field, color) in enumerate(_THERMO_FIELDS):
        row, col = divmod(idx, 2)
        r, c = row + 1, col + 1

        # --- MC ensemble bands (drawn first so single-run line is on top) ---
        if has_ensemble:
            matrix = np.array(
                [[getattr(t[i], field) for i in range(mc_len)] for t in all_ts]
            )
            mean = np.mean(matrix, axis=0)
            p10 = np.percentile(matrix, 10, axis=0)
            p25 = np.percentile(matrix, 25, axis=0)
            p75 = np.percentile(matrix, 75, axis=0)
            p90 = np.percentile(matrix, 90, axis=0)

            # 10-90 % band (lighter)
            fig.add_trace(go.Scatter(
                x=mc_times, y=p90.tolist(), mode="lines",
                line=dict(width=0), showlegend=False, hoverinfo="skip",
            ), row=r, col=c)
            fig.add_trace(go.Scatter(
                x=mc_times, y=p10.tolist(), mode="lines",
                line=dict(width=0), fill="tonexty",
                fillcolor=_hex_fill(color, 0.12),
                showlegend=False, hoverinfo="skip",
            ), row=r, col=c)

            # 25-75 % band (darker)
            fig.add_trace(go.Scatter(
                x=mc_times, y=p75.tolist(), mode="lines",
                line=dict(width=0), showlegend=False, hoverinfo="skip",
            ), row=r, col=c)
            fig.add_trace(go.Scatter(
                x=mc_times, y=p25.tolist(), mode="lines",
                line=dict(width=0), fill="tonexty",
                fillcolor=_hex_fill(color, 0.28),
                showlegend=False, hoverinfo="skip",
            ), row=r, col=c)

            # MC mean trajectory (dashed)
            fig.add_trace(go.Scatter(
                x=mc_times, y=mean.tolist(), mode="lines",
                name=f"MC mean", line=dict(color=color, width=2, dash="dash"),
                showlegend=(idx == 0),
                legendgroup="mc_mean",
            ), row=r, col=c)

        # --- Single-run trajectory (solid, on top) ---
        values = [getattr(s, field) for s in ts]
        fig.add_trace(go.Scatter(
            x=timestamps, y=values, mode="lines",
            name="Single run" if idx == 0 else label,
            line=dict(color=color, width=2.5),
            showlegend=(idx == 0),
            legendgroup="single",
        ), row=r, col=c)

        fig.update_yaxes(title_text="value", row=r, col=c)
        fig.update_xaxes(title_text="time (min)", row=r, col=c)

    title = "Effective thermodynamic quantities over time"
    if has_ensemble:
        title += f" — single run + MC ensemble ({len(all_ts)} runs)"
    fig.update_layout(title=title, height=750)
    _save(fig, "10_effective_thermodynamics", height=750)


# ====================================================================
# 10w. Warm-start thermodynamic ensemble
#      Per-run trajectories (coloured by run #) + mean + bands
# ====================================================================

def plot_warm_thermodynamics(
    warm_sims: List[MultiAgentMailSimulator],
) -> None:
    """Warm-start thermo ensemble — shows learning progression across runs."""
    all_ts = [s.metrics.timeseries for s in warm_sims if s.metrics.timeseries]
    if len(all_ts) < 2:
        print("  [skip] not enough warm-start runs for thermo ensemble")
        return

    min_len = min(len(ts) for ts in all_ts)
    timestamps = [all_ts[0][i].timestamp for i in range(min_len)]
    n_runs = len(all_ts)

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[f[0] for f in _THERMO_FIELDS],
        horizontal_spacing=0.08,
        vertical_spacing=0.12,
    )

    for idx, (label, field, color) in enumerate(_THERMO_FIELDS):
        row, col = divmod(idx, 2)
        r, c = row + 1, col + 1

        matrix = np.array(
            [[getattr(ts[i], field) for i in range(min_len)] for ts in all_ts]
        )
        mean = np.mean(matrix, axis=0)
        p10 = np.percentile(matrix, 10, axis=0)
        p25 = np.percentile(matrix, 25, axis=0)
        p75 = np.percentile(matrix, 75, axis=0)
        p90 = np.percentile(matrix, 90, axis=0)

        # 10-90 % band
        fig.add_trace(go.Scatter(
            x=timestamps, y=p90.tolist(), mode="lines",
            line=dict(width=0), showlegend=False, hoverinfo="skip",
        ), row=r, col=c)
        fig.add_trace(go.Scatter(
            x=timestamps, y=p10.tolist(), mode="lines",
            line=dict(width=0), fill="tonexty",
            fillcolor=_hex_fill(color, 0.10),
            showlegend=False, hoverinfo="skip",
        ), row=r, col=c)

        # 25-75 % band
        fig.add_trace(go.Scatter(
            x=timestamps, y=p75.tolist(), mode="lines",
            line=dict(width=0), showlegend=False, hoverinfo="skip",
        ), row=r, col=c)
        fig.add_trace(go.Scatter(
            x=timestamps, y=p25.tolist(), mode="lines",
            line=dict(width=0), fill="tonexty",
            fillcolor=_hex_fill(color, 0.25),
            showlegend=False, hoverinfo="skip",
        ), row=r, col=c)

        # Individual run trajectories — early runs lighter, late runs bolder
        for run_i, ts_run in enumerate(all_ts):
            alpha = 0.15 + 0.55 * (run_i / max(n_runs - 1, 1))
            width = 0.6 + 1.0 * (run_i / max(n_runs - 1, 1))
            vals = [getattr(ts_run[i], field) for i in range(min_len)]
            fig.add_trace(go.Scatter(
                x=timestamps, y=vals, mode="lines",
                line=dict(color=_hex_fill(color, alpha), width=width),
                showlegend=False,
                hoverinfo="text",
                hovertext=f"run #{run_i + 1}",
            ), row=r, col=c)

        # Mean trajectory (solid, on top)
        fig.add_trace(go.Scatter(
            x=timestamps, y=mean.tolist(), mode="lines",
            name="Warm mean" if idx == 0 else label,
            line=dict(color=color, width=3),
            showlegend=(idx == 0),
            legendgroup="warm_mean",
        ), row=r, col=c)

        fig.update_yaxes(title_text="value", row=r, col=c)
        fig.update_xaxes(title_text="time (min)", row=r, col=c)

    fig.update_layout(
        title=(
            f"Warm-start thermodynamic ensemble — {n_runs} runs "
            f"(early runs lighter → late runs bolder)"
        ),
        height=750,
    )
    _save(fig, "10w_warm_thermodynamics", height=750)


def plot_operational_health(sim: MultiAgentMailSimulator) -> None:
    """Stage 2 operational health: SLA risk, timeout requeues, priority distribution."""
    ts = sim.metrics.timeseries
    if not ts:
        print("  [skip] no timeseries data for operational health")
        return

    timestamps = [s.timestamp for s in ts]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[
            "A. SLA risk timeline",
            "B. Queue timeout requeues (cumulative)",
            "C. Priority distribution over time",
            "D. SLA at-risk vs breaches",
        ],
        horizontal_spacing=0.08,
        vertical_spacing=0.12,
    )

    # --- A. SLA risk count over time ---
    sla_risk_counts = [s.sla_at_risk_count for s in ts]
    fig.add_trace(
        go.Scatter(
            x=timestamps, y=sla_risk_counts, mode="lines",
            name="Cases at SLA risk", line=dict(color="#EF553B", width=2),
            fill="tozeroy", fillcolor="rgba(239,85,59,0.15)",
        ),
        row=1, col=1,
    )
    fig.update_yaxes(title_text="cases at risk", row=1, col=1)
    fig.update_xaxes(title_text="time (min)", row=1, col=1)

    # --- B. Cumulative timeout requeues ---
    timeout_counts = [s.cumulative_timeout_requeues for s in ts]
    fig.add_trace(
        go.Scatter(
            x=timestamps, y=timeout_counts, mode="lines",
            name="Timeout requeues", line=dict(color="#FFA15A", width=2),
        ),
        row=1, col=2,
    )
    fig.update_yaxes(title_text="cumulative requeues", row=1, col=2)
    fig.update_xaxes(title_text="time (min)", row=1, col=2)

    # --- C. Priority distribution (stacked area) ---
    all_prios = sorted({p for s in ts for p in s.priority_distribution})
    prio_colors = {1: "#00CC96", 2: "#636EFA", 3: "#EF553B"}
    for prio in all_prios:
        values = [s.priority_distribution.get(prio, 0) for s in ts]
        fig.add_trace(
            go.Scatter(
                x=timestamps, y=values, mode="lines",
                name=f"Priority {prio}",
                line=dict(color=prio_colors.get(prio, "#AB63FA"), width=1.5),
                stackgroup="priority",
            ),
            row=2, col=1,
        )
    fig.update_yaxes(title_text="active cases", row=2, col=1)
    fig.update_xaxes(title_text="time (min)", row=2, col=1)

    # --- D. SLA at-risk vs cumulative breaches ---
    fig.add_trace(
        go.Scatter(
            x=timestamps, y=sla_risk_counts, mode="lines",
            name="At-risk (live)", line=dict(color="#EF553B", width=2, dash="dot"),
        ),
        row=2, col=2,
    )
    cum_breaches = []
    running = 0
    for s in ts:
        running = sum(
            1 for c in sim.cases.values()
            if c.status == CaseStatus.CLOSED
            and c.close_time is not None
            and c.close_time <= s.timestamp
            and c.close_time > c.deadline
        )
        cum_breaches.append(running)
    fig.add_trace(
        go.Scatter(
            x=timestamps, y=cum_breaches, mode="lines",
            name="SLA breaches (cumul.)", line=dict(color="#AB63FA", width=2),
        ),
        row=2, col=2,
    )
    fig.update_yaxes(title_text="count", row=2, col=2)
    fig.update_xaxes(title_text="time (min)", row=2, col=2)

    fig.update_layout(
        title="Operational health — Stage 2 mechanisms",
        height=750,
        showlegend=True,
        legend=dict(orientation="h", y=-0.08),
    )
    _save(fig, "11_operational_health", height=750)


def plot_warm_start_trend(
    per_run: List[Dict[str, float]],
    cold_sims: Optional[List[MultiAgentMailSimulator]] = None,
    decay: float = 0.9,
) -> None:
    """Warm-start per-run trend vs cold-start baseline."""
    if not per_run:
        print("  [skip] no warm-start data")
        return

    metrics = [
        ("closed_cases", "Closed cases"),
        ("mean_lead_time", "Mean lead time (min)"),
        ("avg_quality", "Avg quality"),
        ("escalation_rate", "Escalation rate"),
        ("routing_entropy", "Routing entropy"),
        ("avg_handoffs_per_case", "Avg handoffs/case"),
    ]

    fig = make_subplots(
        rows=2, cols=3,
        subplot_titles=[m[1] for m in metrics],
        horizontal_spacing=0.07,
        vertical_spacing=0.14,
    )

    run_indices = list(range(1, len(per_run) + 1))

    # Cold-start baselines (mean ± std band)
    cold_summaries = [s.metrics.summary() for s in cold_sims] if cold_sims else []

    for idx, (key, label) in enumerate(metrics):
        row = idx // 3 + 1
        col = idx % 3 + 1
        warm_vals = [r[key] for r in per_run]

        # Warm-start line
        fig.add_trace(
            go.Scatter(
                x=run_indices, y=warm_vals, mode="lines+markers",
                name=f"Warm ({label})",
                line=dict(color="#EF553B", width=2),
                marker=dict(size=6),
                showlegend=(idx == 0),
                legendgroup="warm",
            ),
            row=row, col=col,
        )

        # Cold-start baseline band
        if cold_summaries:
            import statistics as _stats
            cold_vals = [s[key] for s in cold_summaries]
            cold_mean = _stats.mean(cold_vals)
            cold_std = _stats.pstdev(cold_vals) if len(cold_vals) > 1 else 0.0
            fig.add_trace(
                go.Scatter(
                    x=[run_indices[0], run_indices[-1]],
                    y=[cold_mean, cold_mean],
                    mode="lines", name=f"Cold mean ({label})",
                    line=dict(color="#636EFA", width=2, dash="dash"),
                    showlegend=(idx == 0),
                    legendgroup="cold",
                ),
                row=row, col=col,
            )
            if cold_std > 0:
                fig.add_trace(
                    go.Scatter(
                        x=[run_indices[0], run_indices[-1], run_indices[-1], run_indices[0]],
                        y=[cold_mean + cold_std, cold_mean + cold_std,
                           cold_mean - cold_std, cold_mean - cold_std],
                        fill="toself", fillcolor="rgba(99,110,250,0.12)",
                        line=dict(width=0), mode="lines",
                        showlegend=False,
                    ),
                    row=row, col=col,
                )

        fig.update_xaxes(title_text="run #", row=row, col=col)
        fig.update_yaxes(title_text=label, row=row, col=col)

    fig.update_layout(
        title=f"Warm-start per-run trend (decay={decay}) vs cold-start baseline",
        height=700,
        legend=dict(orientation="h", y=-0.08),
    )
    _save(fig, "12_warm_start_trend", height=700)


# ====================================================================


class SimulationVisualizer:
    """Convenience wrapper that holds a simulator reference and exposes
    all plot methods."""

    def __init__(self, sim: MultiAgentMailSimulator, output_dir: str = "") -> None:
        self.sim = sim
        self.output_dir = output_dir or os.path.join(_BASE_OUTPUT, "default")
        global _OUTPUT_DIR, _AGENT_PANEL_HTML
        _OUTPUT_DIR = self.output_dir
        _AGENT_PANEL_HTML = _build_agent_panel(sim)

    def plot_network(self) -> None:
        plot_network(self.sim)

    def plot_input_parameters(self) -> None:
        plot_input_parameters(self.sim)

    def plot_queue_evolution(self) -> None:
        plot_queue_evolution(self.sim)

    def plot_case_status(self) -> None:
        plot_case_status(self.sim)

    def plot_fatigue_evolution(self) -> None:
        plot_fatigue_evolution(self.sim)

    def plot_trust_evolution(self, top_n: int = 15) -> None:
        plot_trust_evolution(self.sim, top_n=top_n)

    def plot_routing_sankey(self) -> None:
        plot_routing_sankey(self.sim)

    def plot_metrics_dashboard(self) -> None:
        plot_metrics_dashboard(self.sim)

    def plot_monte_carlo_comparison(
        self,
        sims: Optional[List[MultiAgentMailSimulator]] = None,
        label: str = "",
    ) -> None:
        plot_monte_carlo_comparison(sims or [self.sim], label=label)

    def plot_effective_thermodynamics(
        self,
        mc_sims: Optional[List[MultiAgentMailSimulator]] = None,
    ) -> None:
        plot_effective_thermodynamics(self.sim, mc_sims=mc_sims)

    def plot_warm_thermodynamics(
        self,
        warm_sims: Optional[List[MultiAgentMailSimulator]] = None,
    ) -> None:
        if warm_sims:
            plot_warm_thermodynamics(warm_sims)

    def plot_operational_health(self) -> None:
        plot_operational_health(self.sim)

    def plot_warm_start_trend(
        self,
        per_run: List[Dict[str, float]],
        cold_sims: Optional[List[MultiAgentMailSimulator]] = None,
        decay: float = 0.9,
    ) -> None:
        plot_warm_start_trend(per_run, cold_sims=cold_sims, decay=decay)

    def plot_all(
        self,
        mc_sims: Optional[List[MultiAgentMailSimulator]] = None,
        warm_sims: Optional[List[MultiAgentMailSimulator]] = None,
        warm_per_run: Optional[List[Dict[str, float]]] = None,
        warm_decay: float = 0.9,
    ) -> None:
        """Generate every chart for a single run.

        If *mc_sims* is provided, also generates the Monte Carlo comparison.
        """
        print("Generating all charts …")
        self.plot_network()
        self.plot_input_parameters()
        self.plot_queue_evolution()
        self.plot_case_status()
        self.plot_fatigue_evolution()
        self.plot_trust_evolution()
        self.plot_routing_sankey()
        self.plot_metrics_dashboard()
        if mc_sims:
            self.plot_monte_carlo_comparison(mc_sims)
        self.plot_effective_thermodynamics(mc_sims)
        self.plot_warm_thermodynamics(warm_sims)
        self.plot_operational_health()
        if warm_per_run:
            self.plot_warm_start_trend(warm_per_run, cold_sims=mc_sims, decay=warm_decay)
        # Export raw data that feeds every chart
        export_all(self.sim, mc_sims=mc_sims, warm_per_run=warm_per_run,
                   warm_decay=warm_decay, output_dir=self.output_dir)
        print("Done.")


# ====================================================================
# CLI entry point
# ====================================================================

if __name__ == "__main__":
    import sys
    from main import load_config, run_single_experiment, run_monte_carlo, run_warm_monte_carlo

    cfg_path = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config(cfg_path)

    print("Running single experiment …")
    summary, sim = run_single_experiment(config, return_sim=True)
    print(f"  closed={summary['closed_cases']:.0f}  "
          f"lead={summary['mean_lead_time']:.1f}  "
          f"quality={summary['avg_quality']:.3f}")

    # Read experiment-level settings from YAML
    import yaml
    from main import _DEFAULT_CONFIG_PATH
    from pathlib import Path
    _cfg_file = Path(cfg_path) if cfg_path else _DEFAULT_CONFIG_PATH
    with open(_cfg_file, encoding="utf-8") as _fh:
        _raw = yaml.safe_load(_fh) or {}
    mc_runs = int(_raw.get("monte_carlo_runs", 5))
    warm_mc_runs = int(_raw.get("warm_monte_carlo_runs", mc_runs))

    print(f"Running Cold-start Monte Carlo ({mc_runs} runs) …")
    mc_summary, mc_sims = run_monte_carlo(mc_runs, base_config=config, return_sims=True)

    print(f"Running Warm-start Monte Carlo ({warm_mc_runs} runs, decay={config.trust_decay}) …")
    mc_warm, warm_sims = run_warm_monte_carlo(n_runs=warm_mc_runs, base_config=config, return_sims=True)

    # Determine output directory from YAML stem
    _cfg_stem = Path(cfg_path).stem if cfg_path else "default"
    _out_dir = os.path.join(_BASE_OUTPUT, _cfg_stem)

    viz = SimulationVisualizer(sim, output_dir=_out_dir)
    viz.plot_all(
        mc_sims=mc_sims,
        warm_sims=warm_sims,
        warm_per_run=mc_warm["per_run"],
        warm_decay=config.trust_decay,
    )
