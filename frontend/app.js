const $=id=>document.getElementById(id);
let snapshot=null, working=false;
const projectKey='autocontent_project',pendingKey='autocontent_pending';
function el(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}
function busy(value){working=value;document.querySelectorAll('button').forEach(b=>b.disabled=value);}
function accept(result){snapshot=result;const id=result.project.id;localStorage.setItem(projectKey,id);$('project-id').value=id;render();}
async function readProject(id){const r=await fetch(`/api/projects/${encodeURIComponent(id)}`);const body=await r.json();if(!r.ok)throw Error(JSON.stringify(body.detail));accept(body);}
async function send(url,payload,retry=false){
 const request={url,payload:retry?payload:{request_id:crypto.randomUUID(),...payload}};
 localStorage.setItem(pendingKey,JSON.stringify(request));$('retry').hidden=false;
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request.payload)});
 const result=await r.json();
 if(!r.ok){if(r.status<500&&r.status!==409){localStorage.removeItem(pendingKey);$('retry').hidden=true;}throw Error(JSON.stringify(result.detail));}
 localStorage.removeItem(pendingKey);$('retry').hidden=true;return result;
}
async function run(action){busy(true);$('error').textContent='';try{await action();}catch(e){$('error').textContent=e.message;if(snapshot)try{await readProject(snapshot.project.id);}catch(_){} }finally{busy(false);}}
async function command(path,extra={}){
 if(localStorage.getItem(pendingKey))throw Error('Спочатку повторіть незавершений запит або оновіть стан.');
 const p=snapshot.project;accept(await send(`/api/projects/${p.id}/${path}`,{expected_revision:p.revision,...extra}));
}
function button(text,action,parent=$('actions')){const b=el('button',text);b.type='button';b.disabled=working;b.onclick=()=>run(action);parent.append(b);return b;}
function textAnswer(label,action,multiline=false){const form=el('form'),l=el('label',label),input=el(multiline?'textarea':'input');input.required=true;l.append(input);form.append(l);const b=el('button','Продовжити');form.append(b);form.onsubmit=e=>{e.preventDefault();run(()=>action(input.value.trim()));};$('actions').append(form);}
function showImage(slide){const a=el('article');a.append(el('h3',`Слайд ${slide.number} · версія ${slide.version}`));const image=el('img');image.className='slide';image.src=slide.url;image.alt=`Слайд ${slide.number}, ${slide.variant}`;const download=el('a','Завантажити PNG 1080×1350');download.href=slide.url;download.download='';a.append(image,download);$('content').append(a);}
function render(){
 $('workspace').hidden=false;$('welcome').hidden=true;$('content').replaceChildren();$('actions').replaceChildren();
 const p=snapshot.project,s=p.setup,state=p.state;
 $('message').textContent=snapshot.message;
 $('saved').textContent=`Проєкт збережено · ${p.id}`;
 if(state==='NICHE_SETUP'){
  if(p.pending_question==='niche_description')textAnswer('Ніша одним реченням',text=>command('setup',{text}));
  else{for(let n=1;n<=10;n++)button(String(n),()=>command('setup',{choice:n}));textAnswer('Або опишіть нішу',text=>command('setup',{text}));}
 }else if(state==='LOGO_SETUP'){
  const input=el('input');input.type='file';input.accept='image/png,image/jpeg';input.setAttribute('aria-label','Логотип PNG або JPEG');$('actions').append(input);
  button('Завантажити логотип',async()=>{if(!input.files[0])throw Error('Оберіть файл.');const body=new FormData();body.append('file',input.files[0]);const r=await fetch('/api/logos',{method:'POST',body});const a=await r.json();if(!r.ok)throw Error(JSON.stringify(a.detail));await command('setup',{logo_asset_id:a.asset_id});});
  button('Немає',()=>command('setup',{text:'немає'}));
 }else if(state==='COLOR_SETUP'){
  if(p.pending_question==='custom_colors')textAnswer('HEX-коди через кому',text=>command('setup',{colors:text.split(/[\s,;]+/).filter(Boolean)}));
  else{p.palette_options.forEach((palette,i)=>{const row=el('div');row.className='palette';palette.colors.forEach(color=>{const chip=el('span',color);chip.style.borderLeft=`24px solid ${color}`;row.append(chip);});$('content').append(row);button(`${i+1} — ${palette.name}`,()=>command('setup',{choice:i+1}));});button('8 — Власні кольори',()=>command('setup',{choice:8}));}
 }else if(state==='STYLE_SETUP'){
  if(p.pending_question==='custom_style')textAnswer('Опис стилю',text=>command('setup',{text}),true);
  else ['Реалізм','Pixar','Minecraft','3D Cartoon','Anime','Cinematic','Мінімалізм','Власний стиль'].forEach((label,i)=>button(`${i+1} — ${label}`,()=>command('setup',{choice:i+1})));
 }else if(state==='CONTENT_TYPE'){
  ['Пост','Reels','Карусель','Прогрів','Контент-план','Тригерні заголовки','CTA','Опис профілю','Stories','Лід-магніт'].forEach((label,i)=>button(`${i+1} — ${label}${i===2?'':' (наступна версія)'}`,()=>command('setup',{choice:i+1})));
 }else if(state==='FORMAT_SETUP'){
  const form=el('form'),fields={};
  for(const [key,label] of [['topic','Тема'],['goal','Ціль'],['audience','Аудиторія'],['product','Продукт / послуга']]){
   if(s[key]){fields[key]=s[key];$('content').append(el('p',`${label}: ${s[key]}`));}
   else{const l=el('label',label),i=el('input');i.required=true;l.append(i);form.append(l);fields[key]=i;}
  }
  const label=el('label','Кількість слайдів, включно з обкладинкою'),count=el('input');count.type='number';count.min=5;count.max=8;count.required=true;count.value=s.slide_count;label.append(count);form.append(label,el('button','Створити сценарій'));
  form.onsubmit=e=>{e.preventDefault();run(()=>command('carousel',{brief:{...Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,typeof v==='string'?v:v.value])),slide_count:Number(count.value)}}));};$('actions').append(form);
 }else if(state==='SCRIPT_REVIEW'){
  snapshot.script.slides.forEach(slide=>{const a=el('article');a.append(el('h3',`${slide.number}. ${slide.title}`),el('p',slide.body),el('p',`Головна думка: ${slide.main_idea}`),el('p',`Візуал: ${slide.visual}`));$('content').append(a);});
  if(p.pending_question==='script_changes')textAnswer('Що змінити?',changes=>command('script/edit',{changes}),true);
  else{button('1 — Так, усе підходить. Створюй окремі зображення.',()=>command('script/approve'));button('2 — Редагувати сценарій',()=>command('script/edit/start'));}
 }else if(['SCRIPT_CREATION','COVER_GENERATION','SLIDE_GENERATION'].includes(state)){
  if(!localStorage.getItem(pendingKey))button('Продовжити поточне завдання',()=>command('generation/resume'));
  button('Оновити стан',()=>readProject(p.id));
 }else if(state==='COVER_SELECTION'){
  snapshot.slides.filter(x=>x.number===1).forEach(showImage);button('1 — З людиною',()=>command('covers/select',{choice:1}));button('2 — Без людини',()=>command('covers/select',{choice:2}));
 }else if(state==='SLIDE_REVIEW'||state==='SLIDE_EDIT'){
  const versions=snapshot.slides.filter(x=>x.number===p.current_slide);showImage(versions.at(-1));
  if(versions.length>1){const details=el('details');details.append(el('summary','Попередні версії'));versions.slice(0,-1).forEach(v=>{const a=el('a',`Версія ${v.version}`);a.href=v.url;details.append(a,el('br'));});$('content').append(details);}
  if(state==='SLIDE_EDIT')textAnswer(`Що змінити у слайді ${p.current_slide}?`,changes=>command('slides/edit',{slide_number:p.current_slide,changes}),true);
  else{button(p.current_slide===p.brief.slide_count?'1 — Завершити карусель':'1 — Наступний',()=>command('slides/next',{confirmed_slide:p.current_slide}));button('2 — Редагуємо',()=>command('slides/edit/start'));}
 }else if(state==='COMPLETED'){
  showImage(snapshot.slides.find(x=>x.id===p.selected_cover));for(let n=2;n<=p.brief.slide_count;n++)showImage(snapshot.slides.filter(x=>x.number===n).at(-1));
 }
}
$('start').onsubmit=e=>{e.preventDefault();run(async()=>{if(localStorage.getItem(pendingKey))throw Error('Є незавершений запит.');const text=$('first-message').value.trim();accept(await send('/api/projects',{first_message:text||null}));});};
$('restore').onsubmit=e=>{e.preventDefault();run(()=>readProject($('project-id').value.trim()));};
$('new').onclick=()=>{if(localStorage.getItem(pendingKey)){$('error').textContent='Спочатку завершіть поточний запит.';return;}snapshot=null;localStorage.removeItem(projectKey);$('workspace').hidden=true;$('welcome').hidden=false;};
$('retry').onclick=()=>run(async()=>{const pending=JSON.parse(localStorage.getItem(pendingKey)||'null');if(pending)accept(await send(pending.url,pending.payload,true));});
$('refresh').onclick=()=>run(async()=>{if(snapshot)await readProject(snapshot.project.id);localStorage.removeItem(pendingKey);$('retry').hidden=true;});
$('retry').hidden=!localStorage.getItem(pendingKey);
const id=localStorage.getItem(projectKey);if(id)run(()=>readProject(id));