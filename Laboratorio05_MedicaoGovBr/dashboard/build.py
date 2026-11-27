#!/usr/bin/env python3
"""Builds dashboard/index.html, a single static page (no server, no CDN), from the files of the study.

    python dashboard/build.py            # needs only pandas

Reads (never edits):
  analysis/output/todas/*.csv   tables of the main analysis (all valid runs)
  analysis/output/impact.csv    impact estimate (hours per month)
  data/usage.json, data/urls.json, data/run-metadata.json, data/failed-runs.csv
  docs/*.md                     text of the method, threats, impact and conclusions

Numbers on the page come from these files, not from the text of this script. The mobile-share
slider recomputes the impact in the browser; build.py checks that the formula reproduces
analysis/output/impact_sensitivity.csv before writing the page.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "index.html"
TEMPLATE = ROOT / "dashboard" / "template.html"
TABLES = ROOT / "analysis" / "output" / "todas"


# ---------------------------------------------------------------- markdown -> html (small subset)
def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        if url.startswith("http"):
            return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'
        return f'<span class="ref">{label}</span>'  # links to files of the repo: keep the text only

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)


def md_to_html(md: str, shift: int = 1) -> str:
    lines = md.replace("\r", "").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1 : j])) + "</pre>")
            i = j + 1
        elif line.startswith("#"):
            level = min(6, len(line) - len(line.lstrip("#")) + shift)
            out.append(f"<h{level}>{inline(line.lstrip('#').strip())}</h{level}>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[2:]]
            t = "<div class='tw'><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
            for r in body:
                t += "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
            out.append(t + "</tbody></table></div>")
        elif re.match(r"^(- |\d+\. )", line):
            ordered = bool(re.match(r"^\d+\. ", line))
            items = []
            while i < len(lines) and re.match(r"^(- |\d+\. )", lines[i]):
                item = re.sub(r"^(- |\d+\. )", "", lines[i])
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
                    item += " " + lines[i].strip()
                    i += 1
                items.append(item)
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
        else:
            para = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||```|- |\d+\. )", lines[i]):
                para.append(lines[i])
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(out)


def section(md: str, prefix: str, stop_at_same_or_higher: bool = True) -> str:
    """Text from the heading that starts with `prefix` up to the next heading of the same or higher level."""
    lines = md.replace("\r", "").split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith(prefix))
    level = len(prefix) - len(prefix.lstrip("#"))
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(#+) ", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return "\n".join(lines[start:end])


def strip_title(md: str) -> str:
    lines = md.replace("\r", "").split("\n")
    return "\n".join(lines[1:]) if lines and lines[0].startswith("# ") else md


# ---------------------------------------------------------------- data
def rows(name: str, folder: Path = TABLES) -> list[dict]:
    return json.loads(pd.read_csv(folder / name).where(lambda d: d.notna(), None).to_json(orient="records"))


def main() -> None:
    urls = json.loads((ROOT / "data" / "urls.json").read_text(encoding="utf-8"))
    usage = json.loads((ROOT / "data" / "usage.json").read_text(encoding="utf-8"))
    meta = json.loads((ROOT / "data" / "run-metadata.json").read_text(encoding="utf-8"))
    full = pd.read_csv(ROOT / "data" / "processed" / "full.csv")
    failed = pd.read_csv(ROOT / "data" / "failed-runs.csv")
    executions = pd.read_csv(ROOT / "data" / "processed" / "full_executions.csv")
    sessions = [s for s in meta["sessions"] if s["phase"] == "full"]
    impact = pd.read_csv(ROOT / "analysis" / "output" / "impact.csv")
    sens = pd.read_csv(ROOT / "analysis" / "output" / "impact_sensitivity.csv")

    # the formula the page uses for the slider must reproduce impact_sensitivity.csv
    for _, r in sens[sens.service != "TOTAL"].iterrows():
        sub = impact[(impact.service == r.service) & (impact.reference == r.reference)].set_index("formFactor")
        desktop = float(sub.loc["desktop", "hours_median"]) if "desktop" in sub.index else 0.0
        calc = r.mobile_share * float(sub.loc["mobile", "hours_median"]) + (1 - r.mobile_share) * desktop
        assert abs(calc - r.hours_median) < 5e-5 * max(1, abs(r.hours_median)), (r.service, r.reference, r.mobile_share)

    proposta = (ROOT / "docs" / "proposta.md").read_text(encoding="utf-8")
    impacto = (ROOT / "docs" / "impacto.md").read_text(encoding="utf-8")
    categorias = (ROOT / "docs" / "categorias-pesquisa.md").read_text(encoding="utf-8")
    ameacas = (ROOT / "docs" / "ameacas-validade.md").read_text(encoding="utf-8")
    conclusoes = (ROOT / "docs" / "conclusoes.md").read_text(encoding="utf-8")
    urlchanges = (ROOT / "docs" / "url-changes.md").read_text(encoding="utf-8")

    data = {
        "builtAt": datetime.now().strftime("%d/%m/%Y"),
        "services": [{"id": s["id"], "name": s["name"], "url": s["url"]} for s in urls["services"]],
        "meta": {
            "validRuns": int(len(full)),
            "attempts": int(len(executions)),
            "failedAttempts": int(len(failed)),
            "lighthouse": sessions[0]["tools"]["lighthouse"],
            "chrome": sessions[0]["tools"]["chrome"].replace("Chrome/", ""),
            "seed": sessions[0]["seed"],
            "sessions": [{"label": s.get("sessionLabel") or s["phase"], "start": s["startedAt"], "end": s["finishedAt"]} for s in sessions],
            "machine": f'{sessions[0]["machine"]["cpu"]["model"]}, {sessions[0]["machine"]["ramGB"]} GB, {sessions[0]["machine"]["os"]["version"]}',
        },
        "desc": rows("descriptives.csv"),
        "kw": rows("rq1_kruskal.csv"),
        "rq2": rows("rq2_correlation.csv"),
        "medians": rows("service_medians.csv"),
        "rq3": rows("rq3_wilcoxon.csv"),
        "rq3svc": rows("rq3_per_service.csv"),
        "impact": json.loads(impact.where(impact.notna(), None).to_json(orient="records")),
        "usage": usage["services"],
        "docs": {
            "criterios": md_to_html(section(proposta, "### 1.3"), 3),
            "metodo": md_to_html(section(proposta, "## 2.") + "\n" + section(proposta, "## 3.") + "\n" + section(proposta, "## 4."), 2),
            "coleta": md_to_html(section(proposta, "## 6."), 2),
            "categorias": md_to_html(section(categorias, "## 1.") + "\n" + section(categorias, "## 3.") + "\n" + section(categorias, "## 4."), 2),
            "urls": md_to_html(section(urlchanges, "## 1.") + "\n" + section(urlchanges, "## 2."), 2),
            "impacto": md_to_html(section(impacto, "## 4.") + "\n" + section(impacto, "## 5.") + "\n" + section(impacto, "## 6."), 2),
            "ameacas": md_to_html(strip_title(ameacas), 1),
            "conclusoes": md_to_html(strip_title(conclusoes), 1),
        },
    }
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    OUT.write_text(TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload), encoding="utf-8", newline="\n")
    print(f"Written {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
