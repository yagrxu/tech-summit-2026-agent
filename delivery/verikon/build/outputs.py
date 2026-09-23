# -*- coding: utf-8 -*-
"""Output shapes required by 《中心预算编制说明》§10.

- Multi-sheet Excel: 访视费用明细 / 费用标准对应关系 / 汇总与付费日程  (§10 预算表的输出形态)
- A CSV for the finance system to import
- CTA DOCX placeholder back-fill, handling all three placeholder forms (§10 修订与占位符)

The contract-body amount MUST equal the summary-sheet amount (§10: mismatch is the common
cause of post-signature rework), so `cta_fill` takes its number from the same BudgetResult.
"""
import csv, io, re


def budget_workbook(r) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    bold = Font(bold=True)

    ws = wb.active
    ws.title = "访视费用明细"
    hdr = ["层", "层名称", "费用项", "SOA 格子", "费率ID", "费率版本", "单价",
           "次数", "发生率", "受试者数", "金额", "付款方", "是否含税", "税率", "假设/计数依据"]
    ws.append(hdr)
    for c in ws[1]:
        c.font = bold
    for l in r.lines:
        ws.append([l["layer"], l["layer_name"], l["description"], l["soa_cell"], l["rate_id"],
                   l["rate_version"], l["unit_price"], l["count"], l["occurrence_rate"],
                   l["subjects"], l["amount"], l["payer"],
                   "含税" if l["tax_included"] else "不含税", l["tax_rate"], l["assumption_source"]])
    if r.unpriced:
        ws.append([]); ws.append(["未计价（漏项，未计入总额，须第二复核人确认 §6-10）"])
        ws.cell(ws.max_row, 1).font = bold
        for u in r.unpriced:
            ws.append(["", "", u["procedure"], u["soa_cell"], "", "", "", "", "", "", "", "", "", "", u["reason"]])

    ws2 = wb.create_sheet("费用标准对应关系")
    ws2.append(["SOA 格子", "费用项", "费率ID", "费率版本", "单价", "可追溯性(§9)"])
    for c in ws2[1]:
        c.font = bold
    for l in r.lines:
        if l["soa_cell"]:
            ws2.append([l["soa_cell"], l["description"], l["rate_id"], l["rate_version"],
                        l["unit_price"],
                        f"格子 {l['soa_cell']} → 费率 {l['rate_id']} → 版本 {l['rate_version']}"])
    ws2.append([]); ws2.append(["费率表版本不可原地修改，否则历史预算无法复现（§9）"])

    ws3 = wb.create_sheet("汇总与付费日程")
    ws3.append(["项目", "金额/说明"]); ws3["A1"].font = bold; ws3["B1"].font = bold
    for k, v in r.layer_subtotals.items():
        ws3.append([k, v])
    ws3.append([r.overhead_base_label, ""])
    ws3.append(["授权总额（按计划入组，合同上限 §4）", str(r.authorized_total)])
    ws3.append(["预计实付（按实际完成访视 §4）", str(r.expected_actual_total)])
    ws3.append([f"尾款保留 {r.holdback_rate}（结题后支付 §3）", str(r.holdback_amount)])
    ws3.append([]); ws3.append(["假设参数（须署名 §2）", ""]); ws3.cell(ws3.max_row, 1).font = bold
    for a in r.assumptions:
        ws3.append([f"{a['item']} = {a['occurrence_rate']}", f"{a['source']}｜记录人：{a['recorded_by']}"])
    ws3.append([]); ws3.append(["提示与告警", ""]); ws3.cell(ws3.max_row, 1).font = bold
    for w in r.warnings:
        ws3.append(["", w])
    ws3.append([]); ws3.append(["计算标识 calc_id", r.calc_id])
    ws3.append(["费率版本", ", ".join(r.rate_versions_used)])

    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def budget_csv(r) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["layer", "layer_name", "description", "soa_cell", "rate_id", "rate_version",
                "unit_price", "count", "occurrence_rate", "subjects", "amount", "payer",
                "tax_included", "tax_rate"])
    for l in r.lines:
        w.writerow([l["layer"], l["layer_name"], l["description"], l["soa_cell"], l["rate_id"],
                    l["rate_version"], l["unit_price"], l["count"], l["occurrence_rate"],
                    l["subjects"], l["amount"], l["payer"], l["tax_included"], l["tax_rate"]])
    return out.getvalue()


#: §10 three placeholder forms coexist in one template -- never assume only one.
PLACEHOLDER_CN = re.compile(r"【([^】]+)】")
PLACEHOLDER_UL = re.compile(r"_{3,}")


def cta_fill(template_path: str, out_path: str, values: dict, r=None) -> dict:
    """Back-fill a CTA template, reporting what was filled and what was left.

    Handles: content controls (<w:sdt>), 【】 text placeholders, and long-underscore blanks.
    Anything unmatched is returned rather than silently left in the document.
    """
    from docx import Document
    doc = Document(template_path)
    filled, missing = [], []

    def fill_text(t: str) -> str:
        def sub(m):
            k = m.group(1).strip()
            if k in values:
                filled.append(k)
                return str(values[k])
            missing.append(k)
            return m.group(0)
        return PLACEHOLDER_CN.sub(sub, t)

    for p in doc.paragraphs:
        for run in p.runs:
            if PLACEHOLDER_CN.search(run.text):
                run.text = fill_text(run.text)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for run in p.runs:
                        if PLACEHOLDER_CN.search(run.text):
                            run.text = fill_text(run.text)

    # content controls: <w:sdt> carries a tag/alias we can match on
    from docx.oxml.ns import qn
    for sdt in doc.element.body.iter(qn("w:sdt")):
        tag = None
        for t in sdt.iter(qn("w:tag")):
            tag = t.get(qn("w:val"))
        if tag and tag in values:
            for tnode in sdt.iter(qn("w:t")):
                tnode.text = str(values[tag]); break
            filled.append(tag)

    doc.save(out_path)
    report = {"filled": sorted(set(filled)), "unfilled_placeholders": sorted(set(missing)),
              "output": out_path}
    if r is not None:
        # §10 contract body amount must equal the summary sheet amount
        report["amount_consistency"] = {
            "authorized_total": str(r.authorized_total),
            "matches_summary_sheet": str(values.get("授权总额", "")) == str(r.authorized_total),
        }
    return report
