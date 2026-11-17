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

# 品种定义：(行情代码, 英文键, 显示名, 单位, 分组)
SYMBOLS = [
    ("fx_susdcny",  "cny",   "在岸人民币 USD/CNY", "—",        "人民币汇率"),
    ("fx_susdcnh",  "cnh",   "离岸人民币 USD/CNH", "—",        "人民币汇率"),
    ("DINIW",       "dxy",   "美元指数 DXY",       "—",        "人民币汇率"),
    ("hf_CL",       "wti",   "WTI 原油",           "美元/桶",  "原油"),
    ("hf_OIL",      "brent", "布伦特原油",         "美元/桶",  "原油"),
    ("nf_SC0",      "sc",    "上海原油 SC 主连",   "元/桶",    "原油"),
    ("hf_XAU",      "xau",   "伦敦现货黄金",       "美元/盎司", "黄金"),
    ("hf_GC",       "gc",    "COMEX 黄金",         "美元/盎司", "黄金"),
    ("nf_AU0",      "au",    "上海黄金 AU 主连",   "元/克",    "黄金"),
    ("hf_XAG",      "xag",   "伦敦现货白银",       "美元/盎司", "其他贵金属"),
    ("hf_SI",       "si",    "COMEX 白银",         "美元/盎司", "其他贵金属"),
    ("nf_AG0",      "ag",    "上海白银 AG 主连",   "元/千克",   "其他贵金属"),
    ("hf_XPT",      "xpt",   "铂金 XPT（纽约）",   "美元/盎司", "其他贵金属"),
    ("hf_XPD",      "xpd",   "钯金 XPD（纽约）",   "美元/盎司", "其他贵金属"),
]

GROUP_COLORS = {
    "人民币汇率": "#1d4ed8",
    "原油":       "#b45309",
    "黄金":       "#a16207",
    "其他贵金属": "#6b7280",
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
    解析单个品种，统一输出 (最新价, 涨跌幅%, 涨跌方向, 备注)
    外盘 hf_*：  字段 0=最新 6=时间 7=昨收 8=今开 4=高 5=低
    现汇 fx_*：  字段 0=时间 1=最新 3=昨收 6=高 7=低
    美元指数：   0=时间 1=最新 3=昨收 5=高 6=低
    内盘 nf_*：  0=名称 8=最新 10=昨结 3=高 4=低
    """
    try:
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
            note = f"昨结 {fmt(prev)}　日高 {fmt(high)}　日低 {fmt(low)}"
            if vol:
                note += f"　持仓 {int(vol):,}"
        else:
            return None

        if last is None or prev is None or prev == 0:
            return None
        pct = (last - prev) / prev * 100
        direction = "up" if pct > 0 else ("down" if pct < 0 else "flat")
        return last, pct, direction, note
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
    for code, key, name, unit, group in SYMBOLS:
        if code not in raw or not raw[code]:
            print(f"[warn] 缺失：{code} {name}", file=sys.stderr)
            continue
        parsed = parse_quote(code, raw[code])
        if not parsed:
            print(f"[warn] 解析失败：{code} {name}", file=sys.stderr)
            continue
        last, pct, direction, note = parsed
        quotes[key] = {
            "name": name, "unit": unit, "group": group,
            "last": last, "pct": pct, "dir": direction, "note": note,
        }

    mid, mid_date, mid_bp = fetch_cny_mid()
    if mid:
        try:
            bp_val = float(mid_bp) if mid_bp not in (None, "", "---") else None
        except ValueError:
            bp_val = None
        note = f"{mid_date} 官方公布值"
        if bp_val is not None:
            # 中国货币网 bp 为上调/下调基点数，正值为调升
            note += f"　较前值{'调升' if bp_val > 0 else ('调降' if bp_val < 0 else '持平')} {abs(bp_val):.0f}bp"
        quotes["mid"] = {
            "name": "人民币中间价", "unit": "—", "group": "人民币汇率",
            "last": float(mid), "pct": None, "dir": "flat",
            "note": note,
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
                      f'style="border-left:4px solid {color}">{group}</td></tr>')
        for k, v in items:
            rows_html += row_cell(v)

    # 派生指标
    kpis = compute_kpis(q)

    up_n = sum(1 for v in q.values() if v["dir"] == "up")
    dn_n = sum(1 for v in q.values() if v["dir"] == "down")
    flat_n = sum(1 for v in q.values() if v["dir"] == "flat")

    kpi_html = ""
    for label, value, desc in kpis:
        kpi_html += (f'<div><div class="k">{label}</div>'
                     f'<div class="v">{value}</div>'
                     f'<div class="d">{desc}</div></div>')
    kpi_html += (f'<div><div class="k">涨跌家数</div>'
                 f'<div class="v"><span class="up">{up_n}</span> : '
                 f'<span class="dn">{dn_n}</span></div>'
                 f'<div class="d">平盘 {flat_n} 个</div></div>')

    missing = [v[2] for v in SYMBOLS if v[1] not in q]
    missing_note = ""
    if missing:
        missing_note = (f'<div class="miss">本期未取到：{("、").join(missing)}'
                        f'（数据源临时不可用，下期自动重试）</div>')

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
.hd .sub span{{white-space:nowrap}}
.hd .sub b{{color:#374151;font-weight:600;font-family:Consolas,monospace}}
.banner{{margin:16px 30px 0;padding:11px 14px;background:#eef4ff;border:1px solid #c7dbff;border-radius:8px;font-size:12.5px;color:#1e40af;line-height:1.7}}
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
.ft{{padding:18px 30px 24px;font-size:12px;color:#9aa0a6;line-height:1.8;border-top:1px solid #f2f3f5;margin-top:18px}}
@media(max-width:760px){{
  body{{padding:14px 10px}}
  .kpi{{grid-template-columns:repeat(2,1fr);padding:16px 16px 4px}}
  .hd,.banner,.ft,.miss{{margin-left:0;margin-right:0}}
  .hd{{padding:20px 18px}}
  .banner,.miss{{margin:12px 16px 0}}
  .ft{{padding:16px 18px 20px}}
  td,th{{padding:9px 10px}}
  .nm{{width:auto}}
  .px{{width:auto;font-size:15px}}
  .nt{{display:none}}
  table{{font-size:13px}}
}}
</style></head><body><div class="wrap">
<div class="hd">
  <h1>金融市场实时行情汇总</h1>
  <div class="sub">
    <span>北京时间 <b>{cn_str}</b></span>
    <span>纽约时间 <b>{ny_str}</b></span>
    <span>伦敦时间 <b>{ldn_str}</b></span>
    <span>迪拜时间 <b>{dxb_str}</b></span>
    <span>涨跌基准 <b>前一交易日收盘 / 昨结</b></span>
    <span>品种数 <b>{len(q)}</b></span>
  </div>
  <div class="banner">行情数据汇总，取自公开行情接口，不含分析判断。涨跌方向按中国习惯标注：<span class="up">红＝上涨</span>、<span class="dn">绿＝下跌</span>；汇率按 USD/CNY 报价口径，数值上涨（红色）表示人民币贬值。</div>
</div>

<div class="kpi">
{kpi_html}
</div>

<table>
<thead><tr><th>品种</th><th style="text-align:right">最新价</th><th style="text-align:right">涨跌幅</th><th>盘面</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
{missing_note}

<div class="ft">
数据源：公开行情接口（hq.sinajs.cn） ／ 中国货币网人民币中间价。<br>
派生指标：金银比（现货金/现货银）、金油比（现货金/WTI）、布伦特-WTI 价差（美元/桶），均由当期报价实时计算。<br>
内容为行情信息整理，不构成投资建议。数据可能存在延迟，请以交易所与官方公布为准。
</div>
</div></body></html>'''


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
    unit = f'<span class="un">{v["unit"]}</span>' if v["unit"] != "—" else ""
    if v["pct"] is None:
        pct_txt = "—"
        abs_txt = "—"
        cls_pct = "flat"
    else:
        arrow = "▲" if d == "up" else ("▼" if d == "down" else "—")
        pct_txt = f'{arrow} {v["pct"]:+.2f}%'
        abs_txt = f'{v["pct"]:+.2f}%'
        cls_pct = d
    return (f'<tr><td class="nm">{v["name"]}{unit}</td>'
            f'<td class="px {d if d != "flat" else ""}">{fmt(v["last"])}</td>'
            f'<td class="pc"><span class="tag {cls_pct}">{pct_txt}</span></td>'
            f'<td class="nt">{v["note"]}</td></tr>')


if __name__ == "__main__":
    main()
