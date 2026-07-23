const pptxgen = require("pptxgenjs");
const ReactDOMServer = require("react-dom/server");
const React = require("react");
const { FaBalanceScale, FaClipboardCheck, FaChartBar, FaUserClock } = require("react-icons/fa");
const sharp = require("sharp");

const NAVY = "1E2761", ICE = "CADCFC", PALE = "F2F6FE", INK = "22283A",
      MUTED = "5A6478", BEST = "1A7F37", WORST = "B35900", WHITE = "FFFFFF";

async function iconPng(Comp, color) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
  const s = pres.addSlide();
  s.background = { color: WHITE };

  // ---------- Assertion title ----------
  s.addText("Many quick best/worst choices combine into one defensible, uncertainty-aware priority ranking", {
    x: 0.55, y: 0.28, w: 12.2, h: 0.85, margin: 0,
    fontFace: "Cambria", fontSize: 22, bold: true, color: NAVY, align: "left",
  });
  s.addText("Best–worst scaling (MaxDiff) — the established market-research method for prioritizing large item lists — applied to our use-case model", {
    x: 0.55, y: 1.08, w: 12.2, h: 0.32, margin: 0,
    fontFace: "Calibri", fontSize: 12.5, italic: true, color: MUTED,
  });

  // ---------- Four-stage flow ----------
  const PX = [0.55, 3.83, 7.11, 10.39], PW = 2.85, PY = 1.62, PH = 3.1;
  const heads = ["1 · ANSWER", "2 · IMPLY", "3 · CROSS-CHECK", "4 · RANK IN CAMEO"];
  const caps = [
    "Each screen: tap the MOST and LEAST important of 4 use cases. ~20 s each; stop anytime — every screen counts.",
    "One screen logically implies 5 head-to-head preferences — 5× the information of a single pairwise vote.",
    "All responses pool. Three independent methods must agree; conflicts are flagged for discussion, never averaged away.",
    "Ranks with 90% confidence intervals are written onto each use case in the model — decisions cite settled ranks, not noise.",
  ];
  for (let i = 0; i < 4; i++) {
    s.addShape("roundRect", { x: PX[i], y: PY, w: PW, h: PH, rectRadius: 0.09,
      fill: { color: PALE }, line: { color: ICE, width: 1 } });
    s.addText(heads[i], { x: PX[i] + 0.16, y: PY + 0.12, w: PW - 0.32, h: 0.3, margin: 0,
      fontFace: "Calibri", fontSize: 12.5, bold: true, color: NAVY, charSpacing: 2 });
    s.addText(caps[i], { x: PX[i] + 0.16, y: PY + 2.02, w: PW - 0.32, h: 1.0, margin: 0,
      fontFace: "Calibri", fontSize: 10.5, color: INK, valign: "top" });
    if (i < 3) s.addText("▶", { x: PX[i] + PW - 0.02, y: PY + 0.78, w: 0.5, h: 0.4,
      margin: 0, fontSize: 16, color: NAVY, align: "center" });
  }

  // Panel 1 visual: mini screen with 4 use-case rows
  const rows = [
    { t: "Replan during execution", tag: "MOST", fill: BEST },
    { t: "Track asset location", tag: "", fill: WHITE },
    { t: "Generate reports", tag: "", fill: WHITE },
    { t: "Manage spare parts", tag: "LEAST", fill: WORST },
  ];
  rows.forEach((r, j) => {
    const y = PY + 0.5 + j * 0.36;
    const on = r.fill !== WHITE;
    s.addShape("roundRect", { x: PX[0] + 0.16, y, w: PW - 0.32, h: 0.3, rectRadius: 0.045,
      fill: { color: on ? r.fill : WHITE }, line: { color: on ? r.fill : "C9D4E8", width: 1 } });
    s.addText(r.t, { x: PX[0] + 0.26, y, w: 1.85, h: 0.3, margin: 0,
      fontFace: "Calibri", fontSize: 9.5, color: on ? WHITE : INK, valign: "middle" });
    if (r.tag) s.addText(r.tag, { x: PX[0] + PW - 0.85, y, w: 0.62, h: 0.3, margin: 0,
      fontFace: "Calibri", fontSize: 8.5, bold: true, color: WHITE, align: "right", valign: "middle" });
  });

  // Panel 2 visual: the five implied pairs
  const pairs = ["Replan  ≻  Track", "Replan  ≻  Reports", "Replan  ≻  Spares",
                 "Track  ≻  Spares", "Reports  ≻  Spares"];
  pairs.forEach((p, j) => {
    s.addText(p, { x: PX[1] + 0.3, y: PY + 0.5 + j * 0.29, w: PW - 0.6, h: 0.27, margin: 0,
      fontFace: "Calibri", fontSize: 10.5, color: j === 0 ? NAVY : INK, bold: j === 0 });
  });

  // Panel 3 visual: three method chips
  const chips = ["Counting  ·  hand-checkable", "Majority vote  ·  Copeland",
                 "Choice model  ·  Bradley–Terry"];
  chips.forEach((c, j) => {
    const y = PY + 0.52 + j * 0.47;
    s.addShape("roundRect", { x: PX[2] + 0.16, y, w: PW - 0.32, h: 0.36, rectRadius: 0.18,
      fill: { color: NAVY }, line: { type: "none" } });
    s.addText(c, { x: PX[2] + 0.16, y, w: PW - 0.32, h: 0.36, margin: 0,
      fontFace: "Calibri", fontSize: 10.5, color: WHITE, align: "center", valign: "middle" });
  });

  // Panel 4 visual: ranked bars with CI whiskers
  const bars = [
    { name: "UC-005", w: 1.55, lo: -0.06, hi: 0.06 },
    { name: "UC-020", w: 1.30, lo: -0.10, hi: 0.14 },
    { name: "UC-033", w: 1.05, lo: -0.16, hi: 0.20 },
    { name: "UC-018", w: 0.78, lo: -0.20, hi: 0.26 },
  ];
  bars.forEach((b, j) => {
    const y = PY + 0.52 + j * 0.36;
    s.addText(String(j + 1), { x: PX[3] + 0.14, y, w: 0.22, h: 0.26, margin: 0,
      fontFace: "Calibri", fontSize: 10, bold: true, color: NAVY, valign: "middle" });
    s.addShape("roundRect", { x: PX[3] + 0.38, y: y + 0.03, w: b.w, h: 0.2, rectRadius: 0.03,
      fill: { color: j === 0 ? NAVY : "6E86C8" }, line: { type: "none" } });
    const cx = PX[3] + 0.38 + b.w;
    s.addShape("line", { x: cx + b.lo, y: y + 0.13, w: b.hi - b.lo, h: 0,
      line: { color: INK, width: 1.4 } });
    s.addShape("line", { x: cx + b.lo, y: y + 0.07, w: 0, h: 0.12, line: { color: INK, width: 1.4 } });
    s.addShape("line", { x: cx + b.hi, y: y + 0.07, w: 0, h: 0.12, line: { color: INK, width: 1.4 } });
  });
  s.addText("90% rank interval", { x: PX[3] + 0.38, y: PY + 1.95, w: PW - 0.6, h: 0.22, margin: 0,
    fontFace: "Calibri", fontSize: 8.5, italic: true, color: MUTED });

  // ---------- Trust band ----------
  s.addText("Why the result can be trusted", { x: 0.55, y: 5.02, w: 6.0, h: 0.3, margin: 0,
    fontFace: "Calibri", fontSize: 13, bold: true, color: NAVY });
  const trust = [
    { icon: await iconPng(FaBalanceScale, WHITE), h: "Balanced by design",
      t: "Every use case is shown equally often and paired evenly — no item gets an easier draw." },
    { icon: await iconPng(FaUserClock, WHITE), h: "Abort-proof & equal-voice",
      t: "Partial sessions are valid data, and each person counts once — 8 screens or 80." },
    { icon: await iconPng(FaClipboardCheck, WHITE), h: "Auditable end to end",
      t: "Raw answers are immutable; every published number is reproducible from them." },
    { icon: await iconPng(FaChartBar, WHITE), h: "Honest about certainty",
      t: "Rank intervals and P(top-10) separate settled priorities from statistical ties; role/org lenses expose disagreement." },
  ];
  const TX = [0.55, 3.83, 7.11, 10.39];
  for (let i = 0; i < 4; i++) {
    s.addShape("ellipse", { x: TX[i], y: 5.42, w: 0.52, h: 0.52, fill: { color: NAVY }, line: { type: "none" } });
    s.addImage({ data: trust[i].icon, x: TX[i] + 0.12, y: 5.54, w: 0.28, h: 0.28 });
    s.addText(trust[i].h, { x: TX[i] + 0.66, y: 5.42, w: 2.2, h: 0.52, margin: 0,
      fontFace: "Calibri", fontSize: 11.5, bold: true, color: INK, valign: "middle" });
    s.addText(trust[i].t, { x: TX[i], y: 6.06, w: 2.85, h: 1.0, margin: 0,
      fontFace: "Calibri", fontSize: 10, color: MUTED, valign: "top" });
  }

  s.addText("Method: Best-Worst Scaling (Louviere; Sawtooth MaxDiff practice)  ·  Bradley–Terry model (Maystre & Grossglauser, NeurIPS 2015)  ·  respondent bootstrap intervals", {
    x: 0.55, y: 7.08, w: 12.2, h: 0.28, margin: 0,
    fontFace: "Calibri", fontSize: 8.5, italic: true, color: MUTED });

  s.addNotes(
    "Talk track: (1) Stakeholders never rank 60 items — they answer quick 4-item best/worst screens; 10 minutes of these covers the whole catalog once, an hour covers it three times. Every completed screen stands alone, so early exits still contribute. " +
    "(2) Each screen implies five head-to-head preferences, so even small panels generate thousands of comparisons. " +
    "(3) We aggregate three independent ways — transparent counting anyone can verify in Excel, election-style majority logic, and the Bradley-Terry choice model used in modern preference science. Agreement across methods is the defense; the few items where they disagree are flagged as discussion items. " +
    "(4) The output lands in the Cameo model: each use case carries its score, rank, 90% rank interval, and probability of being top-10 — so when we commit to building the top-ranked capability, we can show it is statistically separated from the alternatives, not just first by a hair in a noisy average.");

  await pres.writeFile({ fileName: "/tmp/claude-0/-home-user-survey/a10344f3-c41d-549a-9486-7bbdc3a999ac/scratchpad/prioritization_method_slide.pptx" });
  console.log("written");
})();
