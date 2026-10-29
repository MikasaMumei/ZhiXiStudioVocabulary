# Third-party notices

## Fonts

- Noto Sans Regular: [notofonts/noto-fonts](https://github.com/notofonts/noto-fonts), SIL Open Font License 1.1; retained in `englishwords/static/fonts/OFL-Latin.txt`.
- Noto Sans CJK SC Regular: [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk), SIL Open Font License 1.1; retained in `englishwords/static/fonts/OFL-CJK.txt`.

Fonts are bundled locally for Chinese and IPA rendering. PDF exports embed subsets. The optional HTML archive includes font files and their notices. The application MIT license does not replace the fonts' license.

## Software dependencies

Locked versions and integrity hashes are in `requirements.txt` and `requirements-dev.txt`. Flask, Flask-WTF, SQLAlchemy, psycopg, Alembic, openpyxl, Gunicorn, WeasyPrint and their dependencies retain their upstream licenses and copyright notices. Installed wheels keep upstream license metadata.

The Web image uses Python and Debian with Pango/HarfBuzz for shaping. Those components retain their respective licenses; their notices are not replaced by this repository's MIT license.

## Teaching content

`englishwords/static/sample.csv` is a small example authored for this project, explicitly labelled as non-textbook sample content. It is provided to demonstrate importing and printing, rather than as a verified curriculum list.

No private teaching database, commercial dictionary data, textbook collection, source cache or third-party full vocabulary list is included in the source distribution or application image. Users are responsible for obtaining the appropriate permission for data they import and redistribute. A license for an extraction program does not grant a license for extracted dictionary or textbook content.
