from datetime import date, timedelta
from typing import Literal, Annotated
import logging
import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from .db import pymysql
from .security import issue_token, read_token
from .service import Service, DomainError
from .localization import chinese_openapi, validation_errors

@asynccontextmanager
async def lifespan(application):
    async def settle_loop():
        while True:
            try:
                factory = application.dependency_overrides.get(get_service, get_service)
                service = factory()
                if hasattr(service, 'run_weekly_settlement'):
                    await asyncio.to_thread(service.run_weekly_settlement)
                if hasattr(service, 'run_collection_deadlines'):
                    await asyncio.to_thread(service.run_collection_deadlines)
                if hasattr(service, 'run_leader_reports'):
                    await asyncio.to_thread(service.run_leader_reports)
            except Exception:
                log.exception('Weekly settlement failed; will retry in 60 seconds')
            await asyncio.sleep(60)
    task = None if os.environ.get('VOLUNTEER_DISABLE_SCHEDULER') == '1' else asyncio.create_task(settle_loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app=FastAPI(title='图书馆志愿服务管理核心 API',version='2.4.0',lifespan=lifespan,
    description='图书馆志愿服务管理系统接口说明。支持志愿者、普通管理员、分队／美育负责人和全局超级管理员。负责人仅能访问明确授权的本范围接口。请先登录获得访问令牌，所有日期按北京时间解释。',
    docs_url=None,redoc_url=None)
bearer=HTTPBearer(auto_error=False,scheme_name='登录凭证',description='登录后获得的访问令牌，用于确认当前用户身份。')
log=logging.getLogger(__name__)
WEB_ROOT=Path(__file__).resolve().parents[1] / 'web'
app.mount('/static',StaticFiles(directory=WEB_ROOT,check_dir=False),name='static')


def get_service():
    return Service()


def identity(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if not credentials:
        raise HTTPException(401,'请先登录',headers={'WWW-Authenticate':'Bearer'})
    try:
        return read_token(credentials.credentials)
    except ValueError as e:
        raise HTTPException(401,str(e),headers={'WWW-Authenticate':'Bearer'})


S=Annotated[Service,Depends(get_service)]
A=Annotated[dict,Depends(identity)]


def output(value):
    def time_value(t):
        m=int(t.total_seconds()//60)
        return f'{m//60:02d}:{m%60:02d}'
    return JSONResponse(jsonable_encoder(value,custom_encoder={timedelta:time_value}))


@app.exception_handler(DomainError)
async def domain_error(request,exc):
    return JSONResponse({'detail':exc.message},status_code=exc.status)


@app.exception_handler(pymysql.IntegrityError)
async def integrity_error(request,exc):
    return JSONResponse({'detail':'数据重复或引用关系不合法，本次操作已回滚'},status_code=409)


@app.exception_handler(pymysql.MySQLError)
async def database_error(request,exc):
    log.error('Database operation failed (%s)',type(exc).__name__)
    return JSONResponse({'detail':'数据库操作失败，本次修改未提交，请检查服务状态'},status_code=503)


@app.exception_handler(ValueError)
async def value_error(request,exc):
    safe_messages={'密码长度必须为 8—128 个字符':'密码长度必须为 8 至 128 个字符',
                   '密码长度必须为 8 至 128 个字符':'密码长度必须为 8 至 128 个字符',
                   '登录已过期或令牌无效':'登录已过期或令牌无效'}
    message=safe_messages.get(str(exc),'提交的信息无效，请检查格式和取值')
    return JSONResponse({'detail':message},status_code=422)


@app.exception_handler(RuntimeError)
async def runtime_error(request,exc):
    log.error('Runtime operation failed (%s)',type(exc).__name__)
    return JSONResponse({'detail':'服务暂不可用，请检查数据库配置或稍后重试'},status_code=503)


@app.exception_handler(RequestValidationError)
async def request_validation_error(request,exc):
    errors=validation_errors(exc.errors())
    first=errors[0] if errors else {'field':'请求信息','message':'请检查填写内容'}
    return JSONResponse({'detail':f'{first["field"]}：{first["message"]}',
                         'errors':errors},status_code=422)


@app.exception_handler(StarletteHTTPException)
async def http_error(request,exc):
    messages={400:'请求内容无效，请检查后重试',401:'请先登录或重新登录',
              403:'没有执行此操作的权限',404:'请求的页面或资源不存在',
              405:'此接口不支持当前请求方式',413:'提交的内容过大',
              422:'提交的信息无效，请检查后重试',429:'操作过于频繁，请稍后重试'}
    safe_messages={'请先登录','登录已过期或令牌无效'}
    message=(exc.detail if isinstance(exc.detail,str) and exc.detail in safe_messages
             else messages.get(exc.status_code,'请求处理失败，请稍后重试'))
    return JSONResponse({'detail':message},status_code=exc.status_code,headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_error(request,exc):
    log.error('Unexpected request error (%s)',type(exc).__name__)
    return JSONResponse({'detail':'系统暂时无法完成此操作，请稍后重试'},status_code=500)


class Model(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)


class Login(Model):
    kind:Literal['admin','student']
    account:str=Field(min_length=1,max_length=64)
    password:str=Field(min_length=1,max_length=128)


class PasswordReset(Model):
    new_password:str=Field(min_length=8,max_length=128)
    reason:str=Field(min_length=1,max_length=500)


class StudentCreate(Model):
    student_id:str=Field(min_length=1,max_length=32,pattern=r'^[A-Za-z0-9_-]+$')
    name:str=Field(min_length=1,max_length=100)
    password:str=Field(min_length=8,max_length=128)
    college:str=Field(default='',max_length=100)
    phone:str=Field(default='',max_length=32)


class AdminCreate(Model):
    name:str=Field(min_length=1,max_length=100)
    account:str=Field(min_length=1,max_length=64)
    password:str=Field(min_length=8,max_length=128)
    role:Literal['NORMAL','SUPER']='NORMAL'


class SlotCreate(Model):
    team_name:str=Field(min_length=1,max_length=100)
    period_no:int=Field(ge=1,le=100)
    start_time:str=Field(pattern=r'^\d{2}:\d{2}$')
    end_time:str=Field(pattern=r'^\d{2}:\d{2}$')
    location:str=Field(min_length=1,max_length=200)
    need_num:int=Field(ge=1,le=10000)
    manager_admin_id:int=Field(gt=0)


class ScheduleCreate(Model):
    student_id:str=Field(min_length=1,max_length=32)
    slot_id:int=Field(gt=0)
    schedule_date:date


class SlotSettings(Model):
    manager_admin_id:int|None=Field(default=None,gt=0)
    need_num:int|None=Field(default=None,ge=1,le=10000)


class Memberships(Model):
    slot_ids:list[int]=Field(max_length=86)
    effective_date:date|None=None
    reason:str=Field(default="超级管理员调整业务归属",min_length=1,max_length=500)


class RosterImport(Model):
    business_id:int|None=Field(default=None,gt=0)
    file_base64:str=Field(min_length=1,max_length=12*1024*1024)
    sheet_name:str|None=Field(default=None,max_length=100)
    map_categories:bool=True
    commit:bool=False
    initial_password:str|None=Field(default=None,min_length=8,max_length=128)
    accept_warnings:bool=False


class LeaveCreate(Model):
    images:list[str]=Field(default_factory=list,max_length=3)
    schedule_id:int=Field(gt=0)
    reason:str=Field(min_length=1,max_length=500)


class TransferCreate(Model):
    old_schedule_id:int=Field(gt=0)
    new_slot_id:int=Field(gt=0)
    new_date:date
    reason:str=Field(min_length=1,max_length=500)


class FixedTransferCreate(Model):
    old_slot_id:int=Field(gt=0)
    new_slot_id:int=Field(gt=0)
    reason:str=Field(min_length=1,max_length=500)


class SemesterCreate(Model):
    name:str=Field(min_length=1,max_length=100)
    start_date:date
    end_week:int=Field(ge=1,le=53)


class CalendarEdit(Model):
    start_date:date
    end_date:date
    mode:Literal['DEFAULT','REST','WEEKDAY','NATURAL']
    weekday:int|None=Field(default=None,ge=1,le=7)
    reason:str=Field(min_length=1,max_length=500)


class Reason(Model):
    reason:str=Field(min_length=1,max_length=500)


class AdminPromotion(Reason):
    slot_ids:list[int]=Field(default_factory=list,max_length=86)


class Decision(Model):
    approved:bool
    reason:str=Field(default="",max_length=500)


class AttendanceCreate(Model):
    schedule_id:int=Field(gt=0)
    status:Literal['NORMAL','LATE','ABSENT','LEAVE']
    remark:str=Field(default='',max_length=1000)


class HoursEdit(Reason):
    service_minutes:int=Field(ge=0,le=1440)


class RuleEdit(Reason):
    deduct_score:int=Field(ge=0,le=100)


class AttendanceCorrection(Reason):
    status:Literal['NORMAL','LATE','ABSENT','LEAVE']
    expected_revision:int=Field(ge=1)


class CreditSet(Reason):
    credit_score:int=Field(ge=0,le=2147483647)
    expected_version:int=Field(ge=1)


@app.get('/',include_in_schema=False)
def root():
    return FileResponse(WEB_ROOT / 'index.html',media_type='text/html',headers={'Cache-Control':'no-cache'})


@app.get('/docs',include_in_schema=False)
def documentation():
    return FileResponse(WEB_ROOT / 'docs.html',media_type='text/html',headers={'Cache-Control':'no-cache'})


@app.get('/redoc',include_in_schema=False)
def legacy_documentation():
    return RedirectResponse('/docs')


@app.get('/health',tags=['状态'])
def health(service:S):
    with service.db.transaction() as c:
        c.execute('SELECT 1')
    return {'status':'ok'}


@app.post('/auth/login',tags=['登录'])
def login(body:Login,service:S):
    actor=service.login(**body.model_dump())
    return {'access_token':issue_token(actor),'token_type':'bearer','expires_in':3600}


@app.get('/auth/me',tags=['登录'])
def me(actor:A,service:S):
    return service.me(actor)


@app.post('/students',tags=['基础资料'])
def create_student(body:StudentCreate,actor:A,service:S):
    return service.create_student(actor,**body.model_dump())


@app.post('/students/{student_id}/reset-password',tags=['基础资料'])
def reset_student_password(student_id:str,body:PasswordReset,actor:A,service:S):
    return service.reset_password(actor,'student',student_id,**body.model_dump())


@app.post('/admins/{admin_id}/reset-password',tags=['基础资料'])
def reset_admin_password(admin_id:int,body:PasswordReset,actor:A,service:S):
    return service.reset_password(actor,'admin',admin_id,**body.model_dump())


@app.get('/students',tags=['基础资料'])
def students(actor:A,service:S,student_id:str|None=None):
    return service.students(actor,student_id)


@app.post('/students/import',tags=['基础资料'])
def import_students(body:RosterImport,actor:A,service:S):
    return service.import_roster(actor,**body.model_dump())


@app.put('/students/{student_id}/slots',tags=['基础资料'])
def student_memberships(student_id:str,body:Memberships,actor:A,service:S):
    return output(service.set_memberships(actor,student_id,**body.model_dump()))


@app.post('/admins',tags=['基础资料'])
def create_admin(body:AdminCreate,actor:A,service:S):
    return service.create_admin(actor,**body.model_dump())


@app.post('/students/{student_id}/administrator',tags=['基础资料'])
def promote_student(student_id:str,body:AdminPromotion,actor:A,service:S):
    return service.promote_student(actor,student_id,**body.model_dump())


@app.get('/admins',tags=['基础资料'])
def admins(actor:A,service:S):
    with service.db.transaction() as c:
        service.actor(c,actor,('SUPER',))
        c.execute('SELECT admin_id,name,account,role,status,student_id FROM admin ORDER BY admin_id')
        return c.fetchall()


@app.post('/slots',tags=['班次与排班'])
def create_slot(body:SlotCreate,actor:A,service:S):
    return service.create_slot(actor,**body.model_dump())


@app.get('/slots',tags=['班次与排班'])
def slots(actor:A,service:S):
    return output(service.list_slots(actor))


@app.get('/my-transfer-options',tags=['班次与排班'])
def my_transfer_options(old_slot_id:int,actor:A,service:S):
    return output(service.my_transfer_options(actor,old_slot_id))


@app.patch('/slots/{slot_id}',tags=['班次与排班'])
def configure_slot(slot_id:int,body:SlotSettings,actor:A,service:S):
    return service.configure_slot(actor,slot_id,**body.model_dump())


@app.post('/schedules',tags=['班次与排班'])
def create_schedule(body:ScheduleCreate,actor:A,service:S):
    return service.create_schedule(actor,**body.model_dump())


@app.get('/schedules',tags=['班次与排班'])
def schedules(actor:A,service:S):
    return output(service.list_schedules(actor))


@app.get('/my-fixed-slots',tags=['班次与排班'])
def my_fixed_slots(actor:A,service:S):
    return output(service.my_memberships(actor))


@app.get('/semesters',tags=['学期与日历'])
def semesters(actor:A,service:S):
    return output(service.semesters(actor))


@app.post('/semesters',tags=['学期与日历'])
def create_semester(body:SemesterCreate,actor:A,service:S):
    return output(service.save_semester(actor,**body.model_dump()))


@app.put('/semesters/{semester_id}',tags=['学期与日历'])
def edit_semester(semester_id:int,body:SemesterCreate,actor:A,service:S):
    return output(service.save_semester(actor,semester_id=semester_id,**body.model_dump()))


@app.put('/semesters/{semester_id}/calendar',tags=['学期与日历'])
def edit_calendar(semester_id:int,body:CalendarEdit,actor:A,service:S):
    return service.set_calendar(actor,semester_id,**body.model_dump())


@app.post('/semesters/{semester_id}/sync',tags=['学期与日历'])
def sync_semester(semester_id:int,actor:A,service:S):
    return service.sync_calendar(actor,semester_id)


@app.post('/schedules/{schedule_id}/cancel',tags=['班次与排班'])
def cancel_schedule(schedule_id:int,body:Reason,actor:A,service:S):
    return service.cancel_schedule(actor,schedule_id,body.reason)


@app.post('/applications/leave',tags=['申请与审批'])
def leave(body:LeaveCreate,actor:A,service:S):
    return service.apply_leave(actor,**body.model_dump())


@app.post('/applications/transfer',tags=['申请与审批'])
def transfer(body:TransferCreate,actor:A,service:S):
    return service.apply_transfer(actor,**body.model_dump())


@app.post('/applications/fixed-transfer',tags=['申请与审批'])
def fixed_transfer(body:FixedTransferCreate,actor:A,service:S):
    return service.apply_fixed_transfer(actor,**body.model_dump())


@app.post('/applications/withdrawal',tags=['申请与审批'])
def withdrawal(body:Reason,actor:A,service:S):
    return service.apply_withdrawal(actor,body.reason)


@app.get('/applications/{kind}',tags=['申请与审批'])
def applications(kind:Literal['leave','transfer','withdrawal'],actor:A,service:S):
    return service.list_applications(actor,kind)


@app.post('/applications/leave/{leave_id}/decision',tags=['申请与审批'])
def decide_leave(leave_id:int,body:Decision,actor:A,service:S):
    return service.approve_leave(actor,leave_id,body.approved,body.reason)


@app.post('/applications/transfer/{transfer_id}/{stage}',tags=['申请与审批'])
def decide_transfer(transfer_id:int,stage:Literal['first','final'],body:Decision,actor:A,service:S):
    return service.approve_transfer(actor,transfer_id,stage,body.approved)


@app.post('/applications/withdrawal/{withdrawal_id}/decision',tags=['申请与审批'])
def decide_withdrawal(withdrawal_id:int,body:Decision,actor:A,service:S):
    return service.approve_withdrawal(actor,withdrawal_id,body.approved)


@app.post('/attendance',tags=['考勤与时长'])
def attendance(body:AttendanceCreate,actor:A,service:S):
    return service.record_attendance(actor,**body.model_dump())


@app.patch('/schedules/{schedule_id}/attendance',tags=['考勤与时长'])
def correct_attendance(schedule_id:int,body:AttendanceCorrection,actor:A,service:S):
    return service.correct_attendance(actor,schedule_id,**body.model_dump())


class FixedHoursIncrease(BaseModel):
    service_minutes: int = Field(strict=True, ge=1, le=1440)
    expected_minutes: int = Field(strict=True, ge=0, le=1440)
    reason: str = Field(min_length=1, max_length=1000)


@app.post('/schedules/{schedule_id}/increase-hours',tags=['考勤与时长'])
def increase_fixed_hours(schedule_id:int,body:FixedHoursIncrease,actor:A,service:S):
    return service.increase_fixed_hours(actor,schedule_id,**body.model_dump())


@app.put('/students/{student_id}/credit',tags=['信用与审计'])
def set_student_credit(student_id:str,body:CreditSet,actor:A,service:S):
    return service.set_student_credit(actor,student_id,**body.model_dump())


@app.get('/hours',tags=['考勤与时长'])
def hours(actor:A,service:S,student_id:str|None=None,start:date|None=None,end:date|None=None,business_id:int|None=None,group_id:int|None=None):
    return service.hours(actor,student_id,start,end,business_id,group_id)


@app.get('/hours/export',tags=['考勤与时长'])
def hours_export(actor:A,service:S,semester_id:int,business_id:int|None=None,group_id:int|None=None):
    from .hours_export import export_hours
    data=export_hours(service,actor,semester_id,business_id,group_id)
    return Response(data,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':f'attachment; filename="volunteer-hours-semester-{semester_id}.xlsx"',
                             'Cache-Control':'no-store'})


@app.patch('/service-records/{record_id}',tags=['考勤与时长'])
def revise_hours(record_id:int,body:HoursEdit,actor:A,service:S):
    return service.revise_hours(actor,record_id,**body.model_dump())


@app.get('/credit',tags=['信用与审计'])
def credit(actor:A,service:S,student_id:str|None=None):
    return service.credit(actor,student_id)


@app.get('/credit-rules',tags=['信用与审计'])
def rules(actor:A,service:S):
    return service.rules(actor)


@app.put('/credit-rules/{violation_type}',tags=['信用与审计'])
def change_rule(violation_type:Literal['LATE','ABSENT'],body:RuleEdit,actor:A,service:S):
    return service.set_rule(actor,violation_type,**body.model_dump())


@app.get('/operation-logs',tags=['信用与审计'])
def logs(actor:A,service:S,limit:int=100):
    return service.logs(actor,limit)


app.openapi=lambda: chinese_openapi(app)


class BusinessManager(Model):
    manager_admin_id:int|None=Field(default=None,gt=0)


class BusinessWeek(Reason):
    working:bool


class CollectionItem(Model):
    title:str=Field(min_length=1,max_length=100)
    min_minutes:int=Field(ge=30,le=1440,multiple_of=30)
    max_minutes:int=Field(ge=30,le=1440,multiple_of=30)


class CollectionAttachment(Model):
    filename:str=Field(min_length=1,max_length=200)
    file_base64:str=Field(min_length=1,max_length=2800000)


class CollectionCreate(Model):
    business_id:int=Field(gt=0)
    group_id:int|None=Field(default=None,gt=0)
    title:str=Field(min_length=1,max_length=100)
    start_date:date
    end_date:date
    student_ids:list[str]=Field(min_length=1,max_length=10000)
    items:list[CollectionItem]=Field(min_length=1,max_length=100)
    attachments:list[CollectionAttachment]=Field(default_factory=list,max_length=3)
    submission_deadline:date|None=None


class SubmissionCreate(Model):
    item_id:int=Field(gt=0)
    service_date:date
    service_minutes:int=Field(ge=0,le=1440)
    remark:str=Field(default='',max_length=500)
    expected_revision:int|None=Field(default=None,ge=1)
    attachments:list[CollectionAttachment]|None=Field(default=None,max_length=3)


class SubmissionDecision(Decision):
    expected_revision:int=Field(ge=1)


class BatchApprovalItem(Model):
    submission_id:int=Field(gt=0)
    expected_revision:int=Field(ge=1)


class BatchApproval(Model):
    items:list[BatchApprovalItem]=Field(min_length=1,max_length=10000)
    reason:str=Field(default='',max_length=500)


class BatchRead(Model):
    notice_ids:list[int]=Field(min_length=1,max_length=10000)


@app.post('/hour-collections/{collection_id}/approve-batch',tags=['时长征集'])
def approve_collection_batch(collection_id:int,body:BatchApproval,actor:A,service:S):
    return service.approve_hours_batch(actor,collection_id,**body.model_dump())


@app.post('/inbox/read-batch',tags=['收件箱'])
def read_inbox_batch(body:BatchRead,actor:A,service:S):
    return service.read_notices_batch(actor,body.notice_ids)


class SubmissionCorrection(SubmissionDecision):
    reason:str=Field(min_length=1,max_length=500)
    service_minutes:int|None=Field(default=None,ge=0,le=1440)


class CollectionScope(Reason):
    business_ids:list[int]=Field(max_length=100)
    group_ids:list[int]|None=Field(default=None,max_length=100)


@app.get('/inbox',tags=['收件箱'])
def inbox(actor:A,service:S,unread_only:bool=False,before_id:int|None=None,limit:int=50):
    return service.inbox(actor,unread_only,before_id,limit)


@app.post('/inbox/read-all',tags=['收件箱'])
def read_all_notices(actor:A,service:S):
    return service.read_notice(actor)


@app.post('/inbox/{notice_id}/read',tags=['收件箱'])
def read_notice(notice_id:int,actor:A,service:S):
    return service.read_notice(actor,notice_id)


@app.get('/collection-management',tags=['征集管理范围'])
def collection_management(actor:A,service:S):
    return service.collection_management(actor)


@app.put('/collection-managers/{admin_id}',tags=['征集管理范围'])
def set_collection_managers(admin_id:int,body:CollectionScope,actor:A,service:S):
    return service.set_collection_managers(actor,admin_id,**body.model_dump())


@app.post('/collection-scope-requests',tags=['征集管理范围'])
def request_collection_scope(body:CollectionScope,actor:A,service:S):
    return service.request_collection_scope(actor,**body.model_dump())


@app.post('/collection-scope-requests/{request_id}/decision',tags=['征集管理范围'])
def decide_collection_scope(request_id:int,body:SubmissionDecision,actor:A,service:S):
    return service.decide_collection_scope(actor,request_id,**body.model_dump())


@app.post('/hour-collections/{collection_id}/close',tags=['时长征集'])
def close_collection(collection_id:int,body:Reason,actor:A,service:S):
    return service.close_collection(actor,collection_id,body.reason)


@app.post('/hour-submissions/{submission_id}/correction',tags=['时长征集'])
def correct_hours_review(submission_id:int,body:SubmissionCorrection,actor:A,service:S):
    return service.correct_hours_review(actor,submission_id,**body.model_dump())


@app.get('/hour-submissions/{submission_id}/attachments/{attachment_id}',tags=['时长征集'])
def submission_attachment(submission_id:int,attachment_id:int,actor:A,service:S,preview:bool=False):
    f=service.submission_attachment(actor,submission_id,attachment_id)
    inline=preview and f['mime_type'] in ('application/pdf','image/jpeg','image/png')
    return Response(content=f['content'],media_type=f['mime_type'],headers={
        'Content-Disposition':('inline' if inline else 'attachment')+"; filename*=UTF-8''"+quote(f['filename'],safe=''),
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"sandbox; default-src 'none'"})


class SpecialtyImport(Model):
    business_name:str=Field(min_length=1,max_length=100)
    file_base64:str=Field(min_length=1,max_length=12*1024*1024)
    commit:bool=False
    initial_password:str|None=Field(default=None,min_length=8,max_length=128)
    duplicate_rows:dict[int,Literal['skip','separate']]=Field(default_factory=dict)


class EventCreate(Reason):
    business_name:str=Field(min_length=1,max_length=100)
    student_id:str=Field(min_length=1,max_length=32)
    title:str=Field(min_length=1,max_length=100)
    service_date:date
    service_minutes:int=Field(ge=0,le=1440)
    request_key:str=Field(min_length=16,max_length=64)


class EventMember(Reason):
    active:bool
    effective_date:date


@app.put('/businesses/{business_id}/members/{student_id}',tags=['业务管理'])
def set_event_member(business_id:int,student_id:str,body:EventMember,actor:A,service:S):
    return service.set_event_member(actor,business_id,student_id,**body.model_dump())


@app.post('/schedules/{schedule_id}/recognize-event',tags=['业务管理'])
def recognize_event(schedule_id:int,body:HoursEdit,actor:A,service:S):
    return service.recognize_event(actor,schedule_id,**body.model_dump())


@app.get('/businesses',tags=['业务管理'])
def businesses(actor:A,service:S):
    return service.businesses(actor)


class BusinessSlot(Model):
    weekday:int=Field(ge=1,le=7)
    period_no:int=Field(ge=1,le=100)
    start_time:str=Field(pattern=r'^\d{2}:\d{2}$')
    end_time:str=Field(pattern=r'^\d{2}:\d{2}$')
    service_minutes:int=Field(ge=1,le=1440)
    need_num:int=Field(ge=1,le=10000)
    manager_admin_id:int=Field(gt=0)
    location:str=Field(default='',max_length=200)


class BusinessCreate(Model):
    name:str=Field(min_length=1,max_length=100)
    kind:Literal['FIXED','EVENT']
    slots:list[BusinessSlot]=Field(default_factory=list,max_length=700)


class BusinessRename(Reason):
    name:str=Field(min_length=1,max_length=100)


class BusinessStatus(Reason):
    expected_revision:int=Field(ge=1)


class MemberTarget(Model):
    business_id:int=Field(gt=0)
    group_id:int|None=Field(default=None,gt=0)


class MemberChoice(Model):
    skip:bool=False
    student_id:str|None=Field(default=None,max_length=32)
    confirmed:bool=False


class MemberImportRequest(Model):
    file_base64:str=Field(min_length=1,max_length=12*1024*1024)
    mappings:dict[str,MemberTarget|None]=Field(default_factory=dict)
    decisions:dict[str,MemberChoice]=Field(default_factory=dict)
    initial_password:str|None=Field(default=None,min_length=8,max_length=128)
    commit:bool=False


@app.post('/businesses',tags=['业务管理'])
def create_business(body:BusinessCreate,actor:A,service:S):
    return service.create_business(actor,**body.model_dump())


@app.patch('/businesses/{business_id}',tags=['业务管理'])
def rename_business(business_id:int,body:BusinessRename,actor:A,service:S):
    return service.rename_business(actor,business_id,**body.model_dump())


@app.post('/businesses/{business_id}/slots',tags=['业务管理'])
def add_business_slot(business_id:int,body:BusinessSlot,actor:A,service:S):
    return service.add_business_slot(actor,business_id,**body.model_dump())


@app.get('/businesses/{business_id}/archive-impact',tags=['业务管理'])
def archive_impact(business_id:int,actor:A,service:S):
    return service.archive_impact(actor,business_id)


@app.post('/businesses/{business_id}/archive',tags=['业务管理'])
def archive_business(business_id:int,body:BusinessStatus,actor:A,service:S):
    return service.change_business_status(actor,business_id,False,**body.model_dump())


@app.post('/businesses/{business_id}/restore',tags=['业务管理'])
def restore_business(business_id:int,body:BusinessStatus,actor:A,service:S):
    return service.change_business_status(actor,business_id,True,**body.model_dump())


@app.get('/business-groups',tags=['小组与成员'])
def business_groups(actor:A,service:S,business_id:int|None=None):
    return service.business_groups(actor,business_id)


@app.get('/business-groups/{group_id}/members',tags=['小组与成员'])
def group_members(group_id:int,actor:A,service:S):
    return service.group_members(actor,group_id)


@app.put('/business-groups/{group_id}/members/{student_id}',tags=['小组与成员'])
def set_group_member(group_id:int,student_id:str,body:EventMember,actor:A,service:S):
    return service.set_group_member(actor,group_id,student_id,**body.model_dump())


@app.post('/member-imports',tags=['小组与成员'])
def import_members(body:MemberImportRequest,actor:A,service:S):
    return service.import_members(actor,**body.model_dump())


@app.put('/businesses/{business_id}/manager',tags=['业务管理'])
def business_manager(business_id:int,body:BusinessManager,actor:A,service:S):
    return service.configure_business(actor,business_id,body.manager_admin_id)


@app.get('/business-weeks',tags=['业务管理'])
def business_weeks(semester_id:int,actor:A,service:S):
    return service.business_weeks(actor,semester_id)


@app.put('/businesses/{business_id}/semesters/{semester_id}/weeks/{week_no}',tags=['业务管理'])
def business_week(business_id:int,semester_id:int,week_no:int,body:BusinessWeek,actor:A,service:S):
    return service.set_business_week(actor,business_id,semester_id,week_no,**body.model_dump())


@app.post('/schedules/{schedule_id}/confirm-weekly',tags=['业务管理'])
def confirm_weekly(schedule_id:int,body:Reason,actor:A,service:S):
    return service.confirm_garden(actor,schedule_id,body.reason)


@app.get('/hour-collections',tags=['时长征集'])
def collections(actor:A,service:S):
    return service.collections(actor)


@app.get('/hour-collections/participants',tags=['时长征集'])
def collection_participants(actor:A,service:S,business_id:int|None=None,student_id:str='',group_id:int|None=None):
    return service.collection_participants(actor,business_id,student_id,group_id)


@app.get('/hour-collections/{collection_id}/attachments/{attachment_id}',tags=['时长征集'])
def collection_attachment(collection_id:int,attachment_id:int,actor:A,service:S,preview:bool=False):
    f=service.collection_attachment(actor,collection_id,attachment_id)
    inline=preview and f['mime_type'] in ('application/pdf','image/jpeg','image/png')
    return Response(content=f['content'],media_type=f['mime_type'],headers={
        'Content-Disposition':('inline' if inline else 'attachment')+"; filename*=UTF-8''"+quote(f['filename'],safe=''),
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"sandbox; default-src 'none'"})


@app.post('/hour-collections',tags=['时长征集'])
def create_collection(body:CollectionCreate,actor:A,service:S):
    return service.create_collection(actor,**body.model_dump())


@app.post('/hour-submissions',tags=['时长征集'])
def submit_hours(body:SubmissionCreate,actor:A,service:S):
    return service.submit_hours(actor,**body.model_dump())


@app.post('/hour-submissions/{submission_id}/decision',tags=['时长征集'])
def decide_hours(submission_id:int,body:SubmissionDecision,actor:A,service:S):
    return service.decide_hours(actor,submission_id,**body.model_dump())


@app.post('/specialty-imports',tags=['专项导入'])
def specialty_import(body:SpecialtyImport,actor:A,service:S):
    return service.import_specialty(actor,**body.model_dump())


@app.get('/specialty-imports/template',tags=['专项导入'])
def specialty_template(actor:A,service:S):
    with service.db.transaction() as c:service.actor(c,actor,('SUPER',))
    return FileResponse(WEB_ROOT.parent/'templates'/'专项时长导入模板.xlsx',filename='specialty-hours-template.xlsx',headers={'Cache-Control':'no-store'})


@app.post('/business-events',tags=['业务管理'])
def create_event(body:EventCreate,actor:A,service:S):
    return service.create_event(actor,**body.model_dump())


@app.get('/applications/leave/{leave_id}/evidence',tags=['申请与审批'])
def leave_evidence(leave_id:int,actor:A,service:S):
    return service.leave_evidence(actor,leave_id)


@app.get('/applications/leave/{leave_id}/evidence/{attachment_id}',tags=['申请与审批'])
def leave_image(leave_id:int,attachment_id:int,actor:A,service:S):
    data=service.leave_evidence(actor,leave_id,attachment_id)
    return Response(data['content'],media_type=data['mime_type'],headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


class LeaderAppointment(BaseModel):
    student_id: str | None = Field(default=None, max_length=32)
    reason: str = Field(min_length=1,max_length=500)


@app.get('/leaders',tags=['分队与美育负责人'])
def leader_directory(actor:A,service:S):
    return output(service.leader_directory(actor))


@app.put('/leaders/{scope_id}',tags=['分队与美育负责人'])
def appoint_leader(scope_id:int,body:LeaderAppointment,actor:A,service:S):
    return service.appoint_leader(actor,scope_id,**body.model_dump())


@app.get('/leader-workspace',tags=['分队与美育负责人'])
def leader_workspace(actor:A,service:S):
    return output(service.leader_workspace(actor))


@app.get('/leader-reports/{report_id}',tags=['分队与美育负责人'])
def leader_report(report_id:int,actor:A,service:S):
    return output(service.leader_report(actor,report_id))


@app.post('/applications/withdrawal/{withdrawal_id}/first',tags=['分队与美育负责人'])
def withdrawal_first(withdrawal_id:int,body:Decision,actor:A,service:S):
    return service.first_review_withdrawal(actor,withdrawal_id,body.approved,body.reason)
