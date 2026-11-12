'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label = {ARCHIVED:'已归档',ACTIVE:'有效',DISABLED:'已停用',QUIT:'已退队',CANCELLED:'已取消',COMPLETED:'已完成',PENDING:'待处理',FIRST_APPROVED:'待审核',OPEN:'进行中',CLOSED:'已结束',APPROVED:'已通过',REJECTED:'已驳回',NORMAL:'正常出勤',LATE:'迟到',ABSENT:'缺勤',LEAVE:'请假',VALID:'有效',VOID:'已作废',RETIRED:'历史版本',SUPER:'超级管理员',STUDENT:'志愿者'};
const roleName = r => ({SUPER:'超级管理员',NORMAL:'普通管理员',STUDENT:'志愿者'}[r] || '用户');
const operationNames = {INCREASE_FIXED_HOURS:'时段管理员上调时长',APPOINT_LEADER:'任命范围负责人',WITHDRAWAL_FIRST:'退队审核（历史）',CORRECT_ATTENDANCE:"考勤改判与信用冲正",SET_STUDENT_CREDIT:"超级管理员调整信用分",SAVE_SEMESTER:'设置学期',SET_CALENDAR:'设置停工或调休',SYNC_SEMESTER:'核对学期排班',AUTO_WEEKLY_SETTLEMENT:'系统按周结算',IMPORT_ROSTER:'导入队员名单',CONFIGURE_SLOT:'设置班次负责人和建议人数',SET_MEMBERSHIPS:'设置队员归属',REMOVE_SLOT_MEMBER:'移出班次队员',SET_GROUP_MEMBER:'调整小组成员',CREATE_STUDENT:'新增志愿者',CREATE_ADMIN:'新增管理员',CREATE_SLOT:'新增服务班次',CREATE_SCHEDULE:'建立排班',CANCEL_SCHEDULE:'取消排班',APPROVE_LEAVE:'审批请假',TRANSFER_REVIEW:'换班审核',TRANSFER_FIRST:'换班审核（历史）',TRANSFER_FINAL:'换班审核（历史）',APPROVE_WITHDRAWAL:'审批退队',RECORD_ATTENDANCE:'登记考勤',REVISE_HOURS:'修正服务时长',SET_CREDIT_RULE:'修改信用规则'};
const fieldNames = {slots:'归属时段',refunded_score:'退还的实际扣分',revision:'考勤版本',credit_version:'信用版本',student_id:'学号',admin_id:'管理员编号',slot_id:'班次编号',schedule_id:'排班编号',attendance_id:'考勤编号',leave_id:'请假编号',transfer_id:'换班编号',withdrawal_id:'退队编号',record_id:'服务记录编号',rule_id:'规则编号',credit_log_id:'流水编号',name:'姓名',college:'学院',phone:'联系电话',credit_score:'信用分',status:'状态',reason:'原因',team_name:'分队名称',period_no:'时段编号',start_time:'开始时间',end_time:'结束时间',schedule_date:'服务日期',create_time:'创建时间',service_minutes:'服务分钟数',minutes:'服务分钟数',credit_before:'变化前信用分',credit_after:'变化后信用分',cancelled_schedules:'取消的排班',account:'登录账号',role:'角色',version:'规则版本',deduct_score:'规则扣分',record_status:'记录状态',attendance_status:'考勤状态',student_status:'志愿者状态',date:'日期',apply_time:'申请时间',approve_admin_id:'审核管理员',approve_status:'审核状态',approve_time:'审核时间',new_slot_id:'目标班次编号',final_admin_id:'审核人编号',final_status:'审核状态',final_time:'审核时间',active_marker:'有效标记',manager_admin_id:'班次负责人编号',need_num:'建议人数',service_date:'服务日期',violation_type:'违规类型',create_admin_id:'创建管理员'};
const app = $('#app');
const dialog = $('#action-dialog');
const state = {token:sessionStorage.getItem('volunteer_token'),me:null,role:null,capabilities:null,scope:null,page:'overview',tab:'',data:{},dataErrors:{},search:'',status:'',week:'current',scheduleView:'todo',attendanceFilter:'',searchBefore:null,selectedStudent:'',creditStudent:'',from:'',to:'',rosterQuery:'',adminQuery:'',inboxCategory:'',sequence:0,refreshSequence:0,sessionVersion:0,loading:false,refreshError:'',collapsedScheduleGroups:new Set(),hoursMode:'collections'};
let modalSubmit = null;
let previousFocus = null;
let modalVersion = 0;
let modalBusy = false;
let filePickerArmed = 0;
let filePickerCloseGuard = 0;
const nav = [
  // === 工作台 ===
  ['overview','工作概览',['SUPER','NORMAL','STUDENT']],
  ['inbox','收件箱',['SUPER','NORMAL','STUDENT']],
  // === 排班服务（固定业务）===
  ['semesters','学期与日历',['SUPER','NORMAL','STUDENT']],
  ['schedules','排班与考勤',['SUPER','NORMAL','STUDENT']],
  ['applications','申请与审批',['SUPER','NORMAL','STUDENT']],
  // === 时长与信用 ===
  ['collections','时长归集',['SUPER','NORMAL','STUDENT']],
  ['hours','服务时长',['SUPER','NORMAL','STUDENT']],
  ['credit','信用管理',['SUPER','NORMAL','STUDENT']],
  // === 队员与业务 ===
  ['basics','队员资料',['SUPER']],
  ['businesses','业务管理',['SUPER','NORMAL']], // 包含班次、分队负责人和小组
  ['members','本时段队员',['NORMAL']],
  // === 操作日志（独立）===
  ['logs','操作日志',['SUPER']]
];
function applyIdentity(me){
  state.me=me||null;
  state.role=me?.role||'STUDENT';
  state.capabilities=Array.isArray(me?.capabilities)?me.capabilities.slice():null;
  state.scope=me?.scope||null;
}
function hasCapability(page){
  if(Array.isArray(state.capabilities)&&state.capabilities.length)return state.capabilities.includes(page);
  const item=nav.find(n=>n[0]===page);
  return Boolean(item&&item[2].includes(state.role));
}
function navAvailable(){
  return nav.filter(n=>hasCapability(n[0]));
}
const navLabels={STUDENT:{overview:'工作概览',schedules:'我的排班',applications:'我的申请',collections:'我的征集',hours:'我的时长',credit:'我的信用'}};
function navLabel(item){
  if(!item)return '工作概览';
  return navLabels[state.role]?.[item[0]]||item[1];
}

const empty = (title, text) => `<div class="empty"><div class="empty-symbol" aria-hidden="true">${uiIcon('inbox')}</div><h3>${esc(title)}</h3>${text?`<p>${esc(text)}</p>`:''}</div>`;
const badge = (value, override) => `<span class="badge ${['ACTIVE','APPROVED','NORMAL','VALID'].includes(value)?'good':['REJECTED','DISABLED','ABSENT','LATE'].includes(value)?'warning':['PENDING','FIRST_APPROVED'].includes(value)?'pending':''}">${esc(override || label[value] || value || '未登记')}</span>`;
const fmtDate = value => value ? String(value).replace('T',' ').slice(0,16) : '未记录';
const hourText = value => `${Number((Number(value || 0)/60).toFixed(2))} 小时`;
const getDate = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const rowsOf = (arr, key, value) => (arr||[]).find(r => String(r[key]) === String(value));
function studentName(id) { const scheduled=rowsOf(state.data.schedules,'student_id',id);if(scheduled?.student_name)return scheduled.student_name;const s=rowsOf(state.data.students,'student_id',id);return s?s.name:(String(id)===String(state.me?.student_id)?state.me.name:id); }
function slotLabel(s) {
 if (!s) return '';
 const name = String(s.team_name || '').trim();
 const legacy = name.match(/^周([一二三四五六日天])-([一二三四五六七八九十]+)时段$/);
 if (legacy) {
  const digits = { '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10 };
  return `周${legacy[1]}第${s.period_no || digits[legacy[2]] || legacy[2]}时段`;
 }
 if (state.role === 'STUDENT' || s.weekday || ['WEEKLY', 'EVENT'].includes(s.schedule_kind) || name.includes('第')) return name;
 return `${name} · 第 ${s.period_no} 时段`;
}
function slotName(id) { const s=rowsOf(state.data.slots,'slot_id',id); if(!s)return `班次 ${id}`; return slotLabel(s); }
function adminName(id) {if(id===null||id===undefined)return '待分配';const a=rowsOf(state.data.admins,'admin_id',id);return a?a.name:`管理员 ${id}`;}
function tableColumnAlign(header,index,total){
 if(index===total-1&&['操作','设置'].includes(header))return 'right';
 if(/(姓名|学号|队员|志愿者|申请人|操作人|人员|负责人|业务|班次|小组|事项|原因|说明|内容|通知|来源|范围|位置|反馈|归属)/.test(header))return 'left';
 if(/(人数|时长|分钟|小时|信用分|分数|扣分|变化|变动|数量|条数|上限|容量|序号|行号|导入|跳过|版本)/.test(header))return 'right';
 if(/(状态|类型|角色|日期|时间|周次|结果|进度|选择)/.test(header))return 'center';
 return 'left';
}
function alignTableRow(row,aligns){
 let i=0;
 return row.replace(/<td(\s[^>]*)?>/g,(full,attrs='')=>{
  const align=aligns[i++];
  return align&&align!=='left'?`<td${attrs} data-align="${align}">`:full;
 });
}
function tableColumnWidth(header,index,total){
 if(index===total-1&&['操作','设置'].includes(header))return null;
 if(/选择/.test(header))return '46px';
 if(/(姓名|队员|志愿者|申请人|操作人|负责人)/.test(header))return '110px';
 if(/学号/.test(header))return '150px';
 if(/(登录账号|账号)/.test(header))return '140px';
 if(/(日期|时间)/.test(header))return '110px';
 if(/(原因|说明|内容|事项|反馈|通知|来源|范围|问题|处理)/.test(header))return null;
 if(/(状态|类型|角色|进度)/.test(header))return '90px';
 if(/(人数|时长|分数|上限|容量|次数|版本|标准)/.test(header))return '84px';
 if(/(班次|时段|业务|小组)/.test(header))return '140px';
 return null;
}
function table(headers, rows, blank='暂无记录', text='记录生成后会显示在这里。', options={}) {
 if(!rows.length)return empty(blank,text);
 const actionCol=['操作','设置'].includes(headers[headers.length-1]);
 const aligns=headers.map((h,i)=>options.aligns&&options.aligns[i]?options.aligns[i]:tableColumnAlign(h,i,headers.length));
 const widths=options.widths||headers.map((h,i)=>tableColumnWidth(h,i,headers.length));
 const cols=widths.some(Boolean)?`<colgroup>${headers.map((_,i)=>widths[i]?`<col style="width:${widths[i]}">`:'<col>').join('')}</colgroup>`:'';
 const cls=[actionCol?'has-actions':'',options.dense?'compact-table':''].filter(Boolean).join(' ');
 const head=headers.map(x=>`<th scope="col">${esc(x)}</th>`).join('');
 return `<div class="table-wrap"><table${cls?` class="${cls}"`:''}>${cols}<thead><tr>${head}</tr></thead><tbody>${rows.map(r=>alignTableRow(r,aligns)).join('')}</tbody></table></div>`;
}
function tabs(items,current){return `<div class="tabs" role="tablist" aria-label="内容分类">${items.map(([v,t])=>`<button type="button" class="tab ${current===v?'active':''}" role="tab" aria-selected="${current===v}" data-tab="${v}">${t}</button>`).join('')}</div>`;}
function successBar(text){const previous=document.querySelector('.success-bar');if(previous)previous.remove();const bar=document.createElement('div');bar.className='success-bar';bar.setAttribute('role','status');bar.innerHTML=`${uiIcon('check-circle')}<span>${esc(text)}</span>`;document.body.append(bar);setTimeout(()=>bar.remove(),4500);}
function notify(text,error=false){if(!error&&typeof text==='string'&&text.indexOf('密码已更新')===0){successBar(text);return;}const n=document.createElement('div');n.className='toast'+(error?' error':'');n.textContent=text;$('#notifications').append(n);setTimeout(()=>n.remove(),5000);}
function setTheme(theme){if(theme)document.documentElement.dataset.theme=theme;else delete document.documentElement.dataset.theme;}
async function request(path,options={}) {
  const token=state.token;const sessionVersion=state.sessionVersion;
  const headers = {'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})};
  let response;
  try {response=await fetch(path,{...options,headers:{...headers,...options.headers},signal:AbortSignal.timeout((['/students/import','/member-imports'].includes(path)||path.endsWith('/approve-batch')||path.includes('/revert'))?300000:15000)});}
  catch {throw new Error('连接暂时中断，请检查本机服务后重试。');}
  const data=await response.json().catch(()=>({detail:'服务器未返回有效结果，请稍后重试。'}));
  if(!response.ok){
    let message=typeof data.detail==='string'?data.detail:'请检查填写内容后重试。';
    if(response.status===401&&path!=='/auth/login'){
      if(token===state.token&&sessionVersion===state.sessionVersion)signOut(false);
      message='登录已过期，请重新登录。';
    }
    throw new Error(message);
  }
  return data;
}
const send=(path,body,method='POST')=>request(path,{method,body:JSON.stringify(body)});
function signOut(show=true){state.inboxSelected=new Set();state.collectionSelections=new Map();state.token=null;sessionStorage.removeItem('volunteer_token');state.me=null;state.role=null;state.capabilities=null;state.scope=null;state.data={};state.dataErrors={};state.loading=false;state.refreshError='';state.sequence++;state.refreshSequence++;state.sessionVersion++;state.selectedStudent='';state.studentQuery='';state.from='';state.to='';closeDialog(true);loginView();if(show)notify('已退出登录。');}
async function loadData(role=state.role){
 // 只请求当前身份有能力读取的接口；单个接口失败不再拖垮整站。
 const tasks=[['inbox','/inbox?limit=1']];
 if(hasCapability('semesters')||hasCapability('schedules'))tasks.push(['semesters','/semesters']);
 if(hasCapability('schedules'))tasks.push(['schedules','/schedules']);
 if(hasCapability('applications')){tasks.push(['leave','/applications/leave'],['transfer','/applications/transfer'],['withdrawal','/applications/withdrawal']);}
 if(hasCapability('businesses'))tasks.push(['businesses','/businesses'],['groups','/business-groups']);
 if(hasCapability('basics')||hasCapability('members'))tasks.push(['students','/students']);
 if(hasCapability('basics'))tasks.push(['admins','/admins']);
 if(role!=='STUDENT'&&(hasCapability('basics')||hasCapability('members')||hasCapability('businesses')))tasks.push(['affiliationCatalog','/affiliation-catalog']);
 if(role!=='STUDENT'&&(hasCapability('schedules')||hasCapability('businesses')||hasCapability('members')))tasks.push(['slots','/slots']);
 if(role==='STUDENT')tasks.push(['hours','/hours'],['credit','/credit'],['memberships','/my-fixed-slots']);
 const data={};
 const errors={};
 const results=await Promise.allSettled(tasks.map(async([key,path])=>{
  try{data[key]=await request(path);return {key,ok:true};}
  catch(error){errors[key]=error.message;return {key,ok:false};}
 }));
 if(!results.some(result=>result.value?.ok)&&tasks.length){
  const first=errors[Object.keys(errors)[0]]||'暂时无法读取数据';
  throw new Error(first);
 }
 // 页面代码按数组/对象消费数据，失败项给空值，由页面级错误提示解释。
 const defaults={inbox:{items:[],unread_count:0},semesters:[],schedules:[],leave:[],transfer:[],withdrawal:[],
  businesses:[],groups:[],students:[],admins:[],slots:[],memberships:[],affiliationCatalog:{slots:[],businesses:[],groups:[]},hours:{records:[],total_minutes:0,total_hours:0},
  credit:{credit_score:0,status:'ACTIVE',records:[],logs:[]}};
 for(const [key,value] of Object.entries(defaults))if(data[key]===undefined)data[key]=value;
 if(role==='STUDENT')data.slots=[...new Map([...(data.memberships||[]),...(data.schedules||[]),...(data.hours?.records||[])].filter(s=>s&&s.slot_id).map(s=>[s.slot_id,s])).values()];
 data.errors=errors;
 data.loadedAt=new Date().toISOString();
 return data;
}
async function refresh(){
 if(!state.me||!$('#main'))return;
 // Loading the shared data must survive navigation; page-specific queries use sequence.
 const seq=++state.refreshSequence;const session=state.sessionVersion;
 state.sequence++;state.loading=true;state.refreshError='';state.dataErrors={};renderPage();
 const current=()=>seq===state.refreshSequence&&session===state.sessionVersion&&state.me;
 try{
  const me=await request('/auth/me');if(!current())return;
  const previousRole=state.role;applyIdentity(me);
  const data=await loadData(state.role);if(!current())return;
  const roleChanged=previousRole!==state.role;
  state.data=data;state.dataErrors=data.errors||{};state.loading=false;
  if(roleChanged)buildShell();
  renderPage();
 }catch(e){if(!current())return;state.loading=false;state.refreshError=e.message;renderPage();}
}
function navigate(page){closeDialog(true);if(state.page!==page){state.inboxSelected=new Set();state.collectionSelections=new Map();if(page==='basics'||page==='members'){state.rosterQuery='';state.adminQuery='';}}if(page!=='collections'||state.page===page)state.hoursMode='collections';if(page==='schedules'&&state.page!==page){state.scheduleView='todo';state.week='current';state.attendanceFilter='';state.searchBefore=null;}state.page=page;state.tab='';state.search='';state.status='';state.sequence++;document.querySelector('.workspace')?.classList.remove('menu-open');scrollToTop();updateNavigation();renderPage();}
function scrollToTop(){const body=document.querySelector('.workspace-body');if(body)body.scrollTo({top:0});window.scrollTo({top:0});}
function heading(title,text,button='',variant=''){return `<div class="page-heading${variant?' '+variant:''}"><div><h1>${esc(title)}</h1></div>${button?`<div class="page-actions">${button}</div>`:''}</div>`;}
function canFuture(r){return r.status==='ACTIVE'&&new Date(`${r.schedule_date}T${r.start_time}:00+08:00`)>new Date();}
function isEnded(r){if(r.schedule_kind==='WEEKLY'){const day=new Date(`${r.schedule_date}T00:00:00+08:00`);day.setUTCDate(day.getUTCDate()-6);return day<=new Date();}return new Date(`${r.schedule_date}T${r.end_time}:00+08:00`)<=new Date();}
function actionable(a,kind){if(a&&typeof a.can_review==='boolean')return a.can_review;if(kind==='transfer'&&!a.old_slot_id)return false;if(kind==='leave')return state.role==='NORMAL'&&a.approve_status==='PENDING';if(kind==='withdrawal')return state.role==='SUPER'&&a.approve_status==='PENDING'&&!a.requires_first;return state.role==='NORMAL'&&a.final_status==='PENDING';}
function appStatus(a,kind){const text={PENDING:'待审核',APPROVED:'已通过',REJECTED:'已驳回',CANCELLED:'已取消'};if(kind!=='transfer')return[a.approve_status,text[a.approve_status]||label[a.approve_status]];const status=a.final_status;if(status&&status!=='PENDING')return[status,text[status]||label[status]];return['PENDING','待审核'];}
function renderPage(){
 if(!state.me)return;
 if(!navAvailable().some(n=>n[0]===state.page))state.page='overview';
 const title=navLabel(nav.find(x=>x[0]===state.page));
 $('#breadcrumb-title').textContent=title;
 document.title=`${title} · 图书馆志愿服务`;
 document.querySelectorAll('[data-page]').forEach(el=>{el.classList.toggle('active',el.dataset.page===state.page);if(el.dataset.page===state.page)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
 if(state.refreshError){$('#main').innerHTML=`<div class="panel"><div class="empty"><h3>暂时无法读取数据</h3><p>${esc(state.refreshError)}</p><button class="btn" data-action="refresh">重新加载</button></div></div>`;return;}
 if(state.loading||!Array.isArray(state.data.schedules)){$('#main').innerHTML='<div class="loading" role="status">正在读取最新记录…</div>';return;}
 const pageErrorKey={inbox:'inbox',businesses:'businesses',semesters:'semesters',schedules:'schedules',applications:'leave',hours:'hours',credit:'credit',basics:'students',members:'students'}[state.page];
 if(pageErrorKey&&state.dataErrors?.[pageErrorKey]){
  const raw=String(state.dataErrors[pageErrorKey]);
  const permission=raw.includes('没有执行此操作')||raw.includes('权限');
  $('#main').innerHTML=`<div class="panel"><div class="empty"><h3>${permission?'当前账号没有访问该模块的权限':'暂时无法读取数据'}</h3><p>${esc(permission?'请联系超级管理员确认你的管理范围。':raw)}</p>${permission?'<button class="btn" data-page="overview">回到工作概览</button>':'<button class="btn" data-action="refresh">重新加载</button>'}</div></div>`;
  return;
 }
 updateInboxBadge();
 const pages={inbox:inboxPage,businesses:businessesPage,collections:collectionsPage,specialty:specialtyPage,semesters:semesterPage,overview:overview,schedules:schedulesPage,applications:applicationsPage,hours:hoursPage,credit:creditPage,basics:rosterBasicsPage,logs:logsPage,members:membersPage};
 (pages[state.page]||overview)();
 fitFilterSelects();
}
function overview(){
 const d=state.data;const today=getDate();
 const pendingItems=overviewPendingItems(d);
 const pending=pendingItems.length;
 const upcoming=d.schedules.filter(r=>canFuture(r)).sort((a,b)=>(a.schedule_date+a.start_time).localeCompare(b.schedule_date+b.start_time));
 const noScope=state.role==='NORMAL'&&Array.isArray(state.capabilities)&&!state.capabilities.includes('schedules')&&!state.capabilities.includes('businesses');
 const scopeNotice=noScope?'<section class="panel"><div class="empty"><h3>尚未分配管理范围</h3><p>当前账号还没有被分配服务时段或业务。请联系超级管理员分配范围后，再使用排班、申请和队员相关功能。</p></div></section>':'';
 const scheduleJump=hasCapability('schedules')?'<button class="text-button" data-page="schedules">查看全部 →</button>':'';
 const applicationJump=hasCapability('applications')?`<button class="text-button" data-page="applications">进入申请${state.role==='STUDENT'?'记录':'管理'} →</button>`:'';
 const metrics=state.role==='STUDENT'?[['累计服务时长',Number((d.hours.total_minutes/60).toFixed(2)),'小时','按全部有效服务记录汇总'],['当前信用分',d.credit.credit_score,'分',label[d.credit.status]],['待处理申请',pending,'项','请假、换班和退队'],['每周固定班次',(d.memberships||[]).length,'个','可申请长期调整时段']]:[['今日排班',d.schedules.filter(r=>r.schedule_date===today&&r.status!=='CANCELLED').length,'人次','当前权限范围内的安排'],['待处理申请',pending,'项','需要你审批或确认'],['待登记考勤',d.schedules.filter(r=>r.status==='ACTIVE'&&isEnded(r)).length,'次','已结束但尚未登记'],[state.role==='SUPER'?'在队志愿者':'负责服务班次',state.role==='SUPER'?d.students.filter(s=>s.status==='ACTIVE').length:(state.scope?.slot_count||d.slots.length),state.role==='SUPER'?'人':'个',state.role==='SUPER'?'当前正常参与服务':'仅显示你负责的班次']];
 const metricsHtml=`<section class="metrics" aria-label="工作概览统计">${metrics.map(([l,v,u,f])=>{const ic={累计服务时长:'clock',当前信用分:'shield',待处理申请:'check',每周固定班次:'calendar',今日排班:'calendar',待登记考勤:'clock',在队志愿者:'users',负责服务班次:'calendar'}[l]||'info';const accent=l==='累计服务时长'||l==='在队志愿者';return `<div class="metric"><div class="metric-label">${uiIcon(ic)}${l}</div><div class="metric-value${accent?' accent':''}">${esc(v)}<small>${u}</small></div></div>`;}).join('')}</section>`;
 const todoTitle=state.role==='STUDENT'?'申请进度':'今日待办';
 const todoRows=overviewTaskRows(pendingItems);
 const todoPanel=`<section class="panel overview-panel"><header class="panel-header"><div><h2>${todoTitle}</h2></div>${applicationJump}</header><div class="overview-row-list">${todoRows}</div></section>`;
 const serviceGroups=overviewServiceGroups(upcoming);
 const serviceRows=overviewServiceRows(serviceGroups.slice(0,3));
 const servicePanel=`<section class="panel overview-panel"><header class="panel-header"><div><h2>接下来的服务</h2></div>${scheduleJump}</header><div class="overview-service-list">${serviceRows}</div></section>`;
 const quickLinks=overviewQuickLinks();
 const quickPanel=quickLinks?`<section class="panel overview-panel"><header class="panel-header"><h2>快捷入口</h2></header><div class="overview-shortcuts">${quickLinks}</div></section>`:'';
 const fixedPanel=myFixedSlotsPanel();
 const welcome=`<section class="welcome"><div><div class="eyebrow">${roleName(state.role)}工作台</div><h1>${esc(state.me.name)}，欢迎回来。</h1></div><div class="date-stamp"><strong>${today.slice(5).replace('-',' / ')}</strong>${today.slice(0,4)} 年 · ${new Intl.DateTimeFormat('zh-CN',{weekday:'long',timeZone:'Asia/Shanghai'}).format(new Date())}</div></section>`;
 $('#main').innerHTML=`<div class="overview-page">${welcome}${scopeNotice}${metricsHtml}${todoPanel}${fixedPanel}${servicePanel}${quickPanel}</div>`;
}
function overviewPendingItems(d){
 const kinds=[['leave','请假'],['transfer','换班'],['withdrawal','退队']];
 return kinds.flatMap(([kind,title])=>(d[kind]||[]).filter(a=>state.role==='STUDENT'?appStatus(a,kind)[0]==='PENDING':actionable(a,kind)).map(a=>({kind,title,a})));
}
function overviewTaskRows(items){
 const rows=[];
 if(state.role==='STUDENT'){
  if(items.length)rows.push(...items.slice(0,3).map(({kind,title,a})=>`<button class="overview-task" data-page="applications"><span class="overview-task-kind">申请</span><span class="overview-task-main"><strong>${esc(title)}</strong><small>${esc(fmtDate(a.apply_time))} · 待审核</small></span><span class="overview-task-status">查看 →</span></button>`));
  return rows.length?rows.join(''):'<div class="overview-empty">暂无进行中的申请</div>';
 }
 if(items.length){
  rows.push(...items.slice(0,2).map(({kind,title,a})=>`<button class="overview-task" data-page="applications"><span class="overview-task-kind">申请审核</span><span class="overview-task-main"><strong>${esc(studentName(a.student_id))}</strong><small>${esc(title)} · ${esc(fmtDate(a.apply_time))}</small></span><span class="overview-task-action">处理 →</span></button>`));
 }
 if(hasCapability('schedules')){
  const attendance=state.data.schedules.filter(r=>r.status==='ACTIVE'&&isEnded(r)).length;
  if(attendance)rows.push(`<button class="overview-task" data-page="schedules"><span class="overview-task-kind">考勤登记</span><span class="overview-task-main"><strong>${attendance} 次待登记</strong><small>已结束但尚未登记</small></span><span class="overview-task-action">去登记 →</span></button>`);
 }
 return rows.length?rows.join(''):'<div class="overview-empty">暂无待处理事项</div>';
}
function overviewServiceGroups(records){
 const groups=[],seen=new Map();
 for(const r of records){
  const key=[r.schedule_date,r.slot_id,r.start_time||'',r.end_time||''].join('|');
  let g=seen.get(key);
  if(!g){g={date:r.schedule_date,slot_id:r.slot_id,start:r.start_time,end:r.end_time,week_no:r.week_no,records:[]};seen.set(key,g);groups.push(g);}
  g.records.push(r);
 }
 return groups;
}
function overviewServiceRows(groups){
 if(!groups.length)return '<div class="overview-empty">近期没有服务安排</div>';
 return groups.map(g=>{
  const weekday=new Intl.DateTimeFormat('zh-CN',{weekday:'short',timeZone:'Asia/Shanghai'}).format(new Date(`${g.date}T00:00:00+08:00`));
  const range=g.start&&g.end?`${String(g.start).slice(0,5)}–${String(g.end).slice(0,5)}`:'每周一次';
  const names=g.records.map(r=>studentName(r.student_id));
  const shown=names.length>3?names.slice(0,3).join('、')+' 等':names.join('、');
  const week=g.week_no?`第 ${esc(g.week_no)} 周 · `:'';
  const slot=rowsOf(state.data.slots,'slot_id',g.slot_id);
  const label=slotName(g.slot_id);
  const title=slot?.business_name&&!label.includes(slot.business_name)?`${slot.business_name} · ${label}`:label;
  return `<div class="overview-service"><div class="overview-service-when"><strong>${esc(weekday)} · ${esc(String(g.date).slice(5))}</strong><span>${week}${esc(range)}</span></div><div class="overview-service-body"><div class="overview-service-title"><strong>${esc(title)}</strong><span>${g.records.length} 人</span></div><div class="overview-service-names">${esc(shown)}</div></div></div>`;
 }).join('');
}
function overviewQuickLinks(){
 const links=state.role==='STUDENT'
  ?[['申请请假或换班','schedules'],['查看服务时长','hours']]
  :[hasCapability('schedules')?['排班与考勤','schedules']:null,hasCapability('applications')?['处理申请','applications']:null,hasCapability('businesses')?['查看服务班次','businesses']:null,hasCapability('members')?['查看队员资料','members']:null];
 return links.filter(Boolean).map(([label,page])=>`<button class="overview-shortcut" data-page="${page}">${esc(label)}<span aria-hidden="true">→</span></button>`).join('');
}
function scheduleTable(records,actions=true){return table(['服务日期','志愿者','服务班次','状态',...(actions?['操作']:[])],records.map(r=>`<tr><td><strong>${esc(r.schedule_date)}</strong><small>${r.week_no?`第 ${r.week_no} 周 · `:''}${r.schedule_kind==='WEEKLY'?'周日为统计归属日':r.schedule_kind==='EVENT'?'非固定服务':esc(r.start_time)+' 至 '+esc(r.end_time)}</small></td><td>${esc(studentName(r.student_id))}<small>${esc(r.student_id)}</small></td><td><strong>${esc(slotName(r.slot_id))}</strong></td><td>${badge(r.attendance_status||r.status)}${r.attendance_source==='AUTO_WEEKLY'?'<small>按周自动结算</small>':''}${r.leave_approved&&!r.attendance_status?'<small>请假已获批</small>':''}</td>${actions?`<td><div class="row-actions">${scheduleActions(r)}</div></td>`:''}</tr>`),'暂无具体日期排班','设置学期后按固定时段生成，用于请假及考勤。');}
function scheduleActions(r){
 if(r.schedule_kind==='EVENT')return state.role==='SUPER'&&r.status==='ACTIVE'&&r.source_key?.startsWith('manual:')&&r.schedule_date<=getDate()?`<button class="text-button" data-action="event-confirm" data-id="${r.schedule_id}">认定本次时长</button>`:'<span class="muted">已认定记录可在服务时长中修正</span>';
 if(state.role==='STUDENT')return canFuture(r)&&state.me.status==='ACTIVE'?`<button class="text-button" data-action="leave" data-id="${r.schedule_id}">请假</button>`:'<span class="muted">暂无可用操作</span>';
 let buttons=r.schedule_kind==='WEEKLY'&&r.status==='ACTIVE'&&r.schedule_date<=new Date(Date.now()+6*86400000).toISOString().slice(0,10)?`<button class="text-button" data-action="garden-confirm" data-id="${r.schedule_id}">确认本周服务</button>`:'';
 if(state.role==='NORMAL'&&r.schedule_kind==='FIXED'&&['ACTIVE','COMPLETED'].includes(r.status)&&isEnded(r)&&!r.leave_approved&&(!r.attendance_status||['NORMAL','LATE'].includes(r.attendance_status)))buttons+=`<button class="text-button" data-action="increase-fixed-hours" data-id="${r.schedule_id}">上调时长</button>`;
 if(['NORMAL','SUPER'].includes(state.role)&&r.status==='COMPLETED'&&r.attendance_status)buttons+=`<button class="text-button" data-action="attendance-correct" data-id="${r.schedule_id}">考勤改判</button>`;
 if(['NORMAL','SUPER'].includes(state.role)&&(r.status==='ACTIVE'||r.attendance_source==='AUTO_WEEKLY'&&r.attendance_status==='NORMAL')&&isEnded(r))buttons+=`<button class="text-button" data-action="attendance" data-id="${r.schedule_id}">登记考勤</button>`;
 if(canFuture(r))buttons+=`<button class="text-button" data-action="cancel" data-id="${r.schedule_id}">取消排班</button>`;
 return buttons||`<span class="muted">${r.status==='COMPLETED'?'已结算':r.status==='CANCELLED'?'已取消':'待服务结束'}</span>`;
}
function scheduleWeekOf(r,term){
 if(r.week_no)return Number(r.week_no);
 if(!term||!r.schedule_date)return null;
 const diff=(semParse(r.schedule_date)-semParse(semMonday(term.start_date)))/86400000;
 return Math.max(1,Math.min(Number(term.end_week)||1,Math.floor(diff/7)+1));
}
function scheduleWeekRange(term,week){
 const monday=semAdd(semMonday(term.start_date),(Math.max(1,week)-1)*7);
 return {monday,sunday:semAdd(monday,6)};
}
function schedulePending(r){return r.status!=='CANCELLED'&&!r.leave_approved&&!r.attendance_status&&isEnded(r);}
function scheduleAnomaly(r){return r.status!=='CANCELLED'&&['LATE','ABSENT'].includes(r.attendance_status);}
function scheduleAttendance(r){
 if(r.status==='CANCELLED')return {text:'已取消',variant:''};
 if(!isEnded(r))return {text:'未结束',variant:'pending'};
 if(!r.attendance_status&&r.leave_approved)return {text:'请假',variant:'pending'};
 if(!r.attendance_status)return {text:'待登记',variant:'warning'};
 const text=label[r.attendance_status]||r.attendance_status;
 return {text,variant:['LATE','ABSENT'].includes(r.attendance_status)?'warning':r.attendance_status==='LEAVE'?'pending':'good'};
}
function scheduleClock(){
 const stamp=state.data.loadedAt?new Date(state.data.loadedAt):new Date();
 return new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'Asia/Shanghai'}).format(stamp);
}
function scheduleAgeDays(r){
 const end=r.end_time?`${r.schedule_date}T${r.end_time}:00+08:00`:`${r.schedule_date}T23:59:00+08:00`;
 return Math.max(0,Math.floor((Date.now()-new Date(end).getTime())/86400000));
}
function scheduleWeekBadge(term,r){
 const week=scheduleWeekOf(r,term);return week?`第 ${week} 周`:'';
}
function scheduleRowActions(r){
 if(state.role==='STUDENT')return canFuture(r)&&state.me.status==='ACTIVE'?`<button class="btn small" data-action="leave" data-id="${r.schedule_id}">请假</button>`:'<span class="muted">暂无可用操作</span>';
 const primary=[];const menu=[];
 if((r.status==='ACTIVE'||r.attendance_source==='AUTO_WEEKLY'&&r.attendance_status==='NORMAL')&&isEnded(r)&&!r.leave_approved)primary.push(`<button class="btn primary small" data-action="attendance" data-id="${r.schedule_id}">登记考勤</button>`);
 if(r.status==='COMPLETED'&&r.attendance_status)menu.push(`<button type="button" class="text-button" data-action="attendance-correct" data-id="${r.schedule_id}">考勤改判</button>`);
 if(state.role==='NORMAL'&&r.schedule_kind==='FIXED'&&['ACTIVE','COMPLETED'].includes(r.status)&&isEnded(r)&&!r.leave_approved&&(!r.attendance_status||['NORMAL','LATE'].includes(r.attendance_status)))menu.push(`<button type="button" class="text-button" data-action="increase-fixed-hours" data-id="${r.schedule_id}">上调时长</button>`);
 if(r.schedule_kind==='WEEKLY'&&r.status==='ACTIVE'&&r.schedule_date<=new Date(Date.now()+6*86400000).toISOString().slice(0,10))menu.push(`<button type="button" class="text-button" data-action="garden-confirm" data-id="${r.schedule_id}">确认本周服务</button>`);
 if(canFuture(r))menu.push(`<button type="button" class="text-button" data-action="cancel" data-id="${r.schedule_id}">取消排班</button>`);
 const more=menu.length?`<details class="row-menu"><summary aria-label="更多操作" title="更多操作">…</summary><div class="row-menu-list">${menu.join('')}</div></details>`:'';
 return `${primary.join('')}${more}`||'<span class="muted">待处理</span>';
}
function scheduleGroupedTable(records,{term,unregistered=false}={}){
 if(!records.length)return '';
 const rows=[];
 if(unregistered){
  const groups=new Map();
  for(const r of [...records].sort((a,b)=>a.schedule_date.localeCompare(b.schedule_date))){const key=String(r.slot_id);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);}
  for(const [slotId,items] of groups){
   const oldest=Math.max(...items.map(scheduleAgeDays));
   const slot=rowsOf(state.data.slots,'slot_id',Number(slotId));
   const gkey=`slot-${slotId}`,collapsed=state.collapsedScheduleGroups.has(gkey);
   rows.push(`<tr class="schedule-group-row${collapsed?' collapsed':''}" data-schedule-group="${esc(gkey)}"><td colspan="3"><button type="button" class="schedule-group-toggle" data-action="schedule-group-toggle" data-id="${esc(gkey)}" aria-expanded="${!collapsed}"><span class="schedule-group-arrow" aria-hidden="true">▾</span><span class="schedule-group-title"><strong>${esc(slotName(slotId))}</strong><small>负责人 ${esc(slot?.manager_name||adminName(slot?.manager_admin_id))} · 最早 ${oldest} 天前</small></span></button></td></tr>`);
   for(const r of items)rows.push(`<tr data-schedule-member="${esc(gkey)}"${collapsed?' hidden':''}><td><strong>${esc(r.schedule_date)}</strong><small>${esc(studentName(r.student_id))} · ${esc(r.student_id)}</small></td><td>${scheduleAttendanceBadge(r)}<small>${scheduleAgeDays(r)} 天前</small></td><td><div class="row-actions">${scheduleRowActions(r)}</div></td></tr>`);
  }
 }else{
  const groups=new Map();
  for(const r of [...records].sort((a,b)=>a.schedule_date.localeCompare(b.schedule_date)||String(a.slot_id).localeCompare(String(b.slot_id)))){
   if(!groups.has(r.schedule_date))groups.set(r.schedule_date,[]);groups.get(r.schedule_date).push(r);
  }
  for(const [date,items] of groups){
   const r=items[0],week=scheduleWeekOf(r,term);
   const gkey=`date-${date}`,collapsed=state.collapsedScheduleGroups.has(gkey);
   rows.push(`<tr class="schedule-group-row${collapsed?' collapsed':''}" data-schedule-group="${esc(gkey)}"><td colspan="3"><button type="button" class="schedule-group-toggle" data-action="schedule-group-toggle" data-id="${esc(gkey)}" aria-expanded="${!collapsed}"><span class="schedule-group-arrow" aria-hidden="true">▾</span><span class="schedule-group-title"><strong>${esc(date)} ${esc(weekdayText(semWeekday(date)))}</strong><small>${week?`第 ${week} 周 · `:''}${items.length} 条记录</small></span></button></td></tr>`);
   for(const item of items)rows.push(`<tr data-schedule-member="${esc(gkey)}"${collapsed?' hidden':''}><td><strong>${esc(studentName(item.student_id))}</strong><small>${esc(item.student_id)}</small><small class="schedule-slot-line">${esc(slotName(item.slot_id))}${item.start_time?` · ${esc(item.start_time)} 至 ${esc(item.end_time)}`:''}</small></td><td>${scheduleAttendanceBadge(item)}${item.attendance_source==='AUTO_WEEKLY'?'<small>按周自动结算</small>':item.leave_approved&&!item.attendance_status?'<small>请假已获批</small>':''}</td><td><div class="row-actions">${scheduleRowActions(item)}</div></td></tr>`);
  }
 }
 return `<div class="table-wrap"><table class="schedule-table has-actions"><thead><tr><th scope="col">${unregistered?'日期 / 志愿者':'志愿者'}</th><th scope="col">出勤</th><th scope="col">操作</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}
function scheduleAttendanceBadge(r){
 const stateText=scheduleAttendance(r);
 return `<span class="badge ${stateText.variant}">${esc(stateText.text)}</span>`;
}
function scheduleWeekNav(term,view,currentWeek){
 const base=state.week==='all'?currentWeek:Number(state.week)||currentWeek;
 if(view==='unregistered')return '<div class="week-switch"><strong>全部未登记</strong></div><button type="button" class="text-button schedule-range-link" data-action="schedule-back-weekly">返回按周视图</button>';
 if(view==='todo')return `<div class="week-switch"><button type="button" class="week-arrow" data-action="schedule-week-prev" aria-label="上一周" ${currentWeek<=1?'disabled':''}>‹</button><strong>第 ${currentWeek} 周</strong><button type="button" class="week-arrow" data-action="schedule-week-next" aria-label="下一周" ${currentWeek>=term.end_week?'disabled':''}>›</button></div><button type="button" class="text-button schedule-range-link" data-action="schedule-all">全部日期</button>`;
 return `<div class="week-switch"><button type="button" class="week-arrow" data-action="schedule-week-prev" aria-label="上一周" ${base<=1?'disabled':''}>‹</button><strong>${state.week==='all'?'全部日期':`第 ${base} 周`}</strong><button type="button" class="week-arrow" data-action="schedule-week-next" aria-label="下一周" ${base>=term.end_week?'disabled':''}>›</button></div><button type="button" class="text-button schedule-range-link" data-action="schedule-week-current">回到本周</button>`;
}
function schedulesPage(){
 const term=currentSemester();
 if(state.role==='STUDENT'){
  const own=(state.data.schedules||[]).filter(r=>r.status!=='CANCELLED').sort((a,b)=>a.schedule_date.localeCompare(b.schedule_date));
  $('#main').innerHTML=heading('我的排班','')+(term?semesterSummary(term):'')+myFixedSlotsPanel()+(term?semesterPanel(term,false,{onlyExceptions:true}):'')+`<section class="panel"><header class="panel-header"><div><h2>我的服务安排</h2></div><span class="schedule-updated">更新于 ${scheduleClock()}</span></header>${table(['服务日期','服务班次','出勤','操作'],own.map(r=>`<tr><td><strong>${esc(r.schedule_date)}</strong><small>${term?esc(scheduleWeekBadge(term,r))+' · ':''}${esc(weekdayText(semWeekday(r.schedule_date)))}</small></td><td><strong>${esc(slotName(r.slot_id))}</strong>${r.start_time?`<small>${esc(r.start_time)} 至 ${esc(r.end_time)}</small>`:''}</td><td>${scheduleAttendanceBadge(r)}</td><td>${scheduleRowActions(r)}</td></tr>`),'暂无服务安排',term?'固定班次会按学期周历生成。':'设置学期后，你的固定班次会按周生成。')}</section>`;
  return;
 }
 if(!term){
  $('#main').innerHTML=heading('排班与考勤','')+`<section class="panel">${empty('尚未设置学期',state.role==='SUPER'?'设置学期后，系统会按固定班次生成排班。':'请等待超级管理员设置本学期。')}${state.role==='SUPER'?'<div class="empty-action"><button class="btn primary" data-page="semesters">去设置学期</button></div>':''}</section>`;
  return;
 }
 const currentWeek=term.phase==='ENDED'?Number(term.end_week)||1:Math.max(1,Math.min(Number(term.end_week)||1,Number(term.current_week)||1));
 const view=state.scheduleView||'todo';
 const allSchedules=state.data.schedules||[];
 const pendingAll=allSchedules.filter(r=>schedulePending(r)&&(!r.semester_id||r.semester_id===term.semester_id));
 const thisPending=pendingAll.filter(r=>scheduleWeekOf(r,term)===currentWeek);
 const earlierPending=pendingAll.filter(r=>scheduleWeekOf(r,term)<currentWeek);
 const thisAnomalies=allSchedules.filter(r=>scheduleAnomaly(r)&&scheduleWeekOf(r,term)===currentWeek&&(!r.semester_id||r.semester_id===term.semester_id));
 const searchKey=state.search.toLocaleLowerCase();
 const matches=r=>!searchKey||`${r.student_id}${studentName(r.student_id)}${r.team_name||''}${r.schedule_date}${slotName(r.slot_id)}`.toLocaleLowerCase().includes(searchKey);
 const attendanceMatch=r=>{
  if(!state.attendanceFilter)return true;
  if(state.attendanceFilter==='PENDING')return schedulePending(r);
  if(state.attendanceFilter==='ANOMALY')return scheduleAnomaly(r);
  return r.attendance_status===state.attendanceFilter;
 };
 let records=[];
 if(view==='unregistered')records=pendingAll.filter(matches).sort((a,b)=>a.schedule_date.localeCompare(b.schedule_date));
 else if(view==='week'){
  const week=state.week==='all'?null:(Number(state.week)||currentWeek);
  records=allSchedules.filter(r=>r.status!=='CANCELLED'&&(week===null||scheduleWeekOf(r,term)===week)&&matches(r)&&attendanceMatch(r)).sort((a,b)=>a.schedule_date.localeCompare(b.schedule_date));
 }else{
  records=[...thisPending,...thisAnomalies].filter(matches).filter(attendanceMatch).sort((a,b)=>a.schedule_date.localeCompare(b.schedule_date));
 }
 const updated=`<span class="schedule-updated">更新于 ${scheduleClock()}</span>`;
 const summary=`<section class="schedule-summary"><div><span>本周待登记 <b>${thisPending.length}</b> 条</span>${earlierPending.length?`<span class="summary-sep">·</span><button type="button" class="summary-link" data-action="schedule-unregistered">更早待补 <b>${earlierPending.length}</b> 条</button>`:''}${thisAnomalies.length?`<span class="summary-sep">·</span><span class="summary-anomaly">异常 <b>${thisAnomalies.length}</b> 条</span>`:''}</div>${updated}</section>`;
 const filterOptions=view==='todo'?[['','全部待办'],['PENDING','只看待登记'],['ANOMALY','只看异常']]:[['','全部出勤'],['PENDING','待登记'],['ANOMALY','异常（迟到 / 缺勤）'],['NORMAL','正常'],['LATE','迟到'],['ABSENT','缺勤'],['LEAVE','请假']];
 const filterValue=filterOptions.some(([value])=>value===state.attendanceFilter)?state.attendanceFilter:'';
 const search=`<label class="schedule-search"><input class="control" id="search" aria-label="搜索排班" placeholder="搜索姓名、学号、分队或日期" value="${esc(state.search)}"></label>`;
 const filter=view==='unregistered'?'':`<select class="control" id="attendance-filter" aria-label="筛选出勤"><option value="">${filterOptions[0][1]}</option>${filterOptions.slice(1).map(([value,text])=>`<option value="${value}" ${filterValue===value?'selected':''}>${text}</option>`).join('')}</select>`;
 const toolbar=`<div class="schedule-toolbar">${scheduleWeekNav(term,view,currentWeek)}${search}${filter}</div>`;
 const notice=term.phase==='ENDED'?`<div class="notice">本学期已结束，默认显示第 ${currentWeek} 周。</div>`:'';
 const content=view==='unregistered'
  ? `<section class="panel"><header class="panel-header"><div><h2>全部未登记</h2><p>按日期正序，最早的在最前；按负责人 / 班次分组。</p></div><button type="button" class="text-button" data-action="schedule-back-weekly">返回按周视图</button></header>${records.length?scheduleGroupedTable(records,{term,unregistered:true}):empty('没有未登记记录','本周及更早的待登记已全部处理。')}</section>`
  : `<section class="panel">${records.length?scheduleGroupedTable(records,{term}):empty(view==='todo'?'当前没有待办':'当前筛选下没有记录',view==='todo'?'本周待登记和异常均已处理。更早的欠账请查看“全部未登记”。':'调整搜索或出勤筛选后再看。')}</section>`;
 $('#main').innerHTML=heading(state.role==='STUDENT'?'我的排班':'排班与考勤','',state.role!=='STUDENT'?'<button class="btn" data-action="schedule">例外手动排班</button>':'','schedule-page')+semesterNotice()+notice+summary+toolbar+content;
}

function applicationsPage(){
 const choices=[['leave','请假申请'],['transfer','换班申请'],['withdrawal','退队申请']];
 const kind=state.tab||'leave';const rows=state.data[kind]||[];
 $('#main').innerHTML=heading(state.role==='STUDENT'?'我的申请':'申请与审批',state.role==='STUDENT'?'申请提交后可在这里查看进度和处理结果。':'按权限查看申请；普通审核人或超级管理员一次审核即为最终结果，超管可兜底处理，结果会抄送超级管理员。',state.role==='STUDENT'&&state.me.status==='ACTIVE'?`<button class="btn primary" data-action="${kind==='withdrawal'?'withdrawal':'new-application'}">${kind==='withdrawal'?'申请退队':'提交申请'}</button>`:'')+`<div class="toolbar">${tabs(choices,kind)}<button class="text-button" data-action="refresh">刷新记录</button></div><section class="panel">${table(['申请人','申请内容','申请原因','提交时间','进度','操作'],rows.map(a=>{const [status,text]=appStatus(a,kind);const id=a[kind==='leave'?'leave_id':kind==='transfer'?'transfer_id':'withdrawal_id'];const old=a.schedule_id?rowsOf(state.data.schedules,'schedule_id',a.schedule_id):null;return `<tr><td><strong>${esc(studentName(a.student_id))}</strong><small>${esc(a.student_id)}</small></td><td class="wrap">${applicationContent(a,kind,old)}</td><td class="wrap">${esc(a.reason)}${a.review_reason?`<small>审核说明：${esc(a.review_reason)}</small>`:''}${status==='REJECTED'&&a.rejection_reason?`<small>打回原因：${esc(a.rejection_reason)}</small>`:''}${kind==='leave'?`<button class="text-button" data-action="leave-evidence" data-id="${id}">查看证明</button>`:''}</td><td>${fmtDate(a.apply_time)}</td><td>${badge(status,text)}</td><td>${actionable(a,kind)?`<button class="text-button" data-action="approve" data-kind="${kind}" data-id="${id}">审批</button>`:'<span class="muted">暂无待办</span>'}</td></tr>`;}),'暂无这类申请',state.role==='STUDENT'?'固定班次换班可点击提交申请；请假需选择具体日期排班。':'申请提交后，会根据负责范围出现在这里。')}</section>`;
}
function studentSelect(){return `<input type="search" name="student_query" id="query-student" placeholder="输入学号或姓名" value="${esc(state.studentQuery??state.selectedStudent)}" autocomplete="off" aria-describedby="student-query-help">`;}
function matchingStudents(query){
 const text=query.trim().toLocaleLowerCase();if(!text)return [];
 const students=state.data.students||[];
 const exact=students.filter(s=>String(s.student_id).toLocaleLowerCase()===text);
 return exact.length?exact:students.filter(s=>String(s.student_id).toLocaleLowerCase().includes(text)||s.name.toLocaleLowerCase().includes(text));
}
function queriedStudentLabel(){return state.role==='SUPER'?`<div class="section-footer">当前志愿者：<strong>${esc(studentName(state.selectedStudent))}</strong>（${esc(state.selectedStudent)}）</div>`:'';}
function queryStudent(){
 state.sequence++;state.selectedStudent='';state.data.selectedCredit=null;state.data.hourRecords=[];
 const matches=matchingStudents(state.studentQuery);
 if(matches.length===1){state.selectedStudent=matches[0].student_id;renderPage();return;}
 const result=state.page==='hours'?$('#hours-result'):$('#credit-result');
 result.innerHTML=matches.length?`<div class="section-footer">找到 ${matches.length} 位志愿者，请核对学号后选择。</div>`+table(['姓名','学号','状态','操作'],matches.map(s=>`<tr><td>${esc(s.name)}</td><td>${esc(s.student_id)}</td><td>${badge(s.status,s.status==='ACTIVE'?'在队':label[s.status])}</td><td><button type="button" class="text-button" data-action="query-student-pick" data-id="${esc(s.student_id)}">查看记录</button></td></tr>`)):empty(state.studentQuery?'未找到志愿者':'请输入学号或姓名',state.studentQuery?'请检查输入，或尝试部分学号、姓名。':'填写查询条件后点击“查询记录”。');
}
function searchBar(id,value,button='查询',name='query',placeholder='输入姓名或学号'){
 return `<form class="search-bar" id="${id}" novalidate><label class="search-field"><span class="search-icon" aria-hidden="true">${uiIcon('search')}</span><input class="control" type="search" name="${name}" id="${id}-input" placeholder="${esc(placeholder)}" value="${esc(value||'')}" autocomplete="off"></label><button class="btn primary" type="submit">${esc(button)}</button></form>`;
}
let filterSelectCanvas=null;
function fitFilterSelect(select){
 try{
  const option=select.options[select.selectedIndex];if(!option)return;
  const style=getComputedStyle(select);const context=(filterSelectCanvas||(filterSelectCanvas=document.createElement('canvas'))).getContext('2d');
  context.font=`${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
  const width=Math.ceil(context.measureText(option.text).width+parseFloat(style.paddingLeft)+parseFloat(style.paddingRight)+4);
  select.style.width=`${Math.max(92,width)}px`;
 }catch{}
}
function fitFilterSelects(root=document){root.querySelectorAll('select.control, .business-filter select').forEach(fitFilterSelect);}
function hoursFilterForm(){
 const student=state.role==='SUPER'?`<label class="filter-field"><span class="filter-label">志愿者</span><input class="control" type="search" name="student_query" id="hours-query-input" placeholder="输入姓名或学号" value="${esc(state.studentQuery??state.selectedStudent)}" autocomplete="off"></label>`:'';
 return `<form class="filter-bar" id="hours-filter-form" novalidate>${student}<label class="filter-field date-field"><span class="filter-label">开始日期</span><input class="control" id="query-start" name="start" type="date" value="${esc(state.from||'')}"></label><label class="filter-field date-field"><span class="filter-label">结束日期</span><input class="control" id="query-end" name="end" type="date" value="${esc(state.to||'')}"></label>${businessFilter()}<button class="btn primary" type="submit">查询记录</button></form>`;
}
async function hoursPage(){
 const seq=++state.sequence;
 $('#main').innerHTML=heading(state.role==='STUDENT'?'我的时长':'服务时长',state.role==='STUDENT'?'按实际认定的有效记录汇总，可选择日期范围查看。':'按实际认定的有效记录汇总，可选择日期范围查看。',state.role==='SUPER'?'<button class="btn" data-action="hours-export">导出学期周时长</button>':'')+hoursFilterForm()+'<section class="panel" id="hours-result"><div class="loading" role="status">正在读取服务记录…</div></section>';
 if(state.role==='SUPER'&&!state.selectedStudent){$('#hours-result').innerHTML=empty('请输入学号或姓名','查询志愿者后查看服务时长。');return;}
 const query=new URLSearchParams();if(state.role==='SUPER')query.set('student_id',state.selectedStudent);if(state.from)query.set('start',state.from);if(state.to)query.set('end',state.to);if(state.businessId)query.set('business_id',state.businessId);
 try{const data=await request('/hours?'+query);if(seq!==state.sequence)return;state.data.hourRecords=data.records;$('#hours-result').innerHTML=queriedStudentLabel()+`<div class="summary-line"><strong>${Number((data.total_minutes/60).toFixed(2))}</strong><span>累计小时 · ${data.records.filter(r=>r.record_status==='VALID').length} 条有效记录</span></div><p class="section-footer">${(data.group_totals||data.business_totals||[]).map(b=>esc(b.business_name)+(b.group_name?' / '+esc(b.group_name):'')+'：'+hourText(b.total_minutes)).join('；')}</p>${table(['服务日期','服务班次','考勤结果','认定时长','记录状态',...(state.role==='SUPER'?['操作']:[])],data.records.map(r=>`<tr><td>${esc(r.schedule_date)}${r.schedule_kind==='WEEKLY'?'<small>周日统计归属日，非实际日期</small>':''}</td><td>${esc(r.business_name||'')}${r.group_name?' / '+esc(r.group_name):''}<small>${esc(slotName(r.slot_id))}</small></td><td>${badge(r.attendance_status)}</td><td><strong>${hourText(r.service_minutes)}</strong></td><td>${badge(r.record_status)}</td>${state.role==='SUPER'?`<td><button class="text-button" data-action="hours-edit" data-id="${r.record_id}">修正时长</button></td>`:''}</tr>`),'暂无服务记录','正常出勤或迟到完成登记后，认定时长将显示在这里。')}`;}catch(e){if(seq===state.sequence)$('#hours-result').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
}
async function creditPage(){
 const seq=++state.sequence;const kind=state.tab||'credit';
 if(state.role==='NORMAL'){
  $('#main').innerHTML=heading('信用管理','查看本人负责范围内队员的信用分与每次变动。','')+'<section class="panel" id="credit-result"><div class="loading" role="status">正在读取信用记录…</div></section>';
  try{
   const sid=state.creditStudent;
   const data=await request('/credit'+(sid?'?student_id='+encodeURIComponent(sid):''));
   if(seq!==state.sequence)return;
   if(!sid){
    const students=data.students||[];
    $('#credit-result').innerHTML=table(['学号','姓名','学院','信用分','状态','操作'],students.map(s=>`<tr><td><strong>${esc(s.student_id)}</strong></td><td>${esc(s.name)}</td><td>${esc(s.college||'未填写')}</td><td><strong>${s.credit_score} 分</strong></td><td>${badge(s.status,s.status==='ACTIVE'?'在队':label[s.status])}</td><td><button class="text-button" data-action="credit-student" data-id="${esc(s.student_id)}">查看流水</button></td></tr>`),'暂无负责范围内的队员','你负责的时段、业务或分队中的队员会显示在这里。');
    return;
   }
   state.data.selectedCredit=data;
   $('#credit-result').innerHTML=`<div class="summary-line"><strong>${data.credit_score}</strong><span>当前信用分 · ${esc(data.name)}（${esc(data.student_id)}）</span>${badge(data.status,data.status==='ACTIVE'?'正常参与服务':label[data.status])}<button class="btn" data-action="credit-back">返回全部队员</button></div>${table(['发生时间','变更类型与原因','变化前','实际变动','变化后'],(data.logs||[]).map(r=>`<tr><td>${fmtDate(r.change_time)}</td><td class="wrap">${esc(({DEDUCTION:'考勤扣分',REVERSAL:'考勤冲正',MANUAL_SET:'管理员调分'})[r.entry_type]||'信用变更')}<small>${esc(label[r.change_reason]||r.change_reason)}</small></td><td>${r.before_score} 分</td><td><strong>${r.change_score>0?'+':''}${r.change_score} 分</strong></td><td>${r.after_score} 分</td></tr>`),'暂无信用变动','当前没有扣分流水。信用分变化后，可在这里逐笔核对。')}`;
  }catch(e){if(seq===state.sequence)$('#credit-result').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
  return;
 }
 $('#main').innerHTML=heading(state.role==='STUDENT'?'我的信用':'信用管理',state.role==='STUDENT'?'查看分数变化的依据，保留每次处理的历史记录。':'查看分数变化的依据，保留每次处理的历史记录。',state.role==='SUPER'&&kind==='rules'?'<button class="btn primary" data-action="rule">调整扣分规则</button>':'')+(state.role==='SUPER'?`<div class="toolbar">${tabs([['credit','信用流水'],['rules','信用规则']],kind)}</div>`:'')+(kind==='credit'&&state.role==='SUPER'?searchBar('credit-search-form',state.studentQuery??state.selectedStudent,'查询记录','student_query'):'')+'<section class="panel" id="credit-result"><div class="loading" role="status">正在读取信用记录…</div></section>';
 if(kind==='credit'&&state.role==='SUPER'&&!state.selectedStudent){$('#credit-result').innerHTML=empty('请输入学号或姓名','查询志愿者后查看信用流水或调整信用分。');return;}
 try{if(kind==='rules'){const records=await request('/credit-rules');if(seq!==state.sequence)return;state.data.rules=records;$('#credit-result').innerHTML=table(['违规类型','规则版本','扣分标准','状态','创建时间'],records.map(r=>`<tr><td><strong>${label[r.violation_type]}</strong></td><td>第 ${r.version} 版</td><td>${r.deduct_score} 分</td><td>${badge(r.status,r.status==='ACTIVE'?'当前生效':'历史版本')}</td><td>${fmtDate(r.create_time)}</td></tr>`));return;}
 const data=await request('/credit'+(state.role==='SUPER'?'?student_id='+encodeURIComponent(state.selectedStudent):''));if(seq!==state.sequence)return;state.data.selectedCredit=data;
 $('#credit-result').innerHTML=queriedStudentLabel()+`<div class="summary-line"><strong>${data.credit_score}</strong><span>当前信用分</span>${state.role==='SUPER'?'<button class="btn primary" data-action="credit-set">调整信用分</button>':''}${badge(data.status,data.status==='ACTIVE'?'正常参与服务':label[data.status])}</div>${table(['发生时间','变更类型与原因','变化前','实际变动','变化后'],data.logs.map(r=>`<tr><td>${fmtDate(r.change_time)}</td><td class="wrap">${esc(({DEDUCTION:'考勤扣分',REVERSAL:'考勤冲正',MANUAL_SET:'超管调分'})[r.entry_type]||'信用变更')}<small>${esc(label[r.change_reason]||r.change_reason)}</small></td><td>${r.before_score} 分</td><td><strong>${r.change_score>0?'+':''}${r.change_score} 分</strong></td><td>${r.after_score} 分</td></tr>`),'暂无信用变动','当前没有扣分流水。信用分变化后，可在这里逐笔核对。')}</div>`;
 }catch(e){if(seq===state.sequence)$('#credit-result').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
}
function slotTable(){if(state.data.slots.some(s=>s.weekday))return fixedSlotTable();return table(['服务班次','服务时间','建议人数','标准时长','班次负责人'],state.data.slots.map(r=>`<tr><td><strong>${esc(slotLabel(r))}</strong></td><td>${esc(r.start_time)} 至 ${esc(r.end_time)}</td><td>${r.need_num} 人</td><td>${hourText(r.service_minutes)}</td><td>${esc(adminName(r.manager_admin_id))}</td></tr>`),'暂无服务班次','由超级管理员添加班次和负责人后显示。');}
async function logsPage(){const seq=++state.sequence;$('#main').innerHTML=heading('操作日志','查看最近 100 条重要操作，核对修改前后的内容。','<button class="btn" data-action="refresh">刷新日志</button>')+'<section class="panel" id="logs-result"><div class="loading" role="status">正在读取操作日志…</div></section>';try{const rows=await request('/operation-logs');if(seq!==state.sequence)return;state.data.logs=rows;$('#logs-result').innerHTML=table(['操作时间','操作人员','操作内容','说明','操作'],rows.map(r=>`<tr><td>${fmtDate(r.operation_time)}</td><td>${esc(adminName(r.admin_id))}</td><td>${esc(operationNames[r.operation_type]||'数据操作')}</td><td class="wrap">${esc(r.reason||'未附加说明')}</td><td><button class="text-button" data-action="log-detail" data-id="${r.log_id}">查看详情</button></td></tr>`),'暂无操作日志','新增资料、审批和考勤等重要操作会自动留存记录。');}catch(e){if(seq===state.sequence)$('#logs-result').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}}

// All destructive or consequential business actions go through a named dialog.
function openDialog(title,subtitle,fields,onSubmit,button='确认提交'){
 if(modalBusy)return;
 if(dialog.open)closeDialog(true);
 previousFocus=document.activeElement;modalSubmit=onSubmit;modalVersion++;
 dialog.classList.remove('collection-dialog');
 dialog.innerHTML=`<header class="dialog-header"><div><h2 id="dialog-title">${esc(title)}</h2>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div><button class="close-button" data-action="close">关闭</button></header><div class="dialog-body"><form id="action-form" novalidate><div class="form-grid">${fields}</div><div id="action-error" class="notice error" role="alert" hidden></div><footer class="dialog-footer"><button type="button" class="btn" data-action="close">取消</button><button class="btn primary" type="submit">${esc(button)}</button></footer></form></div>`;
 dialog.showModal();
}
function openReadOnlyDialog(title,content,subtitle=''){
 if(modalBusy)return;
 if(dialog.open)closeDialog(true);
 previousFocus=document.activeElement;modalSubmit=null;modalVersion++;
 dialog.classList.remove('collection-dialog');
 dialog.innerHTML=`<header class="dialog-header"><div><h2 id="dialog-title">${esc(title)}</h2>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div><button class="close-button" type="button" data-action="close">关闭</button></header><div class="dialog-body">${content}</div>`;
 dialog.showModal();
}
function openReadOnlyDialog(title,content){
 if(modalBusy||dialog.open)return;
 previousFocus=document.activeElement;modalSubmit=null;modalVersion++;
 dialog.classList.remove('collection-dialog');
 dialog.innerHTML=`<header class="dialog-header"><h2 id="dialog-title">${esc(title)}</h2><button class="close-button" type="button" data-action="close">关闭</button></header><div class="dialog-body">${content}</div>`;
 dialog.showModal();
}
function setModalBusy(busy){modalBusy=busy;dialog.querySelectorAll('[data-action="close"]').forEach(button=>button.disabled=busy);}
function closeDialog(force=false){if(modalBusy&&!force)return;if(!dialog.open&&!modalSubmit)return;setModalBusy(false);modalVersion++;if(dialog.open)dialog.close();dialog.classList.remove('collection-dialog');dialog.innerHTML='';modalSubmit=null;const focus=previousFocus;previousFocus=null;focus?.focus?.();}
function field(name,title,{type='text',value='',options,required=true,full=false,help='',min,max,step,placeholder='',maxLength,minLength,icon}={}){
 const attrs=`id="f-${name}" name="${name}" ${required?'required':''} ${min!==undefined?`min="${min}"`:''} ${max!==undefined?`max="${max}"`:''} ${step!==undefined?`step="${step}"`:''} ${maxLength?`maxlength="${maxLength}"`:''} ${minLength?`minlength="${minLength}"`:''}`;
 const inputElement=options?`<select ${attrs}>${options.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(t)}</option>`).join('')}</select>`:type==='textarea'?`<textarea ${attrs} placeholder="${esc(placeholder)}">${esc(value)}</textarea>`:`<input ${attrs} type="${type}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${type==='password'?'autocomplete="new-password"':''}>`;
 const content = icon ? `<div class="field-control">${uiIcon(icon, 'lead')}${inputElement}</div>` : inputElement;
 return `<div class="field ${full?'full':''}"><label for="f-${name}">${esc(title)}${!required?'<span class="required-label">选填</span>':''}</label>${content}${help?`<small class="field-help">${esc(help)}</small>`:''}</div>`;
}
const reasonField=()=>field('reason','原因说明',{type:'textarea',full:true,maxLength:500,placeholder:'请填写具体原因，便于审批和后续核对'});
function changePasswordDialog(){
 return openDialog('修改密码','',
  field('current_password','当前密码',{type:'password',full:true,maxLength:128,placeholder:'请输入当前密码',icon:'lock'})+
  field('new_password','新密码',{type:'password',full:true,maxLength:128,placeholder:'请输入新密码',icon:'lock'})+
  field('confirm_password','确认新密码',{type:'password',full:true,maxLength:128,placeholder:'请再次输入新密码',icon:'lock'}),
  async v=>{
   if(v.new_password!==v.confirm_password)throw new Error('两次输入的新密码不一致。');
   if(v.new_password===v.current_password)throw new Error('密码与原密码一致，请设置不同的新密码');
   if(!v.new_password||v.new_password.length<8||v.new_password.length>128)throw new Error('新密码长度必须为 8 至 128 个字符。');
   await send('/auth/password/change',{current_password:v.current_password,new_password:v.new_password});
   return {changed:true};
  }, '保存新密码');
}
function scheduleOptions(){return state.data.schedules.filter(canFuture).map(r=>[r.schedule_id,`${r.schedule_date} ${slotName(r.slot_id)}`]);}
function action(name,id,kind,studentId){
 if(name==='menu-close'){document.querySelector('.workspace')?.classList.remove('menu-open');return;}
 if(name==='sidebar-toggle'){const w=document.querySelector('.workspace');w?.classList.toggle('sidebar-collapsed');try{localStorage.setItem('volunteer_sidebar_collapsed',w?.classList.contains('sidebar-collapsed')?'1':'0');}catch{}return;}
 if(modalBusy)return;
 if(name==='schedule-group-toggle'){
  const key=String(id),row=document.querySelector(`[data-schedule-group="${key}"]`);
  if(!row)return;
  const collapsed=row.classList.toggle('collapsed');
  if(collapsed)state.collapsedScheduleGroups.add(key);else state.collapsedScheduleGroups.delete(key);
  document.querySelectorAll(`[data-schedule-member="${key}"]`).forEach(item=>{item.hidden=collapsed;});
  row.querySelector('.schedule-group-toggle')?.setAttribute('aria-expanded',String(!collapsed));
  return;
 }
 if(name==='change-password')return changePasswordDialog();
 if(directoryAction(name,id,kind)||governanceAction(name,id,kind)||businessAction(name,id,kind,studentId)||semesterAction(name,id)||rosterAction(name,id))return;
 if(name==='schedule-unregistered'){
  state.scheduleView='unregistered';state.attendanceFilter='';state.search='';state.searchBefore=null;schedulesPage();return;
 }
 if(name==='schedule-back-weekly'){state.scheduleView='week';state.week='current';state.attendanceFilter='';state.search='';state.searchBefore=null;schedulesPage();return;}
 if(name==='schedule-week-current'){state.scheduleView='week';state.week='current';state.search='';state.searchBefore=null;schedulesPage();return;}
 if(name==='schedule-all'){state.scheduleView='week';state.week='all';schedulesPage();return;}
 if(name==='schedule-week-prev'||name==='schedule-week-next'){
  const term=currentSemester();if(!term)return;
  const current=term.phase==='ENDED'?Number(term.end_week)||1:Math.max(1,Number(term.current_week)||1);
  const base=state.week==='all'||!state.week?current:Number(state.week)||current;
  const next=Math.max(1,Math.min(Number(term.end_week)||1,base+(name==='schedule-week-next'?1:-1)));
  state.scheduleView='week';state.week=String(next);schedulesPage();return;
 }
 const r=rowsOf(state.data.schedules,'schedule_id',id);
 if(name==='transfer')return rosterAction('fixed-transfer');
 if(name==='new-application')return action((state.tab||'leave')==='transfer'?'transfer':'leave');
 if(name==='withdrawal')return openDialog('申请退出志愿队','获批后将取消未来未开始的排班，历史服务和信用记录会保留。',reasonField(),v=>send('/applications/withdrawal',v),'提交退队申请');
 if(name==='schedule'){
  console.log('[DEBUG] schedule action called');
  const slots=state.data.slots.filter(s=>!['WEEKLY','EVENT'].includes(s.schedule_kind)&&(state.role==='SUPER'||s.manager_admin_id===state.me.admin_id));
  if(!slots.length)return notify('当前没有可管理的有效班次，请先建立班次。',true);
  return openDialog('新增排班','系统会检查时段归属与志愿者时间冲突；建议人数仅供参考，不限制新增排班。',(state.role==='SUPER'?field('student_id','志愿者',{options:state.data.students.filter(s=>s.status==='ACTIVE').map(s=>[s.student_id,`${s.name}（${s.student_id}）`]),full:true}):field('student_id','志愿者学号',{full:true,maxLength:32}))+field('slot_id','服务班次',{options:slots.map(s=>[s.slot_id,`${slotName(s.slot_id)}`]),full:true})+field('schedule_date','服务日期',{type:'date',min:getDate(),full:true}),v=>send('/schedules',{...v,slot_id:Number(v.slot_id)}),'确认排班');
 }
 if(name==='cancel')return openDialog('取消这次排班',`${r.schedule_date} ${studentName(r.student_id)}，${slotName(r.slot_id)}。关联的未完成申请也将取消。`,reasonField(),v=>send(`/schedules/${id}/cancel`,v),'确认取消排班');
 if(name==='attendance-correct')return openDialog('考勤改判与信用冲正',`${studentName(r.student_id)}，${r.schedule_date}，当前为${label[r.attendance_status]}。改判将同步修正时长，撤销旧违规并退还原实际扣分，再按新结果处理。时长将恢复班次标准值，覆盖此前的手动分钟修正。`,field('status','正确的考勤结果',{options:[['NORMAL','正常出勤（恢复认定时长）'],['LATE','迟到（计完整时长，按规则扣分）'],['ABSENT','无故缺勤（不计时长，按规则扣分）'],['LEAVE','事后确认请假（不计时长、不扣分）']].filter(x=>r.schedule_kind!=='WEEKLY'||x[0]!=='LATE'),value:r.attendance_status,full:true})+reasonField(),v=>send(`/schedules/${id}/attendance`,{...v,expected_revision:r.attendance_revision},'PATCH'),'确认改判');
 if(name==='credit-student'){state.creditStudent=id;return creditPage();}
 if(name==='credit-back'){state.creditStudent='';return creditPage();}
 if(name==='credit-set'){
  const data=state.data.selectedCredit;if(!data)return notify('请先查询该队员的信用记录。',true);
  return openDialog('调整队员信用分',`${studentName(data.student_id)}（${data.student_id}），当前 ${data.credit_score} 分。新分数与原因会写入信用流水和操作日志。归零将暂停服务，因信用归零停用的队员恢复正分后可继续服务。`,field('credit_score','调整后的信用分',{type:'number',value:data.credit_score,min:0,max:2147483647,step:1,full:true})+reasonField(),v=>send(`/students/${encodeURIComponent(data.student_id)}/credit`,{credit_score:Number(v.credit_score),expected_version:data.credit_version,reason:v.reason},'PUT'),'保存信用分');
 }
 if(name==='attendance')return openDialog('登记考勤',`${studentName(r.student_id)}，${r.schedule_date}，${slotName(r.slot_id)}。本周未登记异常的服务会自动结算。自动认定的正常出勤可补录缺勤或迟到，须填写原因。`,(r.leave_approved?'<div class="notice field full">该排班的请假已经获批，系统将按请假处理。</div>':'')+field('status','出勤情况',{options:(r.attendance_source==='AUTO_WEEKLY'?[['LATE','补录迟到（计完整时长）'],['ABSENT','补录缺勤（撤销自动时长）']]:r.leave_approved?[['LEAVE','已批准请假']]:[['NORMAL','正常出勤'],['LATE','迟到（计完整时长）'],['ABSENT','无故缺勤']]).filter(x=>r.schedule_kind!=='WEEKLY'||x[0]!=='LATE'),full:true})+field('remark','考勤备注',{type:'textarea',required:r.attendance_source==='AUTO_WEEKLY',full:true,maxLength:500}),v=>send('/attendance',{...v,schedule_id:Number(id)}),'确认并结算');
 if(name==='approve'){
  const a=rowsOf(state.data[kind],kind==='leave'?'leave_id':kind==='transfer'?'transfer_id':'withdrawal_id',id);
  const path=kind==='transfer'?`/applications/transfer/${id}/decision`:`/applications/${kind}/${id}/decision`;
  return openDialog('审批申请',`${studentName(a.student_id)}：${a.reason}。普通审核人或超级管理员均可处理；一次审核即为最终结果，结果会抄送超级管理员。`,field('approved','审批结果',{options:[['true','通过申请'],['false','驳回申请']],full:true})+field('reason','审批说明',{type:'textarea',full:true,maxLength:500,required:false,placeholder:'驳回时必须填写，通过可选填'}),v=>send(path,{approved:v.approved==='true',reason:v.reason||''}),'确认审批');
 }
 if(name==='hours-edit'){const record=rowsOf(state.data.hourRecords,'record_id',id),half=record.minute_step===30;return openDialog('修正服务时长','修改具体服务记录，变更前后值与原因将写入操作日志。',field('service_minutes',half?'认定时长（小时）':'认定时长（分钟）',{type:'number',value:record.service_minutes/(half?60:1),min:half?0.5:0,max:half?24:1440,step:half?0.5:1,full:true,help:half?'以0.5小时递增；撤销计时请在征集审批中打回。':'60 分钟等于 1 小时。'})+reasonField(),v=>send(`/service-records/${id}`,{service_minutes:half?halfHourMinutes(v.service_minutes):Number(v.service_minutes),reason:v.reason},'PATCH'),'保存修正');}
 if(name==='rule')return openDialog('调整扣分规则','将生成新的规则版本，已发生的违规保留原来的扣分依据。',field('violation_type','违规类型',{options:[['LATE','迟到'],['ABSENT','无故缺勤']]})+field('deduct_score','扣分数值',{type:'number',min:0,max:100,step:1})+reasonField(),v=>send('/credit-rules/'+v.violation_type,{deduct_score:Number(v.deduct_score),reason:v.reason},'PUT'),'发布新规则');
 if(name==='create-students')return openDialog('新增志愿者','新志愿者初始信用为 5 分。',field('student_id','学号',{maxLength:32,help:'仅使用字母、数字、下划线或连字符。'})+field('name','姓名',{maxLength:100})+field('college','学院',{required:false,maxLength:100})+field('phone','联系电话',{required:false,maxLength:32})+field('password','初始密码',{type:'password',full:true,maxLength:128,help:'设置 8 至 128 个字符的密码。'}),v=>send('/students',v),'创建志愿者');
 if(name==='create-admins')return openDialog('新增管理员','按实际职责分配权限，普通管理员只能处理负责的班次。',field('name','姓名',{maxLength:100})+field('account','登录账号',{maxLength:64})+field('role','管理角色',{options:[['NORMAL','普通管理员'],['SUPER','超级管理员']],full:true})+field('password','初始密码',{type:'password',full:true,maxLength:128,help:'设置 8 至 128 个字符的密码。'}),v=>send('/admins',v),'创建管理员');
 if(name==='create-slots')return notify('固定业务请使用时段设置；临时事项请在业务管理中录入。',true);
 if(name==='legacy-create-slot-disabled')return openDialog('新增服务班次','第 3 时段正常计 3 小时，其余时段计 2 小时。班次须在同一天内结束。',field('team_name','分队名称',{maxLength:100})+field('period_no','时段编号',{type:'number',min:1,max:100,step:1})+field('start_time','开始时间',{type:'time'})+field('end_time','结束时间',{type:'time'})+field('need_num','建议人数',{type:'number',min:1,max:10000,step:1})+field('manager_admin_id','负责管理员',{options:state.data.admins.filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE').map(a=>[a.admin_id,a.name]),full:true}),v=>send('/slots',{...v,period_no:Number(v.period_no),need_num:Number(v.need_num),manager_admin_id:Number(v.manager_admin_id)}),'建立班次');
 if(name==='log-detail'){
  const record=rowsOf(state.data.logs,'log_id',id);
  const displayValue=(key,value)=>value===null||value===undefined||value===''?'未填写':Array.isArray(value)?value.map(v=>key==='slots'?`${slotName(v)}（编号 ${v}）`:v).join('、')||'无':key==='role'?roleName(value):typeof value==='boolean'?(value?'是':'否'):label[value]??value;
  const details=value=>{let data=value;if(typeof data==='string'){try{data=JSON.parse(data);}catch{return esc(data);}}return data?`<dl class="data-list">${Object.entries(data).filter(([k])=>!k.includes('password')).map(([k,v])=>`<dt>${esc(fieldNames[k]||'关联信息')}</dt><dd>${esc(displayValue(k,v))}</dd>`).join('')}</dl>`:'<p class="muted">无</p>';};
  return openReadOnlyDialog(operationNames[record.operation_type]||'操作详情',`<p>${esc(record.reason||'未附加说明')}</p><div class="log-values"><h3>修改前</h3>${details(record.before_value)}<hr><h3>修改后</h3>${details(record.after_value)}</div>`,`${fmtDate(record.operation_time)}，${esc(adminName(record.admin_id))}`);
 }
}
function validate(form){
 const controls=[...form.querySelectorAll('input,select,textarea')];
 for(const el of controls){
  if(el.required&&!el.value.trim()){el.focus();return `请填写${form.querySelector(`label[for="${el.id}"]`)?.textContent||'必填内容'}。`;}
  if(!el.validity.valid){el.focus();return `请检查${form.querySelector(`label[for="${el.id}"]`)?.textContent||'输入内容'}的格式或取值范围。`;}
 }
 return '';
}
document.addEventListener('click',async e=>{
 const reveal=e.target.closest('[data-reveal]');
 if(reveal&&typeof reveal.getAttribute==='function'){
  const input=document.getElementById(reveal.getAttribute('data-reveal'));
  if(input){const show=input.type==='password';input.type=show?'text':'password';reveal.setAttribute('aria-label',show?'隐藏密码':'显示密码');const label=reveal.querySelector('span');if(label)label.textContent=show?'隐藏':'显示';}
  return;
 }
 const inSummary=e.target.closest('summary');if(inSummary&&e.target.closest('[data-action]')&&typeof e.preventDefault==='function')e.preventDefault();
 const target=e.target.closest('button,[data-page]');if(!target)return;
 if(target.dataset.page){navigate(target.dataset.page);return;}
 if(target.dataset.tab){closeDialog(true);state.tab=target.dataset.tab;renderPage();return;}
 const name=target.dataset.action;
 if(name==='hours-export'&&state.role==='SUPER'){
  const semesters=state.data.semesters||[];
  if(!semesters.length)return notify('请先在学期与日历中设置学期。',true);
  return openDialog('导出学期周时长','导出所选学期全队名单，不受页面的个人查询和日期筛选影响。每周表头包含日期范围，未到周留空，当前周仅含已认定时长。',
   field('semester_id','导出学期',{options:semesters.map(s=>[s.semester_id,`${s.name}（${s.start_date} 至 ${s.end_date}）`]),value:currentSemester()?.semester_id,full:true})+field('business_id','导出业务',{options:businessOptions(),required:false,full:true})+field('group_id','导出小组',{options:[['','全部小组'],['0','未分组'],...(state.data.groups||[]).map(g=>[g.group_id,g.business_name+' / '+g.name])],required:false,full:true}),
   async values=>{
    const session=state.sessionVersion;
    const response=await fetch('/hours/export?'+new URLSearchParams({semester_id:values.semester_id,...(values.business_id?{business_id:values.business_id}:{}),...(values.group_id?{group_id:values.group_id}:{})}),{headers:{Authorization:`Bearer ${state.token}`},signal:AbortSignal.timeout(120000)});
    if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(typeof error.detail==='string'?error.detail:'导出失败，请重试。');}
    const blob=await response.blob();if(session!==state.sessionVersion)throw new Error('登录状态已变化，请重新导出。');const url=URL.createObjectURL(blob);const link=document.createElement('a');
    link.href=url;link.download=`志愿服务周时长_学期${values.semester_id}.xlsx`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    return {downloaded:true};
   },'下载 Excel');
 }

 if(name==='theme')return toggleTheme();
 if(name==='password'){const input=$('#login-password');input.type=input.type==='password'?'text':'password';target.textContent=input.type==='password'?'显示':'隐藏';target.setAttribute('aria-label',input.type==='password'?'显示密码':'隐藏密码');return;}
 if(name==='logout')return signOut();
 if(name==='menu')return document.querySelector('.workspace').classList.toggle('menu-open');
 if(name==='close')return closeDialog();
 if(name==='refresh')return refresh();
 if(name==='query-student-pick'&&state.role==='SUPER'){const student=rowsOf(state.data.students,'student_id',target.dataset.id);if(!student)return;state.selectedStudent=student.student_id;state.studentQuery=student.student_id;return renderPage();}
 if(name==='search'){applyScheduleSearch($('#search')?.value||'');return schedulesPage();}
 try{action(name,target.dataset.id,target.dataset.kind,target.dataset.student);}catch(e){console.error('[ERROR] action failed:',name,e);notify('操作失败：' + e.message,true);}
});
dialog.addEventListener('click',e=>{if(e.target.matches?.('input[type="file"]'))filePickerArmed=Date.now();},true);
if(typeof window.addEventListener==='function')window.addEventListener('focus',()=>{if(filePickerArmed){filePickerArmed=0;filePickerCloseGuard=Date.now()+3000;}});
dialog.addEventListener('cancel',e=>{e.preventDefault();if(modalBusy)return;if(document.activeElement?.matches?.('input[type="file"]')||Date.now()<filePickerCloseGuard)return;closeDialog();});
document.addEventListener('submit',async e=>{
 e.preventDefault();const form=e.target;
 if(form.id==='hours-filter-form'){const values=Object.fromEntries(new FormData(form));state.from=values.start||'';state.to=values.end||'';state.businessId=values.business_id||'';if(state.role==='SUPER'){state.studentQuery=(values.student_query||'').trim();queryStudent();}else hoursPage();return;}
 if(form.id==='credit-search-form'){state.studentQuery=($('#credit-search-form-input')?.value||'').trim();queryStudent();return;}
 if(form.id==='student-search-form'){state.rosterQuery=($('#student-search-form-input')?.value||'').trim();renderRosterSearch();return;}
 if(form.id==='admin-search-form'){state.adminQuery=($('#admin-search-form-input')?.value||'').trim();renderAdminSearch();return;}
 if(!['login-form','action-form'].includes(form.id))return;
 if(form.id==='action-form'&&(modalBusy||!dialog.open))return;
 const errorEl=form.id==='login-form'?$('#login-error'):$('#action-error');
 errorEl.hidden=true;const error=form.dataset?.collectionForm==='true'?null:validate(form);if(error){errorEl.textContent=error;errorEl.hidden=false;return;}
 const submit=form.querySelector('[type="submit"]');const oldText=submit.textContent;submit.disabled=true;submit.textContent=form.id==='login-form'?'正在登录…':'正在提交…';
 const values=Object.fromEntries(new FormData(form));
 const session=state.sessionVersion;const version=modalVersion;
 try{
  if(form.id==='login-form'){
   const data=await send('/auth/login',values);if(session!==state.sessionVersion)return;state.sessionVersion++;state.token=data.access_token;sessionStorage.setItem('volunteer_token',state.token);
   applyIdentity(await request('/auth/me'));state.page='overview';buildShell();await refresh();
  }else{
   const callback=modalSubmit;if(!callback)return;
   // Keep the dialog open and preserve user input if the request fails.
   setModalBusy(true);const result=await callback(values);
   if(session!==state.sessionVersion)return;
   if(version===modalVersion){setModalBusy(false);closeDialog();}
   notify(result?.changed?'密码已更新，请牢记新密码。':result?.downloaded?'导出文件已下载。':result?.published?'时长征集已发布。':'操作已完成，记录已更新。');if(!result?.downloaded)await refresh();
  }
 }catch(ex){if(form.id==='action-form'&&(session!==state.sessionVersion||version!==modalVersion))return;if(errorEl.isConnected){errorEl.textContent=ex.message;errorEl.hidden=false;}else notify(ex.message,true);}
 finally{if(form.id==='action-form'&&version===modalVersion)setModalBusy(false);submit.disabled=false;submit.textContent=oldText;}
});
document.addEventListener('change',e=>{
 if(e.target.matches?.('select.control, .business-filter select'))fitFilterSelect(e.target);
 if(e.target.id==='attendance-filter'){state.attendanceFilter=e.target.value;schedulesPage();}
 if(e.target.id==='inbox-category-filter'){state.inboxCategory=e.target.value;inboxPage();}
});
let scheduleSearchTimer=0;
function applyScheduleSearch(value){
 const text=String(value||'').trim();
 if(text){
  if(!state.searchBefore)state.searchBefore={view:state.scheduleView||'todo',week:state.week||'current'};
  state.search=text;
  state.scheduleView='week';
  state.week='all';
 }else{
  state.search='';
  if(state.searchBefore){state.scheduleView=state.searchBefore.view;state.week=state.searchBefore.week;state.searchBefore=null;}
  else if(state.scheduleView==='week'&&state.week==='all')state.scheduleView='todo';
 }
}
document.addEventListener('input',e=>{
 if(e.target.id!=='search')return;
 const value=e.target.value;
 clearTimeout(scheduleSearchTimer);
 scheduleSearchTimer=setTimeout(()=>{
  applyScheduleSearch(value);
  schedulesPage();
  const input=$('#search');
  if(input){input.focus();const end=input.value.length;try{input.setSelectionRange(end,end);}catch{}}
 },240);
});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.id==='search'){e.preventDefault();applyScheduleSearch(e.target.value);schedulesPage();}});
async function start(){
 if(!state.token){loginView();return;}
 try{applyIdentity(await request('/auth/me'));buildShell();await refresh();}
 catch{signOut(false);}
}


Object.assign(operationNames,{CREATE_BUSINESS:'新增业务',CREATE_GROUP:'新增小组',ASSIGN_SLOT_MANAGERS:'按分队设置班次负责人',RENAME_BUSINESS:'修改业务名称',ARCHIVE_BUSINESS:'停用归档业务',RESTORE_BUSINESS:'恢复业务',ADD_BUSINESS_SLOT:'新增业务时段',SET_GROUP_MEMBER:'调整小组归属',IMPORT_MEMBERS:'导入业务小组名单',REVIEW_HOURS_FIRST:'时长申报初审',REVIEW_HOURS_FINAL:'时长申报终审',REVIEW_HOURS_DIRECT:'超管直接审批时长申报',CORRECT_HOURS_REVIEW:'二次更正时长审批',CLOSE_COLLECTION:'结束时长征集',RESET_PASSWORD:'重置账号密码',CONFIGURE_BUSINESS:'设置业务管理员',SET_BUSINESS_WEEK:'更正每周开工安排',CONFIRM_GARDEN:'确认花园本周服务',CREATE_COLLECTION:'发布时长征集',DECIDE_HOURS:'审批时长申报',IMPORT_SPECIALTY:'导入专项名单及时长',CREATE_EVENT:'录入临时服务',RECOGNIZE_EVENT:'认定临时服务时长',PLAN_MEMBERSHIPS:'设置归属生效日期',SET_BUSINESS_MEMBER:'调整专项业务归属'});
Object.assign(fieldNames,{group_id:'小组编号',group_ids:'小组范围编号',group_name:'小组名称',new_students:'新建账号数',kind:'业务类型',business_ids:'业务范围编号',submission_deadline:'申报截止日期',attachments:'附件信息',business_id:'业务编号',business_name:'业务名称',week_no:'周次',working:'是否上工',effective_date:'生效日期',student_ids:'参与队员',items:'工作事项',imported:'导入条数',skipped:'跳过条数',batch_id:'导入批次',duplicate_choices:'重复行处理',active:'是否加入'});

/* ============================================================================
   v2.5 登录页、外壳与主题（墨绿主视觉 + 浅绿色表单区；浅色/深色/跟随系统）
   ========================================================================== */
function uiIcon(name, className) {
  return `<svg class="i ${className || ''}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

const THEME_KEY = 'volunteer_theme';
const THEME_MODES = ['light', 'dark', 'system'];
const THEME_LABELS = { light: '浅色', dark: '深色', system: '跟随系统' };

function themeMode() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return THEME_MODES.includes(value) ? value : 'system';
  } catch (error) {
    return 'system';
  }
}

function systemTheme() {
  try {
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch (error) {
    return 'light';
  }
}

function currentTheme() {
  const mode = themeMode();
  return mode === 'system' ? systemTheme() : mode;
}

function themeText() {
  return '外观：' + THEME_LABELS[themeMode()];
}

function syncThemeButtons() {
  const dark = currentTheme() === 'dark';
  document.querySelectorAll('[data-action="theme"]').forEach(button => {
    const label = button.querySelector('[data-theme-label]');
    if (label) label.textContent = themeText();
    const use = button.querySelector('use');
    if (use) use.setAttribute('href', dark ? '#i-sun' : '#i-moon');
  });
}

function applyTheme() {
  setTheme(currentTheme());
  syncThemeButtons();
}

function setThemeMode(mode) {
  try {
    localStorage.setItem(THEME_KEY, mode);
  } catch (error) {
    /* 隐私模式下仅当前页面生效 */
  }
  applyTheme();
}

function toggleTheme() {
  const index = THEME_MODES.indexOf(themeMode());
  setThemeMode(THEME_MODES[(index + 1) % THEME_MODES.length]);
}

function loginView() {
  document.title = '登录 · 图书馆志愿服务';
  state.me = null;
  state.role = null;
  app.innerHTML = `<main class="auth-page" id="main">
    <section class="auth-hero" aria-label="系统简介">
      <p class="auth-hero-top">四川大学图书馆志愿服务队管理系统</p>
      <div class="auth-hero-main">
        <div class="auth-brand">
          <span class="auth-brand-tile">${uiIcon('book')}</span>
          <span><strong>图书馆志愿服务</strong><small>四川大学图书馆志愿服务队</small></span>
        </div>
        <span class="auth-chip">志愿服务 · 一站式管理</span>
        <h1 class="auth-headline">把每一次志愿服务，安排妥当。</h1>
        <div class="auth-features">
          <div class="auth-feature">
            <span class="auth-feature-icon">${uiIcon('calendar')}</span>
            <span><strong>排班与考勤</strong></span>
          </div>
          <div class="auth-feature">
            <span class="auth-feature-icon">${uiIcon('check')}</span>
            <span><strong>申请与审批</strong></span>
          </div>
          <div class="auth-feature">
            <span class="auth-feature-icon">${uiIcon('clock')}</span>
            <span><strong>时长与信用</strong></span>
          </div>
          <div class="auth-feature">
            <span class="auth-feature-icon">${uiIcon('users')}</span>
            <span><strong>分队与负责人</strong></span>
          </div>
        </div>
      </div>
    </section>
    <section class="auth-panel">
      <button class="icon-button auth-theme" type="button" data-action="theme" title="切换主题">
        <span data-theme-icon>${uiIcon('moon')}</span>
      </button>
      <div class="auth-card">
        <div class="auth-mobile-brand">
          <span class="brand-mark">${uiIcon('book')}</span>
          <span><strong>图书馆志愿服务</strong><small>四川大学图书馆志愿服务队</small></span>
        </div>
        <h2>欢迎回来</h2>
        <p class="auth-sub">使用你的账号登录工作台。</p>
        <form class="auth-form" id="login-form" novalidate>
          <div class="auth-field">
            <label for="login-kind">登录身份</label>
            <div class="auth-control">
              ${uiIcon('users', 'lead')}
              <select id="login-kind" name="kind">
                <option value="admin">管理员</option>
                <option value="student">志愿者</option>
              </select>
              <span class="trail">${uiIcon('chevron-down')}</span>
            </div>
          </div>
          <div class="auth-field">
            <label for="login-account">账号</label>
            <div class="auth-control">
              ${uiIcon('user', 'lead')}
              <input id="login-account" name="account" type="text" autocomplete="username"
                     placeholder="请输入管理员账号或学号" required maxlength="64">
            </div>
          </div>
          <div class="auth-field">
            <div class="auth-label-row">
              <label for="login-password">密码</label>
            </div>
            <div class="auth-control">
              ${uiIcon('lock', 'lead')}
              <input id="login-password" name="password" type="password"
                     autocomplete="current-password"
                     placeholder="请输入密码" required maxlength="128">
              <span class="trail">
                <button class="auth-reveal" type="button" data-reveal="login-password" aria-label="显示密码">
                  ${uiIcon('eye')}<span>显示</span>
                </button>
              </span>
            </div>
          </div>
          <div id="login-error" class="notice error" role="alert" hidden></div>
          <button class="auth-submit" type="submit">登录工作台 ${uiIcon('arrow-right')}</button>
        </form>
        <p class="auth-help auth-help--center">
          <a class="auth-link" href="/password#reset">找回密码</a>
        </p>
      </div>
    </section>
  </main>`;
}

function buildShell() {
  const available = navAvailable();
  if (!available.some(n => n[0] === state.page)) state.page = 'overview';
  const student = state.role === 'STUDENT';
  const workspaceName = student ? '志愿者工作台' : '管理工作台';
  app.innerHTML = `<div class="workspace">
    <aside class="sidebar" aria-label="主导航">
      <a href="/" class="brand">
        <span class="brand-mark" aria-hidden="true">${uiIcon('book')}</span>
        <span><strong>图书馆志愿服务</strong><small>${workspaceName}</small></span>
      </a>
      <button class="sidebar-collapse-btn" type="button" data-action="sidebar-toggle" aria-label="折叠或展开导航">${uiIcon('chevron-right')}</button>
      <nav class="nav-list">${navigationHtml(available)}</nav>
    </aside>
    <button class="sidebar-backdrop" type="button" data-action="menu-close" aria-label="关闭导航菜单"></button>
    <div class="workspace-body">
      <header class="topbar">
        <div class="button-row">
          <button class="btn small mobile-menu" data-action="menu" aria-label="打开或关闭导航菜单">${uiIcon('menu')}<span>菜单</span></button>
          <div class="breadcrumb"><span>${workspaceName}</span><span>/</span><strong id="breadcrumb-title">工作概览</strong></div>
        </div>
        <div class="topbar-actions">
          <button class="icon-button" data-action="theme" title="切换主题"><span data-theme-icon>${uiIcon('moon')}</span></button>
          <div class="profile">
            <span class="avatar" aria-hidden="true">${esc(state.me.name.slice(0, 1))}</span>
            <span><strong>${esc(state.me.account||state.me.student_id||state.me.name)}</strong></span>
          </div>
          <button class="icon-button" data-action="change-password" title="修改密码">${uiIcon('key')}</button>
          <button class="icon-button" data-action="logout" title="退出登录">${uiIcon('logout')}</button>
        </div>
      </header>
      <main class="main-content" id="main" tabindex="-1"></main>
    </div>
  </div>`;
  try{if(localStorage.getItem('volunteer_sidebar_collapsed')==='1')document.querySelector('.workspace')?.classList.add('sidebar-collapsed');}catch{}
  startInboxPolling();
}

try {
  const themeMedia = matchMedia('(prefers-color-scheme: dark)');
  if (themeMedia.addEventListener) {
    themeMedia.addEventListener('change', () => {
      if (themeMode() === 'system') applyTheme();
    });
  }
} catch (error) {
  /* 旧浏览器忽略系统主题变化 */
}

applyTheme();

/* 窄屏表格卡片化：只在浏览器里给表头补 data-label（测试桩没有 MutationObserver，自动跳过）。 */
function decorateTables(){
 if(typeof document==='undefined'||!document.getElementById)return;
 const main=document.getElementById('main');
 if(!main||!main.querySelectorAll)return;
 main.querySelectorAll('table').forEach(table=>{
  if(table.dataset&&table.dataset.cards==='1')return;
  const heads=Array.from(table.querySelectorAll('thead th')).map(th=>(th.textContent||'').trim());
  if(heads.length<4)return;
  if(table.dataset)table.dataset.cards='1';
  table.classList.add('table-cards');
  Array.from(table.querySelectorAll('tbody tr')).forEach(row=>{
   Array.from(row.querySelectorAll('td')).forEach((cell,index)=>{
    if(index>0&&heads[index])cell.setAttribute('data-label',heads[index]);
   });
  });
 });
}
if(typeof MutationObserver!=='undefined'&&typeof document!=='undefined'&&document.body){
 decorateTables();
 new MutationObserver(()=>decorateTables()).observe(document.body,{childList:true,subtree:true});
}
document.addEventListener('keydown',event=>{
 if(event.key!=='Escape')return;
 const workspace=document.querySelector('.workspace');
 if(workspace&&workspace.classList)workspace.classList.remove('menu-open');
});

start();
