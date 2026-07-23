"""The shareable deep-dive: a single self-contained HTML dashboard.

resolve.py calls write_web_report() to produce data/out/report.html — one file,
no external requests, that you can hand to anyone for a richer look than the
plain-text report: the ranking with confidence bars, how the methods and
stakeholder groups (dis)agree, contested items, and coverage. The Cameo model
still carries only the rank; this is where the justification lives.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .profiles import p1_counts, p5_bootstrap


def _esc(s) -> str:
    return html.escape(str(s))


def write_web_report(df: pd.DataFrame, long_df: pd.DataFrame, results: dict,
                     out_path: Path) -> Path:
    item_ids = list(df["id"])
    names = dict(zip(df["id"], df["name"]))
    cats = dict(zip(df["id"], df.get("category", pd.Series("", index=df.index))))
    meta = results["meta"]
    p1 = results["p1_scores"]
    p1_rank = p1_counts.ranks(p1)
    p3_rank = results["p3_equalized"].rank(ascending=False, method="min").astype(int)
    p2_rank = results["p2"]["rank_strict"]
    boot = results["boot"]["p1"]

    answered = long_df[~long_df["skipped"]]
    exposures = answered.groupby("item_id").size().reindex(item_ids).fillna(0).astype(int)
    respondents = (answered.groupby("item_id")["email"].nunique()
                   .reindex(item_ids).fillna(0).astype(int))

    # Build the ranked rows.
    rows = []
    for item in p1_rank.sort_values().index:
        lo, hi = int(boot.loc[item, "rank_lo"]), int(boot.loc[item, "rank_hi"])
        score = float(p1.get(item)) if pd.notna(p1.get(item)) else 0.0
        rows.append({
            "id": item, "name": names.get(item, item), "category": cats.get(item, ""),
            "rank": int(p1_rank[item]), "score": round(score, 1),
            "rank_lo": lo, "rank_hi": hi,
            "p_top": round(float(boot.loc[item, "p_top_n"]), 2),
            "p3_rank": int(p3_rank[item]), "p2_rank": int(p2_rank[item]),
            "n": int(respondents.get(item, 0)),
            "contested": abs(int(p1_rank[item]) - int(p3_rank[item])) > 10,
        })

    # Group lenses.
    def group_block(dim_key, dim_label):
        ranks = results[dim_key]
        if ranks.shape[1] < 2:
            return {"label": dim_label, "groups": [], "w": None, "pairs": [], "contested": []}
        w = p5_bootstrap.kendalls_w(ranks)
        agree = p5_bootstrap.pairwise_agreement(ranks, meta["top_n"])
        spread = p5_bootstrap.contested_items(ranks).sort_values(ascending=False)
        contested = [{"id": i, "name": names.get(i, i), "spread": int(spread[i])}
                     for i in spread.head(6).index if spread[i] > 0]
        return {
            "label": dim_label, "groups": list(ranks.columns),
            "w": round(w, 2) if w is not None else None,
            "pairs": [{"a": r["group_a"], "b": r["group_b"],
                       "tau": round(float(r["kendall_tau"]), 2),
                       "overlap": round(float(r[f"top{meta['top_n']}_overlap"]), 2)}
                      for _, r in agree.iterrows()],
            "contested": contested,
        }

    lenses = [group_block("role_ranks", "Role"), group_block("org_ranks", "Organization")]

    med_ms = answered.drop_duplicates(["email", "session_id", "set_index"]) \
        .groupby("email")["response_ms"].median()
    quality = {"total": int(long_df["email"].nunique()),
               "flagged": int((med_ms < 2000).sum())}

    payload = {
        "meta": {k: (v if not isinstance(v, (np.integer, np.floating)) else float(v))
                 for k, v in meta.items()},
        "rows": rows, "lenses": lenses, "quality": quality,
        "exposure": {"min": int(exposures.min()) if len(exposures) else 0,
                     "median": int(exposures.median()) if len(exposures) else 0,
                     "max": int(exposures.max()) if len(exposures) else 0,
                     "under100": int((exposures < 100).sum())},
        "n_items": len(item_ids),
        "has_p4": results["p4"] is not None,
    }
    injected = json.dumps(payload).replace("</", "<\\/")  # cannot break out of <script>
    out_path.write_text(_HTML.replace("__DATA__", injected), encoding="utf-8")
    return out_path


_HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Use Case Prioritization — Results</title>
<style>
  :root{--ink:#1a2333;--muted:#5b6575;--line:#e2e8f2;--bg:#f6f8fc;--card:#fff;
    --accent:#1f6feb;--bar:#4c7ef3;--barlo:#c9d8f7;--good:#1a7f37;--warn:#b35900;--danger:#c93c37;}
  @media(prefers-color-scheme:dark){:root{--ink:#e8edf6;--muted:#9aa6b8;--line:#2a3446;
    --bg:#0f1420;--card:#161d2b;--bar:#5b8bf5;--barlo:#2a3a5c;}}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:"Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;background:var(--bg);
    color:var(--ink);line-height:1.5;padding:24px 16px 80px}
  .wrap{max-width:1080px;margin:0 auto}
  h1{font-size:24px;margin-bottom:4px}
  h2{font-size:17px;margin:28px 0 12px;font-weight:600}
  .sub{color:var(--muted);font-size:13.5px;margin-bottom:6px}
  .stats{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;flex:1;min-width:120px}
  .stat .n{font-size:26px;font-weight:700}
  .stat .l{font-size:12px;color:var(--muted)}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-top:14px;overflow-x:auto}
  table{border-collapse:collapse;width:100%;font-size:13.5px}
  th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  th{color:var(--muted);font-weight:600;font-size:12px;position:sticky;top:0;background:var(--card)}
  td.name{white-space:normal;min-width:220px}
  .chip{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:1px 8px}
  .bar{position:relative;height:16px;background:var(--barlo);border-radius:4px;min-width:60px}
  .bar>span{position:absolute;left:0;top:0;bottom:0;background:var(--bar);border-radius:4px}
  .rankcell{font-weight:700;font-variant-numeric:tabular-nums}
  .rng{color:var(--muted);font-variant-numeric:tabular-nums}
  .flag{color:var(--warn);font-weight:600}
  .pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;background:var(--barlo);color:var(--ink)}
  .agree td:first-child{font-weight:600}
  .note{color:var(--muted);font-size:12.5px;margin-top:6px}
  .foot{color:var(--muted);font-size:12px;margin-top:30px;border-top:1px solid var(--line);padding-top:12px}
  input[type=search]{padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);
    color:var(--ink);font-size:13px;width:240px;max-width:60vw}
</style></head><body><div class="wrap">
<h1>Use Case Prioritization — Results</h1>
<div class="sub" id="sub"></div>
<div class="stats" id="stats"></div>

<h2>Overall ranking</h2>
<div class="sub">Bars show the P1 score (0–100). The 90% range is how much the rank could move under
respondent resampling — a narrow range is a settled priority; a wide one is a statistical tie.
<span class="flag">Contested</span> = the counting and model methods disagree by &gt;10 places (discuss, don't average).</div>
<div style="margin:8px 0"><input type="search" id="filter" placeholder="filter use cases…"></div>
<div class="card"><table id="rank"><thead><tr>
  <th>Rank</th><th>Use case</th><th>Score</th><th>90% range</th><th>P(top&nbsp;N)</th>
  <th>Model rank</th><th>Majority rank</th><th>Resp.</th></tr></thead><tbody id="rankBody"></tbody></table></div>

<h2>How the stakeholder groups compare</h2>
<div id="lenses"></div>

<h2>Response quality &amp; coverage</h2>
<div class="card" id="quality"></div>

<div class="foot" id="foot"></div>
</div>
<script id="rawdata" type="application/json">__DATA__</script>
<script>
var D=JSON.parse(document.getElementById("rawdata").textContent);
var m=D.meta;
document.getElementById("sub").textContent=
  "Resolved "+m.resolved_at+" · catalog "+m.catalog_hash+" · lineage="+m.lineage;
function esc(s){var d=document.createElement("div");d.textContent=s==null?"":s;return d.innerHTML;}
var stats=[["respondents",m.n_respondents],["screens answered",m.n_screens],
  ["pairwise comparisons",m.n_pairs],["use cases",D.n_items]];
document.getElementById("stats").innerHTML=stats.map(function(s){
  return '<div class="stat"><div class="n">'+s[1]+'</div><div class="l">'+s[0]+'</div></div>';}).join("");

var maxScore=Math.max.apply(null,D.rows.map(function(r){return r.score;}))||100;
function renderRows(q){
  var body=document.getElementById("rankBody");body.innerHTML="";
  D.rows.filter(function(r){return !q||(r.name+" "+r.id+" "+r.category).toLowerCase().indexOf(q)>=0;})
   .forEach(function(r){
    var tr=document.createElement("tr");
    var w=Math.max(4,Math.round(100*r.score/maxScore));
    tr.innerHTML='<td class="rankcell">'+r.rank+'</td>'+
      '<td class="name">'+esc(r.name)+(r.category?' <span class="chip">'+esc(r.category)+'</span>':'')+
        (r.contested?' <span class="flag">contested</span>':'')+'</td>'+
      '<td><div class="bar"><span style="width:'+w+'%"></span></div></td>'+
      '<td class="rng">'+r.rank_lo+'–'+r.rank_hi+'</td>'+
      '<td class="rng">'+r.p_top.toFixed(2)+'</td>'+
      '<td class="rng">'+r.p3_rank+'</td><td class="rng">'+r.p2_rank+'</td>'+
      '<td class="rng">'+r.n+'</td>';
    body.appendChild(tr);
  });
}
renderRows("");
document.getElementById("filter").addEventListener("input",function(e){renderRows(e.target.value.toLowerCase());});

var lensHtml=D.lenses.map(function(L){
  if(!L.groups.length) return '<div class="card"><strong>'+L.label+'</strong><div class="note">Not enough groups yet — needs ≥2 groups with ≥2 respondents each.</div></div>';
  var pairs=L.pairs.map(function(p){return '<tr><td>'+esc(p.a)+' vs '+esc(p.b)+'</td><td class="rng">τ '+
    (p.tau>=0?'+':'')+p.tau.toFixed(2)+'</td><td class="rng">top-N overlap '+Math.round(p.overlap*100)+'%</td></tr>';}).join("");
  var contested=L.contested.length? '<div class="note">Most contested between '+L.label.toLowerCase()+
    ' groups: '+L.contested.map(function(c){return esc(c.name)+' (spread '+c.spread+')';}).join(", ")+'</div>':'';
  return '<div class="card"><strong>'+L.label+'</strong> · '+L.groups.length+' groups · '+
    'concordance W='+(L.w==null?'—':L.w)+' <span class="note">(1 = identical priorities)</span>'+
    '<table class="agree" style="margin-top:8px">'+pairs+'</table>'+contested+'</div>';
}).join("");
document.getElementById("lenses").innerHTML=lensHtml;

var q=D.quality,ex=D.exposure;
document.getElementById("quality").innerHTML=
  '<div>'+q.flagged+' of '+q.total+' respondent(s) had a median under 2 s/screen (possibly rushed; data kept). '+
  'Identities are in the archive, not this shareable report.</div>'+
  '<div class="note" style="margin-top:8px">Exposures per use case: min '+ex.min+', median '+ex.median+
  ', max '+ex.max+'. '+(ex.under100?ex.under100+' item(s) under 100 exposures — expect wider ranges; keep collecting.':'')+
  ' Guideline: 500+ pooled exposures for tight estimates.</div>';

document.getElementById("foot").textContent=
  "Methods: best–worst (MaxDiff) · counting (P1) · Copeland (P2) · Bradley–Terry (P3) · respondent bootstrap (P5)"+
  (D.has_p4?" · Bayesian (P4)":"")+". Self-contained; safe to share. Raw data and methodology stay with the tool.";
</script></body></html>"""
