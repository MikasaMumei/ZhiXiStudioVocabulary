import hashlib
import io
import json
import random
import secrets
import zipfile
import subprocess
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from flask import render_template
from .content import initial, resolved
from .models import PrintJob, uid

MODES = {"study": "中英对照", "en-zh": "看英写中", "zh-en": "看中写英"}
LEGACY_MODES = {**MODES, "answers": "历史教师答案"}
pdf_lock = threading.BoundedSemaphore(1)


def displayed_document(job, mode):
    html = job.documents[mode]
    if mode == 'en-zh':
        # Only correct the known presentation labels, never vocabulary or checksum.
        html = html.replace(' · 看音写中</title>', ' · 看英写中</title>', 1)
        html = html.replace('<p class="metadata">看音写中', '<p class="metadata">看英写中', 1)
    return html


def render_pdf_export(job, mode=None):
    from flask import abort, current_app
    if not pdf_lock.acquire(blocking=False):
        abort(429, '已有 PDF 正在生成，请稍后重试。')
    try:
        selected = [mode] if mode else [k for k in MODES if k in job.documents]
        documents = {LEGACY_MODES[k]: displayed_document(job, k) for k in selected}
        result = subprocess.run(
            [sys.executable, '-m', 'englishwords.pdf_render'],
            input=json.dumps({'format': 'pdf' if mode else 'zip', 'documents': documents, 'checksum': job.checksum}).encode(),
            capture_output=True, timeout=90, check=True,
        )
        return result.stdout
    except (subprocess.SubprocessError, OSError):
        current_app.logger.error('PDF rendering failed for job %s', job.id)
        abort(503, '本次 PDF 未能生成。请缩小范围后重试，或联系管理员检查 PDF 排版组件。')
    finally:
        pdf_lock.release()


def create_print_job(records, form):
    if not records:
        raise ValueError("请选择至少一个词条。")
    if len(records) > 5000:
        raise ValueError("每份资料最多 5,000 条，请分组生成。")
    rows = [resolved(*r) for r in records]
    if any(not r["spelling"] or not r["meaning"] for r in rows):
        raise ValueError("选中词条缺少中文释义，请先补充后生成正式资料。")
    if form.get("dedupe"):
        # Preview lists retained and removed rows before this explicit choice.
        seen = set()
        rows = [r for r in rows if not (r["spelling"] in seen or seen.add(r["spelling"]))]
    seed = form.get("seed", "").strip() or secrets.token_hex(8)
    ranges = list(dict.fromkeys(f"{r['book']} · {r['edition']} / {r['section']}" for r in rows))
    order = form.get('order', 'shuffle' if form.get('shuffle') else 'original')
    grouping = form.get('grouping', 'section')
    if order not in ('original', 'alphabetical', 'shuffle') or grouping not in ('section', 'initial', 'none'):
        raise ValueError('排序或分组参数无效。')
    if grouping == 'initial' and order != 'alphabetical':
        rows.sort(key=lambda r: (initial(r['spelling']) == '#', initial(r['spelling'])))
    elif order == 'alphabetical':
        section_order = {key: i for i, key in enumerate(dict.fromkeys(r['section_id'] for r in rows))}
        rows.sort(key=lambda r: ((section_order[r['section_id']] if grouping == 'section' else 0), initial(r['spelling']) == '#', r['spelling'].casefold(), r['spelling']))
    if order == 'shuffle':
        rng = random.Random(seed)
        if grouping in ('section', 'initial'):
            grouped = {}
            for row in rows:
                key = initial(row['spelling']) if grouping == 'initial' else row['section_id']
                grouped.setdefault(key, []).append(row)
            rows = []
            for group in grouped.values():
                rng.shuffle(group)
                rows.extend(group)
        else:
            rng.shuffle(rows)
    options = {"size": form.get("size", "compact"), "columns": form.get("columns", "2"),
               "break_sections": bool(form.get("break_sections")), "examples": bool(form.get("examples")),
               "phonetic_en_test": True, "zh_en_layout": form.get('zh_en_layout', 'three'),
               "shuffle": order == 'shuffle', "seed": seed,
               "order": order, "grouping": grouping, "density": form.get('density', 'compact'),
               "dedupe": bool(form.get("dedupe")), "accept_missing": True}
    if options["size"] not in ("large", "standard", "compact") or options["columns"] not in ("1", "2") or options['density'] not in ('compact', 'comfortable'):
        raise ValueError("排版参数无效。")
    if options['zh_en_layout'] not in ('three', 'phonetic', 'wide'):
        raise ValueError('看中写英排版参数无效。')
    title = form.get("title", "").strip()[:200] or "智习工作室词表"
    job_id = uid()
    snapshot = {"version": 1, "template": "2.3", "id": job_id, "title": title, "created_at": datetime.now(timezone.utc).isoformat(), "ranges": ranges, "options": options, "rows": rows}
    groups = []
    for number, row in enumerate(rows, 1):
        if grouping == 'initial':
            key, label = initial(row['spelling']), initial(row['spelling'])
        elif grouping == 'section':
            key, label = row['section_id'], f"{row['book']} · {row['edition']} / {row['section']}"
        else:
            key, label = 'combined', '组合词表'
        if not groups or groups[-1]['key'] != key:
            groups.append({'key': key, 'label': label, 'rows': []})
        groups[-1]['rows'].append({'number': number, **row})
    css = (Path(__file__).parent / "static" / "print.css").read_text()
    documents = {mode: render_template("print.html", snapshot=snapshot, mode=mode, mode_title=label, css=css, rows=rows, groups=groups, options=options) for mode, label in MODES.items()}
    checksum = hashlib.sha256(json.dumps({"snapshot": snapshot, "documents": documents}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return PrintJob(id=job_id, title=title, snapshot=snapshot, documents=documents, checksum=checksum)


def print_zip(job):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for mode, label in MODES.items():
            if mode in job.documents:
                archive.writestr(f"{label}.html", displayed_document(job, mode))
        archive.writestr("snapshot.json", json.dumps(job.snapshot, ensure_ascii=False, indent=2))
        archive.writestr("README.txt", "解压全部文件后打开所需 HTML。A4、缩放 100%、关闭浏览器页眉页脚，打印或另存 PDF。三种资料使用相同内容及编号，中英对照可用于核对。\n资料校验值：" + job.checksum)
        for path in (Path(__file__).parent / "static" / "fonts").glob("*"):
            archive.write(path, "assets/" + path.name)
    return buffer.getvalue()


def warnings(records):
    rows = [resolved(*r) for r in records]
    spelling_counts = Counter(r["spelling"] for r in rows)
    meanings = {}
    removed, seen = [], set()
    for row in rows:
        meanings.setdefault(row["meaning"], set()).add(row["spelling"])
        if row["spelling"] in seen:
            removed.append(row)
        seen.add(row["spelling"])
    return {"missing_us": sum(not r["us"] for r in rows),
            "missing_phrase_us": sum(not resolved(*r)["us"] and (r[1].kind == "phrase" or " " in r[1].spelling) for r in records),
            "missing_meaning": sum(not r["meaning"] for r in rows),
            "pending": sum(r["status"] != "reviewed" for r in rows), "duplicates": [s for s, n in spelling_counts.items() if n > 1],
            "ambiguous": {m: sorted(v) for m, v in meanings.items() if m and len(v) > 1}, "removed": removed, "rows": rows}
