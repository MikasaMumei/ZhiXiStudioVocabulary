"""Isolated PDF worker. Only bundled fonts may be fetched; no network access."""
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
import zipfile


def render(payload):
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration
    from weasyprint.urls import URLFetcher, URLFetcherResponse

    fonts = Path(__file__).parent / 'static' / 'fonts'
    allowed = {name: fonts / name for name in ('NotoSans-Regular.ttf', 'NotoSansCJKsc-Regular.otf')}

    class BundledFontFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            parsed = urlparse(url)
            name = Path(parsed.path).name
            if parsed.scheme != 'https' or parsed.netloc != 'fonts.invalid' or parsed.path != '/' + name or name not in allowed:
                raise ValueError('PDF 禁止加载外部资源。')
            return URLFetcherResponse(url, allowed[name].read_bytes(), {'Content-Type': 'font/ttf' if name.endswith('.ttf') else 'font/otf'})

    fetcher = BundledFontFetcher(fail_on_errors=True)

    def pdf(html):
        from .print_layout import aligned_html
        font_config = FontConfiguration()

        def html_factory(source):
            source = source.replace('url("assets/', 'url("https://fonts.invalid/')
            return HTML(string=source, url_fetcher=fetcher)

        html = aligned_html(html, html_factory, font_config) if 'data-layout="shared-grid"' in html else html
        parsed = html_factory(html)
        document = parsed.render(font_config=font_config)
        expected_pages = parsed.etree_element.find('body').get('data-pages')
        if expected_pages and len(document.pages) != int(expected_pages):
            raise ValueError('实际分页与网格计划不一致，请缩小打印范围。')
        return document.write_pdf()

    if payload['format'] == 'pdf':
        return pdf(next(iter(payload['documents'].values())))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, html in payload['documents'].items():
            archive.writestr(name + '.pdf', pdf(html))
        archive.writestr('README.txt', '智习工作室词表 / ZhiXi Studio Vocabulary\nPDF 已内嵌字体，可直接打印。中英对照、看英写中、看中写英三份资料使用相同编号，可用中英对照核对。\n资料校验值：' + payload['checksum'])
    return buffer.getvalue()


if __name__ == '__main__':
    sys.stdout.buffer.write(render(json.load(sys.stdin)))
