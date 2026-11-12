"""名单导入的共用规则：表头识别、按学号合并、身份判定与统计。

两个导入入口（固定业务的 `/students/import`、非固定业务/小组的 `/member-imports`）
共用这里的识别与判定，避免同一条规则在两边写出不同文案或不同结论。
"""
import base64
import re
from collections import OrderedDict
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

MAX_BYTES = 8 * 1024 * 1024
MAX_PARTS = 2000
MAX_UNPACKED = 40 * 1024 * 1024
MAX_ROWS = 10000
MAX_COLUMNS = 100
WEEKDAYS = '一二三四五六日'
PERIODS = '一二三四五'

OK = 'ok'
SKIP = 'skip'
PENDING = 'pending'

ISSUE_NAME = ('name', '姓名与系统不一致')
ISSUE_REACTIVATE = ('reactivate', '已退队，导入将重新启用账号')
ISSUE_DISABLED = ('disabled', '账号已停用')
ISSUE_CREDIT = ('credit', '信用分归零，账号已停用')
ISSUE_DUPNAME = ('dupname', '同一学号在文件里出现多个姓名')
ISSUE_SLOT = ('slot', '时段归属冲突')
ISSUE_GROUP = ('group', '该业务有小组，必须选择小组')
ISSUE_FORMULA = ('formula', '姓名或学号是公式，未取到文本值')


def decode(encoded):
    """Decode a base64 workbook, rejecting oversized or suspicious archives."""
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError('请上传有效的 .xlsx 文件') from exc
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('文件不能超过 8 MB')
    try:
        with ZipFile(BytesIO(raw)) as archive:
            info = archive.infolist()
            if len(info) > MAX_PARTS or sum(i.file_size for i in info) > MAX_UNPACKED:
                raise ValueError('工作簿内容过大，请精简后导入')
    except BadZipFile as exc:
        raise ValueError('请上传有效的 .xlsx 文件') from exc
    return raw


def open_book(raw):
    try:
        return load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ValueError('请上传有效的 .xlsx 文件（不超过 8 MB，解压内容不超过 40 MB）') from exc


def text(value):
    return str(value).strip() if value is not None else ''


def student_id_of(cell, row_number):
    """Numbers typed into a student-id column lose precision; read them as text."""
    value = cell.value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if value != int(value) or abs(value) >= 10 ** 15:
            raise ValueError(f'第 {row_number} 行学号可能存在精度损失，请改用文本学号')
        return str(int(value))
    return text(value)


def read_sheets(raw, sheet_name=None):
    """Return (sheets, rows) with a shared header rule.

    A row that contains both 姓名 and 学号 becomes the header; repeated header
    rows inside one sheet are honoured, so a sheet may hold several blocks.
    """
    book = open_book(raw)
    try:
        names = book.sheetnames
        chosen = [sheet_name] if sheet_name else names
        if sheet_name and sheet_name not in names:
            raise ValueError('所选工作表不存在')
        sheets = []
        rows = []
        for title in chosen:
            sheet = book[title]
            if sheet.max_row is None or sheet.max_column is None:
                sheet.calculate_dimension(force=True)
            if sheet.max_row > MAX_ROWS or sheet.max_column > MAX_COLUMNS:
                raise ValueError('工作表不能超过 10000 行、100 列')
            header = None
            count = 0
            for number, cells in enumerate(sheet.iter_rows(), 1):
                if number > MAX_ROWS:
                    raise ValueError('工作表行数过多')
                labels = {text(cell.value): index for index, cell in enumerate(cells) if text(cell.value)}
                if '姓名' in labels and '学号' in labels:
                    header = labels
                    continue
                if header is None or not labels:
                    continue
                name_cell = cells[header['姓名']]
                id_cell = cells[header['学号']]
                name = text(name_cell.value)
                sid = student_id_of(id_cell, number)
                if not name and not sid:
                    continue
                college_cell = cells[header['学院']] if '学院' in header else None
                college = text(college_cell.value) if college_cell is not None else ''
                extra = {}
                for label in ('分类', '时段', '小组'):
                    if label in header and label not in extra:
                        value = text(cells[header[label]].value)
                        if value:
                            extra[label] = value
                rows.append({'key': f'{title}:{number}', 'sheet': title, 'row': number,
                             'name': name, 'student_id': sid, 'college': college, 'extra': extra,
                             'formula': name_cell.data_type == 'f' or id_cell.data_type == 'f'})
                count += 1
            sheets.append({'name': title, 'count': count})
        return sheets, rows
    finally:
        book.close()


def sid_problem(student_id):
    if not student_id:
        return '缺少学号'
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', student_id):
        return '学号格式无效（1—32 位字母、数字、下划线或短横线）'
    return ''


def merge_people(rows):
    """Collapse rows by student id; conflicting names are kept for a decision."""
    people = OrderedDict()
    for row in rows:
        student_id = row['student_id']
        if not student_id:
            continue
        person = people.setdefault(student_id, {'student_id': student_id, 'name': row['name'],
                                                'college': row['college'], 'rows': [],
                                                'names': set(), 'keys': [], 'formula': False,
                                                'sheets': []})
        person['names'].add(row['name'])
        person['college'] = person['college'] or row['college']
        person['rows'].append(row['row'])
        person['keys'].append(row['key'])
        person['formula'] = person['formula'] or row['formula']
        if row['sheet'] not in person['sheets']:
            person['sheets'].append(row['sheet'])
    return list(people.values())


def evaluate(person, existing, approve):
    """Decide one person's fate under the agreed rules.

    Returns {'status': ok|skip|pending, 'issue': code|None, 'detail': str,
             'approved': bool, 'new': bool}.
    """
    approved = bool(approve)
    if len(person['names']) > 1:
        detail = '同一学号出现多个姓名：' + '、'.join(sorted(n for n in person['names'] if n))
        if not approved:
            return {'status': PENDING, 'issue': ISSUE_DUPNAME[0], 'detail': detail,
                    'approved': False, 'new': False}
    if not existing:
        return {'status': OK, 'issue': None, 'detail': '', 'approved': approved, 'new': True}
    credit_off = bool(existing.get('disabled_by_credit')) or existing.get('status') == 'DISABLED'
    if credit_off:
        return {'status': SKIP, 'issue': ISSUE_CREDIT[0],
                'detail': ISSUE_CREDIT[1], 'approved': approved, 'new': False}
    if person['name'] != existing['name']:
        detail = f'姓名与系统不一致（系统：{existing["name"]}）'
        if not approved:
            return {'status': PENDING, 'issue': ISSUE_NAME[0], 'detail': detail,
                    'approved': False, 'new': False}
    if existing.get('status') != 'ACTIVE':
        if not approved:
            return {'status': PENDING, 'issue': ISSUE_REACTIVATE[0],
                    'detail': ISSUE_REACTIVATE[1], 'approved': False, 'new': False}
    return {'status': OK, 'issue': None, 'detail': '', 'approved': approved, 'new': False}


def person_payload(person, verdict, label=''):
    return {'student_id': person['student_id'], 'name': person['name'], 'college': person['college'],
            'sheets': person['sheets'], 'rows': person['rows'],
            'status': verdict['status'], 'issue': verdict['issue'], 'detail': verdict['detail'],
            'new': verdict['new'], 'target': label}


def counts(people, verdicts, hard_skips, pending, memberships=0):
    new = sum(1 for v in verdicts if v['new'])
    skipped = hard_skips + sum(1 for v in verdicts if v['status'] == SKIP)
    return {'students': len(people), 'new_accounts': new, 'existing': len(people) - new,
            'pending': pending, 'skipped': skipped, 'memberships': memberships}


def issue_kind_labels():
    return {code: label for code, label in (ISSUE_NAME, ISSUE_REACTIVATE, ISSUE_DISABLED,
                                            ISSUE_CREDIT, ISSUE_DUPNAME, ISSUE_SLOT,
                                            ISSUE_GROUP, ISSUE_FORMULA)}
