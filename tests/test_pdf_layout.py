"""Opt-in checks of actual PDF positions, using the existing local renderer.

Set ENGLISHWORDS_PDF_TEST_CONTAINER to a local Web test container and
ENGLISHWORDS_PDF_QA_PYTHON to an existing Python with pdfplumber installed.
No container, database, dependency or stored print job is changed.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile

from flask import Flask, render_template
import pytest


RENDERER = os.environ.get('ENGLISHWORDS_PDF_TEST_CONTAINER')
QA_PYTHON = os.environ.get('ENGLISHWORDS_PDF_QA_PYTHON')
DOCKER_CONTEXT = os.environ.get('ENGLISHWORDS_DOCKER_CONTEXT')
pytestmark = pytest.mark.skipif(
    not (RENDERER and QA_PYTHON), reason='requires the existing local PDF QA environment',
)

CASES = [
    ('four-study', 'study', 4, 2, {}),
    ('odd-study', 'study', 5, 2, {}),
    ('multipage-study', 'study', 111, 2, {}),
    ('multipage-en-zh', 'en-zh', 73, 2, {}),
    ('seven-zh-en', 'zh-en', 7, 3, {}),
    ('multipage-zh-en', 'zh-en', 121, 3, {}),
    ('phonetic-zh-en', 'zh-en', 71, 2, {'zh_en_layout': 'phonetic'}),
    ('single-column', 'study', 55, 1, {'columns': '1'}),
    ('wide-zh-en', 'zh-en', 37, 1, {'zh_en_layout': 'wide'}),
    ('comfortable', 'en-zh', 61, 2, {'density': 'comfortable', 'size': 'large'}),
    ('long-text', 'study', 85, 2, {'examples': True}),
    ('grouped', 'study', 123, 2, {'test_groups': True}),
    ('grouped-break', 'study', 93, 2, {'test_groups': True, 'break_sections': True}),
    ('wrapped-word', 'en-zh', 87, 2, {'test_wrapping': True}),
]


@pytest.fixture(scope='module')
def rendered_layouts(tmp_path_factory):
    from englishwords.printing import MODES
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / 'englishwords/templates'))
    documents, groups_by_case = {}, {}
    with app.app_context():
        for name, mode, count, _, overrides in CASES:
            options = dict(size='compact', density='compact', columns='2',
                           zh_en_layout='three', order='original', examples=False,
                           break_sections=False)
            options.update(overrides)
            rows = [dict(number=i, spelling=f'word{i:03}', us='/wɜːrd/', pos='n.',
                         meaning='词义' + ('；用于检查多行释义是否完整显示' * (i % 3)
                                         if options['examples'] else ''),
                         example='An example sentence for layout checking.'
                                 if options['examples'] and i % 4 == 0 else '',
                         example_zh='排版检查例句。') for i in range(1, count + 1)]
            if options.get('test_wrapping'):
                rows[2]['spelling'] = 'be covered with a thick layer of snow'
                rows[24]['spelling'] = 'an exceptionally long English expression'
            chunks = [rows[:17], rows[17:]] if options.get('test_groups') else [rows]
            groups = [dict(label=f'Unit {i}', rows=chunk) for i, chunk in enumerate(chunks, 1)]
            groups_by_case[name] = [[r['number'] for r in chunk] for chunk in chunks]
            documents[name] = render_template(
                'print.html', snapshot=dict(title='纵向分栏检查', id='layout-check'),
                mode=mode, mode_title=MODES[mode], rows=rows, groups=groups,
                options=options, css=(root / 'englishwords/static/print.css').read_text(),
            )
    payload = dict(format='zip', documents=documents, checksum='synthetic-layout-check')
    result = subprocess.run(
        ['docker'] + (['--context', DOCKER_CONTEXT] if DOCKER_CONTEXT else []) + ['exec', '-i', RENDERER,
         'python', '-m', 'englishwords.pdf_render'],
        input=json.dumps(payload).encode(), capture_output=True, timeout=90, check=True,
    )
    output = tmp_path_factory.mktemp('column-flow')
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
        for name in documents:
            (output / f'{name}.pdf').write_bytes(archive.read(f'{name}.pdf'))
    extraction = subprocess.run([QA_PYTHON, '-c', '''
import json, re, sys
from pathlib import Path
import pdfplumber
layouts = {}
for path in Path(sys.argv[1]).glob('*.pdf'):
    with pdfplumber.open(path) as pdf:
        pages = []
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=['size'])
            cells = [cell for table in page.find_tables() for cell in table.cells]
            numbers = [dict(n=int(w['text'][:-1]), x=w['x0'], y=w['top'],
                            bottom=w['bottom'],
                            cell=next((cell for cell in cells
                                       if cell[0] <= w['x0'] <= cell[2]
                                       and cell[1] <= (w['top']+w['bottom'])/2 <= cell[3]), None)) for w in words
                       if re.fullmatch(r'\\d+\\.', w['text'])]
            pages.append(dict(width=page.width, height=page.height, numbers=numbers,
                              headers=sum(w['text']=='英语单词' or w['text']=='中文释义'
                                          for w in words)))
        layouts[path.stem] = pages
print(json.dumps(layouts))
''', str(output)], capture_output=True, timeout=60, check=True)
    return json.loads(extraction.stdout), groups_by_case, output


@pytest.mark.parametrize('name,mode,count,columns,overrides', CASES)
def test_pdf_reads_down_each_column_and_balances_tail(
    rendered_layouts, name, mode, count, columns, overrides,
):
    layouts, groups, _ = rendered_layouts
    pages = layouts[name]
    all_numbers = [row['n'] for p in pages for row in p['numbers']]
    assert sorted(all_numbers) == list(range(1, count + 1)), 'no missing or duplicate rows'
    assert all(p['numbers'] for p in pages), 'no blank trailing pages'
    for group in groups[name]:
        reading_order, last_columns = [], None
        for page in pages:
            column_rows = [[] for _ in range(columns)]
            for row in page['numbers']:
                if row['n'] not in group:
                    continue
                column = min(columns - 1, int((row['x'] - 28) / (539 / columns)))
                column_rows[column].append(row)
                assert 28 <= row['x'] < page['width'] - 28
                assert row['y'] > 28 and row['bottom'] < page['height'] - 34
            for column in column_rows:
                reading_order.extend(r['n'] for r in sorted(column, key=lambda r: r['y']))
            if any(column_rows):
                last_columns = column_rows
                assert page['headers'] >= sum(bool(c) for c in column_rows)
                for i in range(max(map(len, column_rows))):
                    occupied = [c[i] for c in column_rows if i < len(c)]
                    assert all(r['cell'] for r in occupied), 'each number belongs to a grid cell'
                    tops = [r['cell'][1] for r in occupied]
                    bottoms = [r['cell'][3] for r in occupied]
                    assert max(tops) - min(tops) < .5, 'shared row top aligns across columns'
                    assert max(bottoms) - min(bottoms) < .5, 'shared row bottom aligns across columns'
        assert reading_order == group
        if not overrides.get('examples'):
            lengths = [len(c) for c in last_columns]
            assert max(lengths) - min(lengths) <= 1
        else:
            # Variable-height rows balance by physical height, not item count.
            bottoms = [max(r['bottom'] for r in c) for c in last_columns if c]
            assert max(bottoms) - min(bottoms) < 100
    if name == 'four-study':
        assert [[r['n'] for r in pages[0]['numbers'] if (r['x'] < 297) == (c == 0)]
                for c in range(2)] == [[1, 2], [3, 4]]
    if overrides.get('break_sections'):
        assert not any(any(r['n'] <= 17 for r in p['numbers']) and
                       any(r['n'] > 17 for r in p['numbers']) for p in pages)
