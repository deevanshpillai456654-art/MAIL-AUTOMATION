
window.setSafeHTML = function(el, html) {
  if (!el) return;
  if (typeof html !== 'string') {
    el.textContent = String(html);
    return;
  }
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const badTags = doc.querySelectorAll('script, iframe, object, embed, form, base, applet, meta, link');
  badTags.forEach(n => n.remove());
  const all = doc.querySelectorAll('*');
  for (let i = 0; i < all.length; i++) {
    const node = all[i];
    for (let j = node.attributes.length - 1; j >= 0; j--) {
      const attr = node.attributes[j];
      if (attr.name.toLowerCase().startsWith('on') || attr.name.toLowerCase() === 'javascript:') {
        node.removeAttribute(attr.name);
      }
    }
  }
  el.replaceChildren(...doc.body.childNodes);
};

function applyCategoryColors(root=document){root.querySelectorAll('[data-category-color]').forEach(el=>{el.style.background=el.dataset.categoryColor||'#667085';});}
const API_BASE=(location.protocol.startsWith('http')&&location.hostname?location.origin:'http://127.0.0.1:4597')+'/api/v1';
const categoryColors={Finance:'#12b76a',OTP:'#f79009',Clients:'#2563eb',Personal:'#9e77ed',Promotions:'#e31b54',Spam:'#f04438',Newsletters:'#667085',Trading:'#06b6d4',Logistics:'#795548',Bills:'#7a5af8',Security:'#f04438'};const priorityStyles={Critical:'priority-critical',High:'priority-high',Medium:'priority-medium',Low:'priority-low'};let currentItem=null;let currentClassification=null;function requestId(){return (crypto&&crypto.randomUUID)?crypto.randomUUID():('req_'+Math.random().toString(36).slice(2))}
function setStatus(message,state='online'){const dot=document.getElementById('statusDot');const text=document.getElementById('statusText');if(dot)dot.className=`status-dot ${state}`;if(text)text.textContent=message}async function api(path,opts={}){const r=await fetch(`${API_BASE}${path}`,{...opts,headers:{'Content-Type':'application/json','X-Frontend-Request-ID':requestId(),...(opts.headers||{})}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.message||r.status);return d}async function checkApiStatus(){try{await api('/health');setStatus('Service online','online');return true}catch{setStatus('Service offline','offline');return false}}
if(typeof Office!=='undefined'&&Office.onReady){Office.onReady(info=>{checkApiStatus();loadRecentClassifications();try{if(info.host===Office.HostType.Outlook||info.status==='OfficeHost.Outlook'){Office.context.mailbox.item?.addHandlerAsync?.(Office.EventType.ItemChanged,onItemChanged);const item=Office.context.mailbox.item;if(item){currentItem=item;displayCurrentEmail(item);classifyCurrentEmail(item)}}}catch(e){}})}else{document.addEventListener('DOMContentLoaded',()=>{checkApiStatus();loadRecentClassifications();setStatus('Open inside Outlook','offline')})};
function onItemChanged(){const item=Office.context.mailbox.item;if(item){currentItem=item;displayCurrentEmail(item);classifyCurrentEmail(item)}}function displayCurrentEmail(item){const container=document.getElementById('currentEmail');const subject=item.subject||'No Subject';const sender=item.sender||item.from||{};const fromDisplay=sender.emailAddress?`${sender.name||sender.emailAddress} <${sender.emailAddress}>`:'Unknown sender';window.setSafeHTML(
  container,
  `<div class="current-email"><div><div class="email-label">Subject</div><div class="email-value">${escapeHtml(subject)}</div></div><div><div class="email-label">From</div><div class="email-value">${escapeHtml(fromDisplay)}</div></div></div>`
);applyCategoryColors(document.getElementById('classificationResult'))}
async function classifyCurrentEmail(item){if(!item)return;document.getElementById('classificationPanel').classList.remove('hidden');const resultContainer=document.getElementById('classificationResult');window.setSafeHTML(resultContainer, '<div class="loading">Analyzing…</div>');try{const sender=item.sender||item.from||{};const body=await getEmailBody(item);const result=await api('/classify',{method:'POST',body:JSON.stringify({subject:item.subject||'',sender:sender.name||'',sender_email:sender.emailAddress||'',body})});currentClassification=result;renderClassification(result)}catch(e){window.setSafeHTML(
  resultContainer,
  '<div class="error">Failed to classify. Start the local service and try again.</div>'
);setStatus('Classification unavailable','offline')}}
function renderClassification(result){const color=categoryColors[result.category]||'#667085';window.setSafeHTML(
  document.getElementById('classificationResult'),
  `<div class="classification-result"><div class="category-badge" data-category-color="${color}">${escapeHtml(result.category||'Unclassified')}</div><div class="confidence">Confidence: ${Math.round((result.confidence||0)*100)}% <span class="priority-badge ${priorityStyles[result.priority]||'priority-medium'}">${escapeHtml(result.priority||'Medium')}</span></div></div>`
);applyCategoryColors(document.getElementById('classificationResult'))}
function getEmailBody(item){return new Promise(resolve=>{try{if(item.body){item.body.getAsync(Office.CoercionType.Text,r=>resolve(r.status===Office.AsyncResultStatus.Succeeded?String(r.value||'').slice(0,2000):''))}else resolve('')}catch{resolve('')}})}document.getElementById('moveBtn')?.addEventListener('click',()=>moveCurrentEmailToFolder());async function moveCurrentEmailToFolder(){if(!currentClassification||!currentItem)return;const category=currentClassification.category;setStatus(`Moving to ${category}`,'checking');try{const mailbox=Office.context.mailbox;const userEmail=mailbox.userProfile.emailAddress;let messageId=currentItem.itemId;if(mailbox.convertToRestId&&Office.MailboxEnums?.RestVersion){messageId=mailbox.convertToRestId(currentItem.itemId,Office.MailboxEnums.RestVersion.v2_0)}await api('/outlook/folder',{method:'POST',body:JSON.stringify({email:userEmail,folder_name:category,message_id:messageId})});setStatus(`Moved to ${category}`,'online')}catch{applyOutlookCategory(category)}}function applyOutlookCategory(category){try{const item=Office.context.mailbox.item;if(item.categories?.addAsync){item.categories.addAsync([category],result=>setStatus(result.status===Office.AsyncResultStatus.Succeeded?`Categorized as ${category}`:'Move requires connected account',result.status===Office.AsyncResultStatus.Succeeded?'online':'offline'))}else setStatus('Move requires connected account','offline')}catch{setStatus('Move requires connected account','offline')}}
document.getElementById('changeCategoryBtn')?.addEventListener('click',()=>{const s=document.getElementById('categorySelect');s.style.display=s.style.display==='none'?'block':'none'});document.getElementById('categorySelect')?.addEventListener('change',async e=>{const newCategory=e.target.value;if(newCategory&&currentClassification){const predicted=currentClassification.category;currentClassification={...currentClassification,category:newCategory};renderClassification(currentClassification);await submitFeedback(predicted,newCategory)}});document.querySelectorAll('.suggestion-tag').forEach(tag=>{async function activateSuggestion(){const category=tag.dataset.category;if(currentClassification){const predicted=currentClassification.category;currentClassification={...currentClassification,category};renderClassification(currentClassification);await submitFeedback(predicted,category)}}tag.addEventListener('click',activateSuggestion);tag.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activateSuggestion()}})});async function submitFeedback(predicted,actual){try{await api('/feedback',{method:'POST',body:JSON.stringify({email_id:0,predicted_category:predicted,actual_category:actual,user_id:1})});setStatus('Feedback saved','online')}catch{setStatus('Feedback unavailable','offline')}}async function loadRecentClassifications(){try{const data=await api('/emails?limit=10');const emails=data.emails||[];window.setSafeHTML(
  document.getElementById('history'),
  emails.length?emails.map(email=>`<div class="history-item"><div class="history-category">${escapeHtml(email.category||'Unclassified')}</div><div class="history-subject">${escapeHtml(email.subject||'No subject')}</div></div>`).join(''):'<div class="empty-state">No recent classifications</div>'
)}catch{window.setSafeHTML(
  document.getElementById('history'),
  '<div class="empty-state">Start the local service to load history</div>'
)}}
function escapeHtml(text){return String(text??'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[m]));}function complete(event){try{event.completed()}catch{}}function classifyEmail(event){classifyCurrentEmail(Office.context.mailbox.item).finally(()=>complete(event))}function moveToFolder(event){moveCurrentEmailToFolder().finally(()=>complete(event))}function suggestCategoryCompose(event){classifyEmail(event)}function categorizeMeeting(event){classifyEmail(event)}try{if(typeof Office!=='undefined'&&Office.actions){Office.actions.associate('classifyEmail',classifyEmail);Office.actions.associate('moveToFolder',moveToFolder);Office.actions.associate('suggestCategoryCompose',suggestCategoryCompose);Office.actions.associate('categorizeMeeting',categorizeMeeting)}}catch(e){}