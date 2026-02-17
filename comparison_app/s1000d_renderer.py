"""
Renders S1000D XML data modules to HTML for the comparison view.
Supports both descriptive (descript.xsd) and procedure (proced.xsd) modules.
"""

from lxml import etree
from html import escape


class S1000DHTMLRenderer:
    """Renders S1000D XML data modules to HTML."""

    def __init__(self, graphics_base_url: str = '/graphics'):
        self.graphics_base_url = graphics_base_url
        self._section_counter = 0
        self._anno_counter = 0

    def _anno(self, anno_type: str) -> str:
        """Return data-anno-idx and data-anno-type attributes string."""
        self._anno_counter += 1
        return f'data-anno-idx="{self._anno_counter}" data-anno-type="{anno_type}"'

    def render(self, xml_path: str) -> str:
        """Parse XML file and render to HTML string."""
        parser = etree.XMLParser(
            resolve_entities=False,
            dtd_validation=False,
            load_dtd=False,
        )
        tree = etree.parse(xml_path, parser)
        root = tree.getroot()

        self._section_counter = 0
        self._anno_counter = 0
        parts = []

        # Render header (techName + infoName)
        parts.append(self._render_header(root))

        # Detect module type and render content
        content = root.find('.//content')
        if content is None:
            return '<div class="s1000d-content"><p>No content found</p></div>'

        description = content.find('description')
        procedure = content.find('procedure')

        if description is not None:
            parts.append(self._render_description(description))
        elif procedure is not None:
            parts.append(self._render_procedure(procedure))

        return f'<div class="s1000d-content">{"".join(parts)}</div>'

    def _render_header(self, root) -> str:
        """Extract and render dmTitle as header."""
        tech_name = root.findtext('.//dmTitle/techName', '')
        info_name = root.findtext('.//dmTitle/infoName', '')

        title = escape(tech_name)
        if info_name:
            title += f' &mdash; {escape(info_name)}'

        return f'<h1 class="dm-title" {self._anno("heading")}>{title}</h1>'

    # ------------------------------------------------------------------
    # Descriptive modules
    # ------------------------------------------------------------------

    def _render_description(self, desc) -> str:
        """Render <description> element."""
        parts = []
        count = 0
        for child in desc:
            tag = etree.QName(child.tag).localname if '}' in child.tag else child.tag
            if tag == 'levelledPara':
                if count > 0:
                    parts.append('<div class="page-spacer"></div>')
                parts.append(self._render_levelled_para(child, level=2))
                count += 1
        return ''.join(parts)

    def _render_levelled_para(self, lp, level: int = 2) -> str:
        """Render <levelledPara> with nested content."""
        self._section_counter += 1
        sec_id = f's1000d-sec-{self._section_counter}'

        parts = [f'<div class="levelled-para level-{level}" data-section-id="{sec_id}">']

        first_para = True
        for child in lp:
            tag = _local_tag(child)
            if tag == 'para':
                if first_para and level <= 4:
                    # First para in a levelledPara is often a section heading
                    text = self._get_para_html(child)
                    if text.strip() and not child.find('.//randomList') is not None:
                        parts.append(f'<h{level} {self._anno("heading")} data-section-id="{sec_id}">{text}</h{level}>')
                        first_para = False
                        continue
                parts.append(self._render_para(child))
                first_para = False
            elif tag == 'table':
                parts.append(self._render_table(child))
                first_para = False
            elif tag == 'figure':
                parts.append(self._render_figure(child))
                first_para = False
            elif tag == 'levelledPara':
                parts.append(self._render_levelled_para(child, level=level + 1))
                first_para = False
            elif tag == 'warning':
                parts.append(self._render_warning(child))
                first_para = False
            elif tag == 'caution':
                parts.append(self._render_caution(child))
                first_para = False
            elif tag == 'note':
                parts.append(self._render_note(child))
                first_para = False

        parts.append('</div>')
        return ''.join(parts)

    # ------------------------------------------------------------------
    # Procedure modules
    # ------------------------------------------------------------------

    def _render_procedure(self, proc) -> str:
        """Render <procedure> element."""
        parts = []
        has_content = False
        for child in proc:
            tag = _local_tag(child)
            if tag == 'preliminaryRqmts':
                if has_content:
                    parts.append('<div class="page-spacer"></div>')
                parts.append(self._render_preliminary_rqmts(child))
                has_content = True
            elif tag == 'mainProcedure':
                if has_content:
                    parts.append('<div class="page-spacer"></div>')
                parts.append(self._render_main_procedure(child))
                has_content = True
            elif tag == 'closeRqmts':
                if has_content:
                    parts.append('<div class="page-spacer"></div>')
                parts.append(self._render_close_rqmts(child))
                has_content = True
        return ''.join(parts)

    def _render_preliminary_rqmts(self, prelim) -> str:
        """Render prerequisite section."""
        parts = ['<div class="preliminary-rqmts">',
                 f'<h2 {self._anno("heading")}>Предварительные требования</h2>']

        for child in prelim:
            tag = _local_tag(child)
            if tag == 'reqSupportEquips':
                parts.append(self._render_req_support_equips(child))
            elif tag == 'reqSupplies':
                parts.append(self._render_req_supplies(child))
            elif tag == 'reqSpares':
                parts.append(self._render_req_spares(child))
            elif tag == 'reqSafety':
                parts.append(self._render_req_safety(child))

        parts.append('</div>')
        return ''.join(parts)

    def _render_req_support_equips(self, elem) -> str:
        """Render support equipment table."""
        items = elem.findall('.//supportEquipDescr')
        if not items:
            return ''

        parts = [f'<h3 {self._anno("heading")}>Средства наземного обслуживания</h3>',
                 f'<table class="rqmt-table" {self._anno("table")}><thead><tr>',
                 '<th>#</th><th>Наименование</th><th>Количество</th>',
                 '</tr></thead><tbody>']

        for i, item in enumerate(items, 1):
            name = escape(item.findtext('name', ''))
            qty = escape(item.findtext('reqQuantity', ''))
            parts.append(f'<tr><td>{i}</td><td>{name}</td><td>{qty}</td></tr>')

        parts.append('</tbody></table>')
        return ''.join(parts)

    def _render_req_supplies(self, elem) -> str:
        """Render consumables table."""
        items = elem.findall('.//supplyDescr')
        if not items:
            return ''

        parts = [f'<h3 {self._anno("heading")}>Расходные материалы</h3>',
                 f'<table class="rqmt-table" {self._anno("table")}><thead><tr>',
                 '<th>#</th><th>Наименование</th><th>Количество</th>',
                 '</tr></thead><tbody>']

        for i, item in enumerate(items, 1):
            name = escape(item.findtext('name', ''))
            qty = escape(item.findtext('reqQuantity', ''))
            parts.append(f'<tr><td>{i}</td><td>{name}</td><td>{qty}</td></tr>')

        parts.append('</tbody></table>')
        return ''.join(parts)

    def _render_req_spares(self, elem) -> str:
        """Render spare parts section."""
        if elem.find('noSpares') is not None:
            return (f'<h3 {self._anno("heading")}>Запасные части</h3>'
                    f'<p {self._anno("para")} class="no-items">Не требуются</p>')
        return ''

    def _render_req_safety(self, elem) -> str:
        """Render safety requirements."""
        parts = [f'<h3 {self._anno("heading")}>Требования безопасности</h3>']
        for note in elem.findall('.//note'):
            parts.append(self._render_note(note))
        for warning in elem.findall('.//warning'):
            parts.append(self._render_warning(warning))
        return ''.join(parts)

    def _render_main_procedure(self, main_proc) -> str:
        """Render <mainProcedure> element."""
        parts = ['<div class="main-procedure">',
                 f'<h2 {self._anno("heading")}>Порядок выполнения работ</h2>']

        step_num = 0
        for child in main_proc:
            if _local_tag(child) == 'proceduralStep':
                step_num += 1
                if step_num > 1:
                    parts.append('<div class="page-spacer"></div>')
                parts.append(self._render_procedural_step(child, str(step_num)))

        parts.append('</div>')
        return ''.join(parts)

    def _render_procedural_step(self, step, numbering: str = '') -> str:
        """Render <proceduralStep> as numbered paragraph with nested steps."""
        self._section_counter += 1
        sec_id = f's1000d-sec-{self._section_counter}'

        parts = [f'<div class="procedural-step" data-section-id="{sec_id}">']

        sub_step_num = 0
        for child in step:
            tag = _local_tag(child)
            if tag == 'para':
                text = self._get_para_html(child)
                # Check if this is a section title (first para of a top-level step)
                if '.' not in numbering and sub_step_num == 0:
                    # Top-level step heading
                    parts.append(f'<h3 class="step-title" {self._anno("heading")}>'
                                 f'<span class="step-number">{numbering}</span> {text}</h3>')
                else:
                    parts.append(f'<p class="step-para" {self._anno("para")}>'
                                 f'<span class="step-number">{numbering}</span> {text}</p>')
            elif tag == 'proceduralStep':
                sub_step_num += 1
                sub_numbering = f'{numbering}.{sub_step_num}'
                parts.append(self._render_procedural_step(child, sub_numbering))
            elif tag == 'table':
                parts.append(self._render_table(child))
            elif tag == 'figure':
                parts.append(self._render_figure(child))
            elif tag == 'warning':
                parts.append(self._render_warning(child))
            elif tag == 'caution':
                parts.append(self._render_caution(child))
            elif tag == 'note':
                parts.append(self._render_note(child))

        parts.append('</div>')
        return ''.join(parts)

    def _render_close_rqmts(self, close) -> str:
        """Render closing requirements."""
        # Usually just noConds
        if close.find('.//noConds') is not None:
            return ''
        return f'<div class="close-rqmts"><h2 {self._anno("heading")}>Заключительные требования</h2></div>'

    # ------------------------------------------------------------------
    # Common elements
    # ------------------------------------------------------------------

    def _render_para(self, para) -> str:
        """Render <para> element, handling nested randomList."""
        random_list = para.find('randomList')
        sequenced_list = para.find('sequentialList')

        if random_list is not None:
            # Text before the list + the list
            text_before = _text_content_before_child(para, random_list)
            parts = []
            if text_before.strip():
                parts.append(f'<p {self._anno("para")}>{escape(text_before)}</p>')
            parts.append(self._render_random_list(random_list))
            return ''.join(parts)

        if sequenced_list is not None:
            text_before = _text_content_before_child(para, sequenced_list)
            parts = []
            if text_before.strip():
                parts.append(f'<p {self._anno("para")}>{escape(text_before)}</p>')
            parts.append(self._render_sequenced_list(sequenced_list))
            return ''.join(parts)

        text = self._get_para_html(para)
        if not text.strip():
            return ''
        return f'<p {self._anno("para")}>{text}</p>'

    def _get_para_html(self, para) -> str:
        """Get HTML content of a <para>, handling inline elements."""
        parts = []
        if para.text:
            parts.append(escape(para.text))

        for child in para:
            tag = _local_tag(child)
            if tag == 'emphasis':
                emp_type = child.get('emphasisType', 'em01')
                if emp_type == 'em01':
                    parts.append(f'<strong>{escape(child.text or "")}</strong>')
                elif emp_type == 'em02':
                    parts.append(f'<em>{escape(child.text or "")}</em>')
                else:
                    parts.append(escape(child.text or ''))
            elif tag == 'randomList':
                continue  # handled separately
            elif tag == 'sequentialList':
                continue
            else:
                parts.append(escape(child.text or ''))

            if child.tail:
                parts.append(escape(child.tail))

        return ''.join(parts)

    def _render_table(self, table) -> str:
        """Render S1000D <table> to HTML <table>."""
        table_id = table.get('id', '')
        parts = [f'<table class="s1000d-table" {self._anno("table")} id="{escape(table_id)}">']

        for tgroup in table.findall('tgroup'):
            cols = int(tgroup.get('cols', '1'))

            # Column specs
            colspecs = tgroup.findall('colspec')
            if colspecs:
                parts.append('<colgroup>')
                for cs in colspecs:
                    parts.append(f'<col>')
                parts.append('</colgroup>')

            # Header
            thead = tgroup.find('thead')
            if thead is not None:
                parts.append('<thead>')
                for row in thead.findall('row'):
                    parts.append(self._render_table_row(row, cell_tag='th'))
                parts.append('</thead>')

            # Body
            tbody = tgroup.find('tbody')
            if tbody is not None:
                parts.append('<tbody>')
                for row in tbody.findall('row'):
                    parts.append(self._render_table_row(row, cell_tag='td'))
                parts.append('</tbody>')

        parts.append('</table>')
        return ''.join(parts)

    def _render_table_row(self, row, cell_tag: str = 'td') -> str:
        """Render a table row."""
        parts = ['<tr>']
        for entry in row.findall('entry'):
            colspan = entry.get('nameend', '')
            # Get content from para children
            cell_html = ''
            for child in entry:
                if _local_tag(child) == 'para':
                    cell_html += self._get_para_html(child)

            if not cell_html and entry.text:
                cell_html = escape(entry.text)

            parts.append(f'<{cell_tag}>{cell_html}</{cell_tag}>')
        parts.append('</tr>')
        return ''.join(parts)

    def _render_figure(self, figure) -> str:
        """Render <figure> with <title> and <graphic>."""
        title_text = figure.findtext('title', '')
        parts = [f'<div class="figure" {self._anno("figure")}>']

        for graphic in figure.findall('graphic'):
            ident = graphic.get('infoEntityIdent', '')
            src = f'{self.graphics_base_url}/{ident}.jpg'
            parts.append(f'<img src="{src}" alt="{escape(title_text)}" class="figure-graphic">')

        if title_text:
            parts.append(f'<p class="figure-title">{escape(title_text)}</p>')

        parts.append('</div>')
        return ''.join(parts)

    def _render_random_list(self, rlist) -> str:
        """Render <randomList> as <ul>."""
        parts = [f'<ul class="random-list" {self._anno("unnumbered_list")}>']
        for item in rlist.findall('listItem'):
            item_html = ''
            for child in item:
                if _local_tag(child) == 'para':
                    item_html += self._get_para_html(child)
            parts.append(f'<li>{item_html}</li>')
        parts.append('</ul>')
        return ''.join(parts)

    def _render_sequenced_list(self, slist) -> str:
        """Render <sequentialList> as <ol>."""
        parts = [f'<ol class="sequenced-list" {self._anno("numbered_list")}>']
        for item in slist.findall('listItem'):
            item_html = ''
            for child in item:
                if _local_tag(child) == 'para':
                    item_html += self._get_para_html(child)
            parts.append(f'<li>{item_html}</li>')
        parts.append('</ol>')
        return ''.join(parts)

    def _render_warning(self, warning) -> str:
        """Render <warning> block."""
        parts = [f'<div class="admonition warning" {self._anno("warning")}>',
                 '<div class="admonition-title">ПРЕДУПРЕЖДЕНИЕ</div>']
        for child in warning:
            if _local_tag(child) == 'warningAndCautionPara':
                text = self._get_para_html(child)
                parts.append(f'<p>{text}</p>')
        parts.append('</div>')
        return ''.join(parts)

    def _render_caution(self, caution) -> str:
        """Render <caution> block."""
        parts = [f'<div class="admonition caution" {self._anno("caution")}>',
                 '<div class="admonition-title">ВНИМАНИЕ</div>']
        for child in caution:
            if _local_tag(child) == 'warningAndCautionPara':
                text = self._get_para_html(child)
                parts.append(f'<p>{text}</p>')
        parts.append('</div>')
        return ''.join(parts)

    def _render_note(self, note) -> str:
        """Render <note> block."""
        parts = [f'<div class="admonition note" {self._anno("note")}>',
                 '<div class="admonition-title">ПРИМЕЧАНИЕ</div>']
        for child in note:
            if _local_tag(child) == 'notePara':
                text = escape(child.text or '')
                parts.append(f'<p>{text}</p>')
        parts.append('</div>')
        return ''.join(parts)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _local_tag(elem) -> str:
    """Get local tag name without namespace."""
    tag = elem.tag
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def _text_content_before_child(parent, child_elem) -> str:
    """Get text content of parent before a specific child element."""
    return parent.text or ''


def render_s1000d_to_html(xml_path: str, graphics_base_url: str = '/graphics') -> str:
    """Convenience function to render an S1000D XML file to HTML."""
    renderer = S1000DHTMLRenderer(graphics_base_url=graphics_base_url)
    return renderer.render(xml_path)
