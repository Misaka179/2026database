"""Read roster workbooks without executing formulas or changing source files."""
import re

from .import_common import merge_people, read_sheets, sid_problem, decode

WEEKDAYS = '一二三四五六日'
PERIODS = '一二三四五'
TIMES = [('08:15','09:55'),('10:15','11:55'),('13:50','16:25'),('16:45','18:25'),('19:20','21:00')]


def slot_name(day, period):
    return f'周{WEEKDAYS[day-1]}-{PERIODS[period-1]}时段'


def category_slot(value):
    value = re.sub(r'\s+', '', str(value or ''))
    match = re.fullmatch(r'([一二三四五六七1-7])分队([一二三四五1-5])时段', value)
    if match:
        d,p = match.groups()
        return ('一二三四五六七'.index(d)+1 if not d.isdigit() else int(d),
                PERIODS.index(p)+1 if not p.isdigit() else int(p))
    match = re.fullmatch(r'周([一二三四五六日天])-([一二三四五])时段', value)
    if match:
        d,p=match.groups()
        return (WEEKDAYS.index('日' if d=='天' else d)+1, PERIODS.index(p)+1)
    return None


def parse_workbook(encoded, sheet_name=None, map_categories=True, force_pair=None):
    """Preview a fixed-business roster.

    ``force_pair`` = (weekday, period_no) pins every row to one slot: the
    「分类 / 时段」column is ignored, which is what a third-level
    「导入本班次」 does. Rows with unusable values are skipped instead of
    failing the whole workbook.
    """
    raw = decode(encoded)
    sheets, rows = read_sheets(raw, sheet_name)
    chosen = sheet_name or (sheets[0]['name'] if sheets else '')
    warnings = []
    skipped = []
    people = merge_people(rows)
    slot_of = {}
    for row in rows:
        sid = row['student_id']
        message = ''
        if not sid:
            message = f'第 {row["row"]} 行缺少学号，未建立账号'
        else:
            problem = sid_problem(sid)
            if problem:
                message = f'第 {row["row"]} 行：{problem}'
            elif not row['name']:
                message = f'第 {row["row"]} 行缺少姓名'
            elif row['formula']:
                message = f'第 {row["row"]} 行姓名或学号是公式，未取到文本值'
            elif len(row['name']) > 100 or len(row['college']) > 100:
                message = f'第 {row["row"]} 行姓名或学院超过 100 字'
        if message:
            entry = {'row': row['row'], 'student_id': sid, 'message': message, 'key': row['key']}
            skipped.append(entry)
            warnings.append(entry)
            continue
        pair = force_pair
        if pair is None and map_categories:
            label = row['extra'].get('分类') or row['extra'].get('时段') or ''
            pair = category_slot(label)
            if not pair:
                warnings.append({'row': row['row'], 'student_id': sid,
                                 'message': f'分类“{label or "空白"}”未对应固定时段，将只导入账号，不增加该行时段归属'})
        slot_of.setdefault(sid, [])
        if pair and list(pair) not in slot_of[sid]:
            slot_of[sid].append(list(pair))
    students = []
    for person in people:
        usable = [k for k in person['keys']
                  if not any(s['key'] == k for s in skipped if s.get('key'))]
        if not usable:
            continue
        students.append({'student_id': person['student_id'], 'name': sorted(person['names'])[0],
                         'college': person['college'], 'slots': slot_of.get(person['student_id'], []),
                         'rows': person['rows'], 'keys': person['keys'], 'names': person['names'],
                         'sheets': person['sheets']})
    return {'sheets': [s['name'] for s in sheets], 'sheet': chosen,
            'source_rows': len(rows), 'unique_students': len(students),
            'memberships': sum(len(p['slots']) for p in students),
            'students': students, 'warnings': warnings, 'errors': [], 'skipped': skipped,
            'people': students, 'force_pair': force_pair}
