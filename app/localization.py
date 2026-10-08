"""Chinese documentation and safe request validation messages.

Wire-format field names and enum values remain stable for API consumers.
"""
from fastapi.openapi.utils import get_openapi


FIELD_LABELS = {
    'credit_score':'信用分','expected_revision':'当前考勤版本','expected_version':'当前信用版本',
    'semester_id':'学期编号','start_date':'开始日期','end_date':'结束日期','end_week':'结束周次','mode':'日历模式','weekday':'执行星期',
    'old_slot_id':'原固定班次编号',
    'slot_ids':'归属时段编号列表','file_base64':'Excel 文件内容（Base64）','sheet_name':'工作表名称','map_categories':'按分队数字映射星期','commit':'确认写入','initial_password':'新队员初始密码','accept_warnings':'已核对预览提示',
    'kind': '身份类型', 'account': '账号', 'password': '密码',
    'student_id': '学号', 'name': '姓名', 'college': '学院', 'phone': '联系电话',
    'role': '管理员角色', 'team_name': '分队名称', 'period_no': '时段编号',
    'start_time': '开始时间', 'end_time': '结束时间', 'location': '服务地点',
    'need_num': '需要人数', 'manager_admin_id': '班次负责人编号',
    'slot_id': '班次编号', 'schedule_id': '排班编号', 'schedule_date': '服务日期',
    'reason': '原因说明', 'old_schedule_id': '原排班编号',
    'new_slot_id': '目标班次编号', 'new_date': '目标服务日期',
    'approved': '是否批准', 'status': '考勤状态', 'remark': '备注',
    'service_minutes': '服务时长（分钟）', 'deduct_score': '扣分值',
    'leave_id': '请假申请编号', 'transfer_id': '换班申请编号',
    'stage': '审批阶段', 'withdrawal_id': '退队申请编号',
    'start': '开始日期', 'end': '结束日期', 'record_id': '服务记录编号',
    'violation_type': '违规类型', 'limit': '最多返回条数',
    'detail': '提示信息', 'errors': '错误列表', 'field': '字段位置',
    'message': '错误说明',
}

MODEL_LABELS = {
    'AdminPromotion':'将队员设为普通管理员',
    'AttendanceCorrection':'考勤改判','CreditSet':'信用分调整',
    'SemesterCreate':'学期设置','CalendarEdit':'日历设置',
    'FixedTransferCreate':'固定班次换班申请',
    'Login': '登录信息', 'StudentCreate': '新增志愿者', 'AdminCreate': '新增管理员',
    'SlotCreate': '新增服务班次', 'ScheduleCreate': '新增排班',
    'LeaveCreate': '请假申请', 'TransferCreate': '换班申请',
    'Reason': '原因说明', 'Decision': '审批意见', 'AttendanceCreate': '考勤登记',
    'HoursEdit': '服务时长修正', 'RuleEdit': '信用规则修改',
    'HTTPValidationError': '请求校验结果', 'ValidationError': '字段校验错误',
}

FIELD_DESCRIPTIONS = {
    'kind': '登录身份：admin 为管理员，student 为志愿者。',
    'role': 'NORMAL 为普通管理员，SUPER 为超级管理员。',
    'status': 'NORMAL 为正常出勤，LATE 为迟到，ABSENT 为缺勤，LEAVE 为请假。',
    'password': '用于登录的密码。新增账号的密码长度为 8 至 128 个字符。',
    'student_id': '志愿者学号。新增账号时仅允许字母、数字、下划线和连字符。',
    'approved': '通过审批时填写 true，驳回时填写 false。',
    'start_time': '使用 24 小时制，格式为 时:分，例如 09:00。',
    'end_time': '使用 24 小时制，格式为 时:分，例如 11:00。',
    'schedule_date': '日期格式为 年-月-日；按北京时间解释。',
    'new_date': '旧单次换班字段，已停用。',
    'service_minutes': '修正后的总服务分钟数，允许范围为 0 至 1440。',
    'reason': '请填写本次申请或修改的具体原因，最多 500 个字符。',
}

# Route keys deliberately use the public paths rather than generated operation IDs.
OPERATIONS = {
    ('post','/students/{student_id}/administrator'):('将队员设为普通管理员','仅超级管理员。保留志愿者身份和历史，以学号及现有志愿者密码登录管理员身份；可选择负责的固定时段，勾选会替换现有负责人。重复提交不重复建号，必须填写原因。队员停用或退队后关联管理员权限暂停。'),
    ('patch','/schedules/{schedule_id}/attendance'):('考勤改判与信用冲正','负责时段的普通管理员或超级管理员可改判已结算考勤。撤销旧违规，退还实际扣分，按新结果修正时长并处理信用。必须填写原因和当前考勤版本。'),
    ('put','/students/{student_id}/credit'):('设置队员信用分','仅超级管理员。设置任意队员的非负信用分，须提供原因和当前信用版本，留存信用流水和审计。因信用归零停用的队员恢复正分后恢复服务，已退队者不恢复。'),
    ('get','/semesters'):('查询学期与日历','查看开工日期、结束周次、当前周次和逐日服务班表。'),
    ('post','/semesters'):('设置新学期','仅超级管理员。开工所在自然周为第一周，从开工日起按初始固定名单补齐排班并结算已结束周次；之后成员变动按生效时间计算。'),
    ('put','/semesters/{semester_id}'):('修改学期','仅超级管理员，可调整结束周次。学期开始后不能更改开工日期。'),
    ('put','/semesters/{semester_id}/calendar'):('设置停工或调休','仅超级管理员。REST 停工，WEEKDAY 指定星期班表，NATURAL 按实际星期服务，DEFAULT 恢复内置日历。未收录年份默认暂停排班，须核对。'),
    ('post','/semesters/{semester_id}/sync'):('重新核对排班','仅超级管理员。根据有生效时间的归属补齐安排并结算已结束周次，保留已登记考勤及手动取消。'),
    ('get','/my-fixed-slots'):('查询我的固定班次','志愿者查询本人每周固定班次、时间与负责人，不生成具体日期排班。'),
    ('post','/applications/fixed-transfer'):('申请更换固定班次','按本人固定班次申请长期换班，原时段管理员初审、超级管理员终审。终审再次校验归属、容量及冲突，并原子更新固定班次。'),
    ('post','/students/import'):('从 Excel 导入队员','仅超级管理员。commit=false 预览；确认后重新校验并整体写入。学号去重，支持多时段归属，学院选填；已有账号不会被覆盖。'),
    ('put','/students/{student_id}/slots'):('设置队员归属时段','仅超级管理员可设置。允许多选固定时段；已设置学期时同步未来日期排班。'),
    ('patch','/slots/{slot_id}'):('设置时段负责人和容量','仅超级管理员设置已有固定时段的负责人和人数上限，时间及名称不可修改。'),
    ('get', '/health'): ('检查服务状态', '检查数据库连接是否可用。无需登录。'),
    ('post', '/auth/login'): ('登录系统', '使用管理员账号或志愿者学号及密码登录，获得有效期为一小时的访问令牌。'),
    ('get', '/auth/me'): ('查询本人资料', '查询当前登录者的资料与实际角色，不返回密码信息。'),
    ('post', '/students'): ('新增志愿者', '仅超级管理员可以创建志愿者账号，初始信用分为 5 分。'),
    ('get', '/students'): ('查询志愿者', '按完整学号查询队员。超级管理员可查询全部，普通管理员仅可查询自己负责时段的队员；学院选填。'),
    ('post', '/admins'): ('新增管理员', '仅超级管理员可以创建普通管理员或超级管理员账号。'),
    ('get', '/admins'): ('查询管理员', '仅超级管理员可以查询管理员编号、姓名、账号、角色和状态，用于选择班次负责人。'),
    ('post', '/slots'): ('新增服务班次', '兼容旧接口；启用每周 35 个固定时段后禁止创建班次，请使用时段设置接口。'),
    ('get', '/slots'): ('查询服务班次', '查询班次时间、地点、人数上限与负责人。'),
    ('post', '/schedules'): ('安排志愿者排班', '由班次负责人或超级管理员安排未来排班，检查人数上限与同日时间冲突。'),
    ('get', '/schedules'): ('查询排班', '返回排班及志愿者姓名。志愿者仅可查询本人排班，普通管理员仅可查询负责班次的排班，超级管理员可查询全部排班。'),
    ('post', '/schedules/{schedule_id}/cancel'): ('取消排班', '由有权限的管理员取消尚未开始的排班，并记录取消原因。'),
    ('post', '/applications/leave'): ('提交请假申请', '志愿者针对本人排班申请请假。审批通过后不计服务时长、不扣信用分。'),
    ('post', '/applications/transfer'): ('提交换班申请', '已停用，返回 410。请使用长期固定时段换班接口。'),
    ('post', '/applications/withdrawal'): ('提交退队申请', '志愿者填写原因申请退队，由超级管理员审批。'),
    ('get', '/applications/{kind}'): ('查询申请记录', '按照申请类型与当前用户权限返回请假、换班或退队记录。'),
    ('post', '/applications/leave/{leave_id}/decision'): ('审批请假申请', '仅负责原班次的普通管理员可以通过或驳回请假申请，超级管理员不执行此日常审批。'),
    ('post', '/applications/transfer/{transfer_id}/{stage}'): ('审批换班申请', '仅负责原班次的普通管理员执行初审，超级管理员执行终审。长期换时段通过后替换每周归属并同步未来学期排班；历史单次申请不能继续审批。'),
    ('post', '/applications/withdrawal/{withdrawal_id}/decision'): ('审批退队申请', '仅超级管理员审批。通过后更新志愿者状态并取消未来排班，保留历史记录。'),
    ('post', '/attendance'): ('登记考勤', '负责班次的普通管理员或超级管理员可以在班次结束后登记考勤。正常与迟到均计完整时长，迟到按规则扣分；缺勤不计时并扣分；已批准请假优先按请假处理。'),
    ('get', '/hours'): ('查询服务时长', '超级管理员按学号查询，志愿者只能查询本人。日期范围包含开始日期，不包含结束日期；普通管理员无此权限。'),
    ('get', '/hours/export'): ('导出学期周时长', '仅超级管理员可下载所选学期全队Excel报表。包含队员明细、分队汇总和退队统计；每周注明日期范围，仅汇总有效服务记录，未来周留空。'),
    ('patch', '/service-records/{record_id}'): ('修正服务时长', '仅超级管理员可以修正服务分钟数，必须填写原因，修改会写入操作日志。'),
    ('get', '/credit'): ('查询信用记录', '查询当前信用分及信用变化流水。超级管理员按学号查询，志愿者只能查询本人；普通管理员无此权限。'),
    ('get', '/credit-rules'): ('查询信用规则', '仅超级管理员可以查询信用规则及其版本信息，历史违规保留原规则依据。'),
    ('put', '/credit-rules/{violation_type}'): ('发布信用规则版本', '仅超级管理员可以修改迟到或缺勤扣分值。必须填写原因，历史规则和既有扣分记录保持可追溯。'),
    ('get', '/operation-logs'): ('查询操作日志', '仅超级管理员可以查询重要操作及其修改前后信息。'),
}

PARAMETER_DESCRIPTIONS = {
    'kind': '申请类型：leave 为请假，transfer 为换班，withdrawal 为退队。',
    'stage': '审批阶段：first 为初审，final 为终审。',
    'violation_type': '违规类型：LATE 为迟到，ABSENT 为缺勤。',
    'start': '统计开始日期，格式为 年-月-日。',
    'end': '统计结束日期，不包含当天，格式为 年-月-日。',
    'limit': '操作日志的最大返回条数，默认 100 条。',
}


def localize_schema_node(node, title=None):
    """Translate display metadata without renaming keys or enum constants."""
    if not isinstance(node, dict):
        return
    if title:
        node['title'] = title
    for key, child in node.get('properties', {}).items():
        label = FIELD_LABELS.get(key, '数据项')
        localize_schema_node(child, label)
        if key in FIELD_DESCRIPTIONS:
            child['description'] = FIELD_DESCRIPTIONS[key]
        if key in ('password','initial_password'):
            child['format'] = 'password'
            child['writeOnly'] = True
    for key in ('anyOf', 'oneOf', 'allOf'):
        for child in node.get(key, []):
            localize_schema_node(child, title if 'title' in child else None)
    if isinstance(node.get('items'), dict):
        localize_schema_node(node['items'])


def chinese_openapi(app):
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version,
                         description=app.description, routes=app.routes)
    models = schema.setdefault('components', {}).setdefault('schemas', {})
    # Match the actual localized 422 response, avoiding raw Pydantic input values.
    models['ValidationError'] = {
        'type': 'object', 'required': ['field', 'message'],
        'properties': {'field': {'type': 'string'}, 'message': {'type': 'string'}},
    }
    models['HTTPValidationError'] = {
        'type': 'object', 'required': ['detail', 'errors'],
        'properties': {
            'detail': {'type': 'string'},
            'errors': {'type': 'array', 'items': {'$ref': '#/components/schemas/ValidationError'}},
        },
    }
    for name, model in models.items():
        localize_schema_node(model, MODEL_LABELS.get(name, '接口数据'))
    for path, methods in schema.get('paths', {}).items():
        for method, operation in methods.items():
            if method not in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options'):
                continue
            summary, description = OPERATIONS.get((method, path), ('业务接口', '处理志愿服务管理业务。'))
            operation['summary'], operation['description'] = summary, description
            for parameter in operation.get('parameters', []):
                name = parameter['name']
                label = '申请类型' if name == 'kind' else FIELD_LABELS.get(name, '请求参数')
                parameter['description'] = PARAMETER_DESCRIPTIONS.get(name, f'需要查询或操作的{label}。')
                localize_schema_node(parameter.get('schema', {}), label)
            if 'requestBody' in operation:
                operation['requestBody']['description'] = f'请填写“{summary}”所需的信息。'
            for status, response in operation.get('responses', {}).items():
                response['description'] = ('请求处理成功' if status.startswith('2')
                                           else '请求信息校验失败' if status == '422'
                                           else '请求处理失败')
    app.openapi_schema = schema
    return schema


def validation_message(error):
    """Return Chinese text only; never echo a rejected password or raw input."""
    code = error.get('type', '')
    context = error.get('ctx') or {}
    messages = {
        'missing': '此项不能为空',
        'extra_forbidden': '不允许提交额外字段',
        'string_type': '请填写文本',
        'int_type': '请填写整数',
        'int_parsing': '请填写有效的整数',
        'int_from_float': '请填写整数，不能包含小数',
        'bool_type': '请选择是否批准',
        'bool_parsing': '是否批准的值无效',
        'literal_error': '请选择有效的选项',
        'string_pattern_mismatch': '格式不符合要求，请检查后重试',
        'json_invalid': '请求内容不是有效的结构化数据',
        'model_attributes_type': '请提交包含字段和值的数据对象',
        'model_type': '请提交包含字段和值的数据对象',
        'date_type': '请填写有效日期',
        'date_parsing': '日期无效，请使用年-月-日格式',
        'date_from_datetime_parsing': '日期无效，请使用年-月-日格式',
        'date_from_datetime_inexact': '请仅填写日期，不要包含时间',
        'string_too_short': f'至少需要 {context.get("min_length", 1)} 个字符',
        'string_too_long': f'不能超过 {context.get("max_length", "允许数量")} 个字符',
        'greater_than': f'必须大于 {context.get("gt", 0)}',
        'greater_than_equal': f'不能小于 {context.get("ge", 0)}',
        'less_than': f'必须小于 {context.get("lt", "上限")}',
        'less_than_equal': f'不能大于 {context.get("le", "上限")}',
    }
    return messages.get(code, '填写的信息无效，请检查格式和取值')


def validation_errors(errors):
    locations = {'body': '提交信息', 'query': '查询参数', 'path': '路径参数',
                 'header': '请求头', 'cookie': '会话信息'}
    result = []
    for error in errors:
        labels = [str(item + 1) if isinstance(item, int)
                  else locations.get(item, FIELD_LABELS.get(item, '未知字段'))
                  for item in error.get('loc', ())]
        result.append({'field': ' · '.join(labels) or '请求信息',
                       'message': validation_message(error)})
    return result
