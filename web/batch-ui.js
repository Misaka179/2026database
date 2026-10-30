'use strict';
function collectionBatchBar(c){
 if(state.role!=='SUPER')return '';
 return `<div class="panel-content batch-toolbar" data-batch-collection="${c.collection_id}"><button class="btn" data-action="claim-select-all" data-id="${c.collection_id}">全选可审批条目</button><button class="btn" data-action="claim-select-none" data-id="${c.collection_id}">取消全选</button><span data-batch-count aria-live="polite">已选 0 条</span><button class="btn primary" data-action="claim-approve-batch" data-id="${c.collection_id}" disabled>批量通过</button></div>`;
}
function collectionBatchCell(c,s){return state.role==='SUPER'?`<td>${s.can_review?`<input type="checkbox" data-claim-select="${s.submission_id}" data-claim-collection="${c.collection_id}" aria-label="选择 ${esc(s.name)} ${esc(s.service_date)} ${esc(s.item_title)}">`:'—'}</td>`:'';}
function selectedClaims(id){state.collectionSelections??=new Map();if(!state.collectionSelections.has(String(id)))state.collectionSelections.set(String(id),new Map());return state.collectionSelections.get(String(id));}
function updateClaimSelection(id){const selected=selectedClaims(id),bar=document.querySelector(`[data-batch-collection="${id}"]`);if(!bar)return;bar.querySelector('[data-batch-count]').textContent=`已选 ${selected.size} 条`;bar.querySelector('[data-action="claim-approve-batch"]').disabled=!selected.size;document.querySelectorAll(`[data-claim-collection="${id}"]`).forEach(x=>x.checked=selected.has(Number(x.dataset.claimSelect)));}
function collectionBatchAction(name,id){
 if(!['claim-select-all','claim-select-none','claim-approve-batch'].includes(name))return false;
 if(state.role!=='SUPER')return true;
 const c=(state.data.collections||[]).find(c=>String(c.collection_id)===String(id));if(!c)return true;
 const selected=selectedClaims(id);
 if(name!=='claim-approve-batch'){selected.clear();if(name==='claim-select-all')c.submissions.filter(s=>s.can_review).forEach(s=>selected.set(s.submission_id,s));updateClaimSelection(id);return true;}
 const entries=[...selected.values()];if(!entries.length)return true;
 const people=new Set(entries.map(s=>s.student_id)).size,total=entries.reduce((n,s)=>n+s.service_minutes,0);
 openDialog('批量通过时长申报',`${c.title}：${people}人、${entries.length}条，合计${hourText(total)}。任一条目状态变化将整批取消提交。`,field('reason','审批说明',{type:'textarea',required:false,full:true,maxLength:500}),async v=>{
  const result=await send(`/hour-collections/${id}/approve-batch`,{items:entries.map(s=>({submission_id:s.submission_id,expected_revision:s.revision})),reason:v.reason});selected.clear();return result;
 },'确认批量通过');return true;
}
function inboxBatchBar(){return `<div class="toolbar batch-toolbar" id="inbox-batch"><button class="btn" data-action="inbox-select-all">全选当前列表未读通知</button><button class="btn" data-action="inbox-select-none">取消全选</button><span id="inbox-selected-count" aria-live="polite">已选 ${state.inboxSelected?.size||0} 条</span><button class="btn primary" data-action="inbox-read-batch" ${state.inboxSelected?.size?'':'disabled'}>批量标为已读</button></div>`;}
function updateInboxSelection(){const count=document.querySelector('#inbox-selected-count');if(count)count.textContent=`已选 ${state.inboxSelected?.size||0} 条`;document.querySelectorAll('[data-notice-select]').forEach(x=>x.checked=state.inboxSelected?.has(Number(x.dataset.noticeSelect)));const submit=document.querySelector('[data-action="inbox-read-batch"]');if(submit)submit.disabled=state.inboxBusy||!state.inboxSelected?.size;}
function setInboxBatchBusy(busy){document.querySelectorAll('#inbox-batch button,[data-notice-select]').forEach(x=>x.disabled=busy);updateInboxSelection();}
document.addEventListener('change',e=>{
 const x=e.target;
 if(x.dataset.claimSelect!==undefined){const id=Number(x.dataset.claimSelect),cid=x.dataset.claimCollection,s=(state.data.collections||[]).find(c=>String(c.collection_id)===cid)?.submissions.find(s=>s.submission_id===id&&s.can_review);if(!s)return;const selected=selectedClaims(cid);if(x.checked)selected.set(id,s);else selected.delete(id);updateClaimSelection(cid);}
 if(x.dataset.noticeSelect!==undefined&&!state.inboxBusy){state.inboxSelected??=new Set();const id=Number(x.dataset.noticeSelect);if(x.checked)state.inboxSelected.add(id);else state.inboxSelected.delete(id);updateInboxSelection();}
});
