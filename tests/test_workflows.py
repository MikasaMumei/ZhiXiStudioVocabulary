import io
import json
import re
import zipfile

from openpyxl import Workbook, load_workbook
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from englishwords.content import entries, resolved
from englishwords.importing import parse_files
from englishwords.models import Book, Item, PrintJob, Term, ImportBatch
from werkzeug.datastructures import FileStorage, MultiDict


def csrf(client, path='/'):
    page = client.get(path)
    assert page.status_code == 200, page.data[:1000]
    return re.search(rb'name="csrf_token" value="([^"]+)"', page.data)[1].decode()


def post(client, path, data=None):
    values = MultiDict(data or {})
    values['csrf_token'] = csrf(client)
    return client.post(path, data=values)


def import_csv(client, content=None, filename='sample.csv', configure=None, apply=True):
    content = content or '单词,美音,释义,单元\napple,/ˈæpəl/,苹果,Unit 1\nbook,/bʊk/,书,Unit 1\nread,/riːd/,阅读,Unit 2\n'
    response = client.post('/imports', data={'csrf_token': csrf(client), 'files': (io.BytesIO(content.encode()), filename)}, content_type='multipart/form-data')
    assert response.status_code == 302, response.data
    location = response.location
    page = client.get(location)
    assert page.status_code == 200, page.data
    fields = {'sheet_0':'0','book_code_0':'demo','book_0':'原创示例','stage_0':'初中','edition_0':'原创示例（非教材）',
              'map_0_spelling':'0','map_0_us':'1','map_0_meaning':'2','map_0_section':'3'}
    if configure:
        fields.update(configure)
    response = post(client, location, fields)
    assert response.status_code == 302, response.data
    preview = response.location
    assert client.get(preview).status_code == 200
    if apply:
        response = post(client, preview)
        assert response.status_code == 302, response.data
    return preview


def records(app):
    with Session(app.extensions['engine']) as db:
        return [resolved(*r) for r in entries(db)]


def test_auth_csrf_and_http_headers(app):
    client = app.test_client()
    assert client.get('/').status_code == 302
    assert client.post('/login', data={'password':'test-password'}).status_code == 400
    token = csrf(client, '/login')
    assert client.post('/login', data={'csrf_token':token,'password':'test-password'}).status_code == 302
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert client.post('/books/new', data={'title':'x'}).status_code == 400


def test_duplicate_import_is_noop_and_original_retained(client, app):
    first = import_csv(client)
    second = import_csv(client, apply=False)
    assert first == second
    assert len(records(app)) == 3
    archive = client.get(first + '/original.zip')
    assert zipfile.ZipFile(io.BytesIO(archive.data)).read('1-sample.csv').startswith('单词'.encode())


def test_same_spelling_across_books_and_missing_us_not_filled(client, app):
    import_csv(client)
    import_csv(client, '单词,英音,释义,单元\nbook,/bʊk/,预订,Unit 1\nUS,,美国,Unit 1\nus,,我们,Unit 1\n', configure={'book_code_0':'second','book_0':'第二册','map_0_us':'','map_0_uk':'1'})
    rows = records(app)
    assert len(rows) == 6
    assert {r['meaning'] for r in rows if r['spelling']=='book'} == {'书','预订'}
    assert next(r for r in rows if r['book_code']=='second' and r['spelling']=='book')['us'] == ''
    assert {r['spelling'] for r in rows if r['spelling'].lower()=='us'} == {'US','us'}


def test_no_id_conflict_preserves_manual_value_and_explicit_override(client, app):
    import_csv(client)
    page = import_csv(client, '单词,美音,释义,单元\nbook,/bʊk/,预订,Unit 1\n', filename='new.csv', apply=False)
    html = client.get(page).get_data(as_text=True)
    assert '预订' in html and '确认覆盖' in html
    assert post(client, page).status_code == 302
    assert next(r for r in records(app) if r['spelling']=='book')['meaning'] == '书'
    page = import_csv(client, '单词,美音,释义,单元\nbook,/bʊk/,订票,Unit 1\n', filename='newer.csv', apply=False)
    assert post(client, page, {'overwrite':'0'}).status_code == 302
    assert next(r for r in records(app) if r['spelling']=='book')['meaning'] == '订票'


def test_preview_invalidated_after_edits(client, app):
    import_csv(client)
    page = import_csv(client, '单词,美音,释义,单元\nbook,/bʊk/,预订,Unit 1\n', apply=False)
    book = records(app)[0]
    response = post(client, '/books/' + book['book_id'] + '/edit', {'revision':book['book_revision'],'title':'新书名','code':'demo'})
    assert response.status_code == 302
    assert post(client, page, {'overwrite':'0'}).status_code == 400
    assert next(r for r in records(app) if r['spelling']=='book')['meaning'] == '书'


def test_export_edit_move_roundtrip_and_stale_revision(client, app):
    import_csv(client)
    row = records(app)[0]
    workbook = load_workbook(io.BytesIO(client.get('/books/' + row['book_id'] + '/export.xlsx').data))
    sheet = workbook.active
    headers = [c.value for c in sheet[1]]
    sheet.cell(2,headers.index('单元')+1,'Revised unit')
    sheet.cell(2,headers.index('顺序')+1,9)
    output = io.BytesIO(); workbook.save(output)
    response = client.post('/imports',data={'csrf_token':csrf(client),'files':(io.BytesIO(output.getvalue()),'roundtrip.xlsx')},content_type='multipart/form-data')
    page = response.location
    assert client.get(page).status_code == 200
    mapping = {'sheet_0':'0', **{'map_0_'+key:str(headers.index(label)) for key,label in [('spelling','单词'),('meaning','中文释义'),('us','美音'),('section','单元'),('position','顺序'),('id','条目 ID'),('revision','修订号'),('book_code','书本编号'),('book','书名')]}}
    response = post(client,page,mapping)
    assert post(client,response.location).status_code == 302
    current = next(r for r in records(app) if r['id']==row['id'])
    assert current['section']=='Revised unit' and current['position']==9
    assert current['revision'] > row['revision']
    response = post(client,'/items/'+row['id']+'/edit',{'revision':row['revision'],'book_revision':current['book_revision']})
    assert response.status_code == 409


def test_three_print_sheets_snapshot_and_no_answer_leak(client, app):
    import_csv(client)
    rows = records(app)
    ids = [('item_id',r['id']) for r in rows]
    response = post(client,'/prints/new',ids)
    assert response.status_code == 200
    token = re.search(rb'name="review_token" value="([^"]+)"',response.data)[1].decode()
    response = post(client,'/prints',ids + [('review_token',token),('title','测试打印'),('shuffle','on'),('seed','fixed')])
    assert response.status_code == 302
    job_url = response.location
    chinese_test = client.get(job_url + '/zh-en.html').get_data(as_text=True)
    english_test = client.get(job_url + '/en-zh.html').get_data(as_text=True)
    study = client.get(job_url + '/study.html').get_data(as_text=True)
    assert 'apple' not in chinese_test and '/ˈæpəl/' not in chinese_test
    assert '苹果' not in english_test
    assert 'apple' in study and '苹果' in study
    assert '/ˈæpəl/' in english_test
    assert client.get(job_url + '/answers.html').status_code == 404
    assert client.get(job_url + '/answers.pdf').status_code == 404
    with Session(app.extensions['engine']) as db:
        item = db.get(Item, rows[0]['id']); item.meaning='CHANGED'; db.commit()
    assert client.get(job_url+'/study.html').get_data(as_text=True) == study
    pack = zipfile.ZipFile(io.BytesIO(client.get(job_url+'/download.zip').data))
    assert 'snapshot.json' in pack.namelist()
    assert 'assets/NotoSans-Regular.ttf' in pack.namelist()
    assert pack.read('看中写英.html').decode() == chinese_test.replace('/static/fonts/','assets/')
    assert len([n for n in pack.namelist() if n.endswith('.html')]) == 3


def test_blank_phonetics_are_optional_but_meaning_is_required(client, app):
    import_csv(client,'单词,美音,释义,单元\ntake care of,,照顾,Unit 1\n')
    row = records(app)[0]
    response = post(client,'/prints/new',{'item_id':row['id']})
    assert '其中 1 条为短语' in response.get_data(as_text=True)
    assert b'name="accept_missing"' not in response.data
    token = re.search(rb'name="review_token" value="([^"]+)"',response.data)[1].decode()
    assert post(client,'/prints',{'item_id':row['id'],'review_token':token}).status_code == 302
    with Session(app.extensions['engine']) as db:
        db.get(Item, row['id']).meaning = ''
        db.commit()
    response = post(client,'/prints/new',{'item_id':row['id']})
    token = re.search(rb'name="review_token" value="([^"]+)"',response.data)[1].decode()
    assert post(client,'/prints',{'item_id':row['id'],'review_token':token}).status_code == 400


def test_preview_error_rolls_back_entire_batch(client, app):
    page = import_csv(client,'单词,美音,释义,单元\napple,,苹果,Unit 1\n,,无词形,Unit 1\n',apply=False)
    assert post(client,page).status_code == 400
    assert records(app) == []


def test_formula_rejected_and_xlsx_export_not_formula(client, app):
    workbook=Workbook(); sheet=workbook.active; sheet.append(['单词','释义']); sheet.append(['=1+1','危险'])
    buffer=io.BytesIO(); workbook.save(buffer)
    with pytest.raises(ValueError,match='公式'):
        parse_files([FileStorage(stream=io.BytesIO(buffer.getvalue()),filename='formula.xlsx')])
    import_csv(client,'单词,美音,释义,单元\n=hello,,问候,Unit 1\n<script>alert(1)</script>,,文本,Unit 1\n')
    row=records(app)[0]
    response=client.get('/books/'+row['book_id'])
    assert b'<script>alert(1)</script>' not in response.data
    out=load_workbook(io.BytesIO(client.get('/books/'+row['book_id']+'/export.xlsx').data))
    header=[c.value for c in out.active[1]]
    cell=out.active.cell(2,header.index('单词')+1)
    assert cell.value=='=hello' and cell.data_type=='s'


def test_bulk_group_review_copy_and_public_dictionary_inheritance(client, app):
    import_csv(client)
    rows=records(app); row=rows[0]
    assert post(client,'/books/new',{'title':'复习册','code':'review','stage':'自编'}).status_code==302
    with Session(app.extensions['engine']) as db:
        target=db.scalar(select(Book).where(Book.code=='review')); target_id=target.id
    assert post(client,'/books/'+row['book_id']+'/bulk',{'revision':row['book_revision'],'range_start':'1','range_end':'2','action':'group','section_title':'练习组'}).status_code==302
    current=next(r for r in records(app) if r['id']==row['id'])
    assert current['section']=='练习组'
    assert post(client,'/books/'+row['book_id']+'/bulk',{'revision':current['book_revision'],'item_id':row['id'],'action':'copy','target':target_id}).status_code==302
    assert len([r for r in records(app) if r['book_code']=='review'])==1
    assert post(client,'/dictionary',{'spelling':'apple','revision':'1','meaning':'词典苹果','us':'NEW-US'}).status_code==302
    original=next(r for r in records(app) if r['id']==row['id'])
    assert original['meaning']=='苹果' and original['us']=='/ˈæpəl/'
    edit={'revision':original['revision'],'book_revision':original['book_revision'],'spelling':'apple','section_id':original['section_id'],'position':'1','meaning':'苹果','inherit_us':'on'}
    assert post(client,'/items/'+row['id']+'/edit',edit).status_code==302
    assert next(r for r in records(app) if r['id']==row['id'])['us']=='NEW-US'


def test_mid_import_failure_is_atomic(client, app):
    from sqlalchemy import event
    page=import_csv(client,apply=False)
    inserted=[]
    def fail_second(mapper,connection,target):
        inserted.append(target.term_id)
        if len(inserted)==2:
            raise ValueError('injected import failure')
    event.listen(Item,'before_insert',fail_second)
    try:
        assert post(client,page).status_code==400
    finally:
        event.remove(Item,'before_insert',fail_second)
    assert len(inserted)==2
    assert records(app)==[]
    with Session(app.extensions['engine']) as db:
        assert db.scalar(select(Book)) is None
        assert db.scalar(select(Term)) is None


def test_archive_can_be_restored_without_deletion(client,app):
    import_csv(client)
    row=records(app)[0]
    path='/books/'+row['book_id']+'/bulk'
    assert post(client,path,{'revision':row['book_revision'],'item_id':row['id'],'action':'archive'}).status_code==302
    assert row['id'] not in [r['id'] for r in records(app)]
    with Session(app.extensions['engine']) as db:
        revision=db.get(Book,row['book_id']).revision
        assert db.get(Item,row['id']).status=='archived'
    assert client.get('/books/'+row['book_id']+'?needs=archived').status_code==200
    assert post(client,path,{'revision':revision,'item_id':row['id'],'action':'restore'}).status_code==302
    assert row['id'] in [r['id'] for r in records(app)]


def test_dictionary_edit_is_bound_to_term_identity(client,app):
    import_csv(client)
    with Session(app.extensions['engine']) as db:
        term=db.scalar(select(Term).where(Term.spelling=='apple'))
        term_id,revision=term.id,term.revision
    response=post(client,'/dictionary',{'term_id':term_id,'spelling':'book','revision':revision,'meaning':'意外覆盖'})
    assert response.status_code==400
    with Session(app.extensions['engine']) as db:
        assert db.scalar(select(Term).where(Term.spelling=='book')).meaning == ''


def test_workbook_empty_sheet_does_not_hide_data_sheet():
    workbook=Workbook()
    sheet=workbook.create_sheet('词表')
    sheet.append(['单词','释义']);sheet.append(['apple','苹果'])
    buffer=io.BytesIO();workbook.save(buffer)
    files,_=parse_files([FileStorage(stream=io.BytesIO(buffer.getvalue()),filename='multiple.xlsx')])
    assert len(files[0]['sheets'])==1
    assert files[0]['sheets'][0]['name']=='词表'


def test_initial_navigation_and_print_scope(client, app):
    import_csv(client, '单词,美音,释义,单元\nzebra,/z/,斑马,Unit 1\nApple,/a/,苹果,Unit 1\nbook,/b/,书,Unit 2\n123,/n/,数字,Unit 2\n')
    row = records(app)[0]
    page = client.get('/books/' + row['book_id'] + '?initial=A&section=' + row['section_id']).get_data(as_text=True)
    assert '选择 Apple' in page and '选择 zebra' not in page and '选择 book' not in page
    response = post(client, '/prints/new', {'book_id': row['book_id'], 'initial': 'B'})
    assert response.status_code == 200
    assert 'name="item_id"' in response.get_data(as_text=True)
    selected = re.findall(rb'name="item_id" value="([^"]+)"', response.data)
    assert [r['spelling'] for r in records(app) if r['id'].encode() in selected] == ['book']


def test_six_column_layout_and_grouping_share_answer_order(client, app):
    from englishwords.printing import create_print_job
    import_csv(client, '单词,美音,释义,单元\nzebra,/z/,斑马,Unit 1\nApple,/a/,苹果,Unit 1\napricot,/a/,杏,Unit 2\nbook,/b/,书,Unit 2\n')
    with app.test_request_context(), Session(app.extensions['engine']) as db:
        job = create_print_job(entries(db), {'grouping': 'initial', 'order': 'alphabetical'})
        assert job.snapshot['options']['columns'] == '2'
        assert [r['spelling'] for r in job.snapshot['rows']] == ['Apple', 'apricot', 'book', 'zebra']
        for mode, document in job.documents.items():
            if mode in ('study', 'answers'):
                assert document.count('<th>英语单词</th>') == 3  # repeated per column by the paged renderer
            assert re.findall(r'class="number">(\d+)\.', document) == ['1','2','3','4']
        assert 'Apple' not in job.documents['zh-en']
        assert '苹果' not in job.documents['en-zh']
        by_section = create_print_job(entries(db), {'order': 'alphabetical', 'grouping': 'section'})
        assert [r['spelling'] for r in by_section.snapshot['rows']] == ['Apple','zebra','apricot','book']
        first = create_print_job(entries(db), {'order': 'shuffle','grouping':'initial','seed':'fixed'})
        second = create_print_job(entries(db), {'order': 'shuffle','grouping':'initial','seed':'fixed'})
        assert [r['id'] for r in first.snapshot['rows']] == [r['id'] for r in second.snapshot['rows']]
        with pytest.raises(ValueError):
            create_print_job(entries(db), {'density':'invalid'})


def test_pdf_download_routes_and_busy_response(client, app, monkeypatch):
    from englishwords.printing import create_print_job, pdf_lock
    import_csv(client)
    with app.test_request_context(), Session(app.extensions['engine']) as db:
        job = create_print_job(entries(db), {})
        db.add(job); db.commit(); job_id = job.id
    path = '/prints/' + job_id
    assert app.test_client().get(path + '/study.pdf').status_code == 302
    assert client.get(path + '/invalid.pdf').status_code == 404
    pdf_lock.acquire()
    try:
        assert client.get(path + '/study.pdf').status_code == 429
    finally:
        pdf_lock.release()
    monkeypatch.setattr('englishwords.views.render_pdf_export', lambda job, mode=None: b'%PDF-test-route')
    response = client.get(path + '/study.pdf')
    assert response.mimetype == 'application/pdf'
    assert 'attachment;' in response.headers['Content-Disposition']
    assert response.data.startswith(b'%PDF-')
    preview = client.get(path + '/study.pdf?preview=1')
    assert preview.mimetype == 'application/pdf'
    assert 'inline;' in preview.headers['Content-Disposition']
    detail = client.get(path).get_data(as_text=True)
    assert '预览 PDF' in detail and 'preview=1' in detail


@pytest.mark.parametrize('layout,groups,fields,hint', [('three',3,2,False),('phonetic',2,3,True),('wide',1,2,False)])
def test_chinese_to_english_layouts_and_forced_us_on_english_sheet(client, app, layout, groups, fields, hint):
    from englishwords.printing import create_print_job
    import_csv(client)
    with app.test_request_context(), Session(app.extensions['engine']) as db:
        job = create_print_job(entries(db), {'zh_en_layout': layout, 'grouping': 'none', 'phonetic_en_test': ''})
    assert set(job.documents) == {'study','en-zh','zh-en'}
    zh_en = job.documents['zh-en']
    assert f'groups-{groups} fields-{fields}' in zh_en
    assert zh_en.count('<th>中文释义</th>') == 1
    assert zh_en.count('<th class="group-end">英语单词（填写）</th>') == 1
    assert 'column-fill:balance' in zh_en
    assert job.snapshot['template'] == '2.3'
    assert ('/ˈæpəl/' in zh_en) == hint
    assert 'apple' not in zh_en
    en_zh = job.documents['en-zh']
    assert '/ˈæpəl/' in en_zh and 'apple' in en_zh and '苹果' not in en_zh
    assert en_zh.count('<td class="ipa">') == 3
    assert en_zh.count('<td class="writing-line group-end">') == 3
    for doc in job.documents.values():
        assert re.findall(r'class="number">(\d+)\.', doc) == ['1','2','3']


def test_legacy_answer_kept_in_storage_but_omitted_from_exports(client, app):
    import hashlib
    from englishwords.printing import create_print_job
    import_csv(client)
    with app.test_request_context(), Session(app.extensions['engine']) as db:
        job = create_print_job(entries(db), {})
        job.documents = {**job.documents, 'answers':'<p>Frozen historical document</p>'}
        job.snapshot = {**job.snapshot,'template':'2.0'}
        job.checksum=hashlib.sha256(json.dumps({'snapshot':job.snapshot,'documents':job.documents},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        db.add(job);db.commit();job_id=job.id;checksum=job.checksum
    path='/prints/'+job_id
    assert b'Frozen historical document' in client.get(path+'/answers.html').data
    assert '历史教师答案' not in client.get(path).get_data(as_text=True)
    assert '这份是旧版快照' in client.get(path).get_data(as_text=True)
    pack=zipfile.ZipFile(io.BytesIO(client.get(path+'/download.zip').data))
    assert len([n for n in pack.namelist() if n.endswith('.html')])==3
    with Session(app.extensions['engine']) as db:
        assert db.get(PrintJob,job_id).checksum==checksum


def test_print_picker_preserves_scope_and_combines_chapters(client, app):
    import_csv(client)
    import_csv(client, '单词,美音,释义,单元\npear,/per/,梨,Unit 1\n', configure={'book_code_0':'other','book_0':'另一册'})
    rows = records(app)
    section_ids = [next(r['section_id'] for r in rows if r['spelling']==word) for word in ('read','pear')]
    page = client.get('/prints/new').get_data(as_text=True)
    assert '<select name="book_id" multiple' not in page
    assert '<select name="section_id" multiple' not in page
    assert 'data-book-toggle' in page and 'data-count="2"' in page
    response = post(client, '/prints/new', [('section_id', value) for value in section_ids])
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    selected_ids = re.findall(r'name="item_id" value="([^"]+)"', html)
    assert {r['spelling'] for r in rows if r['id'] in selected_ids} == {'read','pear'}
    back = re.search(r'href="([^"]+)">← 返回调整范围', html)[1].replace('&amp;', '&')
    picker = client.get(back).get_data(as_text=True)
    for value in section_ids:
        assert re.search(r'value="'+value+r'"[^>]*checked', picker)
    assert 'name="initial"' in picker


def test_empty_print_filter_keeps_picker_and_book_selection_is_scoped(client, app):
    import_csv(client)
    rows = records(app)
    section = rows[0]['section_id']
    response = post(client, '/prints/new', {'section_id':section,'initial':'Z'})
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert '没有符合条件' in html and 'data-print-picker' in html
    assert re.search(r'value="'+section+r'"[^>]*checked', html)
    response = post(client, '/prints/new')
    assert response.status_code == 400 and '请勾选至少一个单元' in response.get_data(as_text=True)
    book = client.get('/books/'+rows[0]['book_id']).get_data(as_text=True)
    assert 'data-item-selection' in book and 'data-print-selected' in book
    assert '<option value="archived"' not in book.split('name="action"')[1]


def make_print_jobs(app, count=1):
    from englishwords.printing import create_print_job
    with app.app_context(), Session(app.extensions['engine']) as db:
        jobs = [create_print_job(entries(db), {'title': f'管理样本 {i:02}', 'grouping': 'none'}) for i in range(count)]
        db.add_all(jobs); db.commit()
        return [job.id for job in jobs]


def test_print_delete_review_restore_preserves_frozen_content(client, app):
    import_csv(client)
    job_id = make_print_jobs(app)[0]
    path = '/prints/' + job_id
    with Session(app.extensions['engine']) as db:
        job = db.get(PrintJob, job_id)
        original = (job.snapshot, job.documents, job.checksum)
    form = {'job_id': job_id, 'revision_' + job_id: '1', 'action': 'delete'}
    review = post(client, '/prints/manage', form)
    assert review.status_code == 200 and '确认移到回收站' in review.get_data(as_text=True)
    with Session(app.extensions['engine']) as db:
        assert db.get(PrintJob, job_id).deleted_at is None
    assert post(client, '/prints/manage', {**form, 'phase': 'apply'}).status_code == 302
    assert '管理样本 00' not in client.get('/prints').get_data(as_text=True)
    assert '管理样本 00' in client.get('/prints?state=trash').get_data(as_text=True)
    assert '恢复这份资料' in client.get(path).get_data(as_text=True)
    for suffix in ['/study.pdf', '/pdfs.zip', '/study.html', '/download.zip']:
        assert client.get(path + suffix).status_code == 404
    assert post(client, path + '/rename', {'title': '不能改', 'revision': '2'}).status_code == 409
    assert post(client, '/prints/manage', {'job_id': job_id, 'revision_' + job_id: '2', 'action': 'restore', 'phase': 'apply'}).status_code == 302
    with Session(app.extensions['engine']) as db:
        job = db.get(PrintJob, job_id)
        assert job.deleted_at is None and job.management_revision == 3
        assert (job.snapshot, job.documents, job.checksum) == original
    assert client.get(path + '/study.html').status_code == 200


def test_print_bulk_conflicts_are_atomic_and_rename_only_changes_display(client, app):
    import_csv(client)
    ids = make_print_jobs(app, 2)
    path = '/prints/' + ids[0]
    with Session(app.extensions['engine']) as db:
        job = db.get(PrintJob, ids[0]); original = (job.snapshot, job.documents, job.checksum)
    assert post(client, path + '/rename', {'title': '复习资料 新名称', 'revision': '1'}).status_code == 302
    assert post(client, path + '/rename', {'title': '旧页面覆盖', 'revision': '1'}).status_code == 409
    form = [('job_id', i) for i in ids] + [('action', 'delete'), ('phase', 'apply')] + [('revision_' + i, '1') for i in ids]
    assert post(client, '/prints/manage', form).status_code == 409
    with Session(app.extensions['engine']) as db:
        jobs = [db.get(PrintJob, i) for i in ids]
        assert all(job.deleted_at is None for job in jobs)
        assert (jobs[0].snapshot, jobs[0].documents, jobs[0].checksum) == original
        assert jobs[0].title == '复习资料 新名称'
    form = [(key, '2' if key == 'revision_' + ids[0] else value) for key, value in form]
    assert post(client, '/prints/manage', form).status_code == 302
    with Session(app.extensions['engine']) as db:
        assert all(db.get(PrintJob, i).deleted_at is not None for i in ids)
    assert post(client, '/prints/manage', {'action': 'delete'}).status_code == 400
    assert post(client, '/prints/manage', {'action': 'erase', 'job_id': ids[0]}).status_code == 400


def test_print_search_pagination_literal_search_and_auth(client, app):
    import_csv(client)
    ids = make_print_jobs(app, 26)
    page = client.get('/prints').get_data(as_text=True)
    assert page.count('name="job_id"') == 24 and '下一页' in page and '共 26 份' in page
    assert client.get('/prints?page=2').get_data(as_text=True).count('name="job_id"') == 2
    assert client.get('/prints?page=999').get_data(as_text=True).count('name="job_id"') == 2
    assert client.get('/prints?q=管理样本+00').get_data(as_text=True).count('name="job_id"') == 1
    assert '没有找到匹配的资料' in client.get('/prints?q=%25').get_data(as_text=True)
    assert client.get('/prints?state=invalid').status_code == 400
    assert client.get('/prints?page=abc').status_code == 400
    assert app.test_client().get('/prints').status_code == 302
    fresh = app.test_client()
    token = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', fresh.get('/login').data)[1].decode()
    assert fresh.post('/prints/manage', data={'csrf_token': token, 'action': 'delete', 'job_id': ids[0]}).status_code == 302
    assert client.post('/prints/manage', data={'action': 'delete', 'job_id': ids[0]}).status_code == 400


def test_old_english_to_chinese_label_is_corrected_without_rewriting_source(client, app, monkeypatch):
    from englishwords.printing import MODES, displayed_document
    import_csv(client)
    job_id = make_print_jobs(app)[0]
    with Session(app.extensions['engine']) as db:
        job = db.get(PrintJob, job_id)
        legacy = job.documents['en-zh'].replace('看英写中', '看音写中')
        job.documents = {**job.documents, 'en-zh': legacy}
        db.commit(); checksum = job.checksum
        assert '看英写中' in displayed_document(job, 'en-zh')
    html = client.get('/prints/' + job_id + '/en-zh.html').get_data(as_text=True)
    assert '<p class="metadata">看英写中' in html and ' · 看英写中</title>' in html
    archive = zipfile.ZipFile(io.BytesIO(client.get('/prints/' + job_id + '/download.zip').data))
    assert '看英写中.html' in archive.namelist() and '看音写中.html' not in archive.namelist()
    assert '看英写中' in archive.read('看英写中.html').decode()
    assert MODES['en-zh'] == '看英写中'
    with Session(app.extensions['engine']) as db:
        job = db.get(PrintJob, job_id)
        assert job.documents['en-zh'] == legacy and job.checksum == checksum
