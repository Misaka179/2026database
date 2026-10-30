'use strict';
async function leadersPage(){
 const seq=++state.sequence;
 $('#main').innerHTML=heading('分队与美育负责人','任命现有队员；负责人账号与志愿者共用当前密码，保留原有普通管理员身份。')+'<section class="panel" id="leaders-list">正在读取…</section>';
 try{const rows=await request('/leaders');if(seq!==state.sequence)return;state.data.leaders=rows;
 $('#leaders-list').innerHTML=table(['管理范围','负责人','负责人登录账号','操作'],rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.admin_name||'尚未任命')}<small>${esc(r.student_id||'')}</small></td><td>${esc(r.account||'—')}</td><td><button class="text-button" data-action="appoint-leader" data-id="${r.scope_id}">任命／更换</button>${r.admin_id?`<button class="text-button" data-action="remove-leader" data-id="${r.scope_id}">撤销任命</button>`:''}</td></tr>`));
 }catch(e){if(seq===state.sequence)$('#leaders-list').innerHTML=`<p class="notice error">${esc(e.message)}</p>`;}
}
function leaderWorkspacePage(){
 const d=state.data, kind=state.leadTab||'schedules';
 const options=[['schedules','排班与考勤'],['members','队员与密码'],['slots','时段设置'],['hours','服务时长'],['withdrawal','退队初审'],['reports','工作日报'],['logs','操作日志']];
 const filter=`<div class="toolbar"><input class="control" id="lead-search" aria-label="学号或姓名" placeholder="输入学号或姓名" value="${esc(state.leadSearch||'')}"><input class="control" type="date" id="lead-from" aria-label="开始日期" value="${esc(state.leadFrom||'')}"><input class="control" type="date" id="lead-to" aria-label="结束日期（含当天）" value="${esc(state.leadTo||'')}"><button class="btn" data-action="lead-filter">查询</button></div>`;
 const matches=r=>(!state.leadSearch||`${r.student_id}${r.student_name||r.name||studentName(r.student_id)}`.includes(state.leadSearch))&&(!state.leadFrom||!r.schedule_date||r.schedule_date>=state.leadFrom)&&(!state.leadTo||!r.schedule_date||r.schedule_date<=state.leadTo);
 let content='';
 if(kind==='schedules')content=filter+scheduleTable(d.schedules.filter(matches));
 if(kind==='slots')content=fixedSlotTable();
 if(kind==='members')content=filter+table(['学号','姓名','学院','本范围归属','状态','操作'],d.students.filter(matches).map(s=>`<tr><td>${esc(s.student_id)}</td><td>${esc(s.name)}</td><td>${esc(s.college)}</td><td>${s.slots.map(t=>esc(t.name)).join('、')||'历史队员'}</td><td>${badge(s.status)}</td><td>${s.can_reset?`<button class="text-button" data-action="reset-student-password" data-id="${esc(s.student_id)}">重置密码</button>${s.status==='ACTIVE'?`<button class="text-button" data-action="promote-student" data-id="${esc(s.student_id)}">设置时段管理员</button>`:''}`:'仅查看'}</td></tr>`));
 if(kind==='hours'){
  const records=d.records.filter(matches);const total=records.filter(r=>r.record_status==='VALID').reduce((n,r)=>n+r.service_minutes,0);
  content=filter+`<div class="toolbar"><strong>筛选范围已认定：${hourText(total)}</strong><select class="control" id="lead-export-term" aria-label="导出学期">${d.semesters.map(t=>`<option value="${t.semester_id}">${esc(t.name)}</option>`).join('')}</select><button class="btn" data-action="lead-export">导出本范围学期报表</button></div><p class="rule-note">导出按所选完整学期，仅包含你的管理范围；不使用上方名单和日期筛选。</p>`+table(['服务日期','队员','时段','时长','状态'],records.map(r=>`<tr><td>${esc(r.schedule_date)}</td><td>${esc(r.student_name)}<small>${esc(r.student_id)}</small></td><td>${esc(r.team_name)}</td><td>${hourText(r.service_minutes)}</td><td>${badge(r.record_status)}</td></tr>`));
 }
 if(kind==='withdrawal')content=table(['队员','申请时间','原因','初审','终审','操作'],d.withdrawal.map(r=>`<tr><td>${esc(studentName(r.student_id))}<small>${esc(r.student_id)}</small></td><td>${fmtDate(r.apply_time)}</td><td class="wrap">${esc(r.reason)}</td><td>${badge(r.first_status)}<small>${esc(r.first_reason)}</small></td><td>${badge(r.approve_status)}</td><td>${r.first_status==='PENDING'&&r.approve_status==='PENDING'?`<button class="text-button" data-action="leader-withdrawal" data-id="${r.withdrawal_id}">初审</button>`:'已处理'}</td></tr>`));
 if(kind==='reports')content='<p class="rule-note">当天最后一个实际排班结束后生成。日报是生成时快照，预计时长不代表已入账；正式时长继续按周结算，累计仅包含本范围。截至任命当日起补齐停机期间日报。</p>'+table(['工作日期','范围','生成时间','操作'],d.reports.map(r=>`<tr><td>${esc(r.service_date)}</td><td>${esc(r.name)}</td><td>${fmtDate(r.created_at)}</td><td><button class="text-button" data-action="leader-report" data-id="${r.report_id}">查看日报</button></td></tr>`));
 if(kind==='logs')content=table(['时间','操作人','操作','关联信息','说明'],d.logs.map(r=>`<tr><td>${fmtDate(r.operation_time)}</td><td>${esc(r.operator_name)}</td><td>${esc(operationNames[r.operation_type]||r.operation_type)}</td><td>${esc(({schedule:'排班',service_slot:'时段',attendance:'考勤',service_record:'服务记录'})[r.target_table]||r.target_table)} #${esc(r.target_id)}</td><td class="wrap">${esc(r.reason)}</td></tr>`));
 $('#main').innerHTML=heading('负责人工作台',d.scopes.length?d.scopes.map(r=>r.name).join('、')+' · 仅显示授权范围；信用规则、手动调分和时长修正由全局超管处理。':'尚未获得管理范围，请联系全局超级管理员。','<button class="btn" data-action="refresh">刷新</button>')+`<div class="toolbar"><div class="tabs" role="tablist">${options.map(([id,name])=>`<button class="tab ${kind===id?'active':''}" data-action="lead-tab" data-id="${id}" role="tab" aria-selected="${kind===id}">${name}</button>`).join('')}</div></div><section class="panel">${content}</section>`;
}
async function showLeaderReport(id){
 try{const r=await request(`/leader-reports/${id}`),p=r.payload;
  openDialog(`${r.name} ${r.service_date} 工作日报`,'日报为生成时快照。未登记异常按默认出勤预计；累计为本范围截至该日已入账时长。',`<div class="field full"><p>预计 ${hourText(p.expected_minutes)}；已认定 ${hourText(p.recognized_minutes)}</p>${table(['队员','时段','考勤','预计时长','已认定时长','累计时长'],p.rows.map(x=>`<tr><td>${esc(x.name)}<small>${esc(x.student_id)}</small></td><td>${esc(x.team_name)}</td><td>${x.status==='CANCELLED'?'已取消':esc(label[x.attendance_status]||'默认出勤（未结算）')}</td><td>${hourText(x.expected_minutes)}</td><td>${hourText(x.recognized_minutes)}</td><td>${hourText(x.cumulative_minutes)}</td></tr>`))}</div>`,async()=>{},'关闭');scrollableDialog();
 }catch(e){notify(e.message,true);}
}
function leaderAction(name,id){
 if(name==='lead-tab'){state.leadTab=id;leaderWorkspacePage();return true;}
 if(name==='lead-filter'){state.leadSearch=$('#lead-search').value.trim();state.leadFrom=$('#lead-from').value;state.leadTo=$('#lead-to').value;leaderWorkspacePage();return true;}
 if(name==='leader-report'){showLeaderReport(id);return true;}
 if(name==='appoint-leader'||name==='remove-leader'){
  const r=rowsOf(state.data.leaders,'scope_id',id),remove=name==='remove-leader';
  openDialog((remove?'撤销任命：':'任命负责人：')+r.name,'负责人仅有已约定的本范围权限。更换立即撤销上一负责人的该范围权限。',
   (remove?'':field('student_id','队员学号',{full:true,maxLength:32,help:'填写已在系统登记的在队队员学号；登录账号将为 lead-学号，密码使用其当前志愿者密码。'})+`<div class="field full"><input class="control" id="leader-person-search" placeholder="按学号或姓名查找队员" aria-label="查找任命人选"><div id="leader-person-results"></div></div>`)+reasonField(),async v=>{const result=await send(`/leaders/${id}`,{student_id:remove?null:v.student_id.trim(),reason:v.reason},'PUT');if(result.account)notify(`负责人账号：${result.account}；使用该队员当前志愿者密码。`);return result;},remove?'确认撤销':'确认任命');
  if(!remove)$('#leader-person-search').oninput=()=>{const q=$('#leader-person-search').value.trim();$('#leader-person-results').innerHTML=q?(state.data.students||[]).filter(s=>s.status==='ACTIVE'&&`${s.student_id}${s.name}`.includes(q)).slice(0,15).map(s=>`<button type="button" class="text-button" data-pick-leader="${esc(s.student_id)}">${esc(s.name)} ${esc(s.student_id)}</button>`).join(''):'';$('#leader-person-results').onclick=e=>{const b=e.target.closest('[data-pick-leader]');if(b)$('#f-student_id').value=b.dataset.pickLeader;};};
  return true;
 }
 if(name==='leader-withdrawal'){
  openDialog('退队初审','初审通过后仍须全局超管终审；初审不会直接退出志愿队。',field('approved','初审结果',{options:[['true','通过，提交全局超管'],['false','不通过']],full:true})+reasonField(),v=>send(`/applications/withdrawal/${id}/first`,{approved:v.approved==='true',reason:v.reason}),'确认初审');return true;
 }
 if(name==='lead-export'){
  const term=$('#lead-export-term')?.value;if(!term){notify('尚无可导出学期',true);return true;}
  (async()=>{try{const res=await fetch(`/hours/export?semester_id=${term}`,{headers:{Authorization:`Bearer ${state.token}`}});if(!res.ok)throw new Error((await res.json()).detail||'导出失败');const u=URL.createObjectURL(await res.blob()),a=document.createElement('a');a.href=u;a.download='本范围学期时长.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}catch(e){notify(e.message,true);}})();return true;
 }
 return false;
}
