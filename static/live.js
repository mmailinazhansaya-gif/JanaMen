/* Live presence is session-based; changing focus never changes the signed-in account. */
let liveMembers=[],liveRefreshBusy=false;
function syncLiveScene(scene,members,prefix){if(!scene)return;const visible=members.filter(m=>!m.demo&&(m.id!==user.id||prefix==='teamPerson'));const ids=new Set(visible.map(m=>prefix+m.id));scene.querySelectorAll('.live-person').forEach(el=>{if(!ids.has(el.id))el.remove();});visible.forEach(m=>{let el=document.getElementById(prefix+m.id);if(!el){scene.insertAdjacentHTML('beforeend',sceneAvatar(prefix+m.id,m.name.split(' ')[0],0,'actual-person live-person',m.id));el=document.getElementById(prefix+m.id);}placePerson(el,m.presence);});}
async function refreshLiveOffice(){if(!user||liveRefreshBusy)return;liveRefreshBusy=true;const uid=user.id,token=tabToken;try{const [members,p]=await Promise.all([api('/office-live'),api('/presence')]);if(user?.id!==uid||tabToken!==token)return;liveMembers=members.map(m=>({...m,presence:stampPresence(m.presence)}));if(!officePresence||p.changed_at>=officePresence.changed_at)officePresence=stampPresence(p);syncLiveScene($('#wvOffice'),liveMembers,'livePerson');const count=liveMembers.filter(m=>m.online&&m.presence.mode!=='off').length;const legend=$('#wvOffice .office-room-legend');if(legend)legend.textContent=`● ${lang==='kk'?'Кеңседе':'В офисе'}: ${count}`;if($('#wvTeamOffice')){let allowed=liveMembers;if(user.role==='manager'){const team=await api('/office-team');if(user?.id!==uid||tabToken!==token)return;const ids=new Set(team.map(p=>p.id));allowed=liveMembers.filter(m=>ids.has(m.id));}officeMembers=allowed.filter(m=>m.id!==uid);syncLiveScene($('#wvTeamOffice'),officeMembers,'teamPerson');renderPresenceList();if($('#teamSync'))$('#teamSync').textContent='● Обновлено '+new Date().toLocaleTimeString('ru-RU');}}catch(e){if($('#teamSync'))$('#teamSync').textContent='Нет связи · повторяем';}finally{liveRefreshBusy=false;}}
async function refreshTeamOffice(){await refreshLiveOffice();}
function renderPresenceList(){const list=$('#teamPresenceList');if(!list)return;list.innerHTML=officeMembers.map(m=>`<button class="team-presence-item" data-follow-person="${m.id}"><b>${esc(m.name)}</b><small>${esc(m.position)}</small><span>${m.online?esc(officeStatus(m.presence)):'Не в сети'}</span></button>`).join('')||'<p class="tiny muted">Нет сотрудников в списке команды.</p>';}
async function heartbeat(){if(!user||!tabToken)return;try{await api('/heartbeat','POST',{});}catch{}}
setInterval(heartbeat,20000);
// Only real interaction inside this page counts; polling and heartbeat do not.
let inputToken='',lastHumanInput=0,sentHumanInput=0,lastInputRequest=0,inputBusy=false;
function noteHumanInput(event){
 if(!event.isTrusted||!user||!tabToken||welcomeActive||officePresence?.mode==='off')return;
 if(inputToken!==tabToken){inputToken=tabToken;lastHumanInput=0;sentHumanInput=0;lastInputRequest=0;}
 lastHumanInput=Date.now();
 flushHumanInput();
}
async function flushHumanInput(){
 if(inputBusy||officeBusy||!user||!tabToken||inputToken!==tabToken||welcomeActive||!officePresence||officePresence.mode==='off')return;
 const stamp=Date.now();
 if(lastHumanInput<=sentHumanInput||stamp-lastInputRequest<5000)return;
 const idle=stamp-lastHumanInput;
 if(idle>120000)return;
 const token=tabToken,uid=user.id,input=lastHumanInput;
 inputBusy=true;lastInputRequest=stamp;
 try{
  const p=await api('/activity','POST',{idle_ms:Math.max(0,idle)});
  if(tabToken!==token||user?.id!==uid)return;
  sentHumanInput=input;
  if(!officePresence||p.changed_at>=officePresence.changed_at){officePresence=stampPresence(p);updateOfficeControls();}
 }catch{/* Keep pending input for a later retry. */}finally{inputBusy=false;}
}
for(const event of ['pointermove','pointerdown','keydown','wheel','touchstart'])document.addEventListener(event,noteHumanInput,{passive:true});
setInterval(flushHumanInput,1000);
window.addEventListener('pagehide',()=>{if(!tabToken)return;fetch('/api/disconnect',{method:'POST',credentials:'omit',keepalive:true,headers:{'Content-Type':'application/json','Authorization':'Bearer '+tabToken,'X-CSRF-Token':csrf},body:'{}'}).catch(()=>{});});
window.addEventListener('pageshow',()=>{heartbeat().then(refreshLiveOffice);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)heartbeat().then(refreshLiveOffice);});
// Private attachments must use this tab's credentials, just like other API calls.
document.addEventListener('click',e=>{const link=e.target.closest('[data-document-download]');if(!link)return;e.preventDefault();action(null,async()=>{const token=tabToken;const response=await fetch(link.getAttribute('href'),{credentials:'omit',headers:{Authorization:'Bearer '+token}});if(!response.ok){const err=await response.json();throw Error(err.error||'Не удалось скачать документ');}if(tabToken!==token)return;const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=link.dataset.filename||'document';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);});});

// Restricted live timer anchored to the clicked avatar; no modal interrupts the map.
let mapTimerState=null,mapTimerVersion=0;
function closeMapTimer(){
 mapTimerVersion++;
 if(!mapTimerState)return;
 clearInterval(mapTimerState.interval);
 mapTimerState.avatar.classList.remove('timer-selected');
 mapTimerState.bubble.remove();mapTimerState=null;
}
function openMapPerson(avatar){
 const id=Number(avatar.dataset.person);
 if(avatar.classList.contains('office-person')&&['manager','hr'].includes(user?.role))return showMapTimer(avatar,id);
 return personDetail(id);
}
function mapTimerText(p,elapsed=0){
 const kk=lang==='kk';
 if(p.mode==='off')return {label:kk?'Белсенді ауысым жоқ':'Нет активной смены',time:'—'};
 const label=p.mode==='work'?(kk?'Белсенді · жұмыс орнында':'Активен · на рабочем месте'):
  p.auto_break?(kk?'Әрекетсіздіктен үзіліс':'На перерыве · нет активности'):(kk?'Үзілісте':'На перерыве');
 return {label,time:duration(p.current_seconds+elapsed)};
}
async function showMapTimer(avatar,id){
 if(mapTimerState?.avatar===avatar){closeMapTimer();return;}
 closeMapTimer();const version=mapTimerVersion,token=tabToken;
 const bubble=document.createElement('div');bubble.className='map-person-timer';
 bubble.innerHTML=`<button type="button" class="map-timer-close" data-close-map-timer aria-label="Закрыть таймер">×</button><span class="map-timer-label">${lang==='kk'?'Жүктелуде…':'Загружаем…'}</span><strong class="map-timer-value">—</strong>${id!==user.id?`<div class="map-task-actions"><button type="button" data-open-chat="${id}">Написать сообщение</button><button type="button" data-new-task="${id}">＋ Добавить задачу</button></div>`:''}<button type="button" class="map-timer-profile" data-map-person-profile="${id}">${lang==='kk'?'Профильді ашу':'Открыть профиль'} ↗</button>`;
 avatar.appendChild(bubble);avatar.classList.add('timer-selected');
 const state={avatar,bubble,interval:null,current:null,received:0,busy:false,ticks:0};mapTimerState=state;
 const valid=()=>mapTimerVersion===version&&tabToken===token&&avatar.isConnected&&!avatar.hidden&&['manager','hr'].includes(user?.role);
 const paint=()=>{
  if(!state.current)return;
  const info=mapTimerText(state.current,Math.max(0,(Date.now()-state.received)/1000));
  bubble.querySelector('.map-timer-label').textContent=info.label;
  bubble.querySelector('.map-timer-value').textContent=info.time;
  bubble.style.transform='translateX(-50%)';
  const map=avatar.closest('.wv-office');
  if(map){
   const bounds=map.getBoundingClientRect(),rect=bubble.getBoundingClientRect();
   const dx=rect.left<bounds.left+8?bounds.left+8-rect.left:rect.right>bounds.right-8?bounds.right-8-rect.right:0;
   const dy=Math.max(0,bounds.top+8-rect.top);
   bubble.style.transform=`translate(calc(-50% + ${dx}px),${dy}px)`;
  }
 };
 const refresh=async()=>{
  if(state.busy)return;state.busy=true;
  try{
   const p=await api('/people/'+id+'/map-presence');
   if(!valid())return;
   state.current=p;state.received=Date.now();paint();
  }catch(e){if(valid()){state.current=null;bubble.querySelector('.map-timer-label').textContent=e.message;bubble.querySelector('.map-timer-value').textContent='—';}}
  finally{state.busy=false;}
 };
 state.interval=setInterval(()=>{
  if(!valid()){if(mapTimerState===state)closeMapTimer();return;}
  paint();if(++state.ticks%3===0)refresh();
 },1000);
 await refresh();
}
document.addEventListener('click',e=>{if(mapTimerState&&!e.target.closest('.office-person'))closeMapTimer();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMapTimer();});

document.addEventListener('dblclick',e=>{const avatar=e.target.closest('.office-person[data-person]');if(!avatar||e.target.closest('.map-person-timer'))return;closeMapTimer();action(avatar,()=>personDetail(Number(avatar.dataset.person)));});
