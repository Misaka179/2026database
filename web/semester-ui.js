'use strict';
const weekdayText = n => n ? `周${'一二三四五六日'[n-1]}` : '不上工';
const semModeNames = {NORMAL:'正常服务',HOLIDAY:'节假日停工',MAKEUP_REQUIRED:'待指定调休班表',UNCONFIRMED:'待核对日历',REST:'手动停工',CUSTOM:'调休'};

function semParse(value){const [y,m,d]=String(value).split('-').map(Number);return new Date(Date.UTC(y,m-1,d));}
function semIso(date){return `${date.getUTCFullYear()}-${String(date.getUTCMonth()+1).padStart(2,'0')}-${String(date.getUTCDate()).padStart(2,'0')}`;}
function semAdd(value,days){const date=semParse(value);date.setUTCDate(date.getUTCDate()+days);return semIso(date);}
function semWeekday(value){const date=semParse(value);return date.getUTCDay()||7;}
function semMonday(value){return semAdd(value,1-semWeekday(value));}
function semDateText(value){return value?`${value.slice(5).replace('-','/')}`:'';}
function semMonthDay(value){const date=semParse(value);return `${date.getUTCMonth()+1}月${date.getUTCDate()}日`;}
function currentSemester(){
 const rows=state.data.semesters||[];
 return rows.find(s=>s.phase==='ONGOING')||rows.filter(s=>s.phase==='UPCOMING').sort((a,b)=>a.start_date.localeCompare(b.start_date))[0]||rows[0];
}
function semesterNotice(){
 const s=currentSemester();
 if(!s)return '';
 const progress=s.phase==='ENDED'?'已结束':s.phase==='UPCOMING'?'待开工':`第 ${Math.max(1,s.current_week)} 周`;
 return `<div class="semester-line"><strong>${esc(s.name)}</strong><span>${progress}</span><span>${esc(s.start_date)} 至 ${esc(s.end_date)}</span></div>`;
}
function semCalendarState(day,date){
 if(!day)return {symbol:'?',kind:'pending',label:'待确认',note:'尚未生成日历'};
 const actual=semWeekday(date);
 const mode=day.mode;
 if(mode==='HOLIDAY'||mode==='REST')return {symbol:'⊘',kind:'stop',label:mode==='HOLIDAY'?'节假日停工':'手动停工',note:day.note||''};
 if(mode==='MAKEUP_REQUIRED'||mode==='UNCONFIRMED')return {symbol:'?',kind:'pending',label:semModeNames[mode],note:day.note||''};
 if(mode==='CUSTOM'&&day.effective_weekday&&Number(day.effective_weekday)!==actual)
  return {symbol:'⇄',kind:'makeup',label:`调休 · 执行${weekdayText(Number(day.effective_weekday))}班表`,note:day.note||''};
 return {symbol:'●',kind:'normal',label:'正常服务',note:day.note||''};
}
function semWeekRows(semester){
 const start=semester.start_date,end=semester.end_date;
 const map=new Map();
 for(const day of semester.calendar||[])map.set(day.service_date,day);
 const firstMonday=semMonday(start);
 const count=semester.end_week||Math.ceil((semParse(end)-semParse(start))/86400000/7)+1;
 const rows=[];
 for(let week=1;week<=count;week++){
  const monday=semAdd(firstMonday,(week-1)*7);
  const days=[];
  for(let i=0;i<7;i++){
   const date=semAdd(monday,i);
   const inside=date>=start&&date<=end;
   const entry=inside?semCalendarState(map.get(date),date):null;
   days.push({date,inside,day:map.get(date),entry});
  }
  const exceptions=days.filter(x=>x.entry&&x.entry.kind!=='normal');
  rows.push({week,monday,sunday:semAdd(monday,6),days,exceptions,semesterId:semester.semester_id,current:semester.phase==='ONGOING'&&week===Number(semester.current_week),
   makeup:exceptions.filter(x=>x.entry.kind==='makeup').length,
   stop:exceptions.filter(x=>x.entry.kind==='stop').length,
   pending:exceptions.filter(x=>x.entry.kind==='pending').length});
 }
 return rows;
}
function semWeekBadges(week){
 const parts=[];
 if(week.makeup)parts.push(`⇄${week.makeup}`);
 if(week.stop)parts.push(`⊘${week.stop}`);
 if(week.pending)parts.push(`?${week.pending}`);
 return parts.length?`<span class="semester-week-badges">${parts.join(' ')}</span>`:'<span class="semester-week-badges quiet">—</span>';
}
function semWeekGrid(rows){
 return `<div class="semester-grid" data-semester-id="${rows[0]?.semesterId||''}" role="table" aria-label="学期周历">
  <div class="semester-grid-head" role="row"><span></span>${['周一','周二','周三','周四','周五','周六','周日'].map(x=>`<span role="columnheader">${x}</span>`).join('')}<span></span></div>
  ${rows.map(week=>`<div class="semester-week-row${week.exceptions.length?' has-exceptions':''}${week.current?' is-current':''}" role="row">
   <div class="semester-week-label"><strong>第 ${week.week} 周</strong><small>${semDateText(week.monday)}–${semDateText(week.sunday)}</small></div>
   ${week.days.map(cell=>cell.inside?`<button type="button" class="semester-day ${cell.entry.kind}" role="cell" data-calendar-date="${cell.date}" title="${esc(`${cell.date} ${weekdayText(semWeekday(cell.date))} · ${cell.entry.label}${cell.entry.note?' · '+cell.entry.note:''}`)}" aria-label="${esc(`${cell.date} ${weekdayText(semWeekday(cell.date))} ${cell.entry.label}`)}"><span class="semester-symbol">${cell.entry.symbol}</span></button>`:'<span class="semester-day blank" role="cell" aria-hidden="true"></span>').join('')}
   ${semWeekBadges(week)}
  </div>`).join('')}
 </div>`;
}
function semWeekMobile(rows){
 return `<div class="semester-mobile-list">${rows.map(week=>`<details class="semester-week-card"${week.exceptions.length?' open':''}>
  <summary><strong>第 ${week.week} 周</strong><span>${semMonthDay(week.monday)}–${semMonthDay(week.sunday)}</span>${semWeekBadges(week)}</summary>
  <div class="semester-mobile-days">${week.days.filter(cell=>cell.inside).map(cell=>`<div class="semester-mobile-day ${cell.entry.kind}"><span>${weekdayText(semWeekday(cell.date))} ${semDateText(cell.date)}</span><b>${cell.entry.symbol}</b><em>${esc(cell.entry.label)}</em>${cell.entry.note?`<small>${esc(cell.entry.note)}</small>`:''}</div>`).join('')}</div>
 </details>`).join('')}</div>`;
}
function semCalendarBody(semester,{onlyExceptions=false}={}){
 let rows=semWeekRows(semester);
 if(onlyExceptions)rows=rows.filter(week=>week.exceptions.length);
 if(!rows.length)return empty('本学期没有例外安排','固定班次按每周日历正常执行。');
 return semWeekGrid(rows)+semWeekMobile(rows);
}
function semPendingCount(semester){
 return semWeekRows(semester).reduce((total,week)=>total+week.pending,0);
}
function semesterSummary(semester){
 const pending=semester.phase!=='ENDED'&&state.role!=='STUDENT'?semPendingCount(semester):0;
 const progress=semester.phase==='ENDED'?'已结束':semester.phase==='UPCOMING'?'待开工':`第 ${Math.max(1,semester.current_week)} 周`;
 return `<div class="semester-summary"><div class="semester-summary-main"><strong>${esc(semester.name)}</strong><span class="semester-summary-dot">·</span><span>${esc(progress)} · ${esc(semester.start_date)} 至 ${esc(semester.end_date)}</span></div>${pending?`<button type="button" class="semester-pending" data-action="calendar-focus-pending" data-id="${semester.semester_id}">待确认 <b>${pending}</b> 天</button>`:''}</div>`;
}
function semesterActions(semester,editable){
 if(!editable)return '';
 if(semester.phase==='ENDED')return '<button class="text-button" data-action="semester-create">设置新学期</button>';
 return `<button class="btn primary" data-action="calendar-edit" data-id="${semester.semester_id}">设置停工 / 调休</button><details class="page-action-menu"><summary>更多</summary><div class="page-action-menu-list"><button type="button" class="text-button" data-action="semester-edit" data-id="${semester.semester_id}">修改学期</button><button type="button" class="text-button" data-action="semester-sync" data-id="${semester.semester_id}">重新核对排班</button></div></details>`;
}
function semesterPanel(semester,editable,{onlyExceptions=false}={}){
 return `<section class="panel"><header class="panel-header"><div class="semester-panel-title"><h2>${onlyExceptions?'有例外的那几周':'周历'}</h2><div class="semester-legend" aria-label="日历符号说明"><span><b>●</b>正常</span><span><b>⊘</b>停工</span><span><b>⇄</b>调休</span><span><b>?</b>待确认</span></div></div></header><div class="panel-content semester-calendar-content">${semCalendarBody(semester,{onlyExceptions})}</div></section>`;
}
function semesterHistory(semester){
 const phase=semester.phase==='ENDED'?'已结束':semester.phase==='UPCOMING'?'待开工':'进行中';
 return `<details class="semester-history"><summary><strong>${esc(semester.name)}</strong><span>${phase} · ${semester.end_week} 周</span><span class="semester-history-arrow" aria-hidden="true">›</span></summary><div class="semester-history-body">${semCalendarBody(semester)}</div></details>`;
}
function semesterPage(){
 const editable=state.role==='SUPER';
 const rows=state.data.semesters||[];
 if(!rows.length){
  $('#main').innerHTML=heading('学期与日历','',editable?'<button class="btn primary" data-action="semester-create">设置新学期</button>':'')+`<section class="panel">${empty('尚未设置学期',editable?'点击设置新学期，填写开工日期和结束周次。':'请等待管理员设置本学期。')}</section>`;
  return;
 }
 const ongoing=rows.find(s=>s.phase==='ONGOING');
 const upcoming=rows.filter(s=>s.phase==='UPCOMING').sort((a,b)=>a.start_date.localeCompare(b.start_date))[0];
 const primary=ongoing||upcoming||rows[0];
 const history=rows.filter(s=>s.semester_id!==primary.semester_id);
 if(state.role==='STUDENT'){
  $('#main').innerHTML=heading('学期与日历','')+semesterSummary(primary)+myFixedSlotsPanel()+semesterPanel(primary,false,{onlyExceptions:true});
  return;
 }
 $('#main').innerHTML=heading('学期与日历','',semesterActions(primary,editable))+
  semesterSummary(primary)+semesterPanel(primary,editable)+
  (history.length?`<div class="semester-history-list"><h2 class="semester-history-heading">历史学期</h2>${history.map(semesterHistory).join('')}</div>`:'');
}
function calFieldDate(semester,value){return value&&value>=semester.start_date&&value<=semester.end_date?value:(getDate()<semester.start_date?semester.start_date:getDate()>semester.end_date?semester.end_date:getDate());}
function openCalendarDialog(semester,startDate,endDate){
 const start=calFieldDate(semester,startDate),end=calFieldDate(semester,endDate||startDate);
 openDialog('设置停工或调休',`${semester.name}：可指定某一天或一段日期。当日 08:15 后及过去日期，仅允许补齐待确认的日历，不可改写已有服务。`,
  field('start_date','开始日期',{type:'date',value:start,min:semester.start_date,max:semester.end_date})+
  field('end_date','结束日期（包含当天）',{type:'date',value:end,min:semester.start_date,max:semester.end_date})+
  field('choice','日期安排',{options:[['REST','停工（节假日 / 学校停班）'],...[1,2,3,4,5,6,7].map(n=>[String(n),`执行${weekdayText(n)}的班表`]),['NATURAL','按日期实际星期上工（已核对日历）'],['DEFAULT','恢复内置日历']],full:true})+reasonField(),
  v=>send(`/semesters/${semester.semester_id}/calendar`,{start_date:v.start_date,end_date:v.end_date,mode:/^[1-7]$/.test(v.choice)?'WEEKDAY':v.choice,weekday:/^[1-7]$/.test(v.choice)?Number(v.choice):null,reason:v.reason},'PUT'),'保存并更新排班');
}
function semesterAction(name,id){
 const semester=(state.data.semesters||[]).find(r=>String(r.semester_id)===String(id));
 if(name==='calendar-focus-pending'){
  const target=document.querySelector('.semester-day.pending');if(target){target.scrollIntoView({block:'center',behavior:'smooth'});target.focus({preventScroll:true});}else notify('当前没有待确认的日期。');return true;
 }
 if(name==='calendar-edit'){if(semester)openCalendarDialog(semester);return true;}
 if(name==='semester-create'||name==='semester-edit'){
  const s=semester;
  openDialog(s?'修改学期':'设置新学期','保存后从开工日起补齐排班并结算已结束的周次。学期开始后，开工日期不可更改。',
   field('name','学期名称',{value:s?.name||'',full:true,maxLength:100,placeholder:'例如：2026—2027 学年第一学期'})+
   field('start_date','本学期开工日期',{type:'date',value:s?.start_date||getDate(),full:true,help:'该日期所在的自然周为第 1 周。若选择过去日期，将按初始固定名单补齐并结算已结束周次。'})+
   field('end_week','结束周次（包含该周）',{type:'number',value:s?.end_week||18,min:1,max:53,step:1,full:true}),
   v=>send(s?`/semesters/${s.semester_id}`:'/semesters',{...v,end_week:Number(v.end_week)},s?'PUT':'POST'),'保存并生成排班');
  return true;
 }
 if(name==='semester-sync'){
  openDialog('重新核对学期排班','从开工日起补齐遗漏的日期安排并结算已结束周次。已有考勤、已完成记录及手动取消的安排会保留。','',()=>send(`/semesters/${semester.semester_id}/sync`,{}),'重新核对');return true;
 }
 return false;
}
let semDrag=null;
document.addEventListener('pointerdown',event=>{
 const cell=event.target.closest?.('[data-calendar-date]');
 if(!cell)return;
 const semester=(state.data.semesters||[]).find(s=>String(s.semester_id)===String(cell.closest('.semester-grid')?.dataset.semesterId||cell.dataset.semesterId));
 semDrag={cell,date:cell.dataset.calendarDate,start:cell.dataset.calendarDate,end:cell.dataset.calendarDate};
 cell.classList.add('selected');
});
document.addEventListener('pointerover',event=>{
 if(!semDrag)return;
 const cell=event.target.closest?.('[data-calendar-date]');
 if(!cell||cell===semDrag.cell||!cell.closest('.semester-grid'))return;
 semDrag.end=cell.dataset.calendarDate;
 document.querySelectorAll('.semester-day.selected').forEach(x=>x.classList.remove('selected'));
 const a=semDrag.start<semDrag.end?semDrag.start:semDrag.end;
 const b=semDrag.start<semDrag.end?semDrag.end:semDrag.start;
 const target=cell.closest('.semester-grid');
 target?.querySelectorAll('[data-calendar-date]').forEach(x=>{const d=x.dataset.calendarDate;if(d>=a&&d<=b)x.classList.add('selected');});
});
document.addEventListener('pointerup',()=>{
 if(!semDrag)return;
 const drag=semDrag;semDrag=null;
 document.querySelectorAll('.semester-day.selected').forEach(x=>x.classList.remove('selected'));
 const semester=(state.data.semesters||[]).find(s=>String(s.semester_id)===String(drag.cell.closest('.semester-grid')?.dataset.semesterId));
 if(!semester)return;
 const start=drag.start<drag.end?drag.start:drag.end;
 const end=drag.start<drag.end?drag.end:drag.start;
 openCalendarDialog(semester,start,end);
});
