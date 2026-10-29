"""Page-local, column-major grids with a shared height for each physical row.

Measure cells with the same engine and fonts as the PDF. Keep the planner pure
so uneven line lengths, column balance and page limits can be tested separately.
"""
from copy import deepcopy
from math import ceil
from xml.etree import ElementTree as ET


def column_grid(rows, columns):
    """Split a prefix into balanced columns, then transpose to physical rows."""
    quotient, remainder = divmod(len(rows), columns)
    chunks, start = [], 0
    for column in range(columns):
        end = start + quotient + (column < remainder)
        chunks.append(rows[start:end])
        start = end
    return [[chunk[i] if i < len(chunk) else None for chunk in chunks]
            for i in range(ceil(len(rows) / columns))]


def grid_height(rows, columns, heights):
    return sum(max(heights[row] for row in line if row is not None)
               for line in column_grid(rows, columns))


def plan_pages(groups, columns, heights, overheads, page_height, header_height,
               break_sections=False, safety=8):
    pages = [[]]
    remaining = page_height - header_height
    for index, rows in enumerate(groups):
        if break_sections and index and pages[-1]:
            pages.append([])
            remaining = page_height
        offset = 0
        while offset < len(rows):
            available = remaining - overheads[index] - safety
            tail = rows[offset:]
            # A changed split can change which tall cells share a physical row,
            # so fit is not monotonic. Check bounded candidates in descending order.
            minimum = min(heights[row] for row in tail)
            limit = min(len(tail), max(0, int(available / minimum)) * columns)
            count = next((n for n in range(limit, 0, -1)
                          if grid_height(tail[:n], columns, heights) <= available), 0)
            if not count:
                if not pages[-1] and remaining == page_height:
                    raise ValueError('单条内容超过 A4 可用高度，请减少例句或调整字号。')
                pages.append([])
                remaining = page_height
                continue
            selected = tail[:count]
            pages[-1].append((index, column_grid(selected, columns)))
            remaining -= overheads[index] + grid_height(selected, columns, heights) + safety
            offset += count
            if offset < len(rows):
                pages.append([])
                remaining = page_height
    # A very long title may occupy a separate first page; never discard its header.
    return pages


def aligned_html(source, html_factory, font_config):
    """Return a complete HTML grid; historical templates pass through unchanged."""
    document = html_factory(source)
    root = document.etree_element
    body = root.find('body')
    if body.get('data-layout') != 'shared-grid':
        return source
    columns = int(body.get('data-columns'))
    fields = int(body.get('data-fields'))
    widths = [float(w) for w in body.get('data-widths').split(',')]
    sections = body.findall('section')
    groups = [[int(row.get('data-number')) for row in section.findall('.//tbody/tr')]
              for section in sections]
    entries = {int(row.get('data-number')): row for section in sections
               for row in section.findall('.//tbody/tr')}
    header = body.find('header')
    # Slashes should travel with the neighbouring phoneme, rather than occupy
    # a line of their own. The text itself and stored pronunciation stay intact.
    for row in entries.values():
        for cell in row:
            value = cell.text or ''
            if cell.get('class') == 'ipa' and value.startswith('/') and value.endswith('/') and len(value) > 3:
                cell.text = None
                first = ET.SubElement(cell, 'span', {'style': 'white-space:nowrap'})
                first.text, first.tail = value[:2], value[2:-2]
                ET.SubElement(cell, 'span', {'style': 'white-space:nowrap'}).text = value[-2:]

    # Measure each entry at its final column width. One CSS pixel of spare width
    # conservatively covers the collapsed centre border of the final full table.
    measure_root = deepcopy(root)
    style = measure_root.find('./head/style')
    width = 190 * 96 / 25.4 / columns - 1
    style.text += f'\n.column-flow{{column-count:1!important;width:{width}px}}'
    measured = html_factory(ET.tostring(measure_root, encoding='unicode', method='html')).render(
        font_config=font_config)
    heights, overheads, header_height = {}, {}, None
    for page in measured.pages:
        for box in page._page_box.descendants():
            if box.element_tag == 'header' and type(box).__name__ == 'BlockBox':
                header_height = box.margin_height()
            if type(box).__name__ == 'TableRowBox' and box.element.get('data-number'):
                number = int(box.element.get('data-number'))
                if number in heights:
                    raise ValueError('单条内容超过 A4 可用高度，请减少例句或调整字号。')
                heights[number] = box.height
            if box.element_tag == 'section' and type(box).__name__ == 'BlockBox':
                index = int(box.element.get('data-group'))
                if index not in overheads:
                    first = next((b for b in box.descendants()
                                  if type(b).__name__ == 'TableRowBox'
                                  and b.element.get('data-number')), None)
                    if first:
                        overheads[index] = first.position_y - box.position_y
    if set(heights) != set(entries) or len(overheads) != len(groups) or header_height is None:
        raise ValueError('未能完整测量打印条目。')
    if any(height <= 0 for height in heights.values()):
        raise ValueError('打印行高无效。')
    pages = plan_pages(groups, columns, heights, overheads,
                       measured.pages[0]._page_box.height, header_height,
                       body.get('data-break-sections') == '1')
    for child in list(body):
        body.remove(child)
    body.set('data-layout', 'shared-grid-ready')
    body.set('data-pages', str(len(pages)))
    for page_index, chunks in enumerate(pages):
        page = ET.SubElement(body, 'div', {'class': 'aligned-page'})
        if page_index == 0:
            page.append(deepcopy(header))
        for group_index, grid in chunks:
            section = ET.SubElement(page, 'section', {'class': 'word-group'})
            section.append(deepcopy(sections[group_index].find('h2')))
            original = sections[group_index].find('.//table')
            table = ET.SubElement(section, 'table', {'class': 'vocabulary'})
            cols = ET.SubElement(table, 'colgroup')
            for _ in range(columns):
                for col, width in zip(original.find('colgroup'), widths):
                    new_col = deepcopy(col)
                    new_col.set('style', f'width:{width / columns}%')
                    cols.append(new_col)
            head = ET.SubElement(table, 'thead')
            line = ET.SubElement(head, 'tr')
            for _ in range(columns):
                for cell in original.find('./thead/tr'):
                    line.append(deepcopy(cell))
            tbody = ET.SubElement(table, 'tbody')
            for physical_row in grid:
                line = ET.SubElement(tbody, 'tr')
                for number in physical_row:
                    if number is not None:
                        for cell in entries[number]:
                            line.append(deepcopy(cell))
                    else:
                        for field in range(fields):
                            ET.SubElement(line, 'td', {'class': 'group-end' if field == fields - 1 else ''})
    return '<!doctype html>' + ET.tostring(root, encoding='unicode', method='html')
