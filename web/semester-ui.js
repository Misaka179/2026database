'use strict';
const weekdayText = n => n ? `周${'一二三四五六日'[n-1]}` : '不上工';
function currentSemester(){
 const rows=state.data.semesters||[];
 return rows.find(s=>s.phase==='ONGOING')||rows.filter(s=>s.phase==='UPCOMING').sort((a,b)=>a.start_date.localeCompare(b.start_date))[0]||rows[0];
}
function semesterNotice(){
 const s=currentSemester();
 if(!s)return '<p class="notice">尚未设置学期。请由超级管理员在“学期与日历”填写开工日期与结束周次。</p>';
 const progress=s.phase==='ENDED'?'本学期已结束':s.phase==='UPCOMING'?'尚未开工':`当前第 ${s.current_week} 周`;
 return `<p class="notice"><strong>${esc(s.name)} · ${progress}</strong>　${esc(s.start_date)} 至 ${esc(s.end_date)}，共 ${s.end_week} 周。每周一自动结算上周，已登记的缺勤、迟到和获批请假按考勤处理。 <button class="text-button" data-page="semesters">查看日历</button></p>`;
}
function semesterPage(){
 const editable=state.role==='SUPER',rows=state.data.semesters||[];
 const modeNames={NORMAL:'正常服务',HOLIDAY:'节假日停工',MAKEUP_REQUIRED:'待指定调休班表',UNCONFIRMED:'待核对日历',REST:'手动停工',CUSTOM:'管理员指定'};
 $('#main').innerHTML=heading('学期与日历','开工日期所在的周一至周日为第 1 周；开工前不排班，结束周的周日后停止服务。',editable?'<button class="btn primary" data-action="semester-create">设置新学期</button>':'')+
 '<p class="rule-note">日期安排按固定时段提前生成，方便请假。每周一按北京时间结算已结束的一周，系统停机后会在重启时补结算。普通周末仍按固定班表上工；法定假期停工；调休补班须指定班表。首次设置学期会按初始固定名单补齐开工日起的服务并结算已结束周次；之后新增队员或换时段只从生效时间起计算。</p>'+
 (rows.length?rows.map(s=>{
  let issues=[];try{issues=typeof s.issues==='string'?JSON.parse(s.issues):s.issues||[];}catch{}
  const warning=issues.length?`<div class="notice error">有 ${issues.length} 项日历或配置提示。待确认日期暂停排班；负责人、容量待完善不影响已有固定队员计时。<ul>${issues.slice(0,8).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${issues.length>8?'请展开日历查看其他待确认日期。':''}</div>`:'';
  return `<section class="panel"><header class="panel-header"><div><h2>${esc(s.name)}</h2><p>${esc(s.start_date)} 至 ${esc(s.end_date)} · ${s.end_week} 周 · ${s.phase==='ENDED'?'已结束':s.phase==='UPCOMING'?'待开工':`当前第 ${s.current_week} 周`}</p></div>${editable&&s.phase!=='ENDED'?`<div class="button-row"><button class="btn" data-action="semester-edit" data-id="${s.semester_id}">修改学期</button><button class="btn primary" data-action="calendar-edit" data-id="${s.semester_id}">设置停工 / 调休</button><button class="text-button" data-action="semester-sync" data-id="${s.semester_id}">重新核对排班</button></div>`:''}</header><div class="panel-content">${warning}<p class="rule-note">最近自动结算：${fmtDate(s.last_settled_at)}。内置 2026 年节假日，其他年份须手动核对；待确认日期暂不上工。<a href="https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html" target="_blank" rel="noopener">2026 年官方通知</a></p><details><summary>查看本学期日历（${s.calendar.length} 天）</summary>${table(['日期','安排','执行班表','说明'],s.calendar.map(d=>`<tr><td>${esc(d.service_date)}</td><td>${esc(modeNames[d.mode]||d.mode)}</td><td>${weekdayText(d.effective_weekday)}</td><td class="wrap">${esc(d.note)}</td></tr>`))}</details></div></section>`;
 }).join(''):empty('尚未设置学期',editable?'点击设置新学期，填写开工日期和结束周次。':'请等待管理员设置本学期。'));
}
function semesterAction(name,id){
 if(!['semester-create','semester-edit','calendar-edit','semester-sync'].includes(name))return false;
 const s=(state.data.semesters||[]).find(r=>String(r.semester_id)===String(id));
 if(name==='semester-create'||name==='semester-edit'){
  openDialog(s?'修改学期':'设置新学期','保存后从开工日起补齐排班并结算已结束的周次。学期开始后，开工日期不可更改。',
   field('name','学期名称',{value:s?.name||'',full:true,maxLength:100,placeholder:'例如：2026—2027 学年第一学期'})+
   field('start_date','本学期开工日期',{type:'date',value:s?.start_date||getDate(),full:true,help:'该日期所在的自然周为第 1 周。若选择过去日期，将按初始固定名单补齐并结算已结束周次。'})+
   field('end_week','结束周次（包含该周）',{type:'number',value:s?.end_week||18,min:1,max:53,step:1,full:true}),
   v=>send(s?`/semesters/${s.semester_id}`:'/semesters',{...v,end_week:Number(v.end_week)},s?'PUT':'POST'),'保存并生成排班');
 }else if(name==='calendar-edit'){
  openDialog('设置停工或调休',`${s.name}：可指定某一天或一段日期。当日 08:15 后及过去日期，仅允许补齐待确认的日历，不可改写已有服务。`,
   field('start_date','开始日期',{type:'date',value:getDate()<s.start_date?s.start_date:getDate(),min:s.start_date,max:s.end_date})+
   field('end_date','结束日期（包含当天）',{type:'date',value:getDate()<s.start_date?s.start_date:getDate(),min:s.start_date,max:s.end_date})+
   field('choice','日期安排',{options:[['REST','停工（节假日 / 学校停班）'],...[1,2,3,4,5,6,7].map(n=>[String(n),`执行${weekdayText(n)}的班表`]),['NATURAL','按日期实际星期上工（已核对日历）'],['DEFAULT','恢复内置日历']],full:true})+reasonField(),
   v=>send(`/semesters/${s.semester_id}/calendar`,{start_date:v.start_date,end_date:v.end_date,mode:/^[1-7]$/.test(v.choice)?'WEEKDAY':v.choice,weekday:/^[1-7]$/.test(v.choice)?Number(v.choice):null,reason:v.reason},'PUT'),'保存并更新排班');
 }else{
  openDialog('重新核对学期排班','从开工日起补齐遗漏的日期安排并结算已结束周次。已有考勤、已完成记录及手动取消的安排会保留。','',()=>send(`/semesters/${s.semester_id}/sync`,{}),'重新核对');
 }
 return true;
}
