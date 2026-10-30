'use strict';
function halfHourMinutes(value){const n=Number(value);if(!String(value).trim()||!Number.isFinite(n)||n<0.5||n>24||!Number.isInteger(n*2))throw new Error('请填写0.5至24小时，且为0.5小时的倍数，例如0.5、1.0、1.5。');return n*60;}

function collectionFiles(c){
 return (c.attachments||[]).length?'<div class="collection-files">'+c.attachments.map(f=>`<button class="text-button" data-action="collection-file" data-id="${f.attachment_id}" data-kind="${c.collection_id}">${esc(f.filename)} · ${Math.ceil(f.size_bytes/1024)} KB · ${['application/pdf','image/png','image/jpeg'].includes(f.mime_type)?'预览':'下载'}</button>`).join('')+'</div>':'';
}

async function showCollectionFile(id,collectionId){
 const session=state.sessionVersion;
 const c=(state.data.collections||[]).find(c=>String(c.collection_id)===String(collectionId));
 const file=c?.attachments?.find(f=>String(f.attachment_id)===String(id));if(!file)return;
 const preview=['application/pdf','image/png','image/jpeg'].includes(file.mime_type);
 try{
  const r=await fetch(`/hour-collections/${collectionId}/attachments/${id}?preview=${preview}`,{headers:{Authorization:`Bearer ${state.token}`}});
  if(!r.ok)throw new Error('无法读取附件，请确认登录状态和参与权限。');
  const blob=await r.blob();if(session!==state.sessionVersion)return;
  const url=URL.createObjectURL(blob);
  if(!preview){const a=document.createElement('a');a.href=url;a.download=file.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);return;}
  openDialog(file.filename,'本次征集的工作说明附件','',()=>{});
  const body=$('.dialog-body',dialog);
  body.innerHTML=(file.mime_type==='application/pdf'?`<iframe class="collection-preview" sandbox title="${esc(file.filename)}" src="${url}"></iframe>`:`<img class="collection-image" alt="${esc(file.filename)}" src="${url}">`)+`<p><a class="text-button" href="${url}" download="${esc(file.filename)}">下载原文件</a></p>`;
  modalSubmit=null;dialog.addEventListener('close',()=>URL.revokeObjectURL(url),{once:true});
 }catch(e){if(session===state.sessionVersion)notify(e.message,true);}
}

function openCollectionCreate(){
 if(!['SUPER','NORMAL'].includes(state.role))return;
 const businesses=(state.data.businesses||[]).filter(b=>b.status!=='ARCHIVED'&&(state.role==='SUPER'||b.can_collect)),events=businesses.filter(b=>b.kind==='EVENT');
 if(!events.length){notify(state.role==='NORMAL'?'请先申请征集管理范围并等待超管批准。':'请先创建非固定业务。',true);return;}
 const selected=new Map();let visible=[],files=[],queryVersion=0,timer;
 const errorBox=id=>`<p class="notice error field full" id="${id}" hidden role="alert"></p>`;
 const fields=field('business_id','征集业务',{options:events.map(b=>[b.business_id,b.name])})+
  field('group_id','征集小组',{options:[['','整项业务 / 未分组']],required:false})+field('title','征集标题',{maxLength:100})+
  field('start_date','服务开始日期',{type:'date'})+field('end_date','服务结束日期',{type:'date'})+field('submission_deadline','申报截止日期',{type:'date',full:true,help:'截止当天仍可申报；过期后自动结束。可晚于服务结束日期，方便补报。'})+errorBox('collection-dates-error')+
  '<div class="field full"><label>工作事项</label><small>每项分别填写名称、最低时长和最高时长，时长单位为小时，以0.5小时递增，范围按每人每天计算。</small><div id="collection-items"></div><button type="button" class="btn small" id="collection-add-item">添加工作事项</button></div>'+errorBox('collection-items-error')+
  '<div class="field full"><label for="collection-files">工作说明附件（选填）</label><input id="collection-files" type="file" multiple accept=".pdf,.docx,.xlsx,.txt,.jpg,.jpeg,.png"><small>最多3个，每个不超过2MB。PDF、Word、Excel、TXT或JPG/PNG图片；附件不代替事项及分钟范围。</small><div id="collection-file-list"></div></div>'+errorBox('collection-files-error')+
  field('scope_business','人员范围',{options:[...businesses.map(b=>[b.business_id,b.name]),['',state.role==='SUPER'?'全部在队人员':'全部管理范围内人员']],value:events[0].business_id,required:false,full:true})+
  field('participant_search','按学号搜索',{required:false,full:true,maxLength:32,placeholder:'输入完整或部分学号，保留前导零'})+
  '<div class="field full"><div class="button-row"><button type="button" class="btn small" id="collection-select-all">全选当前结果</button><button type="button" class="btn small" id="collection-clear-results">取消选择当前结果</button><span id="collection-selected-count" aria-live="polite">已选 0 人</span></div><div id="collection-people" class="collection-people" aria-live="polite"></div><details><summary>查看已选人员（可单独移除）</summary><div id="collection-selected" class="collection-people"></div></details></div>'+errorBox('collection-people-error');
 openDialog('发起时长征集','选择业务后加载本业务名单；可切换人员范围，补选其他业务队员。',fields,submit,'确认发布');
 dialog.classList.add('collection-dialog');
 $('#action-form').dataset.collectionForm='true';
 let itemSerial=0;
 function addItem(){
  const id=++itemSerial, row=document.createElement('div');row.className='collection-item-row';row.dataset.itemId=String(id);
  row.innerHTML=field('item_title_'+id,'事项名称',{maxLength:100})+field('item_min_'+id,'最低时长（小时）',{type:'number',min:0.5,max:24,step:0.5})+field('item_max_'+id,'最高时长（小时）',{type:'number',min:0.5,max:24,step:0.5})+'<button type="button" class="text-button" data-remove-item="'+id+'">移除事项</button>';
  $('#collection-items').append(row);
 }
 $('#collection-add-item').addEventListener('click',()=>{if($('#collection-items').children.length>=100){error('collection-items-error','最多添加100项工作事项。');return;}addItem();});
 $('#collection-items').addEventListener('click',e=>{if(e.target.dataset.removeItem){if($('#collection-items').children.length===1){error('collection-items-error','至少保留一项工作事项。');return;}e.target.closest('.collection-item-row').remove();}});
 addItem();
 const version=modalVersion,session=state.sessionVersion;
 const current=()=>version===modalVersion&&session===state.sessionVersion&&dialog.open;
 function error(id,text){const el=$('#'+id);el.textContent=text;el.hidden=!text;}
 function drawPeople(){
  $('#collection-people').innerHTML=visible.length?visible.map(p=>`<label><input type="checkbox" data-person-id="${esc(p.student_id)}" ${selected.has(p.student_id)?'checked':''}> <span>${esc(p.name)} <small>${esc(p.student_id)}</small></span></label>`).join(''):'<p class="muted">当前范围没有匹配的在队人员，可调整范围或学号。</p>';
  $('#collection-selected-count').textContent=`已选 ${selected.size} 人`;
  $('#collection-selected').innerHTML=selected.size?[...selected.values()].map(p=>`<div>${esc(p.name)} · ${esc(p.student_id)} <button type="button" class="text-button" data-remove-person="${esc(p.student_id)}">移除</button></div>`).join(''):'<p class="muted">尚未选择参与人员。</p>';
 }
 async function loadPeople(){
  const seq=++queryVersion;visible=[];drawPeople();$('#collection-people').textContent='正在加载名单…';
  $('#collection-select-all').disabled=true;$('#collection-clear-results').disabled=true;
  const q=new URLSearchParams();if($('#f-scope_business').value)q.set('business_id',$('#f-scope_business').value);if($('#f-group_id').value){q.set('group_id',$('#f-group_id').value);q.set('business_id',$('#f-business_id').value);}
  if($('#f-participant_search').value.trim())q.set('student_id',$('#f-participant_search').value.trim());
  try{const people=await request('/hour-collections/participants?'+q);if(!current()||seq!==queryVersion)return;
   visible=people;drawPeople();error('collection-people-error','');
  }catch(e){if(current()&&seq===queryVersion){$('#collection-people').textContent='名单读取失败，请更改范围或重新搜索。';error('collection-people-error',e.message);}}
  finally{if(current()&&seq===queryVersion){$('#collection-select-all').disabled=modalBusy;$('#collection-clear-results').disabled=modalBusy;}}
 }
 function drawFiles(){
  $('#collection-file-list').innerHTML=files.map((f,i)=>`<div>${esc(f.name)} · ${Math.ceil(f.size/1024)} KB <button class="text-button" type="button" data-remove-file="${i}">移除</button></div>`).join('');
 }
 $('#f-end_date').addEventListener('change',()=>{const end=$('#f-end_date').value;$('#f-submission_deadline').min=end;if(end&&!$('#f-submission_deadline').value){const day=new Date(end+'T00:00:00Z');day.setUTCDate(day.getUTCDate()+7);$('#f-submission_deadline').value=day.toISOString().slice(0,10);}});
 function loadGroupChoices(){const bid=Number($('#f-business_id').value),b=businesses.find(b=>b.business_id===bid);const groups=(state.data.groups||[]).filter(g=>g.business_id===bid&&g.can_manage);$('#f-group_id').innerHTML=(b.can_collect_all||state.role==='SUPER'?'<option value="">整项业务 / 未分组</option>':'')+groups.map(g=>`<option value="${g.group_id}">${esc(g.name)}</option>`).join('');$('#f-group_id').required=!(b.can_collect_all||state.role==='SUPER');syncGroupScope();}
 function syncGroupScope(){const grouped=Boolean($('#f-group_id').value);$('#f-scope_business').disabled=grouped;if(grouped)$('#f-scope_business').value=$('#f-business_id').value;}
 $('#f-group_id').onchange=()=>{selected.clear();syncGroupScope();loadPeople();};
 $('#f-business_id').addEventListener('change',()=>{selected.clear();loadGroupChoices();$('#f-scope_business').value=$('#f-business_id').value;$('#f-participant_search').value='';clearTimeout(timer);loadPeople();});
 $('#f-scope_business').addEventListener('change',()=>{clearTimeout(timer);loadPeople();});
 $('#f-participant_search').addEventListener('input',()=>{clearTimeout(timer);++queryVersion;visible=[];drawPeople();$('#collection-select-all').disabled=true;timer=setTimeout(loadPeople,200);});
 $('#collection-select-all').addEventListener('click',()=>{visible.forEach(p=>selected.set(p.student_id,p));drawPeople();});
 $('#collection-clear-results').addEventListener('click',()=>{visible.forEach(p=>selected.delete(p.student_id));drawPeople();});
 $('#collection-people').addEventListener('change',e=>{const id=e.target.dataset.personId;if(!id)return;const p=visible.find(p=>p.student_id===id);if(p){if(e.target.checked)selected.set(id,p);else selected.delete(id);drawPeople();}});
 $('#collection-selected').addEventListener('click',e=>{const id=e.target.dataset.removePerson;if(id){selected.delete(id);drawPeople();}});
 $('#collection-files').addEventListener('change',e=>{
  const added=[...e.target.files];e.target.value='';error('collection-files-error','');
  if(files.length+added.length>3){error('collection-files-error','最多上传3个附件。');return;}
  if(added.some(f=>!f.size||f.size>2*1024*1024||!(/\.(pdf|docx|xlsx|txt|jpe?g|png)$/i).test(f.name))){error('collection-files-error','请选择非空且不超过2MB的受支持文件。');return;}
  files.push(...added);drawFiles();
 });
 $('#collection-file-list').addEventListener('click',e=>{if(e.target.dataset.removeFile!==undefined){files.splice(Number(e.target.dataset.removeFile),1);drawFiles();}});
 dialog.addEventListener('close',()=>{clearTimeout(timer);dialog.classList.remove('collection-dialog');},{once:true});
 async function submit(v){
  ['collection-dates-error','collection-items-error','collection-files-error','collection-people-error'].forEach(id=>error(id,''));
  let invalid=false,items=[];
  if(!v.title.trim()||!v.start_date||!v.end_date||!v.submission_deadline||v.start_date>v.end_date||v.submission_deadline<v.end_date){error('collection-dates-error','请填写标题、服务日期和申报截止日期；服务结束不早于开始，申报截止不早于服务结束。');invalid=true;}
  try{items=[...$('#collection-items').children].map(row=>{const id=row.dataset.itemId,title=(v['item_title_'+id]||'').trim(),min=v['item_min_'+id],max=v['item_max_'+id];const low=halfHourMinutes(min),high=halfHourMinutes(max);if(!title||title.length>100||low>high)throw new Error('请填写事项名称，最低时长不能超过最高时长。');return {title,min_minutes:low,max_minutes:high};});if(!items.length||items.length>100)throw new Error('请填写1至100项工作事项。');}
  catch(e){error('collection-items-error',e.message);invalid=true;}
  if(!selected.size){error('collection-people-error','请至少选择一名参与人员。');invalid=true;}
  if(invalid)throw new Error('请修正标出的内容后再发布。');
  const controls=[...dialog.querySelectorAll('input,select,textarea,button')];const previous=controls.map(el=>el.disabled);controls.forEach(el=>el.disabled=true);
  try{
   const attachments=await Promise.all(files.map(async f=>({filename:f.name,file_base64:await fileBase64(f)})));
   const result=await send('/hour-collections',{business_id:Number(v.business_id),group_id:v.group_id?Number(v.group_id):null,title:v.title.trim(),start_date:v.start_date,end_date:v.end_date,submission_deadline:v.submission_deadline,items,student_ids:[...selected.keys()],attachments});
   return {...result,published:true};
  }catch(e){
   const target=/附件|文件|文档|PDF|图片/.test(e.message)?'collection-files-error':/队员|名单/.test(e.message)?'collection-people-error':'collection-items-error';error(target,e.message);throw e;
  }finally{if(current())controls.forEach((el,i)=>el.disabled=previous[i]);}
 }
 loadGroupChoices();loadPeople();
}
