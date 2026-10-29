from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO
import json
import csv
import re
import threading
import time

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, send_file, session, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, DataError
from xml.etree.ElementTree import ParseError
from werkzeug.security import check_password_hash

from .content import FIELDS, bump, clean, entries, initial, resolved, stamp
from .importing import ALIASES, LABELS, apply_plan, default_mapping, digest, export_xlsx, make_plan, parse_files
from .models import Book, ImportBatch, Item, PrintJob, Section, Term
from .printing import MODES, create_print_job, displayed_document, print_zip, render_pdf_export, warnings

bp = Blueprint("web", __name__)
attempts = defaultdict(deque)
attempt_lock = threading.Lock()


def write_lock():
    # One small installation; serialize writers so previews and multi-row moves are safe.
    g.db.execute(text("SELECT pg_advisory_xact_lock(249105107)"))


def get_or_404(model, identifier):
    value = g.db.get(model, identifier)
    if value is None:
        abort(404)
    return value


def check_revision(obj):
    if request.form.get("revision") != str(obj.revision):
        abort(409, "页面内容已过期，请刷新后重试。")


def positive_position(value, default=1):
    number = int(value or default)
    if not 1 <= number <= 1000000:
        raise ValueError("顺序须为 1～1,000,000 的整数。")
    return number


@bp.before_request
def protect():
    if request.endpoint not in ("web.login", "web.health") and not session.get("authenticated"):
        return redirect(url_for("web.login"))
    if request.method == "POST" and request.endpoint not in ("web.login", "web.logout"):
        write_lock()


@bp.errorhandler(ValueError)
def invalid(error):
    g.db.rollback()
    return render_template("error.html", error={"code": 400, "description": str(error)}), 400


@bp.errorhandler(IntegrityError)
def duplicate(error):
    g.db.rollback()
    return render_template("error.html", error={"code": 409, "description": "数据编号重复或已经被修改，请刷新后检查。"}), 409


@bp.errorhandler(DataError)
def invalid_database_value(error):
    g.db.rollback()
    return render_template("error.html", error={"code": 400, "description": "字段过长或格式不正确，请检查书本信息、年级和顺序。"}), 400


@bp.route("/health")
def health():
    g.db.execute(text("SELECT 1"))
    return {"status": "ok"}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        key, now = request.remote_addr, time.monotonic()
        with attempt_lock:
            queue = attempts[key]
            while queue and queue[0] < now - 900:
                queue.popleft()
            if len(queue) >= 10:
                abort(429, "尝试次数过多，请 15 分钟后重试。")
            queue.append(now)
        if check_password_hash(current_app.config["ADMIN_PASSWORD_HASH"], request.form.get("password", "")):
            session.clear()
            session["authenticated"] = True
            session.permanent = True
            with attempt_lock:
                attempts.pop(key, None)
            return redirect(url_for("web.home"))
        flash("密码不正确，请重试。", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.login"))


@bp.get("/")
def home():
    books = g.db.scalars(select(Book).order_by(Book.created_at.desc())).all()
    counts = dict(g.db.execute(select(Section.book_id, func.count(Item.id)).join(Item, Item.section_id == Section.id).where(Item.status != "archived").group_by(Section.book_id)).all())
    query = clean(request.args.get("q"))
    stage = request.args.get("stage", "")
    if query:
        books = [b for b in books if query.lower() in " ".join((b.title, b.code, b.edition, b.publisher, b.grade)).lower()]
    if stage:
        books = [b for b in books if b.stage == stage]
    return render_template("home.html", books=books, counts=counts, q=query, stage=stage)


@bp.route("/books/new", methods=["GET", "POST"])
@bp.route("/books/<book_id>/edit", methods=["GET", "POST"])
def book_edit(book_id=None):
    book = get_or_404(Book, book_id) if book_id else None
    if request.method == "POST":
        if book:
            check_revision(book)
        else:
            book = Book()
            g.db.add(book)
        for field in ("code", "title", "stage", "grade", "publisher", "edition", "volume", "tags"):
            setattr(book, field, clean(request.form.get(field)))
        if not book.title or not book.code or len(book.code) > 100:
            raise ValueError("请填写书名和不超过 100 字符的书本编号。")
        book.edition = book.edition or "未核实"
        if book_id:
            bump(book)
        g.db.commit()
        return redirect(url_for("web.book_detail", book_id=book.id))
    return render_template("book_edit.html", book=book)


@bp.get("/books/<book_id>")
def book_detail(book_id):
    book = get_or_404(Book, book_id)
    sections = g.db.scalars(select(Section).where(Section.book_id == book.id).order_by(Section.position, Section.created_at)).all()
    needs = request.args.get("needs", "")
    records = entries(g.db, book.id, include_archived=needs == "archived")
    rows = [resolved(*r) for r in records]
    q = clean(request.args.get("q"))
    section_id = request.args.get("section", "")
    needs = request.args.get("needs", "")
    rows = [r for r in rows if (not q or q.lower() in (r["spelling"] + r["meaning"]).lower()) and (not section_id or r["section_id"] == section_id)]
    if needs == "us":
        rows = [r for r in rows if not r["us"]]
    elif needs == "meaning":
        rows = [r for r in rows if not r["meaning"]]
    elif needs == "review":
        rows = [r for r in rows if r["status"] != "reviewed"]
    elif needs == "archived":
        rows = [r for r in rows if r["status"] == "archived"]
    letters = {letter: sum(initial(r['spelling']) == letter for r in rows) for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ#'}
    selected_initial = request.args.get('initial', '')
    if selected_initial:
        rows = [r for r in rows if initial(r['spelling']) == selected_initial]
    sort = request.args.get('sort', 'original')
    if sort == 'alphabetical':
        rows.sort(key=lambda r: (initial(r['spelling']) == '#', r['spelling'].casefold(), r['spelling']))
    return render_template("book.html", book=book, sections=sections, rows=rows, q=q, selected_section=section_id, needs=needs,
                           total=len(records), letters=letters, selected_initial=selected_initial, sort=sort,
                           targets=g.db.scalars(select(Book).where(Book.id != book.id)).all())


@bp.post("/books/<book_id>/sections")
def sections_edit(book_id):
    book = get_or_404(Book, book_id)
    check_revision(book)
    title = clean(request.form.get("title"))
    if not title:
        raise ValueError("请输入章节名称。")
    section_id = request.form.get("section_id")
    if section_id:
        section = get_or_404(Section, section_id)
        if section.book_id != book.id:
            abort(400)
        if g.db.scalar(select(Section).where(Section.book_id == book.id, Section.title == title, Section.id != section.id)):
            raise ValueError("已有同名章节，请使用不同名称。")
        section.title = title
        section.position = positive_position(request.form.get("position"), section.position)
    else:
        if g.db.scalar(select(Section).where(Section.book_id == book.id, Section.title == title)):
            raise ValueError("已有同名章节，请直接选用。")
        n = g.db.scalar(select(func.count()).select_from(Section).where(Section.book_id == book.id))
        g.db.add(Section(book_id=book.id, code="section-" + digest((title, book.revision))[:16], title=title, position=positive_position(request.form.get("position"), n + 1)))
    bump(book)
    g.db.commit()
    return redirect(url_for("web.book_detail", book_id=book.id))


@bp.post("/books/<book_id>/bulk")
def bulk(book_id):
    book = get_or_404(Book, book_id)
    check_revision(book)
    action = request.form.get("action")
    records = entries(g.db, book.id, include_archived=action == "restore")
    ids = set(request.form.getlist("item_id"))
    if request.form.get("range_start") or request.form.get("range_end"):
        start, end = int(request.form.get("range_start") or 1), int(request.form.get("range_end") or len(records))
        if not 1 <= start <= end <= len(records):
            raise ValueError("行号范围无效，行号以整本书当前顺序为准。")
        ids.update(r[0].id for r in records[start - 1:end])
    selected = [r for r in records if r[0].id in ids]
    if not selected or len(selected) != len(ids):
        raise ValueError("请选择本书中有效的词条。")
    action = request.form.get("action")
    if action == "copy":
        target = get_or_404(Book, request.form.get("target"))
        if target.id == book.id:
            raise ValueError("请选择另一本复习词表。")
        section = Section(book_id=target.id, code="copy-" + digest((book.id, time.time()))[:16], title=clean(request.form.get("section_title")) or "选词复习", position=1 + g.db.scalar(select(func.count()).select_from(Section).where(Section.book_id == target.id)))
        g.db.add(section)
        g.db.flush()
        for i, record in enumerate(selected, 1):
            item, term, old_section, old_book = record
            values = resolved(*record)
            g.db.add(Item(section_id=section.id, term_id=term.id, position=i, **{k: values[k] for k in FIELDS}, pos=item.pos,
                          notes=item.notes, status=item.status, origin_id=item.id, provenance={**item.provenance, "copy": {**stamp(), "origin_revision": item.revision}}))
        bump(target)
    else:
        target_section = None
        if action == "group":
            title = clean(request.form.get("section_title"))
            if not title:
                raise ValueError("请输入目标章节名称。")
            target_section = g.db.scalar(select(Section).where(Section.book_id == book.id, Section.title == title))
            if not target_section:
                target_section = Section(book_id=book.id, code="section-" + digest((title, book.revision))[:16], title=title, position=1 + g.db.scalar(select(func.count()).select_from(Section).where(Section.book_id == book.id)))
                g.db.add(target_section)
                g.db.flush()
        if action not in ("group", "review", "archive", "restore"):
            raise ValueError("批量操作无效。")
        for i, (item, term, section, _) in enumerate(selected, 1):
            if action == "group":
                item.section_id = target_section.id
                item.position = i + 100000
            elif action == "review":
                if not resolved(item, term, section, book)["meaning"]:
                    raise ValueError("有词条缺中文释义，请先补充。")
                item.status = "reviewed"
            elif action == "archive":
                item.status = "archived"
            else:
                item.status = "pending"
            item.revision += 1
            item.provenance = {**item.provenance, action: stamp()}
        g.db.flush()
        if target_section:
            for i, (item, *_rest) in enumerate(entries(g.db, book.id), 1):
                if item.section_id == target_section.id:
                    item.position = i
        bump(book)
    g.db.commit()
    flash(f"已处理 {len(selected)} 条词条。", "success")
    return redirect(url_for("web.book_detail", book_id=book.id))


@bp.route("/books/<book_id>/items/new", methods=["GET", "POST"])
@bp.route("/items/<item_id>/edit", methods=["GET", "POST"])
def item_edit(book_id=None, item_id=None):
    if item_id:
        item = get_or_404(Item, item_id)
        section = get_or_404(Section, item.section_id)
        book = get_or_404(Book, section.book_id)
        term = get_or_404(Term, item.term_id)
    else:
        book, item, term = get_or_404(Book, book_id), None, None
    sections = g.db.scalars(select(Section).where(Section.book_id == book.id).order_by(Section.position)).all()
    if request.method == "POST":
        if item:
            check_revision(item)
        if request.form.get("book_revision") != str(book.revision):
            abort(409, "书本已改变，请刷新后重试。")
        selected = get_or_404(Section, request.form.get("section_id"))
        if selected.book_id != book.id:
            abort(400)
        spelling = clean(request.form.get("spelling"))
        if not spelling:
            raise ValueError("请填写单词。")
        term = g.db.scalar(select(Term).where(Term.spelling == spelling))
        if not term:
            term = Term(spelling=spelling, kind="phrase" if " " in spelling else "word")
            g.db.add(term)
            g.db.flush()
        if not item:
            item = Item()
            g.db.add(item)
        item.section_id, item.term_id = selected.id, term.id
        provenance = dict(item.provenance or {})
        for field in FIELDS:
            # Explicit inherit is separate from explicitly blank.
            value = None if request.form.get("inherit_" + field) else clean(request.form.get(field))
            setattr(item, field, value)
            provenance[field] = stamp()
        item.pos, item.notes = clean(request.form.get("pos")), clean(request.form.get("notes"))
        item.position = positive_position(request.form.get("position"))
        item.status = "reviewed" if request.form.get("reviewed") else "pending"
        if item.status == "reviewed" and not (item.meaning if item.meaning is not None else term.meaning):
            raise ValueError("中文释义为空，不能标记已校对。")
        item.provenance = provenance
        item.revision = item.revision + 1 if item_id else 1
        bump(book)
        g.db.commit()
        return redirect(url_for("web.book_detail", book_id=book.id))
    return render_template("item_edit.html", item=item, term=term, book=book, sections=sections, fields=FIELDS, labels=LABELS)


@bp.get("/books/<book_id>/export.xlsx")
def book_export(book_id):
    get_or_404(Book, book_id)
    return send_file(BytesIO(export_xlsx(entries(g.db, book_id))), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name="englishwords.xlsx")


@bp.route("/dictionary", methods=["GET", "POST"])
def dictionary():
    if request.method == "POST":
        spelling = clean(request.form.get("spelling"))
        if not spelling:
            raise ValueError("请填写单词。")
        term_id = request.form.get("term_id")
        term = get_or_404(Term, term_id) if term_id else g.db.scalar(select(Term).where(Term.spelling == spelling))
        if term_id and spelling != term.spelling:
            raise ValueError("修改词形请新增词典条目，并在对应课程中重新选择；此处仅修改词义与读音。")
        if term:
            if request.form.get("revision") != str(term.revision):
                abort(409, "公共词典已改变，请刷新后重试。")
        else:
            term = Term(spelling=spelling, kind="phrase" if " " in spelling else "word")
            g.db.add(term)
        for field in FIELDS:
            setattr(term, field, clean(request.form.get(field)))
        term.provenance = {field: stamp() for field in FIELDS}
        term.revision = (term.revision or 0) + 1
        g.db.commit()
        flash("公共词典已更新；课程覆盖值与历史打印资料保持原版。", "success")
        return redirect(url_for("web.dictionary", q=spelling))
    q = clean(request.args.get("q"))
    query = select(Term).order_by(Term.spelling)
    if q:
        query = query.where(Term.spelling.ilike("%" + q.replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
    terms = g.db.scalars(query.limit(100)).all()
    editing = g.db.get(Term, request.args.get("edit")) if request.args.get("edit") else None
    return render_template("dictionary.html", terms=terms, editing=editing, q=q, fields=FIELDS, labels=LABELS)


@bp.route("/imports", methods=["GET", "POST"])
def imports():
    if request.method == "POST":
        try:
            files, raw = parse_files(request.files.getlist("files"))
        except (UnicodeError, KeyError, OSError, zipfile.BadZipFile, ParseError, csv.Error) as error:
            raise ValueError("无法读取文件，请检查格式和编码。") from error
        batch = ImportBatch(fingerprint=digest([f["hash"] for f in files]), files=files, raw_archive=raw)
        g.db.add(batch)
        g.db.commit()
        return redirect(url_for("web.import_map", batch_id=batch.id))
    return render_template("imports.html", batches=g.db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(20)).all())


@bp.route("/imports/<batch_id>/map", methods=["GET", "POST"])
def import_map(batch_id):
    batch = get_or_404(ImportBatch, batch_id)
    if batch.state == "applied":
        return redirect(url_for("web.import_preview", batch_id=batch.id))
    options = {"files": []}
    for i, file in enumerate(batch.files):
        sheet_index = int(request.values.get(f"sheet_{i}", "0"))
        if not 0 <= sheet_index < len(file["sheets"]):
            raise ValueError("工作表选择无效。")
        sheet = file["sheets"][sheet_index]
        mapping = default_mapping(sheet["headers"])
        if request.method == "POST":
            mapping = {key: request.form.get(f"map_{i}_{key}", "") for key in ALIASES}
        metadata = {k: clean(request.form.get(f"{k}_{i}")) for k in ("book_code", "book", "stage", "grade", "publisher", "edition", "volume", "source")}
        options["files"].append({"sheet": sheet_index, "mapping": mapping, **metadata})
    if request.method == "POST":
        fingerprint = digest({"hashes": [f["hash"] for f in batch.files], "options": options})
        duplicate = g.db.scalar(select(ImportBatch).where(ImportBatch.fingerprint == fingerprint, ImportBatch.state == "applied"))
        if duplicate:
            flash("相同文件、映射和目标已导入，不会重复写入。", "success")
            return redirect(url_for("web.import_preview", batch_id=duplicate.id))
        batch.options, batch.fingerprint = options, fingerprint
        batch.plan = make_plan(g.db, batch.files, options)
        batch.state = "preview"
        g.db.commit()
        return redirect(url_for("web.import_preview", batch_id=batch.id))
    return render_template("import_map.html", batch=batch, options=options, labels=LABELS, books=g.db.scalars(select(Book)).all())


@bp.route("/imports/<batch_id>", methods=["GET", "POST"])
def import_preview(batch_id):
    batch = get_or_404(ImportBatch, batch_id)
    if request.method == "POST":
        report = apply_plan(g.db, batch, set(request.form.getlist("overwrite")))
        g.db.commit()
        flash(f"导入完成：新增 {report.get('created', 0)} 条，更新 {report.get('updated', 0)} 条。", "success")
        return redirect(url_for("web.home"))
    if batch.state == "draft":
        return redirect(url_for("web.import_map", batch_id=batch.id))
    return render_template("import_preview.html", batch=batch, labels=LABELS)


@bp.get("/imports/<batch_id>/original.zip")
def original(batch_id):
    batch = get_or_404(ImportBatch, batch_id)
    return send_file(BytesIO(batch.raw_archive), as_attachment=True, download_name="original-import.zip", mimetype="application/zip")


def selected_print_records():
    ids = request.form.getlist("item_id")
    books = request.form.getlist("book_id")
    sections = set(request.form.getlist("section_id"))
    records = entries(g.db, ids=ids) if ids else [r for r in entries(g.db) if (not books or r[3].id in books) and (not sections or r[2].id in sections)]
    if not ids and not books and not sections:
        raise ValueError("请至少选择一本书、章节或词条。")
    if ids and len(records) != len(set(ids)):
        raise ValueError("部分词条已不存在，请重新选择。")
    letter = request.form.get('initial', '')
    query = clean(request.form.get('q')).casefold()
    if letter:
        records = [r for r in records if initial(r[1].spelling) == letter]
    if query:
        records = [r for r in records if query in (r[1].spelling + resolved(*r)['meaning']).casefold()]
    return records


@bp.route("/prints/new", methods=["GET", "POST"])
def print_new():
    books = g.db.scalars(select(Book).order_by(Book.created_at)).all()
    sections = g.db.scalars(select(Section).order_by(Section.position, Section.created_at)).all()
    section_counts = dict(g.db.execute(select(Item.section_id, func.count(Item.id)).where(Item.status != "archived").group_by(Item.section_id)).all())
    picker = [{"book": book, "sections": [s for s in sections if s.book_id == book.id and section_counts.get(s.id)],
               "count": sum(section_counts.get(s.id, 0) for s in sections if s.book_id == book.id)} for book in books]
    context = dict(books=books, picker=picker, section_counts=section_counts,
                   selected_sections=set(request.values.getlist("section_id")), initial_value=request.values.get("initial", ""))
    if request.method == "POST":
        if not any(request.form.getlist(key) for key in ("item_id", "book_id", "section_id")):
            return render_template("print_new.html", **context, preview=None, token=None, selection_error="请勾选至少一个单元，或勾选整本书。"), 400
        records = selected_print_records()
        if not records:
            return render_template("print_new.html", **context, preview=None, token=None, selection_error="当前选择没有符合条件的词条，请调整单元或首字母范围。"), 400
        if len(records) > 5000:
            raise ValueError("请选择 1～5,000 条词条。")
        token = URLSafeTimedSerializer(current_app.secret_key).dumps(digest([resolved(*r) for r in records]), salt="print-review")
        scopes = list(dict.fromkeys((r[3].title, r[2].title) for r in records))
        title = records[0][3].title
        if len(scopes) == 1:
            title += " · " + records[0][2].title
        selected_sections = request.form.getlist("section_id")
        back_url = url_for("web.print_new", section_id=selected_sections, initial=request.form.get("initial", ""))
        if request.form.getlist("item_id") and not selected_sections:
            back_url = url_for("web.book_detail", book_id=records[0][3].id)
        return render_template("print_new.html", **context, preview=warnings(records), token=token, default_title=title, scopes=scopes, back_url=back_url)
    return render_template("print_new.html", **context, preview=None, token=None)


@bp.post("/prints")
def print_create():
    records = selected_print_records()
    try:
        expected = URLSafeTimedSerializer(current_app.secret_key).loads(request.form.get("review_token", ""), salt="print-review", max_age=7200)
    except BadSignature:
        abort(409, "打印预览已过期，请重新选择资料。")
    if expected != digest([resolved(*r) for r in records]):
        abort(409, "预览后词条已改变，请重新预览。")
    job = create_print_job(records, request.form)
    g.db.add(job)
    g.db.commit()
    return redirect(url_for("web.print_detail", job_id=job.id))


@bp.get("/prints")
def prints():
    state = request.args.get('state', 'active')
    if state not in ('active', 'trash'):
        abort(400, '资料筛选无效。')
    q = clean(request.args.get('q'))[:200]
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        abort(400, '页码无效。')
    query = select(PrintJob).where(PrintJob.deleted_at.is_not(None) if state == 'trash' else PrintJob.deleted_at.is_(None))
    if q:
        query = query.where(PrintJob.title.icontains(q, autoescape=True))
    total = g.db.scalar(select(func.count()).select_from(query.subquery()))
    pages = max(1, (total + 23) // 24)
    page = min(page, pages)
    jobs = g.db.scalars(query.order_by(PrintJob.created_at.desc(), PrintJob.id.desc()).offset((page - 1) * 24).limit(24)).all()
    counts = {key: g.db.scalar(select(func.count()).select_from(PrintJob).where(condition)) for key, condition in
              [('active', PrintJob.deleted_at.is_(None)), ('trash', PrintJob.deleted_at.is_not(None))]}
    return render_template('prints.html', jobs=jobs, state=state, q=q, page=page, pages=pages, total=total, counts=counts)


@bp.post('/prints/manage')
def print_manage():
    action = request.form.get('action')
    if action not in ('delete', 'restore'):
        abort(400, '资料操作无效。')
    ids = list(dict.fromkeys(request.form.getlist('job_id')))
    if not ids or len(ids) > 100:
        abort(400, '请选择 1～100 份资料。')
    jobs = g.db.scalars(select(PrintJob).where(PrintJob.id.in_(ids)).order_by(PrintJob.id).with_for_update()).all()
    if len(jobs) != len(ids):
        abort(409, '部分资料已不存在，请刷新列表。')
    for job in jobs:
        if request.form.get('revision_' + job.id) != str(job.management_revision):
            abort(409, '资料已被其他页面修改，请刷新后重试。')
        if (action == 'restore') != (job.deleted_at is not None):
            abort(409, '部分资料状态已改变，请刷新后重试。')
    phase = request.form.get('phase', 'review')
    if phase == 'review':
        return render_template('print_manage.html', jobs=jobs, action=action)
    if phase != 'apply':
        abort(400, '确认步骤无效。')
    now = datetime.now(timezone.utc)
    for job in jobs:
        job.deleted_at = now if action == 'delete' else None
        job.management_revision += 1
    g.db.commit()
    flash(f'已将 {len(jobs)} 份资料移至回收站，可随时恢复。' if action == 'delete' else f'已恢复 {len(jobs)} 份资料。', 'success')
    return redirect(url_for('web.prints'))


@bp.post('/prints/<job_id>/rename')
def print_rename(job_id):
    job = g.db.scalar(select(PrintJob).where(PrintJob.id == job_id).with_for_update())
    if job is None:
        abort(404)
    if job.deleted_at is not None:
        abort(409, '请先从回收站恢复资料。')
    if request.form.get('revision') != str(job.management_revision):
        abort(409, '资料已被修改，请刷新后重试。')
    title = clean(request.form.get('title'))
    if not title or len(title) > 200:
        abort(400, '名称须为 1～200 字。')
    job.title = title
    job.management_revision += 1
    g.db.commit()
    flash('显示名称已更新，原 PDF 标题和内容保持不变。', 'success')
    return redirect(url_for('web.print_detail', job_id=job.id))


def printable_job(job_id):
    job = get_or_404(PrintJob, job_id)
    if job.deleted_at is not None:
        abort(404, '资料已移至回收站，请恢复后再下载。')
    return job


@bp.get("/prints/<job_id>")
def print_detail(job_id):
    return render_template("print_detail.html", job=get_or_404(PrintJob, job_id), modes=MODES)


@bp.get("/prints/<job_id>/<mode>.html")
def print_document(job_id, mode):
    job = printable_job(job_id)
    if mode not in job.documents:
        abort(404)
    html = displayed_document(job, mode).replace('url("assets/', 'url("/static/fonts/')
    return Response(html, mimetype="text/html")


@bp.get("/prints/<job_id>/download.zip")
def print_download(job_id):
    return send_file(BytesIO(print_zip(printable_job(job_id))), mimetype="application/zip", as_attachment=True, download_name="englishwords-print.zip")


@bp.get('/prints/<job_id>/<mode>.pdf')
def print_pdf(job_id, mode):
    job = printable_job(job_id)
    if mode not in job.documents:
        abort(404)
    data = render_pdf_export(job, mode)
    return send_file(BytesIO(data), mimetype='application/pdf', as_attachment=request.args.get('preview') != '1',
                     download_name=f'ZhiXiStudioVocabulary-{mode}-{job.id[:8]}.pdf')


@bp.get('/prints/<job_id>/pdfs.zip')
def print_pdf_bundle(job_id):
    job = printable_job(job_id)
    return send_file(BytesIO(render_pdf_export(job)), mimetype='application/zip', as_attachment=True,
                     download_name=f'ZhiXiStudioVocabulary-{job.id[:8]}.zip')


@bp.get("/settings")
def settings():
    counts = {label: g.db.scalar(select(func.count()).select_from(model)) for label, model in [("基础词条", Term), ("书本", Book), ("课程条目（含归档）", Item), ("导入批次", ImportBatch), ("打印快照", PrintJob)]}
    return render_template("settings.html", counts=counts)


import zipfile
