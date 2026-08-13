# 运行前安装：pip install polib pandas openpyxl
import polib
import pandas as pd
import openpyxl


def export_label_langs(po_path='locale/en/LC_MESSAGES/django.po', out_path='workflow-engine_多语言对照表.xlsx'):
    """导出 po 中的 msgid/msgstr 到 Excel 对照表。"""
    po = polib.pofile(po_path)
    data = []
    for entry in po:
        data.append({
            '中文 (msgid)': entry.msgid,
            '英文 (msgstr)': entry.msgstr,
            '所在位置': entry.occurrences,
        })

    df = pd.DataFrame(data)
    df.to_excel(out_path, index=False)
    print(f"对照表已导出 -> {out_path}")


def import_label_langs(excel_path: str, po_path='locale/en/LC_MESSAGES/django.po', msgid_col='中文 (msgid)', msgstr_col='英文 (msgstr)'):
    """从 Excel 对照表导入翻译，更新指定 po 文件的 msgstr。

    excel_path: 包含 msgid/msgstr 的表格路径。
    po_path: 目标 po 文件路径。
    msgid_col/msgstr_col: 列名映射。
    """
    df = pd.read_excel(excel_path)
    po = polib.pofile(po_path)

    translations = {}
    for _, row in df.iterrows():
        msgid = row.get(msgid_col)
        msgstr = row.get(msgstr_col)
        if pd.isna(msgid) or msgid is None:
            continue
        # 允许空字符串清空翻译；跳过 NaN
        if pd.isna(msgstr):
            continue
        translations[str(msgid)] = str(msgstr)

    updated = 0
    for entry in po:
        if entry.msgid in translations:
            entry.msgstr = translations[entry.msgid]
            updated += 1

    po.save(po_path)
    print(f"导入完成：更新 {updated} 条翻译 -> {po_path}")
    return updated