from datetime import date, timedelta
from typing import Literal, Annotated
import logging
import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
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


app=FastAPI(title='图书馆志愿服务管理核心 API',version='1.3.0',lifespan=lifespan,
    description='图书馆志愿服务管理系统接口说明。支持志愿者、普通管理员和超级管理员。请先登录获得访问令牌，所有日期按北京时间解释。',
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
    slot_ids:list[int]=Field(max_length=35)


class RosterImport(Model):
    file_base64:str=Field(min_length=1,max_length=12*1024*1024)
    sheet_name:str|None=Field(default=None,max_length=100)
    map_categories:bool=True
    commit:bool=False
    initial_password:str|None=Field(default=None,min_length=8,max_length=128)
    accept_warnings:bool=False


class LeaveCreate(Model):
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
    slot_ids:list[int]=Field(default_factory=list,max_length=35)


class Decision(Model):
    approved:bool


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


@app.get('/students',tags=['基础资料'])
def students(actor:A,service:S,student_id:str|None=None):
    return service.students(actor,student_id)


@app.post('/students/import',tags=['基础资料'])
def import_students(body:RosterImport,actor:A,service:S):
    return service.import_roster(actor,**body.model_dump())


@app.put('/students/{student_id}/slots',tags=['基础资料'])
def student_memberships(student_id:str,body:Memberships,actor:A,service:S):
    return service.set_memberships(actor,student_id,body.slot_ids)


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
    return service.approve_leave(actor,leave_id,body.approved)


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


@app.put('/students/{student_id}/credit',tags=['信用与审计'])
def set_student_credit(student_id:str,body:CreditSet,actor:A,service:S):
    return service.set_student_credit(actor,student_id,**body.model_dump())


@app.get('/hours',tags=['考勤与时长'])
def hours(actor:A,service:S,student_id:str|None=None,start:date|None=None,end:date|None=None):
    return service.hours(actor,student_id,start,end)


@app.get('/hours/export',tags=['考勤与时长'])
def hours_export(actor:A,service:S,semester_id:int):
    from .hours_export import export_hours
    data=export_hours(service,actor,semester_id)
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
