/* One persisted appearance per employee, shared by every surface. */
const appearances = {};
const avatarTextures = new Map();
const avatarDefaults = {1:0,2:1,3:2,4:9,5:3,6:4,7:5,8:6,9:7,10:8,11:10};
function defaultAppearance(id){return {base:avatarDefaults[id]??3,hair:'original',skin:'original',clothes:'original'};}
function avatarHTML(id,extra='',draft=null){
 const a=draft||appearances[id]||defaultAppearance(id),main=a.base<3,index=main?a.base:a.base-3;
 const style=main?`background-position:0 ${index*50}%`:`background-position:${index%4*100/3}% ${Math.floor(index/4)*50}%`;
 return `<span class="employee-avatar ${main?'character-sheet character-row-'+index:'npc-sheet'} ${extra}" data-avatar-id="${Number(id)}" ${draft?'data-avatar-preview="true"':''} style="${style}" aria-hidden="true"></span>`;
}
function repaintAvatars(){document.querySelectorAll('[data-avatar-id]:not([data-avatar-preview])').forEach(el=>paintAvatar(el,appearances[el.dataset.avatarId]||defaultAppearance(el.dataset.avatarId)));}
function paintAvatar(el,a){
 const key=JSON.stringify(a);if(el.dataset.appearance===key)return;el.dataset.appearance=key;
 const main=a.base<3,index=main?a.base:a.base-3;
 el.classList.remove('character-sheet','npc-sheet','character-row-0','character-row-1','character-row-2');
 el.classList.add(main?'character-sheet':'npc-sheet');if(main)el.classList.add('character-row-'+index);
 el.style.backgroundPosition=main?`0 ${index*50}%`:`${index%4*100/3}% ${Math.floor(index/4)*50}%`;
 el.style.backgroundImage='';
 if(['hair','skin','clothes'].every(k=>a[k]==='original'))return;
 if(!avatarTextures.has(key)){if(avatarTextures.size>=48)avatarTextures.delete(avatarTextures.keys().next().value);avatarTextures.set(key,makeAvatarTexture(a));}
 avatarTextures.get(key).then(url=>{if(el.dataset.appearance===key)el.style.backgroundImage=`url("${url}")`;}).catch(()=>{el.dataset.appearance='';});
}
async function makeAvatarTexture(a){
 const img=new Image();img.src=a.base<3?'/assets/office-characters.png':'/assets/npc-characters.png';await img.decode();
 const canvas=document.createElement('canvas');canvas.width=img.width;canvas.height=img.height;
 const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(img,0,0);
 const frameW=img.width/4,frameH=img.height/3,main=a.base<3,index=main?a.base:a.base-3;
 const pixels=ctx.getImageData(0,0,canvas.width,canvas.height),d=pixels.data;
 const colors=Object.fromEntries(['hair','skin','clothes'].map(k=>[k,a[k]==='original'?null:[1,3,5].map(i=>parseInt(a[k].slice(i,i+2),16))]));
 // Recolour material pixels while preserving outlines, eyes, shading and transparency.
 for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
  if(Math.floor(y/frameH)!==Math.floor(index/(main?1:4))||(!main&&Math.floor(x/frameW)!==index%4))continue;
  const p=(y*canvas.width+x)*4;if(d[p+3]<64)continue;
  const r=d[p],g=d[p+1],b=d[p+2],hi=Math.max(r,g,b),lo=Math.min(r,g,b),fx=(x%frameW)/frameW,fy=(y%frameH)/frameH;
  if(hi<35||lo>235)continue;
  const skin=r>g*1.08&&g>b*1.1&&r-g<100&&g-b<100;
  const face=fx>.28&&fx<.72&&fy>.28&&fy<.60;
  const hand=(fx<.34||fx>.66)&&fy>.64&&fy<.86;
  const back=main&&Math.floor(x/frameW)===3;
  let material=null;
  if(skin&&(!back&&face||hand||fy>.86))material='skin';
  else if(fy<.36 || (fy<.60&&(fx<.28||fx>.72)) || (back&&index!==1&&fy<.72))material='hair';
  else if(fy>.60&&fy<.85&&!hand&&(hi-lo>12||hi<160))material='clothes';
  if(!material||!colors[material])continue;
  const shade=Math.max(.20,Math.min(1.25,(r*.299+g*.587+b*.114)/160));
  for(let j=0;j<3;j++)d[p+j]=Math.min(255,Math.round(colors[material][j]*shade));
 }
 ctx.putImageData(pixels,0,0);return canvas.toDataURL();
}
let avatarSyncBusy=false;
async function syncAvatars(){if(!user||avatarSyncBusy)return;avatarSyncBusy=true;const uid=user.id;try{const data=await api('/avatars');if(user?.id===uid){Object.assign(appearances,data);repaintAvatars();}}catch(e){/* Next poll retries without disrupting office activity. */}finally{avatarSyncBusy=false;}}
function openAvatarEditor(){
 const draft={...(appearances[user.id]||defaultAppearance(user.id))};let tab='base';
 openDialog('Мой образ',`<div class="avatar-editor"><div class="avatar-preview" id="avatarPreview"></div><div class="avatar-options"><div class="avatar-tabs" role="tablist">${[['base','Персонаж'],['hair','Волосы'],['skin','Кожа'],['clothes','Одежда']].map(([k,v])=>`<button class="btn" role="tab" data-look-tab="${k}">${v}</button>`).join('')}</div><div id="avatarChoices"></div></div></div><p class="tiny muted">В «Персонаже» можно выбрать причёску и силуэт. В остальных разделах — изменить цвета.</p><p id="avatarError" role="alert"></p><div class="dialog-actions"><button class="btn" id="avatarCancel">Отмена</button><button class="btn btn-primary" id="avatarSave">Сохранить образ</button></div>`);
 function preview(){const box=$('#avatarPreview');box.innerHTML=avatarHTML(user.id,'',draft);paintAvatar(box.firstElementChild,draft);}
 function choices(){document.querySelectorAll('[data-look-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.lookTab===tab)));
 const root=$('#avatarChoices');if(tab==='base'){root.innerHTML=`<div class="avatar-bases">${Array.from({length:15},(_,base)=>`<button class="avatar-base ${draft.base===base?'selected':''}" data-look-base="${base}" aria-label="Персонаж ${base+1}" aria-pressed="${draft.base===base}">${avatarHTML(user.id,'',{base,hair:'original',skin:'original',clothes:'original'})}</button>`).join('')}</div>`;root.querySelectorAll('[data-look-base]').forEach(b=>b.onclick=()=>{draft.base=Number(b.dataset.lookBase);preview();choices();});}
 else {const palette=tab==='skin'?['#f3c9a6','#dca478','#ba7c52','#895436','#593725']:tab==='hair'?['#292427','#69432b','#ae6b32','#ddbb72','#bfc2c5','#9b2639']:['#28538d','#39764b','#874ba3','#ca4c3e','#d49b32','#38404b'];root.innerHTML=`<div class="avatar-swatches"><button class="btn" data-look-color="original">Исходный</button>${palette.map(c=>`<button style="background:${c}" data-look-color="${c}" aria-label="Цвет ${c}" aria-pressed="${draft[tab]===c}"></button>`).join('')}</div><label>Свой цвет <input id="avatarCustomColor" type="color" value="${draft[tab]==='original'?palette[0]:draft[tab]}"></label>`;root.querySelectorAll('[data-look-color]').forEach(b=>b.onclick=()=>{draft[tab]=b.dataset.lookColor;preview();choices();});$('#avatarCustomColor').oninput=e=>{draft[tab]=e.target.value;preview();};}}
 document.querySelectorAll('[data-look-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.lookTab;choices();});
 $('#avatarCancel').onclick=()=>navigate('profile');
 $('#avatarSave').onclick=e=>action(e.currentTarget,async()=>{try{const saved=await api('/avatar','POST',draft);appearances[user.id]=saved;repaintAvatars();decorateIdentity();await navigate('profile');toast('Образ сохранён и обновлён на карте');}catch(err){$('#avatarError').textContent=err.message;}});
 preview();choices();
}
document.addEventListener('click',e=>{if(e.target.closest('[data-edit-avatar]')){syncAvatars().then(openAvatarEditor);}});
document.addEventListener('DOMContentLoaded',()=>{new MutationObserver(()=>repaintAvatars()).observe(document.body,{childList:true,subtree:true});syncAvatars();setInterval(syncAvatars,4000);});
