# -*- coding: utf-8 -*-
"""
金融行情自动生成器
- 纯数据版：只输出可完全自动化的行情数据，不含任何人工分析文字
- 数据源：新浪财经 hq.sinajs.cn（公开接口）
- 输出：index.html（可直接部署到 Cloudflare Pages）
- 设计目标：本地与 GitHub Actions 环境完全一致，零本地依赖
"""
import io
import os
import sys
import json
import datetime
import urllib.request
from zoneinfo import ZoneInfo

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SINA_URL = "https://hq.sinajs.cn/list="
HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}

# 品种定义：(行情代码, 英文键, 显示名, 单位, 分组, 英文名, 英文单位)
SYMBOLS = [
    ("fx_susdcny",  "cny",   "在岸人民币 USD/CNY", "—",        "人民币汇率", "USD/CNY Onshore",   "—"),
    ("fx_susdcnh",  "cnh",   "离岸人民币 USD/CNH", "—",        "人民币汇率", "USD/CNH Offshore",  "—"),
    ("DINIW",       "dxy",   "美元指数 DXY",       "—",        "人民币汇率", "US Dollar Index",   "—"),
    ("hf_CL",       "wti",   "WTI 原油",           "美元/桶",  "原油",       "WTI Crude",         "USD/bbl"),
    ("hf_OIL",      "brent", "布伦特原油",         "美元/桶",  "原油",       "Brent Crude",       "USD/bbl"),
    ("nf_SC0",      "sc",    "上海原油 SC 主连",   "元/桶",    "原油",       "Shanghai Crude SC", "CNY/bbl"),
    ("hf_XAU",      "xau",   "伦敦现货黄金",       "美元/盎司", "黄金",       "Spot Gold (London)", "USD/oz"),
    ("hf_GC",       "gc",    "COMEX 黄金",         "美元/盎司", "黄金",       "COMEX Gold",        "USD/oz"),
    ("nf_AU0",      "au",    "上海黄金 AU 主连",   "元/克",    "黄金",       "Shanghai Gold AU",  "CNY/g"),
    ("hf_XAG",      "xag",   "伦敦现货白银",       "美元/盎司", "其他贵金属", "Spot Silver (London)", "USD/oz"),
    ("hf_SI",       "si",    "COMEX 白银",         "美元/盎司", "其他贵金属", "COMEX Silver",      "USD/oz"),
    ("nf_AG0",      "ag",    "上海白银 AG 主连",   "元/千克",   "其他贵金属", "Shanghai Silver AG", "CNY/kg"),
    ("hf_XPT",      "xpt",   "铂金 XPT（纽约）",   "美元/盎司", "其他贵金属", "Platinum XPT (NY)", "USD/oz"),
    ("hf_XPD",      "xpd",   "钯金 XPD（纽约）",   "美元/盎司", "其他贵金属", "Palladium XPD (NY)", "USD/oz"),
]

GROUP_COLORS = {
    "人民币汇率": "#1d4ed8",
    "原油":       "#b45309",
    "黄金":       "#a16207",
    "其他贵金属": "#6b7280",
}

GROUP_EN = {
    "人民币汇率": "CNY Rates",
    "原油":       "Crude Oil",
    "黄金":       "Gold",
    "其他贵金属": "Other Metals",
}


def fetch_raw(codes):
    """批量拉取新浪行情，返回 {code: [字段...]}"""
    url = SINA_URL + ",".join(codes)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resp:
        text = resp.read().decode("gbk", errors="replace")
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("var hq_str_"):
            continue
        try:
            head, payload = line.split("=", 1)
            code = head.replace("var hq_str_", "").strip()
            payload = payload.strip().rstrip(";").strip('"')
            out[code] = payload.split(",") if payload else []
        except Exception:
            continue
    return out


def num(s):
    try:
        v = float(s)
        return v
    except (TypeError, ValueError):
        return None


def parse_quote(code, raw):
    """
    解析单个品种，统一输出 (最新价, 涨跌幅%, 涨跌方向, 备注, 结构化盘面字段)
    外盘 hf_*：  字段 0=最新 6=时间 7=昨收 8=今开 4=高 5=低
    现汇 fx_*：  字段 0=时间 1=最新 3=昨收 6=高 7=低
    美元指数：   0=时间 1=最新 3=昨收 5=高 6=低
    内盘 nf_*：  0=名称 8=最新 10=昨结 3=高 4=低
    """
    try:
        vol = None
        prev_kind = "prev"  # prev=昨收，settle=昨结
        if code.startswith("hf_"):
            last = num(raw[0])
            prev = num(raw[7])
            high, low = num(raw[4]), num(raw[5])
            t = raw[6] if len(raw) > 6 else ""
            note = build_note(high, low, prev, t, "外盘")
        elif code.startswith("fx_"):
            last = num(raw[1])
            prev = num(raw[3])
            high, low = num(raw[6]), num(raw[7])
            t = raw[0] if raw else ""
            note = build_note(high, low, prev, t, "现汇")
        elif code == "DINIW":
            last = num(raw[1])
            prev = num(raw[3])
            high, low = num(raw[6]), num(raw[7])
            t = raw[0] if raw else ""
            note = build_note(high, low, prev, t, "指数")
        elif code.startswith("nf_"):
            last = num(raw[8])
            prev = num(raw[10])
            high, low = num(raw[3]), num(raw[4])
            vol = num(raw[13]) if len(raw) > 13 else None
            prev_kind = "settle"
            t = ""
            note = f"昨结 {fmt(prev)}　日高 {fmt(high)}　日低 {fmt(low)}"
            if vol:
                note += f"　持仓 {int(vol):,}"
        else:
            return None

        if last is None or prev is None or prev == 0:
            return None
        pct = (last - prev) / prev * 100
        direction = "up" if pct > 0 else ("down" if pct < 0 else "flat")
        detail = {
            "pk": prev_kind,
            "h": fmt(high), "l": fmt(low), "pv": fmt(prev),
            "t": t, "oi": (f"{int(vol):,}" if vol else ""),
        }
        return last, pct, direction, note, detail
    except (IndexError, TypeError, ZeroDivisionError):
        return None


def build_note(high, low, prev, t, kind):
    parts = []
    if high is not None:
        parts.append(f"日高 {fmt(high)}")
    if low is not None:
        parts.append(f"日低 {fmt(low)}")
    if prev is not None:
        parts.append(f"昨收 {fmt(prev)}")
    if t:
        parts.append(t)
    return "　".join(parts) if parts else "—"


def fmt(v, digits=None):
    if v is None:
        return "—"
    if digits is None:
        digits = 4 if abs(v) < 10 else (2 if abs(v) < 1000 else 1)
    return f"{v:,.{digits}f}"


def fetch_cny_mid():
    """抓人民币中间价（中国货币网）。失败返回 None，不阻塞主流程。"""
    url = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://www.chinamoney.com.cn/",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        for rec in data.get("records", []):
            en = (rec.get("vrtEName") or "").upper().replace(" ", "")
            if en in ("USD/CNY", "USDCNY"):
                price = rec.get("price")
                bp = rec.get("bp")
                date = rec.get("showDateForCn") or rec.get("showDate") or ""
                if price and price != "---":
                    return str(price), date, bp
    except Exception as e:
        print(f"[warn] 中间价抓取失败：{e}", file=sys.stderr)
    return None, None


def main():
    codes = [c for c, *_ in SYMBOLS]
    raw = fetch_raw(codes)
    print(f"[info] 拉取到 {len(raw)}/{len(codes)} 个品种", file=sys.stderr)

    quotes = {}
    for code, key, name, unit, group, en_name, en_unit in SYMBOLS:
        if code not in raw or not raw[code]:
            print(f"[warn] 缺失：{code} {name}", file=sys.stderr)
            continue
        parsed = parse_quote(code, raw[code])
        if not parsed:
            print(f"[warn] 解析失败：{code} {name}", file=sys.stderr)
            continue
        last, pct, direction, note, detail = parsed
        quotes[key] = {
            "name": name, "unit": unit, "group": group,
            "en_name": en_name, "en_unit": en_unit,
            "last": last, "pct": pct, "dir": direction, "note": note,
            "detail": detail,
        }

    mid, mid_date, mid_bp = fetch_cny_mid()
    if mid:
        try:
            bp_val = float(mid_bp) if mid_bp not in (None, "", "---") else None
        except ValueError:
            bp_val = None
        note = f"{mid_date} 官方公布值" if mid_date else "官方公布值"
        en_note = f"{mid_date} official fixing" if mid_date else "official fixing"
        if bp_val is not None:
            # 中国货币网 bp 为上调/下调基点数，正值为调升
            note += f"　较前值{'调升' if bp_val > 0 else ('调降' if bp_val < 0 else '持平')} {abs(bp_val):.0f}bp"
            en_note += f" | {'up' if bp_val > 0 else ('down' if bp_val < 0 else 'flat')} {abs(bp_val):.0f}bp"
        quotes["mid"] = {
            "name": "人民币中间价", "unit": "—", "group": "人民币汇率",
            "en_name": "CNY Central Parity", "en_unit": "—",
            "last": float(mid), "pct": None, "dir": "flat",
            "note": note, "en_note": en_note,
            "detail": {"pk": "fix", "h": "—", "l": "—", "pv": "—", "t": "", "oi": ""},
        }

    if not quotes:
        print("[error] 无任何行情数据，终止", file=sys.stderr)
        sys.exit(1)

    html = render(quotes)
    out_path = os.path.join(BASE_DIR, "finance.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    # 同时写一份 index.html 作为站点根入口
    idx_path = os.path.join(BASE_DIR, "index.html")
    with open(idx_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] 已生成 {out_path}（{len(html)} 字节，{len(quotes)} 个品种）", file=sys.stderr)
    print(f"[ok] 已生成 {idx_path}", file=sys.stderr)


def render(q):
    tz_cn = ZoneInfo("Asia/Shanghai")
    tz_ny = ZoneInfo("America/New_York")
    tz_ldn = ZoneInfo("Europe/London")
    tz_dxb = ZoneInfo("Asia/Dubai")
    now = datetime.datetime.now(datetime.timezone.utc)
    cn = now.astimezone(tz_cn)
    ny = now.astimezone(tz_ny)
    ldn = now.astimezone(tz_ldn)
    dxb = now.astimezone(tz_dxb)
    date_str = cn.strftime("%Y-%m-%d")
    cn_str = cn.strftime("%Y-%m-%d %H:%M")
    ny_str = ny.strftime("%Y-%m-%d %H:%M")
    ldn_str = ldn.strftime("%Y-%m-%d %H:%M")
    dxb_str = dxb.strftime("%Y-%m-%d %H:%M")

    rows_html = ""
    for group in ["人民币汇率", "原油", "黄金", "其他贵金属"]:
        items = [(k, v) for k, v in q.items() if v["group"] == group]
        if not items:
            continue
        color = GROUP_COLORS[group]
        rows_html += (f'<tr class="grp"><td colspan="4" '
                      f'style="border-left:4px solid {color}">'
                      f'<span data-zh="{group}" data-en="{GROUP_EN[group]}">{group}</span>'
                      f'</td></tr>')
        for k, v in items:
            rows_html += row_cell(v)

    up_n = sum(1 for v in q.values() if v["dir"] == "up")
    dn_n = sum(1 for v in q.values() if v["dir"] == "down")
    flat_n = sum(1 for v in q.values() if v["dir"] == "flat")
    kpis = compute_kpis(q) + [("涨跌家数", f"{up_n}:{dn_n}", "count")]

    KPI_EN = {
        "金银比": ("Gold/Silver Ratio", "spot gold / spot silver"),
        "金油比": ("Gold/Oil Ratio", "spot gold / WTI"),
        "布-WTI 价差": ("Brent-WTI Spread", "USD/bbl"),
        "离岸-在岸价差": ("CNH-CNY Spread", "basis points"),
        "涨跌家数": ("Advance / Decline", f"{flat_n} unchanged"),
    }

    kpi_html = ""
    for label, value, desc in kpis:
        en_label, en_desc = KPI_EN.get(label, (label, desc))
        if label == "涨跌家数":
            kpi_html += (f'<div><div class="k"><span data-zh="{label}" data-en="{en_label}">{label}</span></div>'
                         f'<div class="v"><span class="up">{up_n}</span> : '
                         f'<span class="dn">{dn_n}</span></div>'
                         f'<div class="d"><span data-zh="平盘 {flat_n} 个" data-en="{en_desc}">平盘 {flat_n} 个</span></div></div>')
        else:
            kpi_html += (f'<div><div class="k"><span data-zh="{label}" data-en="{en_label}">{label}</span></div>'
                         f'<div class="v">{value}</div>'
                         f'<div class="d"><span data-zh="{desc}" data-en="{en_desc}">{desc}</span></div></div>')

    missing = [s[2] for s in SYMBOLS if s[1] not in q]
    missing_en = [s[5] for s in SYMBOLS if s[1] not in q]
    missing_note = ""
    if missing:
        missing_note = ('<div class="miss">'
                        f'<span data-zh="本期未取到：{("、").join(missing)}（数据源临时不可用，下期自动重试）"'
                        f' data-en="Not available this run: {", ".join(missing_en)} (source temporarily down, retried next run)">'
                        f'本期未取到：{("、").join(missing)}（数据源临时不可用，下期自动重试）</span></div>')

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>金融市场实时行情 · {date_str}</title>
<meta name="robots" content="noindex,nofollow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f5f6f8;color:#1f2328;padding:32px 20px}}
.wrap{{max-width:1080px;margin:0 auto;background:#fff;border-radius:14px;box-shadow:0 2px 16px rgba(0,0,0,.07);overflow:hidden}}
.hd{{padding:26px 30px 20px;border-bottom:1px solid #ebedf0}}
.hd h1{{font-size:21px;font-weight:700;letter-spacing:.3px}}
.hd .sub{{margin-top:7px;font-size:13px;color:#6b7280;display:flex;gap:18px;flex-wrap:wrap;row-gap:6px}}
.hd .sub.sub2{{margin-top:5px;font-size:12.5px;color:#9aa0a6}}
.hd .sub span{{white-space:nowrap}}
.hd .sub b{{color:#374151;font-weight:600;font-family:Consolas,monospace}}
.hd .sub.sub2 b{{color:#6b7280;font-weight:600;font-family:inherit}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{background:#fafbfc;text-align:left;padding:11px 16px;font-size:12px;font-weight:600;color:#6b7280;letter-spacing:.5px;border-bottom:1px solid #ebedf0}}
td{{padding:11px 16px;border-bottom:1px solid #f2f3f5;vertical-align:middle}}
tr.grp td{{background:#f8f9fb;font-size:12.5px;font-weight:700;color:#4b5563;padding:9px 16px;letter-spacing:.6px}}
.nm{{font-weight:600;color:#1f2328;width:190px}}
.un{{font-size:11.5px;color:#9aa0a6;margin-left:6px;font-weight:400}}
.px{{font-family:"SF Mono",Consolas,monospace;font-size:16px;font-weight:700;width:130px;text-align:right}}
.pc{{width:120px;text-align:right}}
.nt{{font-size:12.5px;color:#8b9199}}
.up{{color:#d92b2b}}
.dn{{color:#0f9d58}}
.flat{{color:#6b7280}}
.tag{{display:inline-block;padding:3px 9px;border-radius:20px;font-size:12.5px;font-weight:700;font-family:Consolas,monospace;white-space:nowrap}}
.tag.up{{background:#fdecec;color:#d92b2b}}
.tag.dn{{background:#e9f7ef;color:#0f9d58}}
.tag.flat{{background:#f0f1f3;color:#6b7280}}
.kpi{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;padding:20px 30px 6px}}
.kpi div{{background:#fafbfc;border:1px solid #ebedf0;border-radius:10px;padding:13px 15px}}
.kpi .k{{font-size:11.5px;color:#8b9199;letter-spacing:.4px}}
.kpi .v{{font-size:19px;font-weight:700;font-family:Consolas,monospace;margin-top:5px;color:#1f2328}}
.kpi .d{{font-size:11.5px;color:#9aa0a6;margin-top:3px}}
.miss{{margin:14px 30px 0;padding:10px 14px;background:#fff8e6;border:1px solid #f0d9a8;border-radius:8px;font-size:12.5px;color:#8a6d1f}}
.body-pad{{padding-bottom:22px}}
.topbar{{max-width:1080px;margin:0 auto 14px;display:flex;align-items:center;justify-content:space-between;gap:12px}}
.back{{display:inline-flex;align-items:center;gap:6px;font-size:13.5px;font-weight:600;color:#374151;text-decoration:none;background:#fff;border:1px solid #e3e6ea;border-radius:9px;padding:8px 14px;transition:.15s}}
.back:hover{{border-color:#c8ccd2;color:#111827;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.langbtn{{font-size:13px;font-weight:600;color:#4b5563;background:#fff;border:1px solid #e3e6ea;border-radius:9px;padding:8px 14px;cursor:pointer;transition:.15s}}
.langbtn:hover{{border-color:#c8ccd2;color:#111827}}
@media(max-width:760px){{
  body{{padding:14px 10px}}
  .wrap{{border-radius:12px}}
  .topbar{{margin-bottom:10px;padding:0 2px}}
  .kpi{{grid-template-columns:repeat(2,1fr);padding:16px 16px 4px}}
  .hd,.miss{{margin-left:0;margin-right:0}}
  .hd{{padding:20px 18px}}
  .miss{{margin:12px 16px 0}}
  td,th{{padding:9px 10px}}
  .nm{{width:auto}}
  .px{{width:auto;font-size:15px}}
  .nt{{display:none}}
  table{{font-size:13px}}
}}
</style></head><body>

<div class="topbar">
  <a class="back" href="https://www.ilong.dpdns.org"><span data-zh="← 返回首页" data-en="← Back to Home">← 返回首页</span></a>
  <button class="langbtn" id="langBtn" type="button">EN</button>
</div>

<div class="wrap">
<div class="hd">
  <h1><span data-zh="金融市场实时行情汇总" data-en="Global Markets Live Quotes">金融市场实时行情汇总</span></h1>
  <div class="sub">
    <span><span data-zh="北京时间" data-en="Beijing">北京时间</span> <b>{cn_str}</b></span>
    <span><span data-zh="纽约时间" data-en="New York">纽约时间</span> <b>{ny_str}</b></span>
    <span><span data-zh="伦敦时间" data-en="London">伦敦时间</span> <b>{ldn_str}</b></span>
    <span><span data-zh="迪拜时间" data-en="Dubai">迪拜时间</span> <b>{dxb_str}</b></span>
  </div>
  <div class="sub sub2">
    <span><span data-zh="涨跌基准" data-en="Change basis">涨跌基准</span> <b data-zh="前一交易日收盘 / 昨结" data-en="previous close / prior settle">前一交易日收盘 / 昨结</b></span>
    <span><span data-zh="品种数" data-en="Instruments">品种数</span> <b>{len(q)}</b></span>
  </div>
</div>

<div class="kpi">
{kpi_html}
</div>

<table>
<thead><tr>
<th data-zh="品种" data-en="Instrument">品种</th>
<th style="text-align:right" data-zh="最新价" data-en="Last">最新价</th>
<th style="text-align:right" data-zh="涨跌幅" data-en="Change">涨跌幅</th>
<th data-zh="盘面" data-en="Session">盘面</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
{missing_note}
<div class="body-pad"></div>
</div>

<script>
(function(){{
  var KEY = "ilong-lang";
  var btn = document.getElementById("langBtn");
  var TITLE = {{zh: "金融市场实时行情 · {date_str}", en: "Market Quotes · {date_str}"}};

  function apply(lang){{
    var zh = lang !== "en";
    document.documentElement.lang = zh ? "zh-CN" : "en";
    var nodes = document.querySelectorAll("[data-zh]");
    for (var i = 0; i < nodes.length; i++) {{
      var el = nodes[i];
      var txt = zh ? el.getAttribute("data-zh") : el.getAttribute("data-en");
      if (txt !== null) el.textContent = txt;
    }}
    btn.textContent = zh ? "EN" : "中文";
    btn.setAttribute("aria-label", zh ? "Switch to English" : "切换到中文");
    document.title = zh ? TITLE.zh : TITLE.en;
  }}

  var saved = null;
  try {{ saved = localStorage.getItem(KEY); }} catch (e) {{}}
  apply(saved === "en" ? "en" : "zh");

  btn.addEventListener("click", function(){{
    var next = document.documentElement.lang === "zh-CN" ? "en" : "zh";
    try {{ localStorage.setItem(KEY, next); }} catch (e) {{}}
    apply(next);
  }});
}})();
</script>
</body></html>'''


def compute_kpis(q):
    kpis = []
    xau, xag = q.get("xau"), q.get("xag")
    if xau and xag and xag["last"]:
        ratio = xau["last"] / xag["last"]
        kpis.append(("金银比", f"{ratio:.1f}", "现货金 / 现货银"))
    wti = q.get("wti")
    if xau and wti and wti["last"]:
        kpis.append(("金油比", f"{xau['last'] / wti['last']:.1f}", "现货金 / WTI"))
    brent = q.get("brent")
    if brent and wti and wti["last"]:
        kpis.append(("布-WTI 价差", f"{brent['last'] - wti['last']:.2f}", "美元/桶"))
    cny, cnh = q.get("cny"), q.get("cnh")
    if cny and cnh:
        diff = (cnh["last"] - cny["last"]) * 10000
        kpis.append(("离岸-在岸价差", f"{diff:+.0f}", "基点"))
    if not kpis:
        kpis.append(("—", "—", "派生指标待数据补齐"))
    return kpis[:4]


def row_cell(v):
    d = v["dir"]
    zh_name = v["name"]
    en_name = v.get("en_name") or zh_name
    zh_unit = v["unit"] if v["unit"] != "—" else ""
    en_unit = v.get("en_unit") or ""
    if en_unit == "—":
        en_unit = ""
    unit = (f'<span class="un" data-zh="{zh_unit}" data-en="{en_unit}">{zh_unit}</span>'
            if zh_unit else "")

    if v["pct"] is None:
        pct_txt = "—"
        cls_pct = "flat"
    else:
        arrow = "▲" if d == "up" else ("▼" if d == "down" else "—")
        pct_txt = f'{arrow} {v["pct"]:+.2f}%'
        cls_pct = d

    det = v.get("detail") or {}
    if "en_note" in v:
        # 中间价：整段备注直接中英对照
        note_html = (f'<span data-zh="{v["note"]}" data-en="{v["en_note"]}">{v["note"]}</span>')
    else:
        pk_zh = "昨结" if det.get("pk") == "settle" else ("官方公布值" if det.get("pk") == "fix" else "昨收")
        pk_en = "Settle" if det.get("pk") == "settle" else ("Fixing" if det.get("pk") == "fix" else "Prev")
        zh_parts, en_parts = [], []
        if det.get("h") and det["h"] != "—":
            zh_parts.append(f'日高 {det["h"]}')
            en_parts.append(f'High {det["h"]}')
        if det.get("l") and det["l"] != "—":
            zh_parts.append(f'日低 {det["l"]}')
            en_parts.append(f'Low {det["l"]}')
        if det.get("pv") and det["pv"] != "—":
            zh_parts.append(f'{pk_zh} {det["pv"]}')
            en_parts.append(f'{pk_en} {det["pv"]}')
        if det.get("t"):
            zh_parts.append(det["t"])
            en_parts.append(det["t"])
        if det.get("oi"):
            zh_parts.append(f'持仓 {det["oi"]}')
            en_parts.append(f'OI {det["oi"]}')
        zh_txt = "　".join(zh_parts) if zh_parts else "—"
        en_txt = " · ".join(en_parts) if en_parts else "—"
        note_html = (f'<span data-zh="{zh_txt}" data-en="{en_txt}">{zh_txt}</span>')

    return (f'<tr><td class="nm"><span data-zh="{zh_name}" data-en="{en_name}">{zh_name}</span>{unit}</td>'
            f'<td class="px {d if d != "flat" else ""}">{fmt(v["last"])}</td>'
            f'<td class="pc"><span class="tag {cls_pct}">{pct_txt}</span></td>'
            f'<td class="nt">{note_html}</td></tr>')


if __name__ == "__main__":
    main()
