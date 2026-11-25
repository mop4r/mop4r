#!/usr/bin/env python3
"""Gera SVGs autorais (dark + light) para o GitHub Profile README do mop4r.

Usa apenas a biblioteca padrão do Python. Consulta a API GraphQL do GitHub quando
GITHUB_TOKEN está disponível no ambiente (com timeout e validação) para atualizar
as estatísticas reais, a distribuição de linguagens e o gráfico mensal de atividade.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import html
import http.client
import json
import os
from pathlib import Path
import ssl

GITHUB_USER = "mop4r"
GITHUB_API_HOST = "api.github.com"
GRAPHQL_PATH = "/graphql"
HTTP_TIMEOUT_S = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

FONT_SANS = "ui-sans-serif, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
FONT_MONO = "ui-monospace, 'Cascadia Code', Consolas, 'Liberation Mono', Menlo, monospace"

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0D1117",
        "panel": "#131924",
        "panel2": "#192231",
        "border": "#263042",
        "text": "#E6EDF3",
        "muted": "#8B949E",
        "dim": "#6E7681",
        "claude": "#E88B68",
        "violet": "#9B8CFF",
        "green": "#3FB950",
        "cyan": "#58A6FF",
        "amber": "#D29922",
        "grid": "#212A3A",
        "pill_bg": "#1B2434",
        "dot": "#FFFFFF",
        "dot_op": "0.06",
    },
    "light": {
        "bg": "#FFFFFF",
        "panel": "#F6F8FA",
        "panel2": "#EEF2F7",
        "border": "#D0D7DE",
        "text": "#1F2328",
        "muted": "#59636E",
        "dim": "#6E7781",
        "claude": "#C25934",
        "violet": "#6652E5",
        "green": "#1A7F37",
        "cyan": "#0969DA",
        "amber": "#9A6700",
        "grid": "#DCE3EC",
        "pill_bg": "#EAEFF5",
        "dot": "#1F2328",
        "dot_op": "0.07",
    },
}

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
      totalCommitContributions
      restrictedContributionsCount
    }
    repositories(first: 100, privacy: PUBLIC, isFork: false) {
      totalCount
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class ProfileStats:
    login: str
    since_year: int
    public_repos: int
    total_stars: int
    followers: int
    total_contributions: int
    languages: tuple[tuple[str, float, str], ...]
    monthly_counts: tuple[tuple[str, int], ...]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def aggregate_monthly(weeks: list[dict]) -> tuple[tuple[str, int], ...]:
    """Agrupa dias de contribuição por mês (YYYY-MM) e devolve os últimos 12 meses."""
    by_month: dict[str, int] = {}
    for week in weeks:
        for day in week.get("contributionDays", []):
            date_str = str(day.get("date", ""))
            if len(date_str) >= 7:
                ym = date_str[:7]
                count = max(0, int(day.get("contributionCount", 0) or 0))
                by_month[ym] = by_month.get(ym, 0) + count
    if not by_month:
        return ()
    ordered = sorted(by_month.items())[-12:]
    months_short = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    out: list[tuple[str, int]] = []
    for ym, total in ordered:
        try:
            m_idx = int(ym.split("-")[1]) - 1
            label = months_short[m_idx] if 0 <= m_idx < 12 else ym[5:7]
        except (ValueError, IndexError):
            label = ym[5:7]
        out.append((label, total))
    return tuple(out)


def aggregate_languages(repo_nodes: list[dict]) -> tuple[tuple[str, float, str], ...]:
    """Calcula distribuição percentual das top 5 linguagens nos repositórios públicos."""
    totals: dict[str, int] = {}
    colors: dict[str, str] = {}
    for repo in repo_nodes:
        edges = (repo.get("languages") or {}).get("edges") or []
        for edge in edges:
            size = max(0, int(edge.get("size", 0) or 0))
            node = edge.get("node") or {}
            name = str(node.get("name", "")).strip()
            if not name or size <= 0:
                continue
            totals[name] = totals.get(name, 0) + size
            if name not in colors:
                color = str(node.get("color") or "#8B949E")
                colors[name] = color if color.startswith("#") and len(color) in (4, 7) else "#8B949E"
    grand = sum(totals.values())
    if grand <= 0:
        return (("Python", 40.0, "#3572A5"), ("C", 35.0, "#555555"), ("Shell", 25.0, "#89E051"))
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return tuple((name, round((size / grand) * 100.0, 1), colors[name]) for name, size in ranked)


def parse_graphql_stats(payload: dict, login: str = GITHUB_USER) -> ProfileStats:
    user = (payload.get("data") or {}).get("user")
    if not isinstance(user, dict):
        raise ValueError("Resposta GraphQL sem objeto 'user'")
    created = str(user.get("createdAt") or "2018-01-01")
    since_year = int(created[:4]) if len(created) >= 4 and created[:4].isdigit() else 2018
    followers = max(0, int(((user.get("followers") or {}).get("totalCount")) or 0))

    contrib = user.get("contributionsCollection") or {}
    cal = contrib.get("contributionCalendar") or {}
    total_contrib = max(0, int(cal.get("totalContributions") or 0))
    monthly = aggregate_monthly(cal.get("weeks") or [])

    repos = user.get("repositories") or {}
    nodes = repos.get("nodes") or []
    public_repos = max(0, int(repos.get("totalCount") or len(nodes)))
    total_stars = sum(max(0, int(n.get("stargazerCount") or 0)) for n in nodes)
    languages = aggregate_languages(nodes)

    return ProfileStats(
        login=login,
        since_year=since_year,
        public_repos=public_repos,
        total_stars=total_stars,
        followers=followers,
        total_contributions=total_contrib,
        languages=languages,
        monthly_counts=monthly,
    )


def fetch_github_stats(login: str, token: str) -> ProfileStats:
    """Consulta estatísticas reais via GitHub GraphQL API (HTTPS fixo, TLS verificado, timeout)."""
    body = json.dumps({"query": GRAPHQL_QUERY, "variables": {"login": login}}).encode("utf-8")
    conn = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected (Python 3.11+ with ssl.create_default_context() verifying TLS and hostname)
        GITHUB_API_HOST,
        timeout=HTTP_TIMEOUT_S,
        context=ssl.create_default_context(),
    )
    try:
        conn.request(
            "POST",
            GRAPHQL_PATH,
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "mop4r-profile-generator/1.0",
            },
        )
        resp = conn.getresponse()
        if resp.status != 200:
            raise ValueError(f"GitHub GraphQL retornou HTTP {resp.status}")
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
    finally:
        conn.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Resposta GraphQL excedeu o limite esperado")
    parsed = json.loads(raw.decode("utf-8"))
    if parsed.get("errors"):
        raise ValueError(f"GraphQL retornou erro: {parsed['errors'][0].get('message', 'desconhecido')}")
    return parse_graphql_stats(parsed, login=login)


def render_hero_svg(theme_name: str, stats: ProfileStats) -> str:
    t = THEMES[theme_name]
    g_start = "#0B0F19" if theme_name == "dark" else "#F8FAFD"
    g_end = "#161B2E" if theme_name == "dark" else "#EDF2FA"
    word_a = "#F4A481" if theme_name == "dark" else "#C25934"
    word_b = "#C9B8FF" if theme_name == "dark" else "#5D46E2"
    word_c = "#7FB2FF" if theme_name == "dark" else "#0969DA"
    glow_op = "0.24" if theme_name == "dark" else "0.14"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 280" width="1200" height="280" role="img" aria-labelledby="ht hd">
  <title id="ht">{esc(stats.login)} — Embedded Linux, Hardware &amp; AI Tooling</title>
  <desc id="hd">Custom profile header for {esc(stats.login)} highlighting embedded Linux ports, hardware hacking and local AI agent tooling.</desc>
  <defs>
    <linearGradient id="hbg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{g_start}"/>
      <stop offset="100%" stop-color="{g_end}"/>
    </linearGradient>
    <radialGradient id="hglow1" cx="16%" cy="50%" r="42%">
      <stop offset="0%" stop-color="{t['claude']}" stop-opacity="{glow_op}"/>
      <stop offset="100%" stop-color="{t['claude']}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="hglow2" cx="85%" cy="22%" r="46%">
      <stop offset="0%" stop-color="{t['violet']}" stop-opacity="{glow_op}"/>
      <stop offset="100%" stop-color="{t['violet']}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="hword" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{word_a}"/>
      <stop offset="52%" stop-color="{word_b}"/>
      <stop offset="100%" stop-color="{word_c}"/>
    </linearGradient>
    <pattern id="hdots" width="24" height="24" patternUnits="userSpaceOnUse">
      <circle cx="2" cy="2" r="1.1" fill="{t['dot']}" opacity="{t['dot_op']}"/>
    </pattern>
  </defs>

  <rect width="1200" height="280" rx="20" fill="url(#hbg)" stroke="{t['border']}" stroke-width="1.5"/>
  <rect width="1200" height="280" rx="20" fill="url(#hdots)"/>
  <rect width="1200" height="280" rx="20" fill="url(#hglow1)"/>
  <rect width="1200" height="280" rx="20" fill="url(#hglow2)"/>

  <!-- Custom PCB / SoC + AI Relay artwork (visible at t=0) -->
  <g transform="translate(56, 36)">
    <!-- Circuit traces -->
    <g fill="none" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M22 44 H62 L76 58" stroke="{t['claude']}" opacity="0.85"/>
      <path d="M12 104 H58" stroke="{t['violet']}" opacity="0.85"/>
      <path d="M22 164 H62 L76 150" stroke="{t['green']}" opacity="0.85"/>
      <path d="M196 58 L210 44 H250" stroke="{t['cyan']}" opacity="0.85"/>
      <path d="M214 104 H260" stroke="{t['violet']}" opacity="0.85"/>
      <path d="M196 150 L210 164 H250" stroke="{t['claude']}" opacity="0.85"/>
      <path d="M136 10 V36" stroke="{t['green']}" opacity="0.8"/>
      <path d="M136 172 V198" stroke="{t['cyan']}" opacity="0.8"/>
    </g>
    <!-- Circuit pads -->
    <g>
      <circle cx="22" cy="44" r="4.5" fill="{t['claude']}"/>
      <circle cx="12" cy="104" r="4.5" fill="{t['violet']}"/>
      <circle cx="22" cy="164" r="4.5" fill="{t['green']}"/>
      <circle cx="250" cy="44" r="4.5" fill="{t['cyan']}"/>
      <circle cx="260" cy="104" r="4.5" fill="{t['violet']}"/>
      <circle cx="250" cy="164" r="4.5" fill="{t['claude']}"/>
      <circle cx="136" cy="10" r="4" fill="{t['green']}"/>
      <circle cx="136" cy="198" r="4" fill="{t['cyan']}"/>
    </g>
    <!-- SoC Package -->
    <rect x="58" y="36" width="156" height="136" rx="18" fill="{t['panel']}" stroke="{t['border']}" stroke-width="2"/>
    <rect x="74" y="52" width="124" height="104" rx="11" fill="{t['panel2']}" stroke="{t['violet']}" stroke-opacity="0.45" stroke-width="1.5"/>
    <!-- Oscilloscope waveform inside die (always visible, gentle pulse) -->
    <path d="M88 112 L104 112 L113 84 L126 130 L139 74 L152 122 L162 102 L184 102"
          fill="none" stroke="{t['green']}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
      <animate attributeName="opacity" values="1;0.65;1" dur="3.6s" repeatCount="indefinite"/>
    </path>
    <text x="136" y="144" text-anchor="middle" font-family="{FONT_MONO}" font-size="11" font-weight="700" fill="{t['muted']}">SOC · AI · LINUX</text>
    <!-- Status LED -->
    <circle cx="182" cy="68" r="4" fill="{t['green']}">
      <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
    </circle>
  </g>

  <!-- Right Typography -->
  <g font-family="{FONT_SANS}">
    <text x="364" y="110" font-size="68" font-weight="800" letter-spacing="-2.2" fill="url(#hword)">{esc(stats.login)}</text>
    <text x="366" y="150" font-size="22" font-weight="600" fill="{t['text']}">Embedded Linux ports, hardware reverse engineering &amp; local AI tooling.</text>
    <text x="366" y="182" font-size="16" fill="{t['muted']}">Porting Debian/Armbian to overlooked ARM boards and building zero-dependency CLI workflows.</text>

    <!-- Focus pills -->
    <g font-size="13.5" font-weight="600">
      <rect x="366" y="206" width="152" height="34" rx="17" fill="{t['pill_bg']}" stroke="{t['green']}" stroke-opacity="0.65"/>
      <circle cx="386" cy="223" r="4.5" fill="{t['green']}"/>
      <text x="399" y="228" fill="{t['text']}">Embedded Linux</text>

      <rect x="530" y="206" width="166" height="34" rx="17" fill="{t['pill_bg']}" stroke="{t['violet']}" stroke-opacity="0.65"/>
      <circle cx="550" cy="223" r="4.5" fill="{t['violet']}"/>
      <text x="563" y="228" fill="{t['text']}">Multi-AI Tooling</text>

      <rect x="708" y="206" width="174" height="34" rx="17" fill="{t['pill_bg']}" stroke="{t['claude']}" stroke-opacity="0.65"/>
      <circle cx="728" cy="223" r="4.5" fill="{t['claude']}"/>
      <text x="741" y="228" fill="{t['text']}">Python · C · Shell</text>

      <rect x="894" y="206" width="156" height="34" rx="17" fill="{t['pill_bg']}" stroke="{t['cyan']}" stroke-opacity="0.65"/>
      <circle cx="914" cy="223" r="4.5" fill="{t['cyan']}"/>
      <text x="927" y="228" fill="{t['text']}">GitHub since {stats.since_year}</text>
    </g>
  </g>
</svg>
"""


def build_sparkline_svg(monthly: tuple[tuple[str, int], ...], t: dict[str, str], x0: int, y0: int, w: int, h: int) -> str:
    """Constrói curva de área + pontos + legendas de mês para atividade real dos últimos 12 meses."""
    data = list(monthly) if monthly else [("Jan", 0), ("Dec", 0)]
    if len(data) == 1:
        data = [data[0], data[0]]
    max_val = max(1, max(v for _, v in data))
    step_x = w / max(1, len(data) - 1)
    pts: list[tuple[float, float, str, int]] = []
    for idx, (label, val) in enumerate(data):
        px = x0 + idx * step_x
        py = y0 + h - ((val / max_val) * (h - 16)) - 6
        pts.append((px, py, label, val))

    line_d = " ".join(f"{'M' if i == 0 else 'L'}{px:.1f},{py:.1f}" for i, (px, py, _, _) in enumerate(pts))
    area_d = f"{line_d} L{pts[-1][0]:.1f},{y0 + h:.1f} L{pts[0][0]:.1f},{y0 + h:.1f} Z"

    parts: list[str] = [
        f'<line x1="{x0}" y1="{y0 + h}" x2="{x0 + w}" y2="{y0 + h}" stroke="{t["grid"]}" stroke-width="1"/>',
        f'<line x1="{x0}" y1="{y0 + h / 2:.1f}" x2="{x0 + w}" y2="{y0 + h / 2:.1f}" stroke="{t["grid"]}" stroke-dasharray="3 4" stroke-width="1"/>',
        f'<path d="{area_d}" fill="url(#sparkfill)"/>',
        f'<path d="{line_d}" fill="none" stroke="{t["violet"]}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>',
    ]
    peak_idx = max(range(len(pts)), key=lambda i: pts[i][3])
    for i, (px, py, label, val) in enumerate(pts):
        is_peak = i == peak_idx and val > 0
        r = "4.5" if is_peak else "2.6"
        fill = t["green"] if is_peak else t["violet"]
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{fill}"/>')
        if is_peak:
            anchor = "end" if i == len(pts) - 1 else ("start" if i == 0 else "middle")
            tx = px - 2 if i == len(pts) - 1 else (px + 2 if i == 0 else px)
            parts.append(
                f'<text x="{tx:.1f}" y="{max(y0 + 11, py - 11):.1f}" text-anchor="{anchor}" '
                f'font-family="{FONT_MONO}" font-size="11.5" font-weight="700" fill="{t["green"]}">{val:,}</text>'
            )
        if i % 2 == 0 or i == len(pts) - 1:
            parts.append(
                f'<text x="{px:.1f}" y="{y0 + h + 16}" text-anchor="middle" '
                f'font-family="{FONT_MONO}" font-size="10.5" fill="{t["dim"]}">{esc(label)}</text>'
            )
    return "\n    ".join(parts)


def render_terminal_svg(theme_name: str, stats: ProfileStats, now: datetime) -> str:
    t = THEMES[theme_name]
    years = max(1, now.year - stats.since_year)

    # Stacked language bar (width = 492)
    bar_x, bar_y, bar_w, bar_h = 656, 116, 492, 13
    lang_segs: list[str] = []
    lang_legend: list[str] = []
    cur_x = float(bar_x)
    total_pct = sum(p for _, p, _ in stats.languages) or 100.0
    for idx, (name, pct, color) in enumerate(stats.languages):
        seg_w = (pct / total_pct) * bar_w
        if idx == len(stats.languages) - 1:
            seg_w = max(0.0, (bar_x + bar_w) - cur_x)
        if seg_w > 0.5:
            lang_segs.append(
                f'<rect x="{cur_x:.1f}" y="{bar_y}" width="{seg_w:.1f}" height="{bar_h}" fill="{esc(color)}"/>'
            )
            cur_x += seg_w
        lx = bar_x + (idx % 3) * 168
        ly = 152 + (idx // 3) * 21
        lang_legend.append(
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="4.5" fill="{esc(color)}"/>'
            f'<text x="{lx + 15}" y="{ly}" font-family="{FONT_MONO}" font-size="12" fill="{t["text"]}">'
            f'{esc(name)} <tspan fill="{t["muted"]}">{pct:.1f}%</tspan></text>'
        )

    spark = build_sparkline_svg(stats.monthly_counts, t, x0=656, y0=228, w=492, h=114)
    updated_str = now.strftime("%Y-%m-%d")

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 390" width="1200" height="390" role="img" aria-labelledby="tt td">
  <title id="tt">{esc(stats.login)} — System Specs &amp; Live GitHub Telemetry</title>
  <desc id="td">Terminal style developer summary and live contribution graphs for {esc(stats.login)}.</desc>
  <defs>
    <clipPath id="langclip">
      <rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="6"/>
    </clipPath>
    <linearGradient id="sparkfill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{t['violet']}" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="{t['violet']}" stop-opacity="0.02"/>
    </linearGradient>
  </defs>

  <!-- Outer window -->
  <rect width="1200" height="390" rx="16" fill="{t['panel']}" stroke="{t['border']}" stroke-width="1.5"/>
  <!-- Titlebar -->
  <path d="M0 16 a16 16 0 0 1 16 -16 h1168 a16 16 0 0 1 16 16 v24 h-1200 z" fill="{t['panel2']}"/>
  <line x1="0" y1="40" x2="1200" y2="40" stroke="{t['border']}" stroke-width="1"/>
  <circle cx="24" cy="20" r="6" fill="#FF5F56"/>
  <circle cx="44" cy="20" r="6" fill="#FFBD2E"/>
  <circle cx="64" cy="20" r="6" fill="#27C93F"/>
  <text x="92" y="24" font-family="{FONT_MONO}" font-size="13" fill="{t['muted']}">{esc(stats.login)}@bench — neofetch --github</text>
  <text x="1176" y="24" text-anchor="end" font-family="{FONT_MONO}" font-size="11.5" fill="{t['dim']}">updated {esc(updated_str)}</text>

  <!-- Vertical split -->
  <line x1="620" y1="58" x2="620" y2="368" stroke="{t['border']}" stroke-width="1"/>

  <!-- Left panel: Neofetch specs -->
  <g font-family="{FONT_MONO}" font-size="13.5">
    <text x="32" y="76" font-weight="700" fill="{t['green']}">{esc(stats.login)}<tspan fill="{t['muted']}">@</tspan><tspan fill="{t['cyan']}">github</tspan></text>
    <text x="32" y="94" fill="{t['border']}">──────────────────────────────────────────────</text>

    <text x="32" y="122" fill="{t['claude']}" font-weight="700">OS</text>
    <text x="150" y="122" fill="{t['text']}">Windows 11 · WSL2 · Debian Trixie · Armbian</text>

    <text x="32" y="148" fill="{t['claude']}" font-weight="700">Boards</text>
    <text x="150" y="148" fill="{t['text']}">Rockchip RK3228A · Allwinner A10 · MIPS</text>

    <text x="32" y="174" fill="{t['claude']}" font-weight="700">Languages</text>
    <text x="150" y="174" fill="{t['text']}">Python · C · Shell · PowerShell · C# · SQL</text>

    <text x="32" y="200" fill="{t['claude']}" font-weight="700">AI Agents</text>
    <text x="150" y="200" fill="{t['text']}">Claude Code · Gemini (Antigravity) · Grok CLI</text>

    <text x="32" y="226" fill="{t['claude']}" font-weight="700">Toolbox</text>
    <text x="150" y="226" fill="{t['text']}">U-Boot · Device Tree · SQLite · Docker · Git</text>

    <text x="32" y="252" fill="{t['claude']}" font-weight="700">Uptime</text>
    <text x="150" y="252" fill="{t['text']}">{years}+ years building on GitHub (since {stats.since_year})</text>

    <!-- Metric tiles -->
    <g transform="translate(32, 278)">
      <rect x="0" y="0" width="132" height="78" rx="10" fill="{t['panel2']}" stroke="{t['border']}"/>
      <text x="16" y="34" font-family="{FONT_SANS}" font-size="24" font-weight="800" fill="{t['violet']}">{stats.total_contributions:,}</text>
      <text x="16" y="58" font-size="11.5" fill="{t['muted']}">contribs (1y)</text>

      <rect x="144" y="0" width="132" height="78" rx="10" fill="{t['panel2']}" stroke="{t['border']}"/>
      <text x="160" y="34" font-family="{FONT_SANS}" font-size="24" font-weight="800" fill="{t['green']}">{stats.public_repos}</text>
      <text x="160" y="58" font-size="11.5" fill="{t['muted']}">public repos</text>

      <rect x="288" y="0" width="132" height="78" rx="10" fill="{t['panel2']}" stroke="{t['border']}"/>
      <text x="304" y="34" font-family="{FONT_SANS}" font-size="24" font-weight="800" fill="{t['amber']}">{stats.total_stars}</text>
      <text x="304" y="58" font-size="11.5" fill="{t['muted']}">stars</text>

      <rect x="432" y="0" width="132" height="78" rx="10" fill="{t['panel2']}" stroke="{t['border']}"/>
      <text x="448" y="34" font-family="{FONT_SANS}" font-size="24" font-weight="800" fill="{t['cyan']}">{stats.followers}</text>
      <text x="448" y="58" font-size="11.5" fill="{t['muted']}">followers</text>
    </g>
  </g>

  <!-- Right panel: Real Language Bar + 12-Month Contribution Curve -->
  <g>
    <text x="656" y="76" font-family="{FONT_SANS}" font-size="15" font-weight="700" fill="{t['text']}">Public Repository Languages</text>
    <text x="656" y="96" font-family="{FONT_MONO}" font-size="11.5" fill="{t['muted']}">Weighted by bytes across non-fork public repositories</text>

    <rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="6" fill="{t['grid']}"/>
    <g clip-path="url(#langclip)">
      {''.join(lang_segs)}
    </g>
    {''.join(lang_legend)}

    <text x="656" y="214" font-family="{FONT_SANS}" font-size="15" font-weight="700" fill="{t['text']}">12-Month Contribution Activity</text>
    <text x="1148" y="214" text-anchor="end" font-family="{FONT_MONO}" font-size="11.5" fill="{t['muted']}">monthly commits &amp; activity</text>
    {spark}
  </g>
</svg>
"""


def render_project_card_svg(
    theme_name: str,
    title: str,
    subtitle: str,
    detail: str,
    tags: tuple[str, ...],
    accent_key: str,
    icon_svg: str,
) -> str:
    t = THEMES[theme_name]
    accent = t[accent_key]
    pills: list[str] = []
    px = 28
    for tag in tags:
        tw = max(62, len(tag) * 7.8 + 22)
        pills.append(
            f'<rect x="{px:.0f}" y="146" width="{tw:.0f}" height="26" rx="13" fill="{t["pill_bg"]}" stroke="{t["border"]}"/>'
            f'<text x="{px + tw / 2:.1f}" y="163" text-anchor="middle" font-family="{FONT_MONO}" font-size="11.5" fill="{t["text"]}">{esc(tag)}</text>'
        )
        px += tw + 8

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 580 192" width="580" height="192" role="img" aria-labelledby="ct cd">
  <title id="ct">{esc(title)}</title>
  <desc id="cd">{esc(subtitle)} — {esc(detail)}</desc>
  <rect width="580" height="192" rx="14" fill="{t['panel']}" stroke="{t['border']}" stroke-width="1.5"/>
  <rect x="0" y="0" width="580" height="4" rx="2" fill="{accent}"/>

  <!-- Custom emblem -->
  <g transform="translate(26, 26)">
    <rect width="46" height="46" rx="11" fill="{t['panel2']}" stroke="{accent}" stroke-opacity="0.5"/>
    {icon_svg}
  </g>

  <text x="88" y="48" font-family="{FONT_SANS}" font-size="21" font-weight="700" fill="{t['text']}">{esc(title)}</text>
  <text x="88" y="70" font-family="{FONT_MONO}" font-size="12.5" fill="{accent}">{esc(subtitle)}</text>
  <text x="28" y="106" font-family="{FONT_SANS}" font-size="14.5" fill="{t['muted']}">{esc(detail)}</text>
  <text x="28" y="128" font-family="{FONT_SANS}" font-size="13.5" fill="{t['dim']}">Click to open repository</text>

  {''.join(pills)}
</svg>
"""


def generate_all(output_dir: Path, stats: ProfileStats, now: datetime) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for theme_name in ("dark", "light"):
        t = THEMES[theme_name]
        files: dict[str, str] = {
            f"hero-{theme_name}.svg": render_hero_svg(theme_name, stats),
            f"terminal-{theme_name}.svg": render_terminal_svg(theme_name, stats, now),
            f"card-tagteam-{theme_name}.svg": render_project_card_svg(
                theme_name=theme_name,
                title="TagTeam",
                subtitle="Claude Code ⇄ Gemini (Antigravity) ⇄ Grok CLI",
                detail="Bidirectional native session sync + automatic 95% usage-limit handoff.",
                tags=("Python", "Zero Deps", "MIT", "Site"),
                accent_key="violet",
                icon_svg=(
                    f'<circle cx="23" cy="14" r="5" fill="{t["claude"]}"/>'
                    f'<circle cx="33" cy="31" r="5" fill="{t["violet"]}"/>'
                    f'<circle cx="13" cy="31" r="5" fill="{t["text"]}"/>'
                    f'<path d="M23 14 L33 31 L13 31 Z" fill="none" stroke="{t["muted"]}" stroke-width="1.6"/>'
                ),
            ),
            f"card-tvbox-{theme_name}.svg": render_project_card_svg(
                theme_name=theme_name,
                title="tvbox-rk3228a-armbian",
                subtitle="Armbian · Rockchip RK3228A · R29_5G_LP3",
                detail="SD auto-installer to eMMC, 4K HDMI fix, DDR 660 MHz, Pi-hole + Unbound DoT.",
                tags=("Armbian", "RK3228A", "Pi-hole", "GPL-2.0"),
                accent_key="green",
                icon_svg=(
                    f'<rect x="13" y="13" width="20" height="20" rx="4" fill="none" stroke="{t["green"]}" stroke-width="2"/>'
                    f'<rect x="19" y="19" width="8" height="8" rx="1.5" fill="{t["green"]}"/>'
                    f'<path d="M18 9 V13 M28 9 V13 M18 33 V37 M28 33 V37 M9 18 H13 M9 28 H13 M33 18 H37 M33 28 H37" '
                    f'stroke="{t["muted"]}" stroke-width="1.8" stroke-linecap="round"/>'
                ),
            ),
            f"card-aquarius-{theme_name}.svg": render_project_card_svg(
                theme_name=theme_name,
                title="aquarius-gps-connect-linux",
                subtitle="Debian 13 · Allwinner A10 (sun4i) · MTC4553",
                detail="MicroSD dual-boot RetroArch handheld & XFCE tablet on a car GPS.",
                tags=("Debian 13", "Allwinner A10", "RetroArch", "U-Boot"),
                accent_key="claude",
                icon_svg=(
                    f'<rect x="9" y="14" width="28" height="18" rx="4" fill="none" stroke="{t["claude"]}" stroke-width="2"/>'
                    f'<path d="M16 20 V26 M13 23 H19" stroke="{t["text"]}" stroke-width="1.8" stroke-linecap="round"/>'
                    f'<circle cx="29" cy="21" r="1.8" fill="{t["claude"]}"/>'
                    f'<circle cx="32" cy="25" r="1.8" fill="{t["violet"]}"/>'
                ),
            ),
            f"card-rarseeker-{theme_name}.svg": render_project_card_svg(
                theme_name=theme_name,
                title="RarSeeker",
                subtitle="Python · SQLite · Local Search",
                detail="Fast local browser and filter tool for the archived RARBG SQLite database.",
                tags=("Python", "SQLite", "CLI"),
                accent_key="cyan",
                icon_svg=(
                    f'<circle cx="21" cy="21" r="8" fill="none" stroke="{t["cyan"]}" stroke-width="2.2"/>'
                    f'<path d="M27 27 L35 35" stroke="{t["cyan"]}" stroke-width="2.5" stroke-linecap="round"/>'
                ),
            ),
        }
        for filename, content in files.items():
            dest = output_dir / filename
            dest.write_text(content, encoding="utf-8", newline="\n")
            written.append(dest)
    return written


def default_stats() -> ProfileStats:
    return ProfileStats(
        login=GITHUB_USER,
        since_year=2018,
        public_repos=5,
        total_stars=2,
        followers=16,
        total_contributions=0,
        languages=(
            ("C", 61.2, "#555555"),
            ("Python", 19.3, "#3572A5"),
            ("Shell", 16.3, "#89E051"),
            ("C#", 1.1, "#178600"),
            ("JavaScript", 0.7, "#F1E05A"),
        ),
        monthly_counts=(("Dec", 0), ("Nov", 0)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera os SVGs do perfil GitHub mop4r.")
    parser.add_argument("--user", default=GITHUB_USER, help="Usuário GitHub (padrão: mop4r)")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "assets"),
        help="Pasta de saída para os SVGs",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Não consulta a API do GitHub; usa valores padrão",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if args.offline or not token:
        stats = default_stats()
    else:
        try:
            stats = fetch_github_stats(args.user, token)
        except (http.client.HTTPException, ValueError, OSError) as exc:
            print(f"Erro ao consultar GraphQL do GitHub: {exc}")
            return 1

    written = generate_all(Path(args.out), stats, datetime.now(timezone.utc))
    print(f"Gerados {len(written)} SVGs em {args.out} (contribs={stats.total_contributions}, repos={stats.public_repos})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
