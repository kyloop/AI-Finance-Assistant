"""The Portfolio agent's answer: sections chosen by what the question asks, each giving the figures and a plain explanation of
what they mean for this portfolio. Every figure comes from analyze_portfolio / portfolio_performance / portfolio_dividends and
every explanation from fixed rules over them, so the answer is the same with or without an LLM (mds/agent-portfolio-agent.md)."""
from __future__ import annotations

import re

ASSET_CLASSES = ["US stocks", "International", "Bonds", "Cash", "Real estate"]    # the five analyze_portfolio counts
SECTIONS = ["diversification", "performance", "risk", "fees", "income"]
# What a question is about. None matching, or a request for a review/summary, gets the full report.
FOCUS = {
    "diversification": re.compile(r"diversif|concentrat|sector|\w+[- ]heavy|allocat|spread|balanced|exposure|overweight|"
                                  r"international|\bbonds?\b|\bmix\b|too much (in|of)", re.I),
    "performance": re.compile(r"perform|\breturns?\b|\bdoing\b|did i do|\bgain|\bloss|\blost\b|profit|\bbeat|benchmark|"
                              r"winners?|losers?|\bbest\b|\bworst\b|drove|driv|contribut|vs\.? (the )?market|against the market", re.I),
    "risk": re.compile(r"risk|volatil|\bsafe|swing|drawdown|sharpe|sortino|aggressive|conservative|crash", re.I),
    "fees": re.compile(r"\bfees?\b|expense|\bcharges?\b|costly", re.I),
    "income": re.compile(r"dividend|income|\byield|payout", re.I),
}
FULL_REPORT = re.compile(r"analy[sz]|overview|summar|report|review|breakdown|everything|health|in detail|detailed|full picture", re.I)
MAX_TABLE_ROWS = 10

CONCENTRATION_NOTE = ("_Concentration risk means a large share of your money depends on one holding or sector, so a bad "
                      "stretch there hurts more. Diversifying spreads that risk._")


def focus(question: str) -> list[str]:
    """The report sections a question asks for, in report order; all of them for a general or 'analyse my portfolio' question."""
    asked = [k for k in SECTIONS if FOCUS[k].search(question)]
    return SECTIONS if not asked or FULL_REPORT.search(question) else asked


def _usd(n: float) -> str:
    return f"{'+' if n >= 0 else '-'}${abs(n):,.0f}"


def _pts(x: float) -> str:
    return f"{x * 100:+.1f} pts"


def _shares(items: list[dict], n: int = 5) -> str:
    return ", ".join(f"{x['name']} {x['weight']:.0%}" for x in items[:n])


def summary(a: dict) -> list[str]:
    lines = [f"Your portfolio is worth about **${a['total_value']:,.0f}** across {len(a['holdings'])} holdings."]
    if a["total_gain_loss"] is not None:
        lines.append(f"- Gain/loss against what you paid: **{_usd(a['total_gain_loss'])}** ({a['total_return_pct']:+.1%}), "
                     "for the holdings with a cost basis"
                     + (" (where none was entered, the close on the purchase date)"
                        if any(h.get("cost_basis_source") == "purchase_close" for h in a["holdings"]) else ""))
    if a["day_change"] is not None:
        lines.append(f"- Today: {_usd(a['day_change'])} ({a['day_change_pct']:+.2%})")
    return lines


def holdings_table(a: dict, perf: dict | None) -> list[str]:
    contrib = {c["ticker"]: c["contribution"] for c in (perf or {}).get("contributions") or []}
    head = "| Holding | Value | Weight | Gain/loss on cost |" + (" Contribution to return |" if contrib else "")
    lines = ["", head, "|---|---|---|---|" + ("---|" if contrib else "")]
    rows = sorted(a["holdings"], key=lambda h: -h["weight"])
    for h in rows[:MAX_TABLE_ROWS]:
        gain = f"{_usd(h['gain_loss'])} ({h['gain_loss_pct']:+.1%})" if h["gain_loss"] is not None else "no cost basis"
        if h.get("cost_basis_source") == "purchase_close":
            gain += f" since the {h['cost_basis_date']} close"
        cell = f" {_pts(contrib[h['ticker']])} |" if h["ticker"] in contrib else (" — |" if contrib else "")
        lines.append(f"| {h['ticker']} ({h['name']}) | ${h['value']:,.0f} | {h['weight']:.1%} | {gain} |{cell}")
    if len(rows) > MAX_TABLE_ROWS:
        lines.append(f"\n_…and {len(rows) - MAX_TABLE_ROWS} smaller holdings._")
    return lines


def diversification(a: dict) -> list[str]:
    s, parts = a["diversification_score"], a["score_parts"]
    band = "well spread" if s >= 70 else "moderately spread" if s >= 40 else "concentrated"
    n, eff = len(a["holdings"]), a["effective_holdings"]
    classes = a["asset_classes_present"]
    lines = ["", "**Diversification**",
             f"- Score: **{s}/100**, which this app counts as {band}. It is made of three parts:",
             f"  - Number of holdings: {parts['holdings']:.0f}/40. You own {n}, and by size they act like about {eff} "
             "equal-sized holdings (full marks at 15)",
             f"  - Asset classes: {parts['asset_classes']:.0f}/30. You hold {len(classes)} of the 5 ({', '.join(classes)})"
             + (f"; none in {', '.join(c for c in ASSET_CLASSES if c not in classes)}" if len(classes) < 5 else "")]
    top = a["top_sector"]
    if top:
        lines.append(f"  - Largest sector: {parts['sector']:.0f}/30. {top['name']} is {top['weight']:.0%} once the holdings "
                     "inside your funds are counted (full marks at 25% or less)")
    lines += [f"- By asset class: {_shares(a['allocation'])}",
              f"- By sector: {_shares(a['sectors'])}",
              f"- By region: {_shares(a['geography'])}"]
    # What holds the score back most: the part furthest from its maximum.
    gaps = {"holdings": 1 - parts["holdings"] / 40, "asset_classes": 1 - parts["asset_classes"] / 30,
            "sector": 1 - parts["sector"] / 30 if top else 0}
    worst = max(gaps, key=gaps.get)
    if gaps[worst] > 0.25:
        biggest = max(a["holdings"], key=lambda h: h["weight"])
        why = {"holdings": (f"a few holdings carry most of the value (the largest, {biggest['ticker']}, is {biggest['weight']:.0%}), "
                            f"so your {n} holdings behave like {eff} equal-sized ones"),
               "asset_classes": (f"everything is in {len(classes)} kind{'s' if len(classes) > 1 else ''} of asset, so they tend "
                                 "to rise and fall together; different asset classes often move differently"),
               "sector": (f"{top['name']} is {top['weight']:.0%} of the portfolio, so news about that one industry moves most "
                          "of your money" if top else "")}[worst]
        lines.append(f"- What holds the score back most: {why}.")
    elif s >= 70:
        lines.append("- No single part drags the score down: the money is spread across holdings, asset classes and sectors.")
    return lines


def performance(a: dict, perf: dict | None) -> list[str]:
    lines = ["", "**Performance**"]
    if not perf or perf.get("period_return") is None:
        lines.append("- Performance over time needs daily price history, which isn't available right now.")
    else:
        bench = perf["benchmark"]["name"] if perf.get("benchmark") else "the benchmark"
        lines.append(f"- Since {perf['start']} (each holding counted from its purchase date): **{perf['period_return']:+.1%}**")
        if perf["annualized_return"] is not None:
            lines.append(f"- That is about {perf['annualized_return']:+.1%} a year")
        if perf["benchmark_return"] is not None:
            ahead = "ahead of" if perf["excess_return"] >= 0 else "behind"
            lines.append(f"- The {bench} returned {perf['benchmark_return']:+.1%} over the same period, so the portfolio is "
                         f"**{abs(perf['excess_return']) * 100:.1f} points {ahead}** it")
        contrib = perf.get("contributions") or []
        up = [c for c in contrib if c["contribution"] > 0.0005][:3]
        down = [c for c in reversed(contrib) if c["contribution"] < -0.0005][:3]
        if up or down:
            said = [f"{c['ticker']} {_pts(c['contribution'])}" for c in up] + [f"{c['ticker']} {_pts(c['contribution'])}" for c in down]
            lines.append(f"- What drove it: {', '.join(said)}. A holding's contribution is its own return weighted by how "
                         "much of the portfolio it was, so the contributions add up to the total and a large holding moves it most")
            if up and perf["period_return"] > 0 and up[0]["contribution"] / perf["period_return"] > 0.6:
                lines.append(f"- {up[0]['ticker']} alone produced most of the gain, so the result depends heavily on one holding")
    m = a.get("movers") or {}
    if m.get("winners") or m.get("losers"):
        basis = "against what you paid" if m.get("basis") == "total" else "today"
        best = ", ".join(f"{x['ticker']} {x['change_pct']:+.1%}" for x in m.get("winners", []))
        worst = ", ".join(f"{x['ticker']} {x['change_pct']:+.1%}" for x in m.get("losers", []))
        lines.append(f"- Best and worst {basis}: " + "; ".join(p for p in [f"up {best}" if best else "", f"down {worst}" if worst else ""] if p))
    if perf and perf.get("period_return") is not None:
        lines.append("_These figures assume each holding was bought in full on its purchase date"
                     + (f" ({perf['default_start']} where none is set)._" if perf["assumed"] else "._"))
    return lines


def risk(a: dict, perf: dict | None, tolerance: str) -> list[str]:
    level, cap = a["risk_level"], a["risk_max"]
    fit = "within" if level <= cap else "above"
    lines = ["", "**Risk**",
             f"- Risk level: **{level}/5** ({a['risk_label']}), {fit} the {cap}/5 this app uses as the limit for a {tolerance} "
             "investor. It is the average of each holding's type, weighted by size: cash 1, bonds 2, real estate 3, broad and "
             "international stock funds 4, single stocks and sector funds 5"]
    cushion = sum(x["weight"] for x in a["allocation"] if x["name"] in ("Bonds", "Cash"))
    lines.append(f"- Bonds and cash are {cushion:.0%} of the portfolio. They usually fall less than stocks, so they soften a drop"
                 if cushion else "- There are no bonds or cash, so nothing in the portfolio is likely to hold steady when stocks fall")
    if perf and perf.get("period_return") is not None:
        bench = perf["benchmark"]["name"] if perf.get("benchmark") else "the benchmark"
        if perf["volatility"] is not None:
            v, bv = perf["volatility"], perf.get("benchmark_volatility")
            vs = f" against {bv:.1%} for the {bench}, about {v / bv:.1f}× as bumpy" if bv else ""
            lines.append(f"- Volatility: {v:.1%} a year{vs}. Volatility measures how much the value swings from day to day; "
                         "higher means a bumpier ride, in both directions")
        dd, bdd = perf["max_drawdown"], perf.get("benchmark_max_drawdown")
        vs = f" (the {bench}: {bdd:.1%})" if bdd is not None else ""
        lines.append(f"- Largest fall from a peak: {dd:.1%}{vs}. A fall that size from today's value would be about "
                     f"${abs(dd) * a['total_value']:,.0f}")
        if perf.get("sharpe") is not None:
            sh = perf["sharpe"]
            read = ("cash earning the assumed rate did better" if sh < 0 else "modest return for the swings taken" if sh < 1
                    else "a good return for the swings taken" if sh < 2 else "a very strong return for the swings taken")
            lines.append(f"- Sharpe ratio: {sh:.2f}: {read}. It is the return above cash ({perf['risk_free_rate']:.0%} a year "
                         "assumed) divided by the volatility; a short period can make it look unusually high or low")
    return lines


def fees(a: dict) -> list[str]:
    er = a["weighted_expense_ratio"]
    band = "low" if er < 0.001 else "typical" if er <= 0.005 else "high"
    lines = ["", "**Fees**",
             f"- About **${a['annual_fee']:,.2f} a year** ({er * 100:.2f}% weighted expense ratio), which is {band}: "
             f"${er * 10000:,.0f} a year for every $10,000 invested. Fund fees come out of the fund's value, so you never see "
             "a bill, but they lower your return every year"]
    paying = sorted((h for h in a["holdings"] if h["value"] and h.get("annual_fee")), key=lambda h: -h["annual_fee"])
    if paying:
        lines.append("- Largest fees: " + ", ".join(f"{h['ticker']} ${h['annual_fee']:,.2f}" for h in paying[:3]))
    return lines


def income(div: dict | None) -> list[str]:
    lines = ["", "**Dividend income**"]
    if div is None:
        lines.append("- Dividend history isn't available right now.")
    elif not div["total"]:
        lines.append("- None of your holdings paid dividends over the last 12 months.")
    else:
        lines.append(f"- Over the last 12 months your current shares would have received about **${div['total']:,.2f}**, a "
                     f"{div['yield']:.2%} yield on today's value")
        lines.append("- Largest payers: " + ", ".join(f"{d['ticker']} ${d['amount']:,.2f} ({d['yield']:.2%})"
                                                     for d in div["by_holding"][:3]))
        lines.append("- This is what was paid, not a forecast: companies can raise, cut or stop dividends")
    return lines


def report(a: dict, perf: dict | None, div: dict | None, sections: list[str], tolerance: str) -> str:
    lines = summary(a)
    if sections == SECTIONS or "performance" in sections:
        lines += holdings_table(a, perf)
    for k in sections:
        lines += {"diversification": lambda: diversification(a), "performance": lambda: performance(a, perf),
                  "risk": lambda: risk(a, perf, tolerance), "fees": lambda: fees(a), "income": lambda: income(div)}[k]()
    if a["warnings"]:
        lines += ["", "Things worth a closer look:"] + [f"- {w}" for w in a["warnings"][:5]]
        if any("of your portfolio" in w for w in a["warnings"]):
            lines += ["", CONCENTRATION_NOTE]
    return "\n".join(lines)
