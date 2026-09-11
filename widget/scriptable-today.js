// LeanLoop — "Today" widget for iOS Scriptable (https://scriptable.app)
// Shows today's kcal / protein / carbs / fat vs your target, straight from your LeanLoop server.
// Setup: 1) set WIDGET_KEY on your Cloud Run service  2) paste this into Scriptable  3) fill URL  4) add a Scriptable widget → pick this script.

const URL = "https://garmin-mcp-102012715596.us-central1.run.app/<WIDGET_KEY>/today"; // <- put your WIDGET_KEY here

const w = new ListWidget();
w.backgroundColor = new Color("#111214");
w.setPadding(12, 14, 12, 14);
w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000); // iOS refreshes ~every 15 min

let d = null;
try { d = await new Request(URL).loadJSON(); } catch (e) { d = { error: String(e) }; }

const line = (txt, size, color, bold) => {
  const t = w.addText(txt);
  t.font = bold ? Font.boldSystemFont(size) : Font.systemFont(size);
  t.textColor = color;
  t.lineLimit = 1;
  return t;
};

if (!d || d.error) {
  line("LeanLoop", 12, Color.gray(), true);
  w.addSpacer(4);
  line("ไม่มีข้อมูล / ออฟไลน์", 14, Color.orange(), true);
  line(String((d && d.error) || "").slice(0, 60), 9, Color.gray(), false);
} else {
  const kcal = Math.round(d.kcal || 0);
  const kt = d.kcal_target;
  const rem = d.remaining;
  const pct = kt ? Math.min(kcal / kt, 1.25) : 0;

  line("LeanLoop · " + (d.day || d.date || ""), 11, Color.gray(), true);
  w.addSpacer(3);
  line(kt ? `${kcal.toLocaleString()} / ${kt.toLocaleString()} kcal` : `${kcal.toLocaleString()} kcal`, 20, Color.white(), true);
  if (rem !== null && rem !== undefined) {
    const over = rem < 0;
    line(over ? `เกิน ${Math.abs(rem).toLocaleString()}` : `เหลือ ${rem.toLocaleString()}`, 12, over ? Color.red() : Color.green(), true);
  }
  w.addSpacer(6);

  // progress bar (green → orange near target → red over)
  const W = 300, H = 14;
  const ctx = new DrawContext();
  ctx.size = new Size(W, H); ctx.opaque = false; ctx.respectScreenScale = true;
  ctx.setFillColor(new Color("#2a2c30"));
  ctx.fillPath((() => { const p = new Path(); p.addRoundedRect(new Rect(0, 0, W, H), 7, 7); return p; })());
  const fillW = Math.max(0, Math.min(W, W * Math.min(pct, 1)));
  ctx.setFillColor(pct > 1 ? Color.red() : pct > 0.9 ? Color.orange() : Color.green());
  ctx.fillPath((() => { const p = new Path(); p.addRoundedRect(new Rect(0, 0, fillW, H), 7, 7); return p; })());
  const bar = w.addImage(ctx.getImage()); bar.imageSize = new Size(W / 2, H / 2);

  w.addSpacer(6);
  const p = Math.round(d.p || 0), c = Math.round(d.c || 0), f = Math.round(d.f || 0);
  line(`P ${p}${d.p_target ? "/" + d.p_target : ""}g   C ${c}g   F ${f}g`, 13, Color.white(), true);
  if (!d.logged) line("ยังไม่ได้ log วันนี้", 10, Color.gray(), false);
}

w.addSpacer(4);
const now = new Date();
line("อัปเดต " + now.getHours().toString().padStart(2, "0") + ":" + now.getMinutes().toString().padStart(2, "0"), 9, Color.gray(), false);

if (config.runsInWidget) { Script.setWidget(w); } else { await w.presentSmall(); }
Script.complete();
