# -*- coding: utf-8 -*-
"""Clinical site-budget engine for 维立康 (Project SOAR).

Implements 《中心预算编制说明》v3.2 節選. Every rule below is traceable to a section:

  §2  cycle expansion; cells are counts not ticks; conditional procedures need an
      occurrence rate AND a recorded assumption source
  §3  six cost layers in a fixed order; overhead base must be printed explicitly;
      every line carries a payer so the site-budget total only sums 中心结算 lines
  §4  authorized total (planned enrolment) and expected actual (completed visits) are
      two different numbers and both must be produced
  §5  every amount carries tax_included + tax_rate
  §8  amendment cascade; §10 recalculation baseline is the site's last SIGNED version
  §9  each amount answers: which SOA cell, which rate table, which version of it.
      Rate versions are immutable — never edited in place, or history can't be reproduced.

Design note: an unpriced procedure is NEVER silently treated as 0. It is reported in
`unpriced` and excluded from totals, because a silent zero is exactly the "漏项" that
§6 step 10 (第二复核人) exists to catch. The supplied synthetic sample deliberately
omits rates for 生命体征 / 研究药物给药 / PK样本采集.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_HALF_UP

CYCLE_VISIT = re.compile(r"^C(\d+)D(\d+)$")

# §3 the six layers, in order. Order is part of the spec, not an implementation detail.
LAYERS = {
    1: "受试者层直接费用",
    2: "研究者劳务费",
    3: "方案层固定费用",
    4: "pass-through",
    5: "受试者补贴",
    6: "管理费 Overhead",
}
PAYER_SITE = "中心结算"          # §3 only these roll up into the site budget
PAYER_SPONSOR = "申办方直付"
PAYER_SUBJECT = "受试者"


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Line:
    """One priced row. Carries its own provenance (§9) and tax口径 (§5)."""
    layer: int
    description: str
    soa_cell: str | None            # §9 which SOA cell
    rate_id: str | None             # §9 which rate
    rate_version: str | None        # §9 which version of the rate table
    unit_price: Decimal
    count: Decimal                  # §2 a count, not a tick
    occurrence_rate: Decimal        # §2 conditional procedures < 1.0
    assumption_source: str | None    # §2 auditors check that an assumption has an owner
    payer: str
    tax_included: bool
    tax_rate: Decimal
    subjects: Decimal = Decimal(1)

    @property
    def amount(self) -> Decimal:
        return money(self.unit_price * self.count * self.occurrence_rate * self.subjects)

    def to_dict(self):
        d = asdict(self)
        d.update({k: str(v) for k, v in d.items() if isinstance(v, Decimal)})
        d["layer_name"] = LAYERS[self.layer]
        d["amount"] = str(self.amount)
        return d


@dataclass
class BudgetResult:
    site_code: str
    study_number: str
    visits_expanded: list
    lines: list
    unpriced: list
    layer_subtotals: dict
    overhead_base_layers: list
    overhead_base_label: str
    overhead_rate: Decimal
    overhead_amount: Decimal
    authorized_total: Decimal
    expected_actual_total: Decimal
    holdback_rate: Decimal
    holdback_amount: Decimal
    assumptions: list
    warnings: list
    rate_versions_used: list
    calc_id: str


def expand_visits(study: dict, visits: list) -> list:
    """§2 third error: compressed columns must be expanded first.

    `Cycle 1-6, Day 1/8/15` reads as 3 columns but is 18 visits. A visit whose id looks
    like C<c>D<d> is a cycle template and is expanded over cycles x days_per_cycle.
    """
    cycles = int(study.get("cycles") or 1)
    days = list(study.get("days_per_cycle") or [1])
    out = []
    for v in visits:
        m = CYCLE_VISIT.match(str(v.get("visit_id", "")))
        if not m:
            out.append({**v, "instance_id": v["visit_id"], "cycle": None, "day": None})
            continue
        for c in range(1, cycles + 1):
            for d in days:
                out.append({**v, "instance_id": f"C{c}D{d}",
                            "visit_name": f"第 {c} 周期第 {d} 天",
                            "cycle": c, "day": d, "expanded_from": v["visit_id"]})
    return out


def _counts_for(visit: dict, proc: str) -> tuple[Decimal, str]:
    """§2 first error: a cell may hold a number of timepoints, not a tick.

    blood_draw_points drives per-timepoint billing for sampling procedures; each point is
    charged separately, so treating it as one tick under-counts.
    """
    pts = int(visit.get("blood_draw_points") or 0)
    if pts and re.search(r"(PK|采血|血样|样本采集)", proc):
        return Decimal(pts), f"blood_draw_points={pts}（每时间点单独计费 §2）"
    return Decimal(1), "每次访视 1 次"


def build_budget(payload: dict, *, params: dict | None = None) -> BudgetResult:
    p = params or {}
    study = payload.get("study") or {}
    site = payload.get("site") or {}
    subjects = Decimal(str(study.get("subject_count") or 0))

    rates = {}
    for r in payload.get("rates") or []:
        rates[r["activity_name"]] = r
    rate_versions = sorted({r.get("rate_version") for r in (payload.get("rates") or []) if r.get("rate_version")})

    visits = expand_visits(study, payload.get("visits") or [])

    # §2 conditional procedures: rate must be supplied WITH a recorded source.
    conditional = {k: (Decimal(str(v["rate"])), v["source"])
                   for k, v in (p.get("conditional_rates") or {}).items()}
    tax_included = bool(p.get("tax_included", False))
    tax_rate = Decimal(str(p.get("tax_rate", "0.06")))

    lines: list[Line] = []
    unpriced: list[dict] = []
    warnings: list[str] = []
    assumptions: list[dict] = []

    # ---- layer 1: per-subject direct procedure costs -------------------------
    for v in visits:
        for proc in v.get("procedures") or []:
            cell = f"{v['instance_id']}×{proc}"
            r = rates.get(proc)
            count, count_basis = _counts_for(v, proc)
            occ, src = conditional.get(proc, (Decimal(1), None))
            if occ != 1 and src:
                assumptions.append({"item": proc, "occurrence_rate": str(occ),
                                    "source": src, "recorded_by": p.get("assumption_owner", "未指定")})
            if not r:
                # never silently zero (§6 step 10)
                unpriced.append({"soa_cell": cell, "procedure": proc,
                                 "reason": "费率表中无此项，未计入总额，需补费率或确认付款方"})
                continue
            lines.append(Line(
                layer=1, description=proc, soa_cell=cell,
                rate_id=r.get("rate_id"), rate_version=r.get("rate_version"),
                unit_price=money(r["unit_price"]), count=count, occurrence_rate=occ,
                assumption_source=src or count_basis,
                payer=p.get("payer_overrides", {}).get(proc, PAYER_SITE),
                tax_included=tax_included, tax_rate=tax_rate, subjects=subjects))

    # ---- layer 2: investigator / CRC time, scales with visit count ----------
    if p.get("investigator_fee_per_visit"):
        lines.append(Line(
            layer=2, description="研究者与 CRC 劳务费", soa_cell=None,
            rate_id=p.get("investigator_rate_id"), rate_version=p.get("investigator_rate_version"),
            unit_price=money(p["investigator_fee_per_visit"]), count=Decimal(len(visits)),
            occurrence_rate=Decimal(1), assumption_source=f"访视数={len(visits)}（展开后）",
            payer=PAYER_SITE, tax_included=tax_included, tax_rate=tax_rate, subjects=subjects))

    # ---- layer 3: protocol-level fixed fees (independent of enrolment) ------
    for name, amt in (p.get("fixed_fees") or {}).items():
        lines.append(Line(layer=3, description=name, soa_cell=None, rate_id=None,
                          rate_version=None, unit_price=money(amt), count=Decimal(1),
                          occurrence_rate=Decimal(1), assumption_source="方案层固定费用，与入组人数无关",
                          payer=PAYER_SITE, tax_included=tax_included, tax_rate=tax_rate,
                          subjects=Decimal(1)))

    # ---- layer 4: pass-through (reimbursed at cost) -------------------------
    for name, amt in (p.get("pass_through") or {}).items():
        lines.append(Line(layer=4, description=name, soa_cell=None, rate_id=None,
                          rate_version=None, unit_price=money(amt), count=Decimal(1),
                          occurrence_rate=Decimal(1), assumption_source="实报实销预留",
                          payer=PAYER_SITE, tax_included=tax_included, tax_rate=tax_rate,
                          subjects=Decimal(1)))

    # ---- layer 5: subject stipends — payer is the subject, not the site -----
    if p.get("subject_stipend_per_visit"):
        lines.append(Line(layer=5, description="受试者补贴（交通/误工/住宿）", soa_cell=None,
                          rate_id=None, rate_version=None,
                          unit_price=money(p["subject_stipend_per_visit"]),
                          count=Decimal(len(visits)), occurrence_rate=Decimal(1),
                          assumption_source=f"访视数={len(visits)}",
                          payer=PAYER_SUBJECT, tax_included=tax_included,
                          tax_rate=Decimal(0), subjects=subjects))

    # §3 screen failures and unscheduled visits are separate, rate-driven reserves
    if p.get("screen_failure_rate") and p.get("screening_visit_cost"):
        sf = Decimal(str(p["screen_failure_rate"]))
        assumptions.append({"item": "筛选失败率", "occurrence_rate": str(sf),
                            "source": p.get("screen_failure_source", "人工设定，需记录依据"),
                            "recorded_by": p.get("assumption_owner", "未指定")})
        lines.append(Line(layer=1, description="筛选失败预留", soa_cell=None, rate_id=None,
                          rate_version=None, unit_price=money(p["screening_visit_cost"]),
                          count=Decimal(1), occurrence_rate=sf,
                          assumption_source="筛失人数 × 筛选访视费用（筛失率人工设定 §3）",
                          payer=PAYER_SITE, tax_included=tax_included, tax_rate=tax_rate,
                          subjects=subjects))

    # ---- subtotals; only 中心结算 rolls into the site budget (§3) ------------
    sub = {i: Decimal(0) for i in LAYERS}
    for ln in lines:
        if ln.payer == PAYER_SITE:
            sub[ln.layer] += ln.amount
    excluded = sum((ln.amount for ln in lines if ln.payer != PAYER_SITE), Decimal(0))
    if excluded:
        warnings.append(f"已排除非中心结算金额 {excluded}（付款方≠中心结算，§3）")

    # ---- layer 6: overhead. The base, not the rate, is the negotiation point.
    base_layers = [int(x) for x in (p.get("overhead_base_layers") or [1, 2])]
    overhead_rate = Decimal(str(p.get("overhead_rate", "0.25")))
    base_amount = sum((sub[i] for i in base_layers), Decimal(0))
    overhead = money(base_amount * overhead_rate)
    sub[6] = overhead
    base_label = (f"管理费基数 = 第 {min(base_layers)} 层至第 {max(base_layers)} 层"
                  f"（{'+'.join(str(i) for i in base_layers)}）= {base_amount}"
                  f"；比例 {overhead_rate * 100}%")
    if 4 in base_layers:
        warnings.append("管理费基数含第 4 层 pass-through —— 通常不计入，需与机构书面确认（§3）")
    if 5 in base_layers:
        warnings.append("管理费基数含第 5 层受试者补贴 —— 通常不计入（§3）")
    if 3 in base_layers:
        warnings.append("管理费基数含第 3 层固定费 —— 存在争议，部分机构认为启动费已含管理成本（§3）")

    authorized = money(sum(sub.values()))

    # §4 expected actual: planned enrolment vs completed visits are different numbers
    completion = Decimal(str(p.get("expected_completion_rate", "1")))
    if completion != 1:
        assumptions.append({"item": "预计完成率（脱落/入组不足）", "occurrence_rate": str(completion),
                            "source": p.get("completion_source", "历史数据或人工假设，需记录依据"),
                            "recorded_by": p.get("assumption_owner", "未指定")})
    enrol_scaled = sum((sub[i] for i in (1, 2, 5)), Decimal(0)) * completion
    fixed_part = sum((sub[i] for i in (3, 4)), Decimal(0))
    actual_base = sum(((sub[i] * completion if i in (1, 2) else sub[i]) for i in base_layers), Decimal(0))
    expected_actual = money(enrol_scaled + fixed_part + money(actual_base * overhead_rate))

    holdback_rate = Decimal(str(p.get("holdback_rate", "0.10")))
    if not (Decimal("0.05") <= holdback_rate <= Decimal("0.10")):
        warnings.append(f"尾款保留 {holdback_rate} 超出常见 5%~10% 区间（§3）")

    if unpriced:
        warnings.append(f"{len(unpriced)} 个 SOA 格子无对应费率，已列入 unpriced 且未计入总额 —— "
                        f"漏项须由第二复核人确认（§6 步骤 10）")
    if not tax_included:
        warnings.append("金额按不含税编制；医院常按含税报价，签署前须对齐口径，否则财务无法入账（§5）")

    payload_key = json.dumps({"payload": payload, "params": p}, sort_keys=True,
                             ensure_ascii=False, default=str)
    calc_id = hashlib.sha256(payload_key.encode()).hexdigest()[:16]

    return BudgetResult(
        site_code=site.get("site_code", ""), study_number=study.get("study_number", ""),
        visits_expanded=[{"instance_id": v["instance_id"], "visit_name": v.get("visit_name"),
                          "cycle": v.get("cycle"), "day": v.get("day"),
                          "expanded_from": v.get("expanded_from")} for v in visits],
        lines=[ln.to_dict() for ln in lines], unpriced=unpriced,
        layer_subtotals={f"{i}:{LAYERS[i]}": str(sub[i]) for i in LAYERS},
        overhead_base_layers=base_layers, overhead_base_label=base_label,
        overhead_rate=overhead_rate, overhead_amount=overhead,
        authorized_total=authorized, expected_actual_total=expected_actual,
        holdback_rate=holdback_rate, holdback_amount=money(authorized * holdback_rate),
        assumptions=assumptions, warnings=warnings, rate_versions_used=rate_versions,
        calc_id=calc_id)


def amendment_impact(old: BudgetResult, new: BudgetResult, changed_procedures: list) -> dict:
    """§8/§10 the baseline is the site's LAST SIGNED version, never the first draft.

    Returns the affected SOA cells so a recalculation can be scoped to the sites that
    actually contain the changed procedures — instead of re-signing all 40-50 sites
    because nobody could prove which ones were affected.
    """
    changed = set(changed_procedures)
    # Scan BOTH versions: a REMOVED procedure is absent from `new`, so scanning only the
    # new lines would report "not affected" while the total moved -- which is precisely the
    # "couldn't prove which sites were affected" failure that caused the all-sites re-sign.
    affected = sorted({l["soa_cell"] for l in (list(old.lines) + list(new.lines))
                       if l["description"] in changed and l["soa_cell"]})
    added = {l["description"] for l in new.lines} - {l["description"] for l in old.lines}
    removed = {l["description"] for l in old.lines} - {l["description"] for l in new.lines}
    delta = money(Decimal(new.authorized_total) - Decimal(old.authorized_total))
    return {
        "baseline_calc_id": old.calc_id, "baseline_note": "基准为该中心上一版已签署版本（§10）",
        "new_calc_id": new.calc_id,
        "affected": bool(affected), "affected_cells": affected,
        "changed_procedures": sorted(changed),
        "procedures_added": sorted(added), "procedures_removed": sorted(removed),
        "authorized_delta": str(delta),
        "requires_recalculation": bool(affected) or delta != 0,
        "unpriced_delta": len(new.unpriced) - len(old.unpriced),
        "no_change_note": None if (affected or delta) else
            "本中心不含被修改程序且金额未变 —— 无需重签（§8：换预算附件+双方书面确认即可）",
    }
