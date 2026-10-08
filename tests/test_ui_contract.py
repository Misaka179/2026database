"""Exercise browser-script business behavior without a database or browser install.

The Node VM fixture only supplies DOM primitives used by these scenarios. Full
layout, focus, responsive and native dialog behavior require browser verification.
"""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import os
os.environ['VOLUNTEER_DISABLE_SCHEDULER'] = '1'

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE.parent / '.work' / 'python-packages'))

from fastapi.testclient import TestClient
from app.api import app


class PageAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == 'script' and data.get('src'):
            self.paths.append(data['src'])
        if tag == 'link' and data.get('rel') == 'stylesheet':
            self.paths.append(data['href'])


JS_SETUP = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
const documentHandlers = new Map();
function element(key) {
  if (!elements.has(key)) elements.set(key, {
    innerHTML:'', textContent:'', open:false, dataset:{},listeners:{},isConnected:true,
    classList:{add(){},remove(){},toggle(){}},
    addEventListener(type,callback){this.listeners[type]=callback;},setAttribute(){},removeAttribute(){},focus(){},
    showModal(){this.open=true;},close(){this.open=false;},
    querySelector(){return null;},querySelectorAll(){return [];},
    append(){},remove(){}
  });
  return elements.get(key);
}
function storage() {const values = new Map();return {
  getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)
};}
let now = '2026-09-25T02:00:00.000Z';
class FixedDate extends Date {constructor(...args){super(...(args.length?args:[now]));}static now(){return new Date(now).getTime();}}
const context = vm.createContext({
  console, Date:FixedDate, Intl, URLSearchParams, AbortSignal,
  sessionStorage:storage(),localStorage:storage(),
  matchMedia:()=>({matches:false}),setTimeout:()=>0,
  document:{querySelector:element,querySelectorAll:()=>[],
    documentElement:{dataset:{}},activeElement:null,addEventListener:(type,callback)=>documentHandlers.set(type,callback),
    createElement:()=>element('created')},
  fetch:()=>new Promise(()=>{})
});
const source = fs.readFileSync(process.argv[1], 'utf8').replace(/\nstart\(\);\s*$/, '\n');
vm.runInContext(fs.readFileSync(require('node:path').join(require('node:path').dirname(process.argv[1]),'roster-ui.js'),'utf8'),context,{filename:'roster-ui.js'});
vm.runInContext(fs.readFileSync(require('node:path').join(require('node:path').dirname(process.argv[1]),'semester-ui.js'),'utf8'),context,{filename:'semester-ui.js'});
vm.runInContext(source,context,{filename:'app.js'});
const run = code => vm.runInContext(code,context);
const response = value => ({ok:true,status:200,json:async()=>value});
function actionForm(values) {
  const submit={textContent:'确认提交',disabled:false};
  const form={id:'action-form',values,querySelectorAll:()=>[],querySelector:()=>submit};
  context.FormData=class {constructor(form){this.form=form;}*[Symbol.iterator](){yield* Object.entries(this.form.values);}};
  return form;
}
"""


class InterfaceAssetTests(unittest.TestCase):
    def test_all_page_scripts_and_styles_resolve_locally(self):
        with TestClient(app) as client:
            checked = set()
            for page in ('/', '/docs'):
                parsed = PageAssets()
                response = client.get(page)
                self.assertEqual(response.status_code, 200)
                parsed.feed(response.text)
                self.assertTrue(parsed.paths)
                for path in parsed.paths:
                    with self.subTest(page=page, resource=path):
                        self.assertTrue(path.startswith('/static/'), path)
                        if path in checked:
                            continue
                        checked.add(path)
                        asset = client.get(path)
                        self.assertEqual(asset.status_code, 200)
                        self.assertGreater(len(asset.content), 100)
                        if path.split('?', 1)[0].endswith('.js'):
                            self.assertIn('javascript', asset.headers['content-type'])
                        else:
                            self.assertIn('text/css', asset.headers['content-type'])


@unittest.skipUnless(shutil.which('node'), 'Node.js is required for browser-script unit scenarios')
class WorkbenchBehaviorTests(unittest.TestCase):
    def test_fixed_membership_appears_and_opens_transfer_without_dated_schedule(self):
        self.js(r'''
run(`state.role='STUDENT';state.me={student_id:'001',name:'甲',status:'ACTIVE'};
state.data={schedules:[],transfer:[],memberships:[{slot_id:3,team_name:'周一-一时段',status:'ACTIVE',start_time:'08:15',end_time:'09:55'}],
slots:[{slot_id:3,team_name:'周一-一时段',status:'ACTIVE',weekday:1},{slot_id:8,team_name:'周二-一时段',status:'ACTIVE',weekday:2,start_time:'08:15',end_time:'09:55'}]};
schedulesPage();`);
assert.match(element('#main').innerHTML,/我的固定班次/);
assert.match(element('#main').innerHTML,/周一-一时段/);
run("action('transfer')");
assert.equal(element('#action-dialog').open,true);
assert.match(element('#action-dialog').innerHTML,/申请更换固定班次/);
assert.match(element('#action-dialog').innerHTML,/周二-一时段/);
assert.doesNotMatch(element('#action-dialog').innerHTML,/name="new_date"/);
run("state.data.transfer=[{old_slot_id:3,first_status:'PENDING',final_status:'PENDING'}];schedulesPage()");
assert.match(element('#main').innerHTML,/换班审批中/);
''')

    def test_calendar_dialog_and_week_filter_follow_semester(self):
        self.js(r'''
run(`state.role='SUPER';state.me={admin_id:1};state.data={semesters:[{semester_id:1,name:'秋季学期',start_date:'2026-09-07',end_date:'2026-09-27',end_week:3,current_week:3,phase:'ONGOING',calendar:[]}],schedules:[]};semesterPage();`);
assert.match(element('#main').innerHTML,/秋季学期/);
run("action('calendar-edit',1)");
assert.match(element('#action-dialog').innerHTML,/执行周一的班表/);
assert.match(element('#action-dialog').innerHTML,/停工/);
run("closeDialog();schedulesPage();");
assert.match(element('#main').innerHTML,/当前周（第 3 周）/);
assert.match(element('#main').innerHTML,/每周一自动结算上周/);
''')

    def test_dated_student_schedule_never_offers_single_transfer(self):
        self.js(r'''
run("state.role='STUDENT';state.me={status:'ACTIVE'};");
context.row={status:'ACTIVE',schedule_date:'2030-01-01',start_time:'08:15',end_time:'09:55',schedule_id:1};
assert.match(run('scheduleActions(row)'),/请假/);
assert.doesNotMatch(run('scheduleActions(row)'),/换班/);
''')

    def test_auto_settled_attendance_opens_required_correction_form(self):
        self.js(r'''
run("state.role='NORMAL';state.me={admin_id:1};state.data={schedules:[{schedule_id:1,student_id:'001',schedule_date:'2026-09-07',start_time:'08:15',end_time:'09:55',status:'COMPLETED',attendance_status:'NORMAL',attendance_source:'AUTO_WEEKLY'}]};action('attendance',1)");
assert.match(element('#action-dialog').innerHTML,/补录缺勤/);
assert.match(element('#action-dialog').innerHTML,/name="remark" required/);
assert.doesNotMatch(element('#action-dialog').innerHTML,/value="NORMAL"/);
''')

    def test_attendance_correction_submits_the_displayed_revision(self):
        self.js(r'''
const requests=[];
context.fetch=async(path,options)=>{requests.push({path,...options});return response({});};
run("state.token='current';state.role='NORMAL';state.me={admin_id:1};refresh=async()=>{};state.data={schedules:[{schedule_id:17,student_id:'001',schedule_date:'2026-09-07',start_time:'08:15',end_time:'09:55',status:'COMPLETED',attendance_status:'ABSENT',attendance_revision:3}]};");
assert.match(run('scheduleActions(state.data.schedules[0])'),/考勤改判/);
run("action('attendance-correct',17)");
assert.match(element('#action-dialog').innerHTML,/退还原实际扣分/);
assert.match(element('#action-dialog').innerHTML,/name="reason" required/);
const form=actionForm({status:'NORMAL',reason:'签到表核实到岗'});
documentHandlers.get('submit')({preventDefault(){},target:form}).then(()=>{
  assert.equal(requests[0].path,'/schedules/17/attendance');
  assert.equal(requests[0].method,'PATCH');
  assert.deepEqual(JSON.parse(requests[0].body),{status:'NORMAL',reason:'签到表核实到岗',expected_revision:3});
}).catch(error=>{console.error(error);process.exitCode=1;});
''')

    def test_super_credit_dialog_uses_captured_student_and_version(self):
        self.js(r'''
const requests=[];
context.fetch=async(path,options)=>{requests.push({path,...options});return response({});};
run(`state.token='current';state.role='SUPER';state.me={admin_id:1};refresh=async()=>{};
state.data={students:[{student_id:'001',name:'<script>bad</script>'}],selectedCredit:{student_id:'001',credit_score:7,credit_version:4}};action('credit-set');`);
assert.doesNotMatch(element('#action-dialog').innerHTML,/<script>/);
assert.match(element('#action-dialog').innerHTML,/&lt;script&gt;/);
run("state.selectedStudent='002';state.data.selectedCredit={student_id:'002',credit_score:9,credit_version:1}");
const form=actionForm({credit_score:'12',reason:'补录评优奖励'});
documentHandlers.get('submit')({preventDefault(){},target:form}).then(()=>{
  assert.equal(requests[0].path,'/students/001/credit');
  assert.equal(requests[0].method,'PUT');
  assert.deepEqual(JSON.parse(requests[0].body),{credit_score:12,expected_version:4,reason:'补录评优奖励'});
}).catch(error=>{console.error(error);process.exitCode=1;});
''')

    def test_student_query_disambiguates_names_and_clears_previous_records(self):
        self.js(r'''
run(`state.role='SUPER';state.page='credit';state.data={students:[
{student_id:'001',name:'同名',status:'ACTIVE'},
{student_id:'002',name:'同名',status:'QUIT'},
{student_id:'0010',name:'其他',status:'DISABLED'}],selectedCredit:{student_id:'001'}};
state.selectedStudent='001';state.studentQuery=' 同名 ';queryStudent();`);
assert.equal(run('state.selectedStudent'),'');
assert.equal(run('state.data.selectedCredit'),null);
assert.match(element('#credit-result').innerHTML,/001/);
assert.match(element('#credit-result').innerHTML,/002/);
assert.doesNotMatch(element('#credit-result').innerHTML,/调整信用分/);
assert.equal(run("matchingStudents('001').length"),1);
assert.equal(run("matchingStudents('00').length"),3);
run("state.studentQuery='不存在';queryStudent()");
assert.match(element('#credit-result').innerHTML,/未找到志愿者/);
run("state.studentQuery='';queryStudent()");
assert.match(element('#credit-result').innerHTML,/请输入学号或姓名/);
''')

    def test_student_query_uses_resolved_id_and_retains_hours_date_range(self):
        self.js(r'''
const requests=[];
context.fetch=async(path)=>{requests.push(path);return response({records:[],total_minutes:0,logs:[],credit_score:5,status:'ACTIVE'});};
(async()=>{
run(`state.role='SUPER';state.me={admin_id:1};state.page='hours';state.data={schedules:[],students:[{student_id:'S001',name:'测试姓名',status:'ACTIVE'}]};
state.studentQuery='测试';state.from='2026-09-01';state.to='2026-10-01';queryStudent();`);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(requests[0],'/hours?student_id=S001&start=2026-09-01&end=2026-10-01');
assert.match(element('#hours-result').innerHTML,/测试姓名/);
assert.match(element('#hours-result').innerHTML,/S001/);
await run("state.page='credit';state.tab='';creditPage()");
assert.equal(requests[1],'/credit?student_id=S001');
assert.match(element('#main').innerHTML,/type="search"/);
assert.match(element('#credit-result').innerHTML,/测试姓名/);
})().catch(error=>{console.error(error);process.exitCode=1;});
''')

    def test_hours_export_selects_semester_and_reports_download_errors(self):
        self.js(r'''
const requests=[];
context.fetch=async(path,options)=>{requests.push({path,...options});return {ok:false,json:async()=>({detail:'没有执行此操作的权限'})};};
(async()=>{
run(`state.role='SUPER';state.token='test';state.data={semesters:[{semester_id:12,name:'秋学期',start_date:'2026-08-31',end_date:'2026-12-13',phase:'ONGOING'}]};`);
await documentHandlers.get('click')({target:{closest:()=>({dataset:{action:'hours-export'}})}});
assert.match(element('#action-dialog').innerHTML,/不受页面的个人查询和日期筛选影响/);
assert.match(element('#action-dialog').innerHTML,/秋学期/);
await assert.rejects(run("modalSubmit({semester_id:'12'})"),/没有执行此操作的权限/);
assert.equal(requests[0].path,'/hours/export?semester_id=12');
assert.equal(requests[0].headers.Authorization,'Bearer test');
})().catch(error=>{console.error(error);process.exitCode=1;});
''')

    def js(self, scenario):
        result = subprocess.run(
            [shutil.which('node'), '-e', JS_SETUP + '\n' + scenario, str(CORE / 'web' / 'app.js')],
            capture_output=True, text=True, encoding='utf-8', timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_super_can_grant_a_volunteer_without_changing_student_membership(self):
        self.js(r'''
const requests=[];
context.fetch=async(path,options)=>{requests.push({path,...options});return response({});};
run(`state.token='current';state.role='SUPER';state.me={admin_id:1};refresh=async()=>{};
state.data={students:[{student_id:'001',name:'<b>甲</b>',status:'ACTIVE',slots:[]}],
admins:[],slots:[{slot_id:8,weekday:2,period_no:1,status:'ACTIVE',team_name:'周二-一时段',manager_admin_id:null}]};`);
assert.match(run('rosterStudentTable(state.data.students)'),/设为普通管理员/);
run("action('promote-student','001')");
assert.match(element('#action-dialog').innerHTML,/使用学号和现有志愿者密码/);
assert.doesNotMatch(element('#action-dialog').innerHTML,/<b>/);
assert.doesNotMatch(element('#action-dialog').innerHTML,/name="password"/);
const form=actionForm({manage_8:'8',reason:'安排时段负责人'});
documentHandlers.get('submit')({preventDefault(){},target:form}).then(()=>{
  assert.equal(requests[0].path,'/students/001/administrator');
  assert.equal(requests[0].method,'POST');
  assert.deepEqual(JSON.parse(requests[0].body),{slot_ids:[8],reason:'安排时段负责人'});
}).catch(error=>{console.error(error);process.exitCode=1;});
''')

    def test_manager_and_inactive_students_do_not_offer_admin_grant(self):
        self.js(r'''
run("state.role='NORMAL';state.data={admins:[],students:[{student_id:'001',name:'甲',status:'ACTIVE'}]};");
assert.doesNotMatch(run('rosterStudentTable(state.data.students)'),/设为普通管理员/);
run("state.role='SUPER';state.data.students[0].status='QUIT';");
assert.doesNotMatch(run('rosterStudentTable(state.data.students)'),/设为普通管理员/);
run("state.data.students[0].status='ACTIVE';state.data.admins=[{admin_id:4,student_id:'001',role:'NORMAL',status:'ACTIVE'}];");
assert.match(run('rosterStudentTable(state.data.students)'),/普通管理员/);
assert.doesNotMatch(run('rosterStudentTable(state.data.students)'),/data-action="promote-student"/);
''')

    def test_navigation_before_initial_data_arrives_does_not_crash(self):
        self.js(r"""
run("state.me={name:'管理员',admin_id:1};state.role='SUPER';state.data={};");
assert.doesNotThrow(()=>run("navigate('schedules')"));
assert.equal(run('state.page'),'schedules');
""")

    def test_late_unauthorized_response_cannot_sign_out_new_session(self):
        self.js(r"""
context.fetch=async()=>({ok:false,status:401,json:async()=>({detail:'请重新登录'})});
run("state.token='old-session';state.me={name:'旧用户'};");
const pending=run("request('/schedules')").catch(()=>{});
run("state.token='new-session';state.me={name:'新用户'};");
pending.then(()=>{
  assert.equal(run('state.token'),'new-session');
  assert.equal(run('state.me.name'),'新用户');
}).catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_initial_load_commits_to_the_page_selected_while_waiting(self):
        self.js(r"""
let release;
context.fetch=path=>path==='/auth/me'?new Promise(resolve=>{release=resolve;}):Promise.resolve(response([]));
run("state.token='current';state.me={name:'管理员',admin_id:1};state.role='SUPER';");
const loading=run('refresh()');
run("navigate('schedules')");
release(response({name:'管理员',admin_id:1,role:'SUPER'}));
loading.then(()=>{
  assert.equal(run('state.page'),'schedules');
  assert.match(element('#main').innerHTML,/排班与考勤/);
  assert.match(element('#main').innerHTML,/暂无具体日期排班/);
  assert.doesNotMatch(element('#main').innerHTML,/正在读取/);
}).catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_refresh_updates_student_status_before_showing_application_actions(self):
        self.js(r"""
const future={schedule_id:1,student_id:'20260001',student_name:'张三',schedule_date:'2030-01-02',start_time:'10:00',end_time:'12:00',team_name:'一分队',period_no:1,status:'ACTIVE'};
context.fetch=async path=>response(path==='/auth/me'?{student_id:'20260001',name:'张三',status:'DISABLED'}:path==='/schedules'?[future]:path==='/hours'?{total_minutes:0,records:[]}:path==='/credit'?{credit_score:0,status:'DISABLED',logs:[]}:[]);
run("state.token='current';state.me={student_id:'20260001',name:'张三',status:'ACTIVE'};state.role='STUDENT';state.page='schedules';");
run('refresh()').then(()=>{
  assert.equal(run('state.me.status'),'DISABLED');
  assert.match(element('#main').innerHTML,/张三/);
  assert.doesNotMatch(element('#main').innerHTML,/data-action="(?:leave|transfer)"/);
}).catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_manager_can_search_names_without_global_student_directory(self):
        self.js(r"""
run("state.me={name:'负责人',admin_id:1};state.role='NORMAL';state.search='张三';state.data={schedules:[{schedule_id:1,student_id:'20260001',student_name:'张三',team_name:'一分队',period_no:1,location:'图书馆',schedule_date:'2030-01-02',start_time:'10:00',end_time:'12:00',status:'ACTIVE'}]};schedulesPage();");
assert.match(element('#main').innerHTML,/<td>张三<small>20260001/);
assert.doesNotMatch(element('#main').innerHTML,/暂无服务安排/);
""")

    def test_pending_action_cannot_close_or_replace_its_dialog(self):
        self.js(r"""
let release;
context.pendingAction=()=>new Promise(resolve=>{release=resolve;});
run("state.token='current';state.me={name:'管理员'};refresh=async()=>{};openDialog('第一次申请','说明','',pendingAction);");
const form=actionForm({reason:'填写的原因'});
const dialog=element('#action-dialog');
const closeButton={disabled:false};dialog.querySelectorAll=()=>[closeButton];
const submitted=documentHandlers.get('submit')({preventDefault(){},target:form});
assert.equal(closeButton.disabled,true);
run('closeDialog()');
assert.equal(dialog.open,true);
let prevented=false;dialog.listeners.cancel({preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(dialog.open,true);
run("openDialog('第二次申请','说明','',()=>Promise.resolve())");
assert.match(dialog.innerHTML,/第一次申请/);
assert.doesNotMatch(dialog.innerHTML,/第二次申请/);
release({});
submitted.then(()=>{
  assert.equal(dialog.open,false);
  assert.equal(closeButton.disabled,false);
}).catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_failed_action_keeps_input_and_reenables_dialog(self):
        self.js(r"""
context.failedAction=async()=>{throw new Error('人数已满，请更换班次');};
run("state.token='current';state.me={name:'管理员'};openDialog('新增排班','说明','',failedAction);");
const form=actionForm({reason:'原来填写的内容'});
const dialog=element('#action-dialog');const closeButton={disabled:false};dialog.querySelectorAll=()=>[closeButton];
documentHandlers.get('submit')({preventDefault(){},target:form}).then(()=>{
  assert.equal(dialog.open,true);
  assert.equal(form.values.reason,'原来填写的内容');
  assert.equal(form.querySelector().disabled,false);
  assert.equal(closeButton.disabled,false);
  assert.equal(element('#action-error').hidden,false);
  assert.match(element('#action-error').textContent,/人数已满/);
}).catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_old_action_success_does_not_close_new_login_dialog(self):
        self.js(r"""
let release;
context.pendingAction=()=>new Promise(resolve=>{release=resolve;});
run("state.token='old-session';state.me={name:'旧用户'};openDialog('旧申请','说明','',pendingAction);");
const form=actionForm({reason:'原因'});
const submitted=documentHandlers.get('submit')({preventDefault(){},target:form});
run("signOut(false);state.token='new-session';state.me={name:'新用户'};openDialog('新申请','说明','',()=>Promise.resolve());");
release({});
submitted.then(()=>{
  assert.equal(element('#action-dialog').open,true);
  assert.match(element('#action-dialog').innerHTML,/新申请/);
  assert.equal(run('state.token'),'new-session');
}).catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_beijing_time_boundaries_match_scheduling_rules(self):
        self.js(r"""
run("state.me={status:'ACTIVE'};state.role='STUDENT';");
context.row={status:'ACTIVE',schedule_date:'2026-09-25',start_time:'10:00',end_time:'12:00',schedule_id:9};
now='2026-09-25T01:59:59.999Z';
assert.equal(run('canFuture(row)'),true);
assert.match(run('scheduleActions(row)'),/请假/);
now='2026-09-25T02:00:00.000Z';
assert.equal(run('canFuture(row)'),false);
assert.doesNotMatch(run('scheduleActions(row)'),/data-action="leave"/);
run("state.role='NORMAL';");
now='2026-09-25T03:59:59.999Z';
assert.equal(run('isEnded(row)'),false);
now='2026-09-25T04:00:00.000Z';
assert.equal(run('isEnded(row)'),true);
assert.match(run('scheduleActions(row)'),/登记考勤/);
""")

    def test_stored_user_text_is_escaped_in_tables_and_application_dialogs(self):
        self.js(r"""
context.dirty='<img src=x onerror="alert(1)">';
run("state.me={student_id:'20260001',name:dirty,status:'ACTIVE'};state.role='STUDENT';state.data={students:[],slots:[{slot_id:1,team_name:dirty,period_no:1}],schedules:[{slot_id:1,schedule_id:1,student_id:'20260001',team_name:dirty,period_no:1,location:dirty,schedule_date:'2030-01-02',start_time:'10:00',end_time:'12:00',status:'ACTIVE'}]};");
const html=run('scheduleTable(state.data.schedules,false)');
assert.doesNotMatch(html,/<img/);
assert.match(html,/&lt;img/);
run("action('leave',1)");
assert.doesNotMatch(element('#action-dialog').innerHTML,/<img/);
assert.match(element('#action-dialog').innerHTML,/&lt;img/);
""")

    def test_audit_detail_preserves_zero_scores_and_zero_minutes(self):
        self.js(r"""
run("state.data={admins:[],logs:[{log_id:1,operation_type:'RECORD_ATTENDANCE',admin_id:1,operation_time:'2026-09-25T12:00:00',before_value:null,after_value:{credit_after:0,service_minutes:0}}]};action('log-detail',1);");
const html=element('#action-dialog').innerHTML;
assert.match(html,/<dt>变化后信用分<\/dt><dd>0<\/dd>/);
assert.match(html,/<dt>服务分钟数<\/dt><dd>0<\/dd>/);
""")


if __name__ == '__main__':
    unittest.main(verbosity=2)
