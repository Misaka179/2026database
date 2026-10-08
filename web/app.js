'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label = {ACTIVE:'有效',DISABLED:'已停用',QUIT:'已退队',CANCELLED:'已取消',COMPLETED:'已完成',PENDING:'待处理',APPROVED:'已通过',REJECTED:'已驳回',NORMAL:'正常出勤',LATE:'迟到',ABSENT:'缺勤',LEAVE:'请假',VALID:'有效',VOID:'已作废',RETIRED:'历史版本',SUPER:'超级管理员',STUDENT:'志愿者'};
const roleName = r => ({SUPER:'超级管理员',NORMAL:'普通管理员',STUDENT:'志愿者'}[r] || '用户');
const operationNames = {PROMOTE_STUDENT:"将队员设为普通管理员",CORRECT_ATTENDANCE:"考勤改判与信用冲正",SET_STUDENT_CREDIT:"超级管理员调整信用分",SAVE_SEMESTER:'设置学期',SET_CALENDAR:'设置停工或调休',SYNC_SEMESTER:'核对学期排班',AUTO_WEEKLY_SETTLEMENT:'系统按周结算',IMPORT_ROSTER:'导入队员名单',CONFIGURE_SLOT:'设置时段负责人和容量',SET_MEMBERSHIPS:'设置队员归属',CREATE_STUDENT:'新增志愿者',CREATE_ADMIN:'新增管理员',CREATE_SLOT:'新增服务班次',CREATE_SCHEDULE:'建立排班',CANCEL_SCHEDULE:'取消排班',APPROVE_LEAVE:'审批请假',TRANSFER_FIRST:'换班初审',TRANSFER_FINAL:'换班终审',APPROVE_WITHDRAWAL:'确认退队',RECORD_ATTENDANCE:'登记考勤',REVISE_HOURS:'修正服务时长',SET_CREDIT_RULE:'修改信用规则'};
const fieldNames = {slots:'归属时段',refunded_score:'退还的实际扣分',revision:'考勤版本',credit_version:'信用版本',student_id:'学号',admin_id:'管理员编号',slot_id:'班次编号',schedule_id:'排班编号',attendance_id:'考勤编号',leave_id:'请假编号',transfer_id:'换班编号',withdrawal_id:'退队编号',record_id:'服务记录编号',rule_id:'规则编号',credit_log_id:'流水编号',name:'姓名',college:'学院',phone:'联系电话',credit_score:'信用分',status:'状态',reason:'原因',team_name:'分队名称',period_no:'时段编号',start_time:'开始时间',end_time:'结束时间',schedule_date:'服务日期',create_time:'创建时间',service_minutes:'服务分钟数',minutes:'服务分钟数',credit_before:'变化前信用分',credit_after:'变化后信用分',cancelled_schedules:'取消的排班',account:'登录账号',role:'角色',version:'规则版本',deduct_score:'规则扣分',record_status:'记录状态',attendance_status:'考勤状态',new_schedule_id:'新排班编号',student_status:'志愿者状态',date:'日期',apply_time:'申请时间',approve_admin_id:'审批管理员',approve_status:'审批状态',approve_time:'审批时间',old_schedule_id:'原排班编号',new_slot_id:'目标班次编号',new_date:'目标日期',first_admin_id:'初审管理员',first_status:'初审状态',first_time:'初审时间',final_admin_id:'终审管理员',final_status:'终审状态',final_time:'终审时间',active_marker:'有效标记',manager_admin_id:'负责人编号',need_num:'人数上限',service_date:'服务日期',violation_type:'违规类型',create_admin_id:'创建管理员',location:'地点'};
const app = $('#app');
const dialog = $('#action-dialog');
const state = {token:sessionStorage.getItem('volunteer_token'),me:null,role:null,page:'overview',tab:'',data:{},search:'',status:'',week:'current',selectedStudent:'',from:'',to:'',sequence:0,refreshSequence:0,sessionVersion:0,loading:false,refreshError:''};
let modalSubmit = null;
let previousFocus = null;
let modalVersion = 0;
let modalBusy = false;
const nav = [
  ['overview','工作概览',['SUPER','NORMAL','STUDENT']],['schedules','排班与考勤',['SUPER','NORMAL','STUDENT']],
  ['semesters','学期与日历',['SUPER','NORMAL','STUDENT']],['applications','申请与审批',['SUPER','NORMAL','STUDENT']],['hours','服务时长',['SUPER','STUDENT']],
  ['credit','信用管理',['SUPER','STUDENT']],['basics','基础资料',['SUPER']],['slots','服务班次',['NORMAL','STUDENT']],['logs','操作日志',['SUPER']],['members','本时段队员',['NORMAL']]
];
const empty = (title, text) => `<div class="empty"><div class="empty-symbol" aria-hidden="true">□</div><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
const badge = (value, override) => `<span class="badge ${['ACTIVE','APPROVED','NORMAL','VALID'].includes(value)?'good':['REJECTED','DISABLED','ABSENT','LATE'].includes(value)?'warning':value==='PENDING'?'pending':''}">${esc(override || label[value] || value || '未登记')}</span>`;
const fmtDate = value => value ? String(value).replace('T',' ').slice(0,16) : '未记录';
const hourText = value => `${Number((Number(value || 0)/60).toFixed(2))} 小时`;
const getDate = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const rowsOf = (arr, key, value) => (arr||[]).find(r => String(r[key]) === String(value));
function studentName(id) { const scheduled=rowsOf(state.data.schedules,'student_id',id);if(scheduled?.student_name)return scheduled.student_name;const s=rowsOf(state.data.students,'student_id',id);return s?s.name:(String(id)===String(state.me?.student_id)?state.me.name:id); }
function slotName(id) { const s=rowsOf(state.data.slots,'slot_id',id); return s?(s.weekday?s.team_name:`${s.team_name} · 第 ${s.period_no} 时段`):`班次 ${id}`; }
function adminName(id) {if(id===null||id===undefined)return '待分配';const a=rowsOf(state.data.admins,'admin_id',id);return a?a.name:`管理员 ${id}`;}
function table(headers, rows, blank='暂无记录', text='记录生成后会显示在这里。') {return rows.length?`<div class="table-wrap"><table><thead><tr>${headers.map(x=>`<th scope="col">${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:empty(blank,text);}
function tabs(items,current){return `<div class="tabs" role="tablist" aria-label="内容分类">${items.map(([v,t])=>`<button class="tab ${current===v?'active':''}" role="tab" aria-selected="${current===v}" data-tab="${v}">${t}</button>`).join('')}</div>`;}
function notify(text,error=false){const n=document.createElement('div');n.className='toast'+(error?' error':'');n.textContent=text;$('#notifications').append(n);setTimeout(()=>n.remove(),5000);}
function setTheme(theme){if(theme)document.documentElement.dataset.theme=theme;else delete document.documentElement.dataset.theme;}
setTheme(localStorage.getItem('volunteer_theme'));
function toggleTheme(){const dark=document.documentElement.dataset.theme==='dark'||(!document.documentElement.dataset.theme&&matchMedia('(prefers-color-scheme:dark)').matches);const theme=dark?'light':'dark';setTheme(theme);localStorage.setItem('volunteer_theme',theme);document.querySelectorAll('[data-action="theme"]').forEach(b=>b.textContent=dark?'深色外观':'浅色外观');}
function themeText(){return (document.documentElement.dataset.theme==='dark'||(!document.documentElement.dataset.theme&&matchMedia('(prefers-color-scheme:dark)').matches))?'浅色外观':'深色外观';}
async function request(path,options={}) {
  const token=state.token;const sessionVersion=state.sessionVersion;
  const headers = {'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})};
  let response;
  try {response=await fetch(path,{...options,headers:{...headers,...options.headers},signal:AbortSignal.timeout(path==='/students/import'?300000:15000)});}
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
function loginView(){
  document.title='登录 · 图书馆志愿服务';
  state.me=null;state.role=null;
  app.innerHTML=`<main class="login-page" id="main"><section class="login-story"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true">图</span><span><strong>图书馆志愿服务</strong><small>志愿队管理工作台</small></span></a><div class="login-story-main"><div class="eyebrow">服务有记录，协作更清楚</div><h1>把每一次志愿服务<br>安排妥当。</h1><p>从排班与申请，到考勤、服务时长和信用记录，在同一处完成日常管理。</p><div class="story-list"><div class="story-row"><strong>排班与考勤</strong><span>查看服务安排，记录实际出勤</span></div><div class="story-row"><strong>申请与审批</strong><span>请假、换班和退队，进度清晰可查</span></div><div class="story-row"><strong>时长与信用</strong><span>逐笔记录，保留每次变更的依据</span></div></div></div><div class="login-footer">四川大学图书馆志愿服务队</div></section><section class="login-side"><button class="theme-button" data-action="theme">${themeText()}</button><div class="login-form-wrap"><h2>欢迎回来</h2><p>使用你的账号登录工作台。</p><form id="login-form" class="form-stack" novalidate><div class="field"><label for="login-kind">登录身份</label><select id="login-kind" name="kind"><option value="admin">管理员</option><option value="student">志愿者</option></select></div><div class="field"><label for="login-account">账号</label><input id="login-account" name="account" autocomplete="username" placeholder="请输入管理员账号或学号" required maxlength="64"></div><div class="field"><label for="login-password">密码</label><div class="password-wrap"><input id="login-password" name="password" type="password" autocomplete="current-password" placeholder="请输入密码" required maxlength="128"><button type="button" class="btn" data-action="password" aria-label="显示密码">显示</button></div></div><div id="login-error" class="notice error" role="alert" hidden></div><button class="btn primary wide" type="submit">登录工作台</button></form><p class="login-help">不同角色登录后会看到对应的工作范围。<br>首次使用请向项目管理员获取账号和密码。</p><a class="text-button" href="/docs">查看中文接口说明 →</a></div></section></main>`;
}
function signOut(show=true){state.token=null;sessionStorage.removeItem('volunteer_token');state.data={};state.loading=false;state.refreshError='';state.sequence++;state.refreshSequence++;state.sessionVersion++;state.selectedStudent='';state.studentQuery='';state.from='';state.to='';closeDialog(true);loginView();if(show)notify('已退出登录。');}
function buildShell(){
 const available=nav.filter(n=>n[2].includes(state.role));
 if(!available.some(n=>n[0]===state.page))state.page='overview';
 app.innerHTML=`<div class="workspace"><aside class="sidebar" aria-label="主导航"><a href="/" class="brand"><span class="brand-mark" aria-hidden="true">图</span><span><strong>图书馆志愿服务</strong><small>管理工作台</small></span></a><div class="nav-label">日常工作</div><nav class="nav-list">${available.map(([id,title])=>`<button class="nav-link ${state.page===id?'active':''}" data-page="${id}" ${state.page===id?'aria-current="page"':''}>${title}</button>`).join('')}</nav><div class="sidebar-bottom"><a href="/docs">中文接口说明 ↗</a><div class="profile"><span class="avatar" aria-hidden="true">${esc(state.me.name.slice(-2))}</span><span><strong>${esc(state.me.name)}</strong><small>${roleName(state.role)}</small></span></div><button class="text-button" style="text-align:left" data-action="logout">退出登录</button></div></aside><div class="workspace-body"><header class="topbar"><div class="button-row"><button class="btn small mobile-menu" data-action="menu" aria-label="打开或关闭导航菜单">菜单</button><div class="breadcrumb"><span>管理工作台</span><span>/</span><strong id="breadcrumb-title">工作概览</strong></div></div><div class="topbar-actions"><span class="connection" id="connection">正在连接</span><button class="theme-button" data-action="theme">${themeText()}</button></div></header><main class="main-content" id="main" tabindex="-1"></main></div></div>`;
 request('/health').then(()=>{if($('#connection'))$('#connection').textContent='服务连接正常';}).catch(()=>{if($('#connection')){$('#connection').textContent='服务连接中断';$('#connection').classList.add('failed');}});
}
async function loadData(role=state.role){
 const data={};
 const tasks=[['semesters','/semesters'],['slots','/slots'],['schedules','/schedules'],['leave','/applications/leave'],['transfer','/applications/transfer']];
 if(role!=='NORMAL')tasks.push(['withdrawal','/applications/withdrawal']);
 if(role==='NORMAL')tasks.push(['students','/students']);
 if(role==='SUPER')tasks.push(['students','/students'],['admins','/admins']);
 if(role==='STUDENT')tasks.push(['hours','/hours'],['credit','/credit'],['memberships','/my-fixed-slots']);
 await Promise.all(tasks.map(async([key,path])=>{data[key]=await request(path);}));
 return data;
}
async function refresh(){
 if(!state.me||!$('#main'))return;
 // Loading the shared data must survive navigation; page-specific queries use sequence.
 const seq=++state.refreshSequence;const session=state.sessionVersion;
 state.sequence++;state.loading=true;state.refreshError='';renderPage();
 const current=()=>seq===state.refreshSequence&&session===state.sessionVersion&&state.me;
 try{
  const me=await request('/auth/me');if(!current())return;
  const role=me.role||'STUDENT';const data=await loadData(role);if(!current())return;
  const roleChanged=state.role!==role;
  state.me=me;state.role=role;state.data=data;state.loading=false;
  if(roleChanged)buildShell();
  renderPage();
 }catch(e){if(!current())return;state.loading=false;state.refreshError=e.message;renderPage();}
}
function navigate(page){state.page=page;state.tab='';state.search='';state.status='';state.sequence++;document.querySelector('.workspace')?.classList.remove('menu-open');renderPage();}
function heading(title,text,button=''){return `<div class="page-heading"><div><h1>${title}</h1><p>${text}</p></div>${button}</div>`;}
function canFuture(r){return r.status==='ACTIVE'&&new Date(`${r.schedule_date}T${r.start_time}:00+08:00`)>new Date();}
function isEnded(r){return new Date(`${r.schedule_date}T${r.end_time}:00+08:00`)<=new Date();}
function actionable(a,kind){if(kind==='transfer'&&!a.old_slot_id)return false;if(kind==='leave')return state.role==='NORMAL'&&a.approve_status==='PENDING';if(kind==='withdrawal')return state.role==='SUPER'&&a.approve_status==='PENDING';return state.role==='NORMAL'&&a.first_status==='PENDING'&&a.final_status==='PENDING'||state.role==='SUPER'&&a.first_status==='APPROVED'&&a.final_status==='PENDING';}
function appStatus(a,kind){if(kind!=='transfer')return[a.approve_status,label[a.approve_status]];if(a.first_status==='REJECTED')return['REJECTED','初审驳回'];if(a.final_status!=='PENDING')return[a.final_status,label[a.final_status]];return['PENDING',a.first_status==='APPROVED'?'待最终确认':'待初审'];}
function renderPage(){
 if(!state.me)return;
 const title=nav.find(x=>x[0]===state.page)?.[1]||'工作概览';
 $('#breadcrumb-title').textContent=title;
 document.title=`${title} · 图书馆志愿服务`;
 document.querySelectorAll('[data-page]').forEach(el=>{el.classList.toggle('active',el.dataset.page===state.page);if(el.dataset.page===state.page)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
 if(state.refreshError){$('#main').innerHTML=`<div class="panel"><div class="empty"><h3>暂时无法读取数据</h3><p>${esc(state.refreshError)}</p><button class="btn" data-action="refresh">重新加载</button></div></div>`;return;}
 if(state.loading||!Array.isArray(state.data.schedules)){$('#main').innerHTML='<div class="loading" role="status">正在读取最新记录…</div>';return;}
 const pages={semesters:semesterPage,overview:overview,schedules:schedulesPage,applications:applicationsPage,hours:hoursPage,credit:creditPage,basics:rosterBasicsPage,slots:slotsPage,logs:logsPage,members:membersPage};
 (pages[state.page]||overview)();
}
function overview(){
 const d=state.data;const today=getDate();const pending=['leave','transfer','withdrawal'].reduce((n,k)=>n+(d[k]||[]).filter(a=>state.role==='STUDENT'?appStatus(a,k)[0]==='PENDING':actionable(a,k)).length,0);
 const upcoming=d.schedules.filter(r=>canFuture(r)).sort((a,b)=>(a.schedule_date+a.start_time).localeCompare(b.schedule_date+b.start_time));
 const metrics=state.role==='STUDENT'?[['累计服务时长',Number((d.hours.total_minutes/60).toFixed(2)),'小时','按全部有效服务记录汇总'],['当前信用分',d.credit.credit_score,'分',label[d.credit.status]],['待处理申请',pending,'项','请假、换班和退队'],['每周固定班次',(d.memberships||[]).length,'个','可申请长期调整时段']]:[['今日排班',d.schedules.filter(r=>r.schedule_date===today&&r.status!=='CANCELLED').length,'人次','当前权限范围内的安排'],['待处理申请',pending,'项','需要你审批或确认'],['待登记考勤',d.schedules.filter(r=>r.status==='ACTIVE'&&isEnded(r)).length,'次','已结束但尚未登记'],[state.role==='SUPER'?'在队志愿者':'负责服务班次',state.role==='SUPER'?d.students.filter(s=>s.status==='ACTIVE').length:d.slots.filter(s=>s.manager_admin_id===state.me.admin_id).length,state.role==='SUPER'?'人':'个',state.role==='SUPER'?'当前正常参与服务':'仅显示你负责的班次']];
 $('#main').innerHTML=`<section class="welcome"><div><div class="eyebrow">${roleName(state.role)}工作台</div><h1>${esc(state.me.name)}，欢迎回来。</h1><p>${state.role==='STUDENT'?'查看接下来的服务安排，及时跟进你的申请。':'先处理待办，再确认接下来的服务安排。'}</p></div><div class="date-stamp"><strong>${today.slice(5).replace('-',' / ')}</strong>${today.slice(0,4)} 年 · ${new Intl.DateTimeFormat('zh-CN',{weekday:'long',timeZone:'Asia/Shanghai'}).format(new Date())}</div></section><section class="metrics" aria-label="工作概览统计">${metrics.map(([l,v,u,f])=>`<div class="metric"><div class="metric-label">${l}</div><div class="metric-value">${esc(v)}<small>${u}</small></div><div class="metric-foot">${esc(f)}</div></div>`).join('')}</section><div class="overview-grid"><div>${myFixedSlotsPanel()}<section class="panel"><header class="panel-header"><div><h2>接下来的服务</h2><p>按服务日期排序，显示最近五条安排</p></div><button class="text-button" data-page="schedules">查看全部 →</button></header>${scheduleTable(upcoming.slice(0,5),false)}</section><section class="panel"><header class="panel-header"><div><h2>${state.role==='STUDENT'?'申请进度':'审批待办'}</h2><p>${pending?`目前有 ${pending} 项申请等待处理`:'当前没有待处理申请'}</p></div><button class="text-button" data-page="applications">进入申请${state.role==='STUDENT'?'记录':'管理'} →</button></header><div class="panel-content">${pending?`<p class="muted">${state.role==='STUDENT'?'审批结果会显示在申请记录中。换班确认前，请仍按原排班参加服务。':'请先核对申请内容，再进行审批。换班需要初审通过后才能最终确认。'}</p>`:'<p class="muted">新的申请提交后，会出现在这里。</p>'}</div></section></div><div><section class="panel"><header class="panel-header"><h2>常用操作</h2></header><div class="panel-content quick-links">${state.role==='STUDENT'?quick('申请请假或换班','选择对应排班，填写申请原因','schedules'):quick('查看服务安排','核对班次、人员与考勤状态','schedules')}${quick(state.role==='STUDENT'?'查看服务时长':'处理申请',state.role==='STUDENT'?'逐笔查看已认定的服务记录':'请假、换班和退队审批',state.role==='STUDENT'?'hours':'applications')}${quick('查看服务班次','了解服务时间、地点与人数上限',state.role==='SUPER'?'basics':'slots')}</div></section><section class="panel panel-quiet"><header class="panel-header"><h2>工作提示</h2></header><div class="panel-content"><p class="rule-note">请假获批后不计服务时长，也不按缺勤扣分。</p><p class="rule-note">正常出勤和迟到均计完整班次时长。考勤需在班次结束后登记。</p><p class="rule-note">${state.role==='STUDENT'?'排班调整须等待最终确认，信用分归零后将暂停后续服务安排。':'重要修改会留下操作记录，便于后续核对。'}</p></div></section></div></div>`;
}
function quick(title,text,page){return `<button class="quick-link" data-page="${page}"><div><strong>${title}</strong><span>${text}</span></div><em aria-hidden="true">→</em></button>`;}
function scheduleTable(records,actions=true){return table(['服务日期','志愿者','服务班次','状态',...(actions?['操作']:[])],records.map(r=>`<tr><td><strong>${esc(r.schedule_date)}</strong><small>${r.week_no?`第 ${r.week_no} 周 · `:''}${esc(r.start_time)} 至 ${esc(r.end_time)}</small></td><td>${esc(studentName(r.student_id))}<small>${esc(r.student_id)}</small></td><td><strong>${esc(slotName(r.slot_id))}</strong><small>${esc(r.location)}</small></td><td>${badge(r.attendance_status||r.status)}${r.attendance_source==='AUTO_WEEKLY'?'<small>按周自动结算</small>':''}${r.leave_approved&&!r.attendance_status?'<small>请假已获批</small>':''}</td>${actions?`<td><div class="row-actions">${scheduleActions(r)}</div></td>`:''}</tr>`),'暂无具体日期排班','设置学期后按固定时段生成，用于请假及考勤。');}
function scheduleActions(r){
 if(state.role==='STUDENT')return canFuture(r)&&state.me.status==='ACTIVE'?`<button class="text-button" data-action="leave" data-id="${r.schedule_id}">请假</button>`:'<span class="muted">暂无可用操作</span>';
 let buttons='';
 if(['NORMAL','SUPER'].includes(state.role)&&r.status==='COMPLETED'&&r.attendance_status)buttons+=`<button class="text-button" data-action="attendance-correct" data-id="${r.schedule_id}">考勤改判</button>`;
 if(['NORMAL','SUPER'].includes(state.role)&&(r.status==='ACTIVE'||r.attendance_source==='AUTO_WEEKLY'&&r.attendance_status==='NORMAL')&&isEnded(r))buttons+=`<button class="text-button" data-action="attendance" data-id="${r.schedule_id}">登记考勤</button>`;
 if(canFuture(r))buttons+=`<button class="text-button" data-action="cancel" data-id="${r.schedule_id}">取消排班</button>`;
 return buttons||`<span class="muted">${r.status==='COMPLETED'?'已结算':r.status==='CANCELLED'?'已取消':'待服务结束'}</span>`;
}
function schedulesPage(){
 const term=currentSemester();
 const selectedWeek=state.week||'current';
 const inWeek=r=>!term||selectedWeek==='all'||r.semester_id===term.semester_id&&r.week_no===(selectedWeek==='current'?Math.max(1,term.current_week):Number(selectedWeek));
 const records=state.data.schedules.filter(r=>inWeek(r)&&(!state.status||r.status===state.status)&&(!state.search||`${r.student_id}${studentName(r.student_id)}${r.team_name}${r.schedule_date}`.includes(state.search))).sort((a,b)=>b.schedule_date.localeCompare(a.schedule_date));
 $('#main').innerHTML=heading('排班与考勤',state.role==='STUDENT'?'查看每周安排；请假选择具体日期，长期换时段从固定班次申请。':'每周自动计时；请及时登记缺勤、迟到等异常，获批请假不计时。',state.role!=='STUDENT'?'<button class="btn" data-action="schedule">例外手动排班</button>':'')+semesterNotice()+myFixedSlotsPanel()+`<div class="toolbar"><div class="filter-group">${term?`<select class="control" id="week-filter" aria-label="筛选周次"><option value="current" ${selectedWeek==='current'?'selected':''}>当前周（第 ${Math.max(1,term.current_week)} 周）</option><option value="all" ${selectedWeek==='all'?'selected':''}>全部日期</option>${Array.from({length:term.end_week},(_,i)=>`<option value="${i+1}" ${selectedWeek===String(i+1)?'selected':''}>第 ${i+1} 周</option>`).join('')}</select>`:''}<input class="control" id="search" aria-label="搜索排班" placeholder="搜索姓名、学号、分队或日期" value="${esc(state.search)}"><select class="control" id="status-filter" aria-label="筛选排班状态"><option value="">全部状态</option>${['ACTIVE','COMPLETED','CANCELLED'].map(v=>`<option value="${v}" ${state.status===v?'selected':''}>${label[v]}</option>`).join('')}</select><button class="btn" data-action="search">查询</button></div><button class="text-button" data-action="refresh">刷新记录</button></div><section class="panel">${scheduleTable(records)}</section>`;
}
function applicationsPage(){
 const choices=[['leave','请假申请'],['transfer','换班申请'],...(state.role!=='NORMAL'?[['withdrawal','退队申请']]:[])];
 const kind=state.tab||'leave';const rows=state.data[kind]||[];
 $('#main').innerHTML=heading('申请与审批',state.role==='STUDENT'?'申请提交后可在这里查看进度和处理结果。':'按权限查看申请，审批结果会同步影响后续服务安排。',state.role==='STUDENT'&&state.me.status==='ACTIVE'?`<button class="btn primary" data-action="${kind==='withdrawal'?'withdrawal':'new-application'}">${kind==='withdrawal'?'申请退队':'提交申请'}</button>`:'')+`<div class="toolbar">${tabs(choices,kind)}<button class="text-button" data-action="refresh">刷新记录</button></div><section class="panel">${table(['申请人','申请内容','申请原因','提交时间','进度','操作'],rows.map(a=>{const [status,text]=appStatus(a,kind);const id=a[kind==='leave'?'leave_id':kind==='transfer'?'transfer_id':'withdrawal_id'];const old=rowsOf(state.data.schedules,'schedule_id',a.schedule_id||a.old_schedule_id);return `<tr><td><strong>${esc(studentName(a.student_id))}</strong><small>${esc(a.student_id)}</small></td><td class="wrap">${applicationContent(a,kind,old)}</td><td class="wrap">${esc(a.reason)}</td><td>${fmtDate(a.apply_time)}</td><td>${badge(status,text)}</td><td>${actionable(a,kind)?`<button class="text-button" data-action="approve" data-kind="${kind}" data-id="${id}">${kind==='transfer'&&state.role==='SUPER'?'最终确认':'审批'}</button>`:'<span class="muted">暂无待办</span>'}</td></tr>`;}),'暂无这类申请',state.role==='STUDENT'?'固定班次换班可点击提交申请；请假需选择具体日期排班。':'申请提交后，会根据负责范围出现在这里。')}</section>`;
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
function queryForm(includeDates){return `<form class="query-form" id="query-form" novalidate>${state.role==='SUPER'?`<div class="field"><label for="query-student">志愿者</label>${studentSelect()}</div>`:''}${includeDates?`<div class="field"><label for="query-start">开始日期</label><input id="query-start" name="start" type="date" value="${state.from}"></div><div class="field"><label for="query-end">结束日期（不含当天）</label><input id="query-end" name="end" type="date" value="${state.to}"></div>`:''}<button class="btn primary" type="submit">查询记录</button>${state.role==='SUPER'?'<p class="query-help" id="student-query-help">支持部分学号或姓名；匹配多人时请按学号选择。</p>':''}</form>`;}
async function hoursPage(){
 const seq=++state.sequence;
 $('#main').innerHTML=heading('服务时长','按实际认定的有效记录汇总，可选择日期范围查看。',state.role==='SUPER'?'<button class="btn" data-action="hours-export">导出学期周时长</button>':'')+queryForm(true)+'<section class="panel" id="hours-result"><div class="loading" role="status">正在读取服务记录…</div></section>';
 if(state.role==='SUPER'&&!state.selectedStudent){$('#hours-result').innerHTML=empty('请输入学号或姓名','查询志愿者后查看服务时长。');return;}
 const query=new URLSearchParams();if(state.role==='SUPER')query.set('student_id',state.selectedStudent);if(state.from)query.set('start',state.from);if(state.to)query.set('end',state.to);
 try{const data=await request('/hours?'+query);if(seq!==state.sequence)return;state.data.hourRecords=data.records;$('#hours-result').innerHTML=queriedStudentLabel()+`<div class="summary-line"><strong>${Number((data.total_minutes/60).toFixed(2))}</strong><span>累计小时 · ${data.records.filter(r=>r.record_status==='VALID').length} 条有效记录</span></div>${table(['服务日期','服务班次','考勤结果','认定时长','记录状态',...(state.role==='SUPER'?['操作']:[])],data.records.map(r=>`<tr><td>${esc(r.schedule_date)}</td><td>${esc(slotName(r.slot_id))}</td><td>${badge(r.attendance_status)}</td><td><strong>${hourText(r.service_minutes)}</strong></td><td>${badge(r.record_status)}</td>${state.role==='SUPER'?`<td><button class="text-button" data-action="hours-edit" data-id="${r.record_id}">修正时长</button></td>`:''}</tr>`),'暂无服务记录','正常出勤或迟到完成登记后，认定时长将显示在这里。')}`;}catch(e){if(seq===state.sequence)$('#hours-result').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
}
async function creditPage(){
 const seq=++state.sequence;const kind=state.tab||'credit';
 $('#main').innerHTML=heading('信用管理','查看分数变化的依据，保留每次处理的历史记录。',state.role==='SUPER'&&kind==='rules'?'<button class="btn primary" data-action="rule">调整扣分规则</button>':'')+(state.role==='SUPER'?`<div class="toolbar">${tabs([['credit','信用流水'],['rules','信用规则']],kind)}</div>`:'')+(kind==='credit'&&state.role==='SUPER'?queryForm(false):'')+'<section class="panel" id="credit-result"><div class="loading" role="status">正在读取信用记录…</div></section>';
 if(kind==='credit'&&state.role==='SUPER'&&!state.selectedStudent){$('#credit-result').innerHTML=empty('请输入学号或姓名','查询志愿者后查看信用流水或调整信用分。');return;}
 try{if(kind==='rules'){const records=await request('/credit-rules');if(seq!==state.sequence)return;state.data.rules=records;$('#credit-result').innerHTML=table(['违规类型','规则版本','扣分标准','状态','创建时间'],records.map(r=>`<tr><td><strong>${label[r.violation_type]}</strong></td><td>第 ${r.version} 版</td><td>${r.deduct_score} 分</td><td>${badge(r.status,r.status==='ACTIVE'?'当前生效':'历史版本')}</td><td>${fmtDate(r.create_time)}</td></tr>`));return;}
 const data=await request('/credit'+(state.role==='SUPER'?'?student_id='+encodeURIComponent(state.selectedStudent):''));if(seq!==state.sequence)return;state.data.selectedCredit=data;
 $('#credit-result').innerHTML=queriedStudentLabel()+`<div class="summary-line"><strong>${data.credit_score}</strong><span>当前信用分</span>${state.role==='SUPER'?'<button class="btn primary" data-action="credit-set">调整信用分</button>':''}${badge(data.status,data.status==='ACTIVE'?'正常参与服务':label[data.status])}</div>${table(['发生时间','变更类型与原因','变化前','实际变动','变化后'],data.logs.map(r=>`<tr><td>${fmtDate(r.change_time)}</td><td class="wrap">${esc(({DEDUCTION:'考勤扣分',REVERSAL:'考勤冲正',MANUAL_SET:'超管调分'})[r.entry_type]||'信用变更')}<small>${esc(label[r.change_reason]||r.change_reason)}</small></td><td>${r.before_score} 分</td><td><strong>${r.change_score>0?'+':''}${r.change_score} 分</strong></td><td>${r.after_score} 分</td></tr>`),'暂无信用变动','当前没有扣分流水。信用分变化后，可在这里逐笔核对。')}<div class="section-footer">信用分最低为 0 分。实际扣分可能小于规则扣分，归零后将暂停后续服务安排。</div>`;
 }catch(e){if(seq===state.sequence)$('#credit-result').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
}
function slotTable(){if(state.data.slots.some(s=>s.weekday))return fixedSlotTable();return table(['服务班次','服务时间','地点','人数上限','标准时长','负责人'],state.data.slots.map(r=>`<tr><td><strong>${esc(r.team_name)}</strong><small>第 ${r.period_no} 时段 ${r.status==='DISABLED'?'（已停用）':''}</small></td><td>${esc(r.start_time)} 至 ${esc(r.end_time)}</td><td>${esc(r.location)}</td><td>${r.need_num} 人</td><td>${hourText(r.service_minutes)}</td><td>${esc(adminName(r.manager_admin_id))}</td></tr>`),'暂无服务班次','由超级管理员添加班次和负责人后显示。');}
function slotsPage(){ $('#main').innerHTML=heading('服务班次','查看班次时间、服务地点与人数上限。')+`<section class="panel">${slotTable()}</section>`;}
function basicsPage(){const kind=state.tab||'students';const titles={students:'志愿者',admins:'管理员',slots:'服务班次'};let content;
 if(kind==='students')content=table(['姓名与学号','学院','联系电话','信用分','状态'],state.data.students.map(s=>`<tr><td><strong>${esc(s.name)}</strong><small>${esc(s.student_id)}</small></td><td>${esc(s.college||'未填写')}</td><td>${esc(s.phone||'未填写')}</td><td>${s.credit_score} 分</td><td>${badge(s.status,s.status==='ACTIVE'?'在队':label[s.status])}</td></tr>`),'暂无志愿者','点击新增志愿者建立第一条记录。');
 else if(kind==='admins')content=table(['姓名','登录账号','关联队员','管理角色','负责时段','状态'],state.data.admins.map(a=>`<tr><td><strong>${esc(a.name)}</strong></td><td>${esc(a.account)}</td><td>${esc(a.student_id||'独立管理员')}</td><td>${roleName(a.role)}</td><td class="wrap">${a.role==='SUPER'?'全队管理':state.data.slots.filter(s=>s.weekday&&s.manager_admin_id===a.admin_id).map(s=>esc(s.team_name)).join('、')||'尚未分配'}</td><td>${badge(a.status,a.status==='ACTIVE'?'已启用':'已停用')}</td></tr>`));
 else content=slotTable();
 $('#main').innerHTML=heading('基础资料','维护志愿者、管理员及服务班次。',`<button class="btn primary" data-action="create-${kind}">新增${titles[kind]}</button>`)+`<div class="toolbar">${tabs([['students','志愿者'],['admins','管理员'],['slots','服务班次']],kind)}</div><section class="panel">${content}</section>`;
}
async function logsPage(){const seq=++state.sequence;$('#main').innerHTML=heading('操作日志','查看最近 100 条重要操作，核对修改前后的内容。','<button class="btn" data-action="refresh">刷新日志</button>')+'<section class="panel" id="logs-result"><div class="loading" role="status">正在读取操作日志…</div></section>';try{const rows=await request('/operation-logs');if(seq!==state.sequence)return;state.data.logs=rows;$('#logs-result').innerHTML=table(['操作时间','操作人员','操作内容','说明','操作'],rows.map(r=>`<tr><td>${fmtDate(r.operation_time)}</td><td>${esc(adminName(r.admin_id))}</td><td>${esc(operationNames[r.operation_type]||'数据操作')}</td><td class="wrap">${esc(r.reason||'未附加说明')}</td><td><button class="text-button" data-action="log-detail" data-id="${r.log_id}">查看详情</button></td></tr>`),'暂无操作日志','新增资料、审批和考勤等重要操作会自动留存记录。');}catch(e){if(seq===state.sequence)$('#logs-result').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}}

// All destructive or consequential business actions go through a named dialog.
function openDialog(title,subtitle,fields,onSubmit,button='确认提交'){
 if(modalBusy)return;
 previousFocus=document.activeElement;modalSubmit=onSubmit;modalVersion++;
 dialog.innerHTML=`<header class="dialog-header"><div><h2 id="dialog-title">${esc(title)}</h2><p>${esc(subtitle)}</p></div><button class="close-button" data-action="close">关闭</button></header><div class="dialog-body"><form id="action-form" novalidate><div class="form-grid">${fields}</div><div id="action-error" class="notice error" role="alert" hidden></div><footer class="dialog-footer"><button type="button" class="btn" data-action="close">取消</button><button class="btn primary" type="submit">${esc(button)}</button></footer></form></div>`;
 dialog.showModal();
}
function setModalBusy(busy){modalBusy=busy;dialog.querySelectorAll('[data-action="close"]').forEach(button=>button.disabled=busy);}
function closeDialog(force=false){if(modalBusy&&!force)return;setModalBusy(false);modalVersion++;if(dialog.open)dialog.close();modalSubmit=null;previousFocus?.focus?.();}
function field(name,title,{type='text',value='',options,required=true,full=false,help='',min,max,step,placeholder='',maxLength}={}){
 const attrs=`id="f-${name}" name="${name}" ${required?'required':''} ${min!==undefined?`min="${min}"`:''} ${max!==undefined?`max="${max}"`:''} ${step!==undefined?`step="${step}"`:''} ${maxLength?`maxlength="${maxLength}"`:''}`;
 const input=options?`<select ${attrs}>${options.map(([v,t])=>`<option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(t)}</option>`).join('')}</select>`:type==='textarea'?`<textarea ${attrs} placeholder="${esc(placeholder)}">${esc(value)}</textarea>`:`<input ${attrs} type="${type}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${type==='password'?'autocomplete="new-password"':''}>`;
 return `<div class="field ${full?'full':''}"><label for="f-${name}">${esc(title)}${!required?'<span class="required-label">选填</span>':''}</label>${input}${help?`<small>${esc(help)}</small>`:''}</div>`;
}
const reasonField=()=>field('reason','原因说明',{type:'textarea',full:true,maxLength:500,placeholder:'请填写具体原因，便于审批和后续核对'});
function scheduleOptions(){return state.data.schedules.filter(canFuture).map(r=>[r.schedule_id,`${r.schedule_date} ${slotName(r.slot_id)}`]);}
function action(name,id,kind){
 if(modalBusy)return;
 if(semesterAction(name,id)||rosterAction(name,id))return;
 const r=rowsOf(state.data.schedules,'schedule_id',id);
 if(name==='leave'){
  const opts=id?[[id,`${r.schedule_date} ${slotName(r.slot_id)}`]]:scheduleOptions();
  if(!opts.length)return notify('请假需要具体服务日期，请联系管理员检查学期日历与时段配置。',true);
  return openDialog('提交请假申请','请假获批后不计服务时长，也不按缺勤扣分。',field('schedule_id','对应排班',{options:opts,full:true})+reasonField(),v=>send('/applications/leave',{schedule_id:Number(v.schedule_id),reason:v.reason}));
 }
 if(name==='transfer')return rosterAction('fixed-transfer');
 if(name==='new-application')return action((state.tab||'leave')==='transfer'?'transfer':'leave');
 if(name==='withdrawal')return openDialog('申请退出志愿队','获批后将取消未来未开始的排班，历史服务和信用记录会保留。',reasonField(),v=>send('/applications/withdrawal',v),'提交退队申请');
 if(name==='schedule'){
  const slots=state.data.slots.filter(s=>s.status==='ACTIVE'&&(state.role==='SUPER'||s.manager_admin_id===state.me.admin_id));
  if(!slots.length)return notify('当前没有可管理的有效班次，请先建立班次。',true);
  return openDialog('新增排班','系统会检查该日期的班次容量及志愿者时间冲突。',(state.role==='SUPER'?field('student_id','志愿者',{options:state.data.students.filter(s=>s.status==='ACTIVE').map(s=>[s.student_id,`${s.name}（${s.student_id}）`]),full:true}):field('student_id','志愿者学号',{full:true,maxLength:32}))+field('slot_id','服务班次',{options:slots.map(s=>[s.slot_id,`${slotName(s.slot_id)}`]),full:true})+field('schedule_date','服务日期',{type:'date',min:getDate(),full:true}),v=>send('/schedules',{...v,slot_id:Number(v.slot_id)}),'确认排班');
 }
 if(name==='cancel')return openDialog('取消这次排班',`${r.schedule_date} ${studentName(r.student_id)}，${slotName(r.slot_id)}。关联的未完成申请也将取消。`,reasonField(),v=>send(`/schedules/${id}/cancel`,v),'确认取消排班');
 if(name==='attendance-correct')return openDialog('考勤改判与信用冲正',`${studentName(r.student_id)}，${r.schedule_date}，当前为${label[r.attendance_status]}。改判将同步修正时长，撤销旧违规并退还原实际扣分，再按新结果处理。`,field('status','正确的考勤结果',{options:[['NORMAL','正常出勤（恢复认定时长）'],['LATE','迟到（计完整时长，按规则扣分）'],['ABSENT','无故缺勤（不计时长，按规则扣分）'],['LEAVE','事后确认请假（不计时长、不扣分）']],value:r.attendance_status,full:true})+reasonField(),v=>send(`/schedules/${id}/attendance`,{...v,expected_revision:r.attendance_revision},'PATCH'),'确认改判');
 if(name==='credit-set'){
  const data=state.data.selectedCredit;if(!data)return notify('请先查询该队员的信用记录。',true);
  return openDialog('调整队员信用分',`${studentName(data.student_id)}（${data.student_id}），当前 ${data.credit_score} 分。新分数与原因会写入信用流水和操作日志。归零将暂停服务，因信用归零停用的队员恢复正分后可继续服务。`,field('credit_score','调整后的信用分',{type:'number',value:data.credit_score,min:0,max:2147483647,step:1,full:true})+reasonField(),v=>send(`/students/${encodeURIComponent(data.student_id)}/credit`,{credit_score:Number(v.credit_score),expected_version:data.credit_version,reason:v.reason},'PUT'),'保存信用分');
 }
 if(name==='attendance')return openDialog('登记考勤',`${studentName(r.student_id)}，${r.schedule_date}，${slotName(r.slot_id)}。本周未登记异常的服务会自动结算。自动认定的正常出勤可补录缺勤或迟到，须填写原因。`,(r.leave_approved?'<div class="notice field full">该排班的请假已经获批，系统将按请假处理。</div>':'')+field('status','出勤情况',{options:r.attendance_source==='AUTO_WEEKLY'?[['LATE','补录迟到（计完整时长）'],['ABSENT','补录缺勤（撤销自动时长）']]:r.leave_approved?[['LEAVE','已批准请假']]:[['NORMAL','正常出勤'],['LATE','迟到（计完整时长）'],['ABSENT','无故缺勤']],full:true})+field('remark','考勤备注',{type:'textarea',required:r.attendance_source==='AUTO_WEEKLY',full:true,maxLength:500}),v=>send('/attendance',{...v,schedule_id:Number(id)}),'确认并结算');
 if(name==='approve'){
  const a=rowsOf(state.data[kind],kind==='leave'?'leave_id':kind==='transfer'?'transfer_id':'withdrawal_id',id);
  let path=kind==='transfer'?`/applications/transfer/${id}/${state.role==='SUPER'?'final':'first'}`:`/applications/${kind}/${id}/decision`;
  return openDialog(kind==='transfer'&&state.role==='SUPER'?'确认换班结果':'审批申请',`${studentName(a.student_id)}：${a.reason}`,field('approved','审批结果',{options:[['true','通过申请'],['false','驳回申请']],full:true}),v=>send(path,{approved:v.approved==='true'}),'确认审批');
 }
 if(name==='hours-edit'){const record=rowsOf(state.data.hourRecords,'record_id',id);return openDialog('修正服务时长','修改具体服务记录，变更前后值与原因将写入操作日志。',field('service_minutes','认定时长（分钟）',{type:'number',value:record.service_minutes,min:0,max:1440,step:1,full:true,help:'60 分钟等于 1 小时。'})+reasonField(),v=>send(`/service-records/${id}`,{service_minutes:Number(v.service_minutes),reason:v.reason},'PATCH'),'保存修正');}
 if(name==='rule')return openDialog('调整扣分规则','将生成新的规则版本，已发生的违规保留原来的扣分依据。',field('violation_type','违规类型',{options:[['LATE','迟到'],['ABSENT','无故缺勤']]})+field('deduct_score','扣分数值',{type:'number',min:0,max:100,step:1})+reasonField(),v=>send('/credit-rules/'+v.violation_type,{deduct_score:Number(v.deduct_score),reason:v.reason},'PUT'),'发布新规则');
 if(name==='create-students')return openDialog('新增志愿者','新志愿者初始信用为 5 分。',field('student_id','学号',{maxLength:32,help:'仅使用字母、数字、下划线或连字符。'})+field('name','姓名',{maxLength:100})+field('college','学院',{required:false,maxLength:100})+field('phone','联系电话',{required:false,maxLength:32})+field('password','初始密码',{type:'password',full:true,maxLength:128,help:'设置 8 至 128 个字符的密码。'}),v=>send('/students',v),'创建志愿者');
 if(name==='create-admins')return openDialog('新增管理员','按实际职责分配权限，普通管理员只能处理负责的班次。',field('name','姓名',{maxLength:100})+field('account','登录账号',{maxLength:64})+field('role','管理角色',{options:[['NORMAL','普通管理员'],['SUPER','超级管理员']],full:true})+field('password','初始密码',{type:'password',full:true,maxLength:128,help:'设置 8 至 128 个字符的密码。'}),v=>send('/admins',v),'创建管理员');
 if(name==='create-slots')return notify('班次固定为每周 35 个时段，请使用时段设置。',true);
 if(name==='legacy-create-slot-disabled')return openDialog('新增服务班次','第 3 时段正常计 3 小时，其余时段计 2 小时。班次须在同一天内结束。',field('team_name','分队名称',{maxLength:100})+field('period_no','时段编号',{type:'number',min:1,max:100,step:1})+field('start_time','开始时间',{type:'time'})+field('end_time','结束时间',{type:'time'})+field('location','服务地点',{maxLength:200})+field('need_num','人数上限',{type:'number',min:1,max:10000,step:1})+field('manager_admin_id','负责管理员',{options:state.data.admins.filter(a=>a.role==='NORMAL'&&a.status==='ACTIVE').map(a=>[a.admin_id,a.name]),full:true}),v=>send('/slots',{...v,period_no:Number(v.period_no),need_num:Number(v.need_num),manager_admin_id:Number(v.manager_admin_id)}),'建立班次');
 if(name==='log-detail'){
  const record=rowsOf(state.data.logs,'log_id',id);
  const displayValue=(key,value)=>value===null||value===undefined||value===''?'未填写':Array.isArray(value)?value.map(v=>key==='slots'?`${slotName(v)}（编号 ${v}）`:v).join('、')||'无':key==='role'?roleName(value):typeof value==='boolean'?(value?'是':'否'):label[value]??value;
  const details=value=>{let data=value;if(typeof data==='string'){try{data=JSON.parse(data);}catch{return esc(data);}}return data?`<dl class="data-list">${Object.entries(data).filter(([k])=>!k.includes('password')).map(([k,v])=>`<dt>${esc(fieldNames[k]||'关联信息')}</dt><dd>${esc(displayValue(k,v))}</dd>`).join('')}</dl>`:'<p class="muted">无</p>';};
  previousFocus=document.activeElement;modalSubmit=null;modalVersion++;dialog.innerHTML=`<header class="dialog-header"><div><h2 id="dialog-title">${esc(operationNames[record.operation_type]||'操作详情')}</h2><p>${fmtDate(record.operation_time)}，${esc(adminName(record.admin_id))}</p></div><button class="close-button" data-action="close">关闭</button></header><div class="dialog-body"><p>${esc(record.reason||'未附加说明')}</p><div class="log-values"><h3>修改前</h3>${details(record.before_value)}<hr><h3>修改后</h3>${details(record.after_value)}</div></div>`;return dialog.showModal();
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
 const target=e.target.closest('button,[data-page]');if(!target)return;
 if(target.dataset.page){navigate(target.dataset.page);return;}
 if(target.dataset.tab){state.tab=target.dataset.tab;renderPage();return;}
 const name=target.dataset.action;
 if(name==='hours-export'&&state.role==='SUPER'){
  const semesters=state.data.semesters||[];
  if(!semesters.length)return notify('请先在学期与日历中设置学期。',true);
  return openDialog('导出学期周时长','导出所选学期全队名单，不受页面的个人查询和日期筛选影响。每周表头包含日期范围，未到周留空，当前周仅含已认定时长。',
   field('semester_id','导出学期',{options:semesters.map(s=>[s.semester_id,`${s.name}（${s.start_date} 至 ${s.end_date}）`]),value:currentSemester()?.semester_id,full:true}),
   async values=>{
    const session=state.sessionVersion;
    const response=await fetch('/hours/export?'+new URLSearchParams({semester_id:values.semester_id}),{headers:{Authorization:`Bearer ${state.token}`},signal:AbortSignal.timeout(120000)});
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
 if(name==='search'){state.search=$('#search').value.trim();state.status=$('#status-filter').value;state.week=$('#week-filter')?.value||'current';return schedulesPage();}
 try{action(name,target.dataset.id,target.dataset.kind);}catch{notify('操作暂时无法打开，请刷新后重试。',true);}
});
dialog.addEventListener('cancel',e=>{e.preventDefault();if(!modalBusy)closeDialog();});
document.addEventListener('submit',async e=>{
 e.preventDefault();const form=e.target;
 if(form.id==='query-form'){const values=Object.fromEntries(new FormData(form));state.from=values.start||'';state.to=values.end||'';if(state.role==='SUPER'){state.studentQuery=(values.student_query||'').trim();queryStudent();}else renderPage();return;}
 if(!['login-form','action-form'].includes(form.id))return;
 if(form.id==='action-form'&&(modalBusy||!dialog.open))return;
 const errorEl=form.id==='login-form'?$('#login-error'):$('#action-error');
 errorEl.hidden=true;const error=validate(form);if(error){errorEl.textContent=error;errorEl.hidden=false;return;}
 const submit=form.querySelector('[type="submit"]');const oldText=submit.textContent;submit.disabled=true;submit.textContent=form.id==='login-form'?'正在登录…':'正在提交…';
 const values=Object.fromEntries(new FormData(form));
 const session=state.sessionVersion;const version=modalVersion;
 try{
  if(form.id==='login-form'){
   const data=await send('/auth/login',values);if(session!==state.sessionVersion)return;state.sessionVersion++;state.token=data.access_token;sessionStorage.setItem('volunteer_token',state.token);
   state.me=await request('/auth/me');state.role=state.me.role||'STUDENT';state.page='overview';buildShell();await refresh();
  }else{
   const callback=modalSubmit;if(!callback)return;
   // Keep the dialog open and preserve user input if the request fails.
   setModalBusy(true);const result=await callback(values);
   if(session!==state.sessionVersion)return;
   if(version===modalVersion){setModalBusy(false);closeDialog();}
   notify(result?.downloaded?'导出文件已下载。':'操作已完成，记录已更新。');if(!result?.downloaded)await refresh();
  }
 }catch(ex){if(form.id==='action-form'&&(session!==state.sessionVersion||version!==modalVersion))return;if(errorEl.isConnected){errorEl.textContent=ex.message;errorEl.hidden=false;}else notify(ex.message,true);}
 finally{if(form.id==='action-form'&&version===modalVersion)setModalBusy(false);submit.disabled=false;submit.textContent=oldText;}
});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.id==='search'){e.preventDefault();state.search=e.target.value.trim();state.status=$('#status-filter').value;state.week=$('#week-filter')?.value||'current';schedulesPage();}});
async function start(){
 if(!state.token){loginView();return;}
 try{state.me=await request('/auth/me');state.role=state.me.role||'STUDENT';buildShell();await refresh();}
 catch{signOut(false);}
}
start();
