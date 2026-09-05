#!/usr/bin/env python3
"""
build_docx.py — Apple-Notes-HTML -> EIN DOCX-Dokument

Erzeugt ein Word-Dokument, das Pages verlustarm oeffnet:
  * Notiztitel als "Ueberschrift 1" (Pages baut daraus sein Inhaltsverzeichnis)
  * je Notiz ein harter Seitenumbruch
  * klickbares Inhaltsverzeichnis am Dokumentanfang (interne Hyperlinks)
  * fett / kursiv / unterstrichen / durchgestrichen, Listen, Tabellen, Links, Bilder

Nutzt ausschliesslich die Python-Standardbibliothek (+ optional PIL fuers
Herunterskalieren grosser Bilder). Keine Netzwerkzugriffe.
"""

import base64, io, json, os, re, subprocess, sys, tempfile, zipfile
from html.parser import HTMLParser
from datetime import datetime

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

DE = os.environ.get('EXPORT_NOTES_LANG', 'de') == 'de'

def t(de, en):
    """Text in der Sprache, in der auch das Programm spricht."""
    return de if DE else en

EMU_PER_PX   = 9525
MAX_IMG_W    = 5486400        # 6,0 Zoll nutzbare Textbreite (A4 minus Raender)
MAX_IMG_H    = 7315200        # 8,0 Zoll, damit ein Bild nicht mehrseitig wird
MAX_PIXELS   = 1400           # groesste Kantenlaenge nach dem Skalieren
XML_BAD      = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

def esc(t):
    """XML-sicher machen und Steuerzeichen entfernen."""
    return XML_BAD.sub('', t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

# ---------------------------------------------------------------- Parser ----

class Run:
    __slots__ = ('text', 'b', 'i', 'u', 's', 'mono', 'link')
    def __init__(self, text, b=False, i=False, u=False, s=False, mono=False, link=None):
        self.text, self.b, self.i, self.u, self.s = text, b, i, u, s
        self.mono, self.link = mono, link

class Block:
    """Ein Absatz, ein Listenpunkt, ein Bild oder eine Tabelle."""
    def __init__(self, kind, runs=None, level=0, ordered=False):
        self.kind = kind          # p | h1 | h2 | h3 | li | img | table
        self.runs = runs or []
        self.level = level
        self.ordered = ordered
        self.image = None         # (bytes, ext, w_emu, h_emu)
        self.rows = None          # fuer Tabellen: Liste von Listen von Blocks

class NotesHTMLParser(HTMLParser):
    """Wandelt Notes-HTML in eine flache Blockliste."""

    BLOCK_TAGS = {'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'br',
                  'tr', 'td', 'th', 'table', 'ul', 'ol', 'blockquote'}

    # Inline-Tags und die Auszeichnungen, die sie einschalten
    INLINE = {'b': ('b',), 'strong': ('b',), 'i': ('i',), 'em': ('i',),
              'u': ('u',), 's': ('s',), 'strike': ('s',), 'del': ('s',),
              'tt': ('mono',), 'code': ('mono',), 'kbd': ('mono',),
              'samp': ('mono',), 'pre': ('mono',)}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.cur = []                 # offene Runs
        self.fmt = {'b': 0, 'i': 0, 'u': 0, 's': 0, 'mono': 0}
        # Jedes geoeffnete Inline-Tag merkt sich, was es eingeschaltet hat,
        # damit das schliessende Tag genau das wieder zuruecknimmt. Ohne
        # diesen Stack blieb z. B. ein <span style="font-weight: bold">
        # bis zum Ende der Notiz aktiv.
        self.inline_stack = []
        self.link = None
        self.list_stack = []          # ('ul'|'ol', level)
        self.pending_kind = 'p'
        self.failed_images = []
        self.in_table = 0
        self.table_rows = None
        self.row = None

    def _oeffne(self, tag, keys):
        for k in keys:
            self.fmt[k] += 1
        self.inline_stack.append((tag, keys))

    def _schliesse(self, tag):
        # Von oben das passende offene Tag suchen: Notes verschachtelt
        # span/font gern unsauber, ein fehlendes Gegenstueck darf nichts
        # kaputtmachen.
        for i in range(len(self.inline_stack) - 1, -1, -1):
            if self.inline_stack[i][0] == tag:
                _, keys = self.inline_stack.pop(i)
                for k in keys:
                    self.fmt[k] = max(0, self.fmt[k] - 1)
                return

    # -- Hilfen ------------------------------------------------------------
    def flush(self, kind=None):
        """Offene Runs zu einem Block machen."""
        runs = [r for r in self.cur if r.text]
        self.cur = []
        k = kind or self.pending_kind
        if not runs:
            return
        if self.list_stack and k == 'p':
            style, lvl = self.list_stack[-1]
            blk = Block('li', runs, level=lvl, ordered=(style == 'ol'))
        else:
            blk = Block(k, runs)
        self.target().append(blk)
        self.pending_kind = 'p'

    def target(self):
        """Wohin Bloecke gehen: Tabellenzelle oder Dokument."""
        if self.in_table and self.row:
            return self.row[-1]
        return self.blocks

    def add_text(self, text):
        if not text:
            return
        self.cur.append(Run(text,
                            b=self.fmt['b'] > 0, i=self.fmt['i'] > 0,
                            u=self.fmt['u'] > 0, s=self.fmt['s'] > 0,
                            mono=self.fmt['mono'] > 0, link=self.link))

    # -- HTMLParser-Callbacks ---------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'img':
            self.handle_image(a.get('src', ''))
            return
        if tag in self.INLINE:
            self._oeffne(tag, self.INLINE[tag])
        elif tag == 'a':
            self.link = a.get('href')
        elif tag in ('span', 'font'):
            st = (a.get('style') or '').replace(' ', '')
            keys = []
            if 'font-weight:bold' in st or 'font-weight:600' in st \
               or 'font-weight:700' in st: keys.append('b')
            if 'italic' in st: keys.append('i')
            if 'underline' in st: keys.append('u')
            if 'line-through' in st: keys.append('s')
            # Notes drueckt Auszeichnungen auch ueber den Schriftnamen aus,
            # z. B. face=".AppleSystemUIFontMonospaced-Regular" oder
            # face="Arial-BoldMT".
            face = (a.get('face') or '').lower()
            if 'monospace' in st or 'mono' in face or 'menlo' in face \
               or 'courier' in face: keys.append('mono')
            if 'bold' in face and 'b' not in keys: keys.append('b')
            if 'italic' in face and 'i' not in keys: keys.append('i')
            self._oeffne(tag, tuple(keys))
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.flush()
            self.pending_kind = 'h2' if tag in ('h1', 'h2') else 'h3'
        elif tag in ('ul', 'ol'):
            self.flush()
            self.list_stack.append((tag, len(self.list_stack)))
        elif tag == 'li':
            self.flush()
        elif tag in ('div', 'p', 'blockquote'):
            self.flush()
        elif tag == 'br':
            self.flush()
        elif tag == 'table':
            self.flush()
            self.in_table += 1
            self.table_rows = []
        elif tag == 'tr' and self.in_table:
            self.row = []
            self.table_rows.append(self.row)
        elif tag in ('td', 'th') and self.in_table and self.row is not None:
            self.flush()
            self.row.append([])          # neue Zelle = eigene Blockliste

    def handle_endtag(self, tag):
        if tag in self.INLINE or tag in ('span', 'font'):
            self._schliesse(tag)
        elif tag == 'a':
            self.link = None
        elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.flush('h2' if tag in ('h1', 'h2') else 'h3')
        elif tag in ('ul', 'ol'):
            self.flush()
            if self.list_stack: self.list_stack.pop()
        elif tag in ('li', 'div', 'p', 'blockquote'):
            self.flush()
        elif tag in ('td', 'th'):
            self.flush()
        elif tag == 'tr':
            self.flush(); self.row = None
        elif tag == 'table' and self.in_table:
            self.flush()
            self.in_table -= 1
            rows = self.table_rows
            self.table_rows = None
            if rows and any(any(c) for c in rows):
                blk = Block('table'); blk.rows = rows
                self.blocks.append(blk)

    def handle_data(self, data):
        if data:
            self.add_text(data)

    # -- Bilder ------------------------------------------------------------
    def handle_image(self, src):
        if not src.startswith('data:'):
            self.failed_images.append('externe Quelle')
            return
        m = re.match(r'data:image/([A-Za-z0-9.+-]+);base64,(.*)', src, re.S)
        if not m:
            # Notes liefert fuer manche Anhaenge "data:(null);base64,(null)":
            # das Medium ist auf diesem Geraet nicht (mehr) verfuegbar.
            self.failed_images.append('von Notizen nicht geliefert')
            return
        ext = m.group(1).lower()
        if ext == 'jpeg': ext = 'jpg'
        try:
            raw = base64.b64decode(m.group(2), validate=False)
        except Exception:
            return
        if not raw:
            return
        self.flush()
        data, w_px, h_px, ext = process_image(raw, ext)
        if data is None:
            self.failed_images.append(ext or 'unbekannt')
            return
        w_emu = w_px * EMU_PER_PX
        h_emu = h_px * EMU_PER_PX
        if w_emu > MAX_IMG_W:
            h_emu = int(h_emu * MAX_IMG_W / w_emu); w_emu = MAX_IMG_W
        if h_emu > MAX_IMG_H:
            w_emu = int(w_emu * MAX_IMG_H / h_emu); h_emu = MAX_IMG_H
        blk = Block('img')
        blk.image = (data, ext, max(w_emu, 1), max(h_emu, 1))
        self.target().append(blk)


def heic_zu_jpeg(raw):
    """HEIC/HEIF ueber das macOS-Bordmittel `sips` nach JPEG wandeln.

    Notizen vom iPhone enthalten Fotos oft als HEIC. PIL kann das ohne
    Zusatzmodul nicht lesen, und DOCX kennt das Format ohnehin nicht.
    `sips` gehoert zu macOS, es wird also nichts nachinstalliert.
    """
    src = dst = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.heic', delete=False) as fh:
            fh.write(raw); src = fh.name
        dst = src[:-5] + '.jpg'
        r = subprocess.run(['sips', '-s', 'format', 'jpeg', src, '--out', dst],
                           capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
            with open(dst, 'rb') as fh:
                return fh.read()
    except Exception:
        pass
    finally:
        for f in (src, dst):
            if f and os.path.exists(f):
                try: os.unlink(f)
                except Exception: pass
    return None


def process_image(raw, ext):
    """Bild pruefen, exotische Formate wandeln, bei Bedarf verkleinern."""
    if not HAVE_PIL:
        return raw, 400, 300, ext if ext in ('png', 'jpg', 'gif') else 'png'
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        # HEIC/HEIF erkennt man am 'ftyp'-Kennsatz an Position 4.
        if len(raw) > 12 and raw[4:8] == b'ftyp':
            conv = heic_zu_jpeg(raw)
            if conv:
                try:
                    im = Image.open(io.BytesIO(conv)); im.load()
                    raw, ext = conv, 'jpg'
                except Exception:
                    return None, 0, 0, ext
            else:
                return None, 0, 0, ext
        else:
            return None, 0, 0, ext
    w, h = im.size
    if w == 0 or h == 0:
        return None, 0, 0, ext
    # Klein genug und in einem Format, das DOCX direkt kennt: unveraendert
    # uebernehmen — jedes Neukodieren kostet nur Qualitaet.
    if max(w, h) <= MAX_PIXELS and len(raw) < 900_000 \
       and im.format in ('PNG', 'JPEG', 'GIF'):
        return raw, w, h, ('jpg' if im.format == 'JPEG' else im.format.lower())
    scale = min(1.0, MAX_PIXELS / max(w, h))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    try:
        if scale < 1.0:
            im = im.resize((nw, nh), Image.LANCZOS)
        buf = io.BytesIO()
        if im.mode in ('RGBA', 'LA', 'P'):
            im = im.convert('RGBA'); im.save(buf, 'PNG', optimize=True); out = 'png'
        else:
            im = im.convert('RGB'); im.save(buf, 'JPEG', quality=85, optimize=True); out = 'jpg'
        return buf.getvalue(), nw, nh, out
    except Exception:
        return raw, w, h, ext

# ------------------------------------------------------------- DOCX-Bau ----

class DocxBuilder:
    def __init__(self):
        self.body = []
        self.rels = []            # (id, type, target, mode)
        self.media = {}           # name -> bytes
        self.link_rids = {}       # URL -> Beziehungs-ID (Mehrfachnutzung)
        self.rid = 0
        self.bookmark_id = 0

    def new_rid(self):
        self.rid += 1
        return 'rId%d' % self.rid

    def add_image(self, data, ext):
        name = 'image%d.%s' % (len(self.media) + 1, ext)
        self.media[name] = data
        rid = self.new_rid()
        self.rels.append((rid, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image',
                          'media/' + name, None))
        return rid

    def add_hyperlink(self, url):
        # Dieselbe Adresse braucht nur eine Beziehung im Paket.
        if url in self.link_rids:
            return self.link_rids[url]
        rid = self.new_rid()
        self.rels.append((rid, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',
                          url, 'External'))
        self.link_rids[url] = rid
        return rid

    # -- Bausteine ---------------------------------------------------------
    MONO_FONT = '<w:rFonts w:ascii="Menlo" w:hAnsi="Menlo" w:cs="Menlo"/>'

    def runs_xml(self, runs):
        out = []
        for r in runs:
            props = []
            if r.mono: props.append(self.MONO_FONT)
            if r.b: props.append('<w:b/>')
            if r.i: props.append('<w:i/>')
            if r.u: props.append('<w:u w:val="single"/>')
            if r.s: props.append('<w:strike/>')
            if r.mono: props.append('<w:sz w:val="20"/>')
            marken = ''.join(props)
            if r.link and r.link.startswith(('http://', 'https://', 'mailto:')):
                rid = self.add_hyperlink(r.link)
                out.append('<w:hyperlink r:id="%s"><w:r><w:rPr>'
                           '<w:rStyle w:val="Hyperlink"/>%s</w:rPr>'
                           '<w:t xml:space="preserve">%s</w:t></w:r></w:hyperlink>'
                           % (rid, marken, esc(r.text)))
            else:
                rpr = '<w:rPr>%s</w:rPr>' % marken if marken else ''
                out.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>'
                           % (rpr, esc(r.text)))
        return ''.join(out)

    def para(self, runs, style=None, numid=None, level=0, bookmark=None, page_break=False):
        ppr = []
        if style: ppr.append('<w:pStyle w:val="%s"/>' % style)
        if numid: ppr.append('<w:numPr><w:ilvl w:val="%d"/><w:numId w:val="%d"/></w:numPr>' % (level, numid))
        if page_break: ppr.append('<w:pageBreakBefore/>')
        ppr_xml = '<w:pPr>%s</w:pPr>' % ''.join(ppr) if ppr else ''
        bm = ''
        if bookmark:
            self.bookmark_id += 1
            bm = ('<w:bookmarkStart w:id="%d" w:name="%s"/><w:bookmarkEnd w:id="%d"/>'
                  % (self.bookmark_id, bookmark, self.bookmark_id))
        self.body.append('<w:p>%s%s%s</w:p>' % (ppr_xml, bm, self.runs_xml(runs)))

    def para_raw(self, xml):
        self.body.append(xml)

    def image_para(self, blk):
        data, ext, w, h = blk.image
        rid = self.add_image(data, ext)
        self.body.append(
            '<w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:drawing>'
            '<wp:inline distT="0" distB="0" distL="0" distR="0">'
            '<wp:extent cx="%d" cy="%d"/><wp:docPr id="%d" name="Bild%d"/>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:nvPicPr><pic:cNvPr id="%d" name="Bild%d"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
            % (w, h, len(self.media), len(self.media), len(self.media), len(self.media), rid, w, h))

    def internal_link_para(self, text, anchor, style=None):
        ppr = '<w:pPr><w:pStyle w:val="%s"/></w:pPr>' % style if style else ''
        self.body.append(
            '<w:p>%s<w:hyperlink w:anchor="%s"><w:r><w:rPr><w:rStyle w:val="Hyperlink"/></w:rPr>'
            '<w:t xml:space="preserve">%s</w:t></w:r></w:hyperlink></w:p>'
            % (ppr, anchor, esc(text)))

    def table(self, rows, render_cell):
        xml = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
               '<w:tblW w:w="0" w:type="auto"/>'
               '<w:tblBorders>'
               + ''.join('<w:%s w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>' % s
                         for s in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
               + '</w:tblBorders></w:tblPr>']
        ncols = max((len(r) for r in rows), default=1)
        xml.append('<w:tblGrid>' + '<w:gridCol w:w="%d"/>' % (9000 // max(ncols, 1)) * ncols + '</w:tblGrid>')
        for row in rows:
            xml.append('<w:tr>')
            for c in range(ncols):
                cell = row[c] if c < len(row) else []
                inner = render_cell(cell)
                if not inner:
                    inner = '<w:p/>'
                xml.append('<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>%s</w:tc>' % inner)
            xml.append('</w:tr>')
        xml.append('</w:tbl><w:p/>')
        self.body.append(''.join(xml))

# --------------------------------------------------------- XML-Vorlagen ----

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Default Extension="gif" ContentType="image/gif"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''

ROOT_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

def heading_style(sid, name, size_half_pt, color, outline, space_before=240, bold=True):
    return ('<w:style w:type="paragraph" w:styleId="%s"><w:name w:val="%s"/>'
            '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
            '<w:pPr><w:keepNext/><w:outlineLvl w:val="%d"/>'
            '<w:spacing w:before="%d" w:after="120"/></w:pPr>'
            '<w:rPr>%s<w:color w:val="%s"/><w:sz w:val="%d"/><w:szCs w:val="%d"/></w:rPr></w:style>'
            % (sid, name, outline, space_before, '<w:b/>' if bold else '', color,
               size_half_pt, size_half_pt))

STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Helvetica Neue" w:hAnsi="Helvetica Neue" w:cs="Helvetica Neue"/>
<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
''' + heading_style('Heading1', 'heading 1', 40, '1A1A1A', 0, 480) \
    + heading_style('Heading2', 'heading 2', 30, '2C2C2C', 1, 320) \
    + heading_style('Heading3', 'heading 3', 26, '3A3A3A', 2, 260) \
    + heading_style('Title', 'Title', 56, '1A1A1A', 0, 0) \
    + '''<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/>
<w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="240"/></w:pPr>
<w:rPr><w:color w:val="6B6B6B"/><w:sz w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TOC1"><w:name w:val="toc 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:after="60"/><w:ind w:left="0"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="NoteMeta"><w:name w:val="Notiz-Metadaten"/>
<w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="240"/></w:pPr>
<w:rPr><w:color w:val="8A8A8A"/><w:sz w:val="18"/><w:i/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>
<w:rPr><w:color w:val="0B6BCB"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>
<w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
<w:left w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
<w:right w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
<w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
</w:tblBorders></w:tblPr></w:style>
</w:styles>'''

def _num_lvls(fmt, chars):
    out = []
    for i in range(9):
        ch = chars[i % len(chars)]
        txt = ch if fmt == 'bullet' else '%' + str(i + 1) + '.'
        out.append('<w:lvl w:ilvl="%d"><w:start w:val="1"/><w:numFmt w:val="%s"/>'
                   '<w:lvlText w:val="%s"/><w:lvlJc w:val="left"/>'
                   '<w:pPr><w:ind w:left="%d" w:hanging="360"/></w:pPr>'
                   '<w:rPr><w:rFonts w:ascii="Helvetica Neue" w:hAnsi="Helvetica Neue"/></w:rPr></w:lvl>'
                   % (i, fmt, txt, 720 + i * 360))
    return ''.join(out)

NUMBERING = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:abstractNum w:abstractNumId="0">' + _num_lvls('bullet', ['•', '◦', '▪']) + '</w:abstractNum>'
    '<w:abstractNum w:abstractNumId="1">' + _num_lvls('decimal', ['']) + '</w:abstractNum>'
    '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>'
    '</w:numbering>')

def core_props(title, count):
    now = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>%s</dc:title><dc:subject>%s</dc:subject>'
        '<dc:creator>export-notes</dc:creator>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
        '</cp:coreProperties>'
        % (esc(title),
           esc(t('Export aus Apple Notizen (%d Notizen)',
                 'Export from Apple Notes (%d notes)') % count), now, now))

APP_PROPS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    '<Application>export-notes</Application></Properties>')

DOC_OPEN = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document '
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<w:body>')

DOC_CLOSE = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1417" w:right="1417" w:bottom="1417" w:left="1417" '
    'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')

# ------------------------------------------------------------------ Main ----

def render_blocks(doc, blocks):
    """Blocks in die Dokumentliste schreiben."""
    for blk in blocks:
        if blk.kind == 'img':
            doc.image_para(blk)
        elif blk.kind == 'table':
            doc.table(blk.rows, lambda cell: render_cell_xml(doc, cell))
        elif blk.kind == 'li':
            doc.para(blk.runs, style=None, numid=(2 if blk.ordered else 1),
                     level=min(blk.level, 8))
        elif blk.kind in ('h2', 'h3'):
            doc.para(blk.runs, style='Heading2' if blk.kind == 'h2' else 'Heading3')
        else:
            doc.para(blk.runs)

def render_cell_xml(doc, cell_blocks):
    """Tabellenzelle rendern: temporaer in eine eigene Body-Liste."""
    saved = doc.body
    doc.body = []
    render_blocks(doc, cell_blocks)
    xml = ''.join(doc.body) or '<w:p/>'
    doc.body = saved
    return xml

SORTIERUNGEN = {
    'tagebuch':    t('chronologisch, älteste zuerst', 'chronological, oldest first'),
    'rueckwaerts': t('chronologisch rückwärts, neueste zuerst',
                     'reverse chronological, newest first'),
    'geaendert':   t('zuletzt geänderte zuerst', 'most recently edited first'),
    'ordner':      t('nach Ordner gruppiert, darin neueste zuerst',
                     'grouped by folder, newest first within'),
    'titel':       t('alphabetisch nach Titel', 'alphabetical by title'),
}


def sortiere(notes, modus):
    """Notizen in die gewuenschte Reihenfolge bringen.

    'ordner' behaelt die Reihenfolge bei, in der Notizen gelesen wurden
    (Ordner fuer Ordner, darin wie in Apple Notizen). Alle anderen Modi
    ordnen ueber saemtliche Ordner hinweg durch.
    """
    def schluessel_datum(n, feld):
        # Notizen ohne Datum ans Ende, damit sie die Chronologie nicht stoeren
        return (n.get(feld) is None, n.get(feld) or '')

    if modus == 'ordner':
        return list(notes)
    if modus == 'tagebuch':
        return sorted(notes, key=lambda n: schluessel_datum(n, 'created'))
    if modus == 'rueckwaerts':
        return sorted(notes, key=lambda n: schluessel_datum(n, 'created'),
                      reverse=True)
    if modus == 'geaendert':
        return sorted(notes, key=lambda n: schluessel_datum(n, 'modified'),
                      reverse=True)
    if modus == 'titel':
        return sorted(notes, key=lambda n: (n.get('title') or '').lower())
    return list(notes)


def jahr_von(n):
    d = n.get('created') or n.get('modified')
    return d[:4] if d else None


def fmt_date(iso_str):
    if not iso_str:
        return None
    try:
        d = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return d.strftime('%d.%m.%Y, %H:%M')
    except Exception:
        return None

def main():
    if len(sys.argv) < 3:
        print('Aufruf: build_docx.py <workDir> <ausgabe.docx> [reihenfolge]',
              file=sys.stderr)
        print('Reihenfolgen: ' + ', '.join(SORTIERUNGEN), file=sys.stderr)
        return 2
    work_dir, out_path = sys.argv[1], sys.argv[2]
    modus = sys.argv[3] if len(sys.argv) > 3 else 'tagebuch'
    if modus not in SORTIERUNGEN:
        print('Unbekannte Reihenfolge: %s' % modus, file=sys.stderr)
        return 2

    with open(os.path.join(work_dir, 'manifest.json'), encoding='utf-8') as fh:
        manifest = json.load(fh)
    notes = sortiere(manifest['notes'], modus)

    doc = DocxBuilder()
    report = {'total': len(notes), 'ok': 0, 'failed': [], 'empty': [],
              'locked': [], 'lost_images': [], 'images': 0}

    # ---- Titelseite ----
    doc.para([Run(t('Apple Notes Gesamtexport', 'Apple Notes Export'))], style='Title')
    doc.para([Run(t('%d Notizen · exportiert am %s'
                    % (len(notes), datetime.now().strftime('%d.%m.%Y um %H:%M')),
                    '%d notes · exported %s'
                    % (len(notes), datetime.now().strftime('%Y-%m-%d %H:%M'))))],
             style='Subtitle')
    doc.para([Run(t('Reihenfolge: %s', 'Order: %s') % SORTIERUNGEN[modus])],
             style='NoteMeta')

    # ---- Inhaltsverzeichnis ----
    doc.para([Run(t('Inhaltsverzeichnis', 'Table of contents'))],
             style='Heading1', page_break=True)
    doc.para([Run(t('Pages kann zusätzlich ein eigenes, automatisch gepflegtes '
                    'Inhaltsverzeichnis einblenden: Menü „Ansicht“ → '
                    '„Inhaltsverzeichnis einblenden“.',
                    'Pages can also show its own automatically maintained table '
                    'of contents: View → Show Table of Contents.'))],
             style='NoteMeta')
    # Mehrfach vergebene Titel (Apple vergibt oft "Neue Notiz") bekommen im
    # Verzeichnis das Datum dazu — sonst stehen mehrere gleich aussehende
    # Eintraege untereinander und man weiss nicht, welcher welcher ist.
    haeufigkeit = {}
    for n in notes:
        titel_text = (n['title'] or t('(ohne Titel)', '(untitled)')).strip()
        haeufigkeit[titel_text] = haeufigkeit.get(titel_text, 0) + 1

    # Zwischenueberschriften passend zur Sortierung: nach Ordner gruppiert
    # sind Ordnernamen sinnvoll, chronologisch sortiert die Jahreszahl.
    letzte_gruppe = None
    for n in notes:
        if modus == 'ordner':
            gruppe = n.get('folder')
        elif modus in ('tagebuch', 'rueckwaerts', 'geaendert'):
            gruppe = jahr_von(n)
        else:
            gruppe = None
        if gruppe and gruppe != letzte_gruppe:
            doc.para([Run(gruppe, b=True)], style='Heading3')
            letzte_gruppe = gruppe
        title = (n['title'] or t('(ohne Titel)', '(untitled)')).strip()
        beschriftung = title
        if haeufigkeit.get(title, 0) > 1:
            datum = fmt_date(n.get('created')) or fmt_date(n.get('modified'))
            if datum:
                beschriftung = '%s  ·  %s' % (title, datum.split(',')[0])
            elif n.get('folder'):
                beschriftung = '%s  ·  %s' % (title, n['folder'])
        einzug = '    ' if gruppe else ''
        doc.internal_link_para(einzug + beschriftung, 'note%d' % n['index'],
                               style='TOC1')

    # ---- Notizen ----
    for n in notes:
        title = n['title'] or t('(ohne Titel)', '(untitled)')
        path = os.path.join(work_dir, 'notes', n['file'])
        if n.get('locked'):
            doc.para([Run(title)], style='Heading1',
                     bookmark='note%d' % n['index'], page_break=True)
            doc.para([Run(t('Ordner: %s · passwortgeschützt',
                            'Folder: %s · password-protected')
                          % n.get('folder', '?'))], style='NoteMeta')
            doc.para([Run(t('Diese Notiz ist in Apple Notizen mit einem Passwort '
                            'geschützt. Gesperrte Notizen geben ihren Inhalt aus '
                            'Sicherheitsgründen nicht an die Automatisierung weiter — '
                            'der Text ist deshalb hier nicht enthalten. Er lässt sich '
                            'nur direkt in Apple Notizen nach Eingabe des Passworts '
                            'einsehen.',
                            'This note is password-protected in Apple Notes. Locked '
                            'notes do not hand their contents to automation, for '
                            'security reasons — the text is therefore not included '
                            'here. It can only be viewed directly in Apple Notes '
                            'after entering the password.'))])
            report['locked'].append({'title': title, 'id': n.get('id'),
                                     'folder': n.get('folder')})
            report['ok'] += 1
            continue

        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                raw = fh.read()
        except Exception as e:
            report['failed'].append({'title': title, 'id': n.get('id'),
                                     'grund': 'HTML nicht lesbar: %s' % e})
            continue

        # Ueberschrift 1 + Bookmark (Sprungziel des Inhaltsverzeichnisses)
        doc.para([Run(title)], style='Heading1',
                 bookmark='note%d' % n['index'], page_break=True)

        meta = []
        if n.get('folder'):
            meta.append(t('Ordner: %s', 'Folder: %s') % n['folder'])
        d = fmt_date(n.get('created'))
        if d: meta.append(t('erstellt %s', 'created %s') % d)
        d = fmt_date(n.get('modified'))
        if d: meta.append(t('geändert %s', 'modified %s') % d)
        if meta:
            doc.para([Run(' · '.join(meta))], style='NoteMeta')

        try:
            before_media = len(doc.media)
            parser = NotesHTMLParser()
            parser.feed(raw)
            parser.close()
            parser.flush()
            blocks = parser.blocks
            if not blocks:
                doc.para([Run(t('(Diese Notiz enthält keinen darstellbaren Inhalt.)',
                                '(This note has no displayable content.)'))],
                         style='NoteMeta')
                report['empty'].append({'title': title, 'id': n.get('id')})
            render_blocks(doc, blocks)
            report['images'] += len(doc.media) - before_media
            for fmt in parser.failed_images:
                report['lost_images'].append({'title': title, 'format': fmt})
            report['ok'] += 1
        except Exception as e:
            doc.para([Run(t('(Inhalt konnte nicht vollständig umgewandelt werden: %s)',
                            '(Content could not be fully converted: %s)') % e)],
                     style='NoteMeta')
            report['failed'].append({'title': title, 'id': n.get('id'),
                                     'grund': 'Umwandlung fehlgeschlagen: %s' % e})

    # ---- Paket schreiben ----
    doc_xml = DOC_OPEN + ''.join(doc.body) + DOC_CLOSE
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rIdNum" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>']
    for rid, typ, target, mode in doc.rels:
        m = ' TargetMode="External"' if mode else ''
        rels.append('<Relationship Id="%s" Type="%s" Target="%s"%s/>'
                    % (rid, typ, esc(target), m))
    rels.append('</Relationships>')

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', ROOT_RELS)
        z.writestr('docProps/core.xml', core_props('Apple Notes Gesamtexport', len(notes)))
        z.writestr('docProps/app.xml', APP_PROPS)
        z.writestr('word/document.xml', doc_xml)
        z.writestr('word/styles.xml', STYLES)
        z.writestr('word/numbering.xml', NUMBERING)
        z.writestr('word/_rels/document.xml.rels', ''.join(rels))
        for name, data in doc.media.items():
            z.writestr('word/media/' + name, data)

    report['size_mb'] = round(os.path.getsize(out_path) / 1048576, 2)
    with open(os.path.join(work_dir, 'report.json'), 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps({'ok': report['ok'], 'failed': len(report['failed']),
                      'empty': len(report['empty']), 'locked': len(report['locked']),
                      'images': report['images'],
                      'size_mb': report['size_mb']}, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    sys.exit(main())
