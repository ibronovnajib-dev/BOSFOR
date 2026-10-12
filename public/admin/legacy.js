/* ================= STATE ================= */
const $=s=>document.querySelector(s), $$=s=>document.querySelectorAll(s);
let LANG=localStorage.getItem('bosfor_adm_lang')||'ru';
let CSRF='';
let PRINCIPAL_ROLE='owner', PRINCIPAL_NAME='Owner';
let TAB='dash', QUERY='', SOUND=localStorage.getItem('bosfor_sound')!=='0', LOGGED_IN=false;
let DATA={orders:[],bookings:[],customers:[],promos:[]}, TABLES=[], TABLES_DIRTY=false, lastTs=0, ready=false;
let OF='all', MENU=[], MENU_LOADED=false, MENU_DIRTY=false, SETTINGS=null;

const T=(ru,tj)=>LANG==='tj'?tj:ru;
const ST_O={new:['Новый','Нав'],confirmed:['Подтверждён','Тасдиқшуда'],cooking:['Готовится','Омода мешавад'],delivery:['В пути','Дар роҳ'],done:['Выдан','Супорида шуд'],cancelled:['Отменён','Бекор шуд']};
const ST_B={new:['Новая','Нав'],confirmed:['Подтверждена','Тасдиқшуда'],cancelled:['Отменена','Бекор шуд']};
const PAY={cash:['Наличные','Нақд'],card:['Карта','Корт'],qr:['QR-код','QR-код'],wallet:['Эл.кошелёк','Ҳамёни эл.']};
const CATS={break:['Завтраки','Субҳона'],grill:['На гриле','Дар гриль'],fast:['Фастфуд','Фастфуд'],sushi:['Суши','Суши'],salad:['Салаты','Салатҳо'],drinks:['Напитки','Нӯшокиҳо']};
const ORDF={all:['Все','Ҳама'],newF:['Новые','Навҳо'],active:['Активные','Фаъолӣ'],doneF:['Завершённые','Анҷомёфта'],cancelled:['Отменённые','Бекоршуда']};

/* ================= HELPERS ================= */
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function fmtTime(ts){try{const d=new Date(ts);return d.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'})+' '+d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}catch(e){return'—'}}
function initials(n){const w=String(n||'?').trim().split(/\s+/);return ((w[0]?.[0]||'?')+(w[1]?.[0]||'')).toUpperCase()}
function phoneHref(p){return (String(p||'').replace(/[^+\d]/g,''))||'#'}
function waHref(p){let d=String(p||'').replace(/\D/g,'');if(d.length===9)d='992'+d;return 'https://wa.me/'+d}
function dayKey(ts){const d=new Date(ts);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
let toastT;
function toast(txt){const t=$('#toast');t.textContent=txt;t.classList.add('show');clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove('show'),2800)}
function beep(){if(!SOUND)return;try{
  const ctx=new (window.AudioContext||window.webkitAudioContext)();
  const o=ctx.createOscillator(),g=ctx.createGain();o.connect(g);g.connect(ctx.destination);
  o.type='sine';o.frequency.value=880;g.gain.setValueAtTime(.14,ctx.currentTime);
  o.start();o.frequency.setValueAtTime(1318,ctx.currentTime+.14);
  g.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+.55);o.stop(ctx.currentTime+.6);
}catch(e){}}

/* ================= API ================= */
async function api(path){
  const r=await fetch(path,{cache:'no-store',credentials:'same-origin'});
  if(r.status===401){showLogin();throw new Error('auth')}
  if(!r.ok)throw new Error('http '+r.status);
  return r.json();
}
async function adminPost(path,body={}){
  const r=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':CSRF},body:JSON.stringify(body)});
  const j=await r.json().catch(()=>({}));
  if(r.status===401){showLogin();throw new Error('auth')}
  if(!r.ok)throw new Error(j.error||('http '+r.status));
  return j;
}
async function logout(){try{await fetch('/api/admin/logout',{method:'POST',credentials:'same-origin'})}catch(e){} CSRF='';showLogin()}
function showLogin(){
  LOGGED_IN=false;clearInterval(retryT);clearInterval(pollT);
  $('#appView').classList.remove('on');
  $('#loginView').style.display='grid';
  $('#loginErr').textContent='';
}
async function loadAll(silent){
  try{
    const [o,b,st,c,p,tables]=await Promise.all([api('/api/orders'),api('/api/bookings'),api('/api/settings'),api('/api/customers'),api('/api/promotions'),api('/api/tables')]);
    const mx=Math.max(0,...o.map(x=>+x.ts||0),...b.map(x=>+x.ts||0));
    if(!silent&&ready&&mx>lastTs){toast(T('🔔 Новая заявка!','🔔 Дархости нав!'));beep()}
    lastTs=mx; ready=true; DATA={orders:o,bookings:b,customers:c,promos:p}; if(!TABLES_DIRTY)TABLES=tables; SETTINGS=st;
    if(!(TAB==='menu'&&MENU_DIRTY)) render();
    updateSettingsUI();
    const e=$('#apiErr'); if(e)e.remove();
  }catch(err){
    if(String(err.message)!=='auth'&&!$('#apiErr')&&TAB!=='menu'){
      const d=document.createElement('div');d.id='apiErr';
      const span=document.createElement('span');span.textContent='⚠️ '+T('Сервер API не отвечает — повторная попытка…','Сервери API посух намекунад — бозкӯшиш…');
      const btn=document.createElement('button');btn.textContent='⟳';btn.onclick=()=>loadAll(false);d.append(span,btn);
      document.body.appendChild(d); setTimeout(()=>loadAll(false),7000);
    }
  }
}

/* ================= RENDER ROUTER ================= */
function render(){
  $$('.view').forEach(v=>v.classList.remove('on'));
  ($('#v-'+(TAB==='books'?'books':TAB))||$('#v-dash')).classList.add('on');
  $('#searchInp').style.visibility=(TAB==='orders'||TAB==='books'||TAB==='customers')?'visible':'hidden';
  renderCounts();
  if(TAB==='dash')renderDash();
  if(TAB==='orders')renderOrders();
  if(TAB==='kitchen')renderKitchen();
  if(TAB==='books')renderBooks();
  if(TAB==='menu')renderMenuTab();
  if(TAB==='customers')renderCustomers();
  if(TAB==='promos')renderPromos();
  if(TAB==='tables')renderTables();
}
function renderCounts(){
  $('#cntOrders').textContent='('+DATA.orders.length+')';
  $('#cntBooks').textContent='('+DATA.bookings.length+')';
}

/* ================= DASHBOARD ================= */
function renderDash(){
  const d0=new Date();d0.setHours(0,0,0,0);const t0=d0.getTime();
  const ot=DATA.orders.filter(o=>(+o.ts||0)>=t0);
  $('#stOrders').textContent=ot.length;
  const rev=ot.filter(o=>o.status!=='cancelled').reduce((s,o)=>s+(+o.total||0),0);
  $('#stRevenue').textContent=rev;
  $('#stBooks').textContent=DATA.bookings.filter(b=>(+b.ts||0)>=t0).length;
  $('#stPending').textContent=[...DATA.orders,...DATA.bookings].filter(x=>x.status==='new').length;
  renderChart(); renderTop(); renderFeed();
}
function renderChart(){
  const days=[];const sums={};let total=0;
  for(let i=6;i>=0;i--){const d=new Date();d.setDate(d.getDate()-i);const k=dayKey(d);days.push({k,l:String(d.getDate()).padStart(2,'0')+'.'+String(d.getMonth()+1).padStart(2,'0')});sums[k]=0}
  DATA.orders.forEach(o=>{const k=dayKey(o.ts||0);if(k in sums&&o.status!=='cancelled'){sums[k]+=+o.total||0;total+=+o.total||0}});
  const vals=days.map(d=>sums[d.k]);const mx=Math.max(...vals,0);
  $('#chartSum').textContent=T('всего: ','ҳамагӣ: ')+total+' с';
  if(!mx){$('#chart').innerHTML='<div class="chart-empty">'+T('Пока нет данных — создайте тестовый заказ 🧪','Ҳанӯз маълумот нест — фармоиши озмоишӣ созед 🧪')+'</div>';return}
  const W=700,H=210,padT=26,padB=34,padX=14;
  const bw=Math.floor((W-padX*2)/7)-20;
  let bars='';
  [0.25,0.5,0.75].forEach(f=>{const y=padT+(H-padT-padB)*(1-f);bars+='<line class="grid-l" x1="'+padX+'" x2="'+(W-padX)+'" y1="'+y+'" y2="'+y+'"/>'});
  days.forEach((d,i)=>{
    const v=sums[d.k];const h=mx?(H-padT-padB)*(v/mx):0;
    const x=padX+i*((W-padX*2)/7)+10;const y=H-padB-h;
    bars+='<rect x="'+x+'" y="'+y+'" width="'+bw+'" height="'+Math.max(h,2)+'" rx="7" fill="url(#gg)"/>'+
      (v?'<text class="bar-val" x="'+(x+bw/2)+'" y="'+(y-7)+'" text-anchor="middle">'+v+'</text>':'')+
      '<text class="bar-lbl" x="'+(x+bw/2)+'" y="'+(H-padB+18)+'" text-anchor="middle">'+d.l+'</text>';
  });
  $('#chart').innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%"><defs><linearGradient id="gg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f6dd95"/><stop offset="1" stop-color="#b4832a"/></linearGradient></defs>'+bars+'</svg>';
}
function renderTop(){
  const agg={};
  DATA.orders.filter(o=>o.status!=='cancelled').forEach(o=>(o.items||[]).forEach(i=>{
    const nm=LANG==='tj'?(i.n2||i.n||'?'):(i.n||'?');
    agg[nm]=(agg[nm]||0)+(+i.q||1);
  }));
  const top=Object.entries(agg).sort((a,b)=>b[1]-a[1]).slice(0,5);
  if(!top.length){$('#topDishes').innerHTML='<div class="chart-empty">—</div>';return}
  const mx=top[0][1];
  $('#topDishes').innerHTML=top.map(([n,c])=>'<div class="top-i"><div class="row"><span>'+esc(n)+'</span><b>'+c+'×</b></div><div class="topbar"><i style="width:'+Math.round(c/mx*100)+'%"></i></div></div>').join('');
}
function renderFeed(){
  const all=[...DATA.orders.map(x=>({...x,_t:'order'})),...DATA.bookings.map(x=>({...x,_t:'booking'}))]
    .sort((a,b)=>(+b.ts||0)-(+a.ts||0)).slice(0,6);
  if(!all.length){$('#feed').innerHTML='<div class="chart-empty">'+T('Заявок пока нет','Ҳанӯз дархост нест')+'</div>';return}
  $('#feed').innerHTML=all.map(x=>{
    const map=x._t==='order'?ST_O:ST_B;const st=map[x.status||'new'];
    return '<div class="feed-i"><span style="font-size:19px">'+(x._t==='order'?'📦':'🍽️')+'</span>'+
      '<div class="who"><b>'+esc(x.name||'—')+' · #'+esc(x.id||'')+'</b><span>'+fmtTime(x.ts)+(x._t==='order'&&x.total?' · '+x.total+' с':'')+(x.date?' · '+esc(x.date)+' '+esc(x.time||''):'')+'</span></div>'+
      '<span class="mini-badge st-'+(x.status||'new')+'">'+T(st[0],st[1])+'</span>'+
      '<button class="btn-sm" onclick="goItem(\''+x._t+'\',\''+esc(x.id)+'\')">'+T('Открыть','Кушодан')+' →</button></div>';
  }).join('');
}
function goItem(type,id){
  TAB=type==='order'?'orders':'books';
  QUERY=id;$('#searchInp').value=id;
  $$('.tab').forEach(t=>t.classList.toggle('on',t.dataset.tab===TAB));
  render();
}

/* ================= ORDERS / BOOKINGS ================= */
function matchQ(arr){
  const q=QUERY.trim().toLowerCase();
  return arr.filter(x=>!q||[x.id,x.name,x.phone,(x.items||[]).map(i=>i.n).join(' ')].join(' ').toLowerCase().includes(q));
}
function renderOrders(){
  const wrap=$('#ordFilters');
  const cnt=(f)=>DATA.orders.filter(x=>f==='all'?true:f==='newF'?x.status==='new':f==='active'?(x.status!=='done'&&x.status!=='cancelled'):f==='doneF'?x.status==='done':x.status==='cancelled').length;
  wrap.innerHTML=Object.keys(ORDF).map(k=>'<button class="fchip '+(OF===k?'on':'')+'" data-f="'+k+'">'+T(ORDF[k][0],ORDF[k][1])+' ('+cnt(k)+')</button>').join('');
  wrap.querySelectorAll('.fchip').forEach(b=>b.onclick=()=>{OF=b.dataset.f;renderOrders()});
  let arr=matchQ([...DATA.orders].sort((a,b)=>(+b.ts||0)-(+a.ts||0)));
  if(OF!=='all')arr=arr.filter(x=>OF==='newF'?x.status==='new':OF==='active'?(x.status!=='done'&&x.status!=='cancelled'):OF==='doneF'?x.status==='done':x.status==='cancelled');
  $('#list').innerHTML=arr.length?arr.map(orderCard).join(''):emptyHtml('📦',T('Заказов пока нет','Ҳанӯз фармоиш нест'));
}
function renderKitchen(){
  const active=[...DATA.orders].filter(o=>['new','confirmed','cooking'].includes(o.status)).sort((a,b)=>(+a.ts||0)-(+b.ts||0));
  $('#kitchenList').innerHTML=active.length?active.map(o=>{
    const items=(o.items||[]).map(i=>'<div class="li"><span><b>'+esc(i.q||1)+'×</b> '+esc(LANG==='tj'&&i.n2?i.n2:i.n)+'</span></div>').join('');
    const next=o.status==='new'?'confirmed':o.status==='confirmed'?'cooking':'done';
    const lbl=o.status==='new'?T('Принять','Қабул'):o.status==='confirmed'?T('Готовить','Омода кардан'):T('Готово','Тайёр');
    return '<div class="ocard"><div class="oc-top"><span class="oc-id">#'+esc(o.id)+'</span><span class="oc-time">'+fmtTime(o.ts)+'</span></div><div class="oc-items">'+items+'</div><div class="chips">'+(o.scheduled_for?'<span class="chip">🕒 '+esc(o.scheduled_for.replace('T',' '))+'</span>':'')+(o.table_no?'<span class="chip gold">🪑 '+esc(o.table_no)+'</span>':'')+'</div><div class="oc-foot"><span class="oc-total">'+(+o.total||0)+' <i>с</i></span><button class="btn-gold" data-kitchen-id="'+esc(o.id)+'" data-kitchen-next="'+next+'">'+lbl+' →</button></div></div>';
  }).join(''):'<div class="chart-empty">'+T('Активных заказов нет','Фармоиши фаъол нест')+'</div>';
  $('#kitchenList').querySelectorAll('[data-kitchen-id]').forEach(b=>b.onclick=()=>kitchenNext(b.dataset.kitchenId,b.dataset.kitchenNext));
}
async function kitchenNext(id,status){
  try{await adminPost('/api/status',{type:'order',id,status});const o=DATA.orders.find(x=>x.id===id);if(o)o.status=status;renderKitchen();renderCounts();toast(T('✓ Статус обновлён','✓ Ҳолат тағйир ёфт'))}
  catch(e){toast(T('Ошибка','Хатогӣ'))}
}

function renderBooks(){
  const arr=matchQ([...DATA.bookings].sort((a,b)=>(+b.ts||0)-(+a.ts||0)));
  $('#listB').innerHTML=arr.length?arr.map(bookCard).join(''):emptyHtml('🍽️',T('Броней пока нет','Ҳанӯз брон нест'));
}
function emptyHtml(ic,txt){
  return '<div class="empty"><div class="big">'+ic+'</div><p>'+txt+'</p>'+
  '<button class="btn-ghost" onclick="sendDemo()" style="margin-top:16px">🧪 '+T('Создать тестовую заявку','Дархости озмоишӣ сохтан')+'</button></div>';
}
function statusSelect(type,id,cur,map){
  return '<select class="stsel st-'+cur+'" onchange="setStatus(\''+type+'\',\''+esc(id)+'\',this.value,this)">'+
    Object.keys(map).map(k=>'<option value="'+k+'" '+(k===cur?'selected':'')+'>'+T(map[k][0],map[k][1])+'</option>').join('')+'</select>';
}
function orderCard(o){
  const st=o.status||'new';
  const items=(o.items||[]).map(i=>'<div class="li"><span><b>'+esc(i.q||1)+'×</b> '+esc(LANG==='tj'&&i.n2?i.n2:i.n)+'</span><span>'+((i.q||1)*(+i.p||0))+' с</span></div>').join('')||'<div class="li">—</div>';
  const mode=o.mode==='delivery'?T('🛵 Доставка','🛵 Расонидан'):(o.mode==='dinein'?T('🍽 В ресторане','🍽 Дар ресторан'):T('🥡 Самовывоз','🥡 Худам мебарам'));
  const pay=T((PAY[o.pay]||[o.pay||'—',o.pay||'—'])[0],(PAY[o.pay]||[o.pay||'—',o.pay||'—'])[1]);
  return '<div class="ocard">'+
    '<div class="oc-top"><span class="oc-id">#'+esc(o.id||'—')+'</span><button class="btn-sm" onclick="printOrder(\''+esc(o.id)+'\')" title="'+T('Печать чека','Чопи чек')+'">🖨️</button><span class="oc-time">'+fmtTime(o.ts)+'</span></div>'+
    '<div class="oc-items">'+items+'</div>'+
    '<div class="oc-who"><div class="avatar">'+esc(initials(o.name))+'</div>'+
      '<div style="flex:1;min-width:0"><b>'+esc(o.name||'—')+'</b>'+
      '<div class="oc-contact"><a href="tel:'+phoneHref(o.phone)+'">📞 '+esc(o.phone||'—')+'</a><a href="'+waHref(o.phone)+'" target="_blank" rel="noopener">WhatsApp →</a></div></div></div>'+
    '<div class="chips"><span class="chip gold">'+mode+'</span><span class="chip">💳 '+pay+'</span>'+(o.addr?'<span class="chip">📍 '+esc(o.addr)+'</span>':'')+(o.table_no?'<span class="chip">🪑 '+esc(o.table_no)+'</span>':'')+(o.scheduled_for?'<span class="chip">🕒 '+esc(o.scheduled_for.replace('T',' '))+'</span>':'')+(o.promo_code?'<span class="chip">🎟 '+esc(o.promo_code)+' −'+(+o.discount||0)+' с</span>':'')+(o.loyalty_earned?'<span class="chip">🎁 +'+(+o.loyalty_earned||0)+'</span>':'')+'</div>'+
    '<div class="oc-foot"><span class="oc-total">'+(+o.total||0)+' <i>с</i></span>'+statusSelect('order',o.id,st,ST_O)+'</div></div>';
}
function bookCard(b){
  const st=b.status||'new';
  return '<div class="ocard">'+
    '<div class="oc-top"><span class="oc-id">#'+esc(b.id||'—')+'</span><span class="oc-time">'+fmtTime(b.ts)+'</span></div>'+
    '<div class="oc-items"><div class="li"><span>🗓 '+T('Дата и время','Сана ва вақт')+'</span><b>'+esc(b.date||'—')+' · '+esc(b.time||'—')+'</b></div>'+
    '<div class="li"><span>👥 '+T('Гостей','Меҳмонон')+'</span><b>'+esc(b.guests||'—')+'</b></div>'+
    (b.note?'<div class="li"><span>💬 '+T('Пожелания','Дархостҳо')+'</span><b>'+esc(b.note)+'</b></div>':'')+'</div>'+
    '<div class="oc-who"><div class="avatar" style="background:linear-gradient(130deg,#c98ef0,#7d4fd0)">'+esc(initials(b.name))+'</div>'+
      '<div style="flex:1;min-width:0"><b>'+esc(b.name||'—')+'</b>'+
      '<div class="oc-contact"><a href="tel:'+phoneHref(b.phone)+'">📞 '+esc(b.phone||'—')+'</a><a href="'+waHref(b.phone)+'" target="_blank" rel="noopener">WhatsApp →</a></div></div></div>'+
    '<div class="oc-foot"><span class="chip gold">🍽️ '+T('Бронь стола','Фармоиши миз')+'</span>'+statusSelect('booking',b.id,st,ST_B)+'</div></div>';
}

/* ================= CUSTOMERS & PROMOS ================= */
function renderCustomers(){
  const q=QUERY.trim().toLowerCase(); const arr=(DATA.customers||[]).filter(x=>!q||[x.name,x.phone].join(' ').toLowerCase().includes(q));
  $('#customerList').innerHTML=arr.length?arr.map(c=>'<div class="feed-i"><div class="avatar">'+esc(initials(c.name))+'</div><div class="who"><b>'+esc(c.name||'—')+'</b><span>'+esc(c.phone||'')+'</span></div><span class="chip">📦 '+(+c.orders_count||0)+'</span><span class="chip">💰 '+(+c.total_spent||0)+' с</span><span class="chip gold">🎁 '+(+c.points||0)+'</span></div>').join(''):'<div class="chart-empty">—</div>';
}

function renderTables(){
  const box=$('#tableEdit'); if(!box)return;
  const base=($('#qrBaseUrl')?.value||location.origin).replace(/\/$/,'');
  box.innerHTML=(TABLES||[]).map((tb,i)=>{
    const code=tb.code||'';
    const qrSrc='/api/table-qr.svg?table='+encodeURIComponent(code)+'&base='+encodeURIComponent(base);
    return `<div class="mitem"><div class="md-g"><input class="inp" value="${esc(code)}" placeholder="12" onchange="tset(${i},'code',this.value)"><input class="inp" value="${esc(tb.label||'')}" placeholder="Стол 12 / Мизи 12" onchange="tset(${i},'label',this.value)"><input class="inp" type="number" min="1" max="30" value="${esc(tb.capacity||2)}" onchange="tset(${i},'capacity',this.value)"><input class="inp" value="${esc(tb.zone||'')}" placeholder="Зал / Веранда" onchange="tset(${i},'zone',this.value)"></div><div style="margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><label class="chk"><input type="checkbox" ${tb.active!==0?'checked':''} onchange="tset(${i},'active',this.checked)"> <span>${T('Активен','Фаъол')}</span></label><code style="color:var(--gold2)">${esc(base)}/?table=${esc(code)}</code><button class="btn-sm" onclick="printSingleQr(${i})">QR</button><a class="btn-sm" href="${qrSrc}" target="_blank" rel="noopener">SVG</a><button class="btn-danger" onclick="tdel(${i})">${T('Удалить','Нест кардан')}</button></div></div>`
  }).join('') || `<div class="empty">🪑 ${T('Столы пока не добавлены','Мизҳо ҳоло илова нашудаанд')}</div>`;
}
function tset(i,k,v){TABLES[i][k]=k==='capacity'?Math.max(1,Math.min(30,+v||1)):(k==='active'?(v?1:0):v);TABLES_DIRTY=true;renderTables()}
function tdel(i){if(!confirm(T('Удалить стол?','Миз нест шавад?')))return;TABLES.splice(i,1);TABLES_DIRTY=true;renderTables()}
function getQrBase(){let b=($('#qrBaseUrl')?.value||location.origin).trim();if(!/^https?:\/\//.test(b))b=location.origin;return b.replace(/\/$/,'')}
function activeTables(){return (TABLES||[]).filter(t=>t&&t.code&&t.active!==0)}
function printSingleQr(i){printQrCards([TABLES[i]].filter(Boolean))}
function printQrCards(list){
  const arr=(list&&list.length?list:activeTables());
  if(!arr.length){toast(T('Сначала добавьте активные столы','Аввал мизҳои фаъолро илова кунед'));return}
  const base=getQrBase();
  const w=window.open('','_blank','width=960,height=720');
  if(!w){toast(T('Разрешите всплывающие окна','Равзанаҳои pop-up иҷозат диҳед'));return}
  const cards=arr.map(t=>{const code=esc(t.code||'');const label=esc(t.label||('Стол '+code));const zone=esc(t.zone||'');const src='/api/table-qr.svg?table='+encodeURIComponent(t.code||'')+'&base='+encodeURIComponent(base);return `<section class="card"><div class="brand"><b>БОСФОР</b><span>QR ORDER</span></div><img src="${src}" alt="QR ${code}"><h2>${label}</h2><p>${zone}</p><small>${esc(base)}/?table=${code}</small><div class="foot">Наведите камеру · Камераро равона кунед</div></section>`}).join('');
  const html=`<!DOCTYPE html><html><head><meta charset="utf-8"><title>QR cards · Bosfor</title><style>body{margin:0;background:#eee;font-family:Arial,sans-serif;color:#211604}.wrap{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;padding:16px}.card{background:#fff;border:2px solid #211604;border-radius:18px;padding:22px;text-align:center;min-height:390px;display:flex;flex-direction:column;align-items:center;justify-content:center;break-inside:avoid}.brand{display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:10px}.brand b{letter-spacing:.18em;font-size:22px}.brand span{border:1px solid #211604;border-radius:999px;padding:4px 9px;font-size:10px;font-weight:bold}.card img{width:210px;height:210px}.card h2{font-size:28px;margin:10px 0 4px}.card p{margin:0 0 8px;color:#6a5840}.card small{font-size:11px;color:#79664a}.foot{margin-top:14px;font-weight:bold}@media print{body{background:#fff}.wrap{padding:0;gap:0;grid-template-columns:repeat(2,1fr)}.card{border-radius:0;border:1px dashed #999;margin:0;min-height:48vh}}</style></head><body onload="setTimeout(()=>window.print(),400)"><div class="wrap">${cards}</div></body></html>`;
  w.document.write(html);w.document.close();
}

function renderPromos(){
  $('#promoList').innerHTML=(DATA.promos||[]).length?DATA.promos.map(p=>'<div class="feed-i"><div class="who"><b>'+esc(p.code)+'</b><span>'+esc(p.discount_type==='percent'?p.value+'%':p.value+' с')+' · min '+(+p.min_total||0)+' с</span></div><span class="mini-badge '+(p.active?'st-done':'st-cancelled')+'">'+(p.active?'ON':'OFF')+'</span><button class="btn-danger" data-promo-del="'+esc(p.code)+'">🗑</button></div>').join(''):'<div class="chart-empty">'+T('Промокодов пока нет','Ҳанӯз промокод нест')+'</div>';
  $('#promoList').querySelectorAll('[data-promo-del]').forEach(b=>b.onclick=()=>deletePromo(b.dataset.promoDel));
}
async function deletePromo(code){if(!confirm(T('Удалить промокод?','Промокод нест шавад?')))return;try{await adminPost('/api/promotions',{action:'delete',code});DATA.promos=await api('/api/promotions');renderPromos();toast(T('Удалено','Нест шуд'))}catch(e){toast(T('Ошибка','Хатогӣ'))}}

/* ================= ACTIONS ================= */
async function setStatus(type,id,status,el){
  try{
    await adminPost('/api/status',{type,id,status});
    const coll=type==='order'?DATA.orders:DATA.bookings;
    const it=coll.find(x=>x.id===id); if(it)it.status=status;
    toast(T('✓ Статус обновлён','✓ Ҳолат тағйир ёфт')); render();
  }catch(e){toast(T('Ошибка связи','Хатои алоқа'));loadAll(true)}
}
async function sendDemo(){
  const demoO={name:T('Тест Гость','Меҳмони озмоишӣ'),phone:'+992 900 112 211',mode:'delivery',addr:'ул. Гафурова, 68',pay:'cash',items:[{id:'shashlik',qty:1}]};
  const demoB={name:'Демо Бронь',phone:'+992 900 333 444',guests:'3–4',date:(()=>{const d=new Date(),p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())})(),time:'19:00',note:T('Веранда, если можно','Веранда, агар мумкин')};
  try{
    let r=await fetch('/api/order',{method:'POST',headers:{'Content-Type':'application/json','X-Idempotency-Key':'demo-order-'+Date.now()},body:JSON.stringify(demoO)});if(!r.ok)throw new Error();
    r=await fetch('/api/booking',{method:'POST',headers:{'Content-Type':'application/json','X-Idempotency-Key':'demo-booking-'+Date.now()},body:JSON.stringify(demoB)});if(!r.ok&&r.status!==409)throw new Error();
    toast(T('✓ Тестовые заявки созданы','✓ Дархостҳои озмоишӣ сохта шуд')); loadAll(true);
  }catch(e){toast(T('Сервер API не отвечает','Сервери API посух намекунад'))}
}

/* ================= PRINT RECEIPT ================= */
function printOrder(id){
  const o=DATA.orders.find(x=>x.id===id); if(!o)return;
  const C=t=>'</'+t+'>'; /* закрывающие теги собираем динамически — чтобы viewer не резал страницу */
  const rows=(o.items||[]).map(i=>'<tr><td>'+esc(i.q||1)+'× '+esc(i.n||'')+C('td')+'<td style="text-align:right">'+((i.q||1)*(+i.p||0))+C('td')+C('tr')).join('');
  const w=window.open('','_blank','width=380,height=640');
  if(!w){toast(T('Разрешите всплывающие окна','Равзанаҳои поп-упро иҷозат диҳед'));return}
  const html=[
    '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Чек '+esc(id)+C('title'),
    '<style>body{font-family:monospace;width:280px;margin:18px auto;color:#000;font-size:13px}'+
    'h1{font-size:19px;text-align:center;margin:0 0 2px}.sub{text-align:center;font-size:11px;margin-bottom:12px}'+
    'table{width:100%;border-collapse:collapse;margin:10px 0}td{padding:3px 0}'+
    '.tot{border-top:1px dashed #000;border-bottom:1px dashed #000;padding:8px 0;margin:8px 0;font-size:16px;font-weight:bold;display:flex;justify-content:space-between}'+
    '.f{text-align:center;margin-top:14px;font-size:11px}hr{border:none;border-top:1px dashed #000}'+
    '@media print{body{margin:0}}'+C('style'),
    C('head')+'<body onload="window.print()">',
    '<h1>БОСФОР</h1><div class="sub">ул. Гафурова 68 · +992 977 11 21 12<br>'+fmtTime(o.ts)+' · Заказ '+esc(id)+C('div')+'<hr>',
    '<table>'+rows+C('table'),
    '<div class="tot"><span>ИТОГО</span><span>'+(+o.total||0)+' с</span>'+C('div'),
    '<div>Клиент: '+esc(o.name||'')+'<br>Тел: '+esc(o.phone||'')+'<br>'+(o.mode==='delivery'?'Доставка: '+esc(o.addr||''):'Самовывоз')+'<br>Оплата: '+esc(o.pay||'')+C('div'),
    '<div class="f">Спасибо за заказ! · Ташаккур! 🔥'+C('div'),
    C('body')+C('html')
  ].join('');
  w.document.write(html);
  w.document.close();
}

/* ================= MENU EDITOR ================= */
async function loadMenu(force){
  if(MENU_LOADED&&!force){if(!MENU_DIRTY)renderMenuRows();return}
  try{
    const r=await fetch('/api/dishes',{cache:'no-store'});MENU=await r.json();
    MENU_LOADED=true;MENU_DIRTY=false;renderMenuRows();
  }catch(e){$('#menuEdit').innerHTML='<div class="chart-empty">'+T('Не удалось загрузить меню. Запущен ли server.py?','Меню бор нашуд. server.py кор мекунад?')+'</div>'}
}
function renderMenuTab(){
  $('#menuEdit').innerHTML='<div class="chart-empty">⏳</div>';
  loadMenu(false);
}
function menuProblems(){
  const problems=[];
  const ids=new Set();
  (MENU||[]).forEach((d,i)=>{
    const row=[];
    if(!d.id)row.push('ID'); else if(ids.has(d.id))row.push('duplicate ID'); else ids.add(d.id);
    if(!d.ru)row.push('RU name'); if(!d.tj)row.push('TJ name');
    if(!d.dru)row.push('RU description'); if(!d.dtj)row.push('TJ description');
    if(!(Number(d.price)>=0))row.push('price'); if(!d.img)row.push('photo');
    if(!d.ingredients)row.push('ingredients'); if(!d.allergens)row.push('allergens');
    try{const mods=typeof d.modifiers==='string'?JSON.parse(d.modifiers||'[]'):(d.modifiers||[]);if(!Array.isArray(mods))throw new Error()}catch(e){row.push('modifiers JSON')}
    if(row.length)problems.push('#'+(i+1)+' '+(d.ru||d.tj||d.id||'?')+': '+row.join(', '));
  });
  return problems;
}
function renderMenuQuality(){
  const box=$('#menuQuality'); if(!box)return;
  const bad=menuProblems();
  const active=(MENU||[]).filter(x=>!x.off).length;
  if(!bad.length)box.innerHTML='<span class="ok">✅ '+T('Меню заполнено профессионально','Меню касбӣ пур карда шудааст')+'</span> · <b>'+MENU.length+'</b> '+T('позиций, активных','мавқеъ, фаъол')+' <b>'+active+'</b>';
  else box.innerHTML='<span class="bad">⚠️ '+T('Нужно заполнить','Пур кардан лозим')+':</span> '+esc(bad.slice(0,6).join(' · '))+(bad.length>6?' · +'+(bad.length-6):'');
}
function renderMenuRows(){
  renderMenuQuality();
  $('#menuEdit').innerHTML=MENU.map((d,i)=>{
    const off=d.off?true:false;
    return '<div class="mdrow'+(off?' off-row':'')+'" data-ix="'+i+'">'+
    '<div class="md-g">'+
      '<input class="inp" value="'+esc(d.id||'')+'" placeholder="ID: shashlik" onchange="mset('+i+',\'id\',this.value)">'+
      '<input class="inp" value="'+esc(d.ru||'')+'" placeholder="Название RU" onchange="mset('+i+',\'ru\',this.value)">'+
      '<input class="inp" value="'+esc(d.tj||'')+'" placeholder="Ном TJ" onchange="mset('+i+',\'tj\',this.value)">'+
      '<input class="inp" type="number" min="0" value="'+(+d.price||0)+'" title="Цена" onchange="mset('+i+',\'price\',+this.value)">'+
      '<select class="inp" onchange="mset('+i+',\'cat\',this.value)">'+Object.keys(CATS).map(c=>'<option value="'+c+'" '+(d.cat===c?'selected':'')+'>'+T(CATS[c][0],CATS[c][1])+'</option>').join('')+'</select>'+
    '</div>'+
    '<div class="md-g2">'+
      '<input class="inp" value="'+esc(d.dru||'')+'" placeholder="Описание RU" onchange="mset('+i+',\'dru\',this.value)">'+
      '<input class="inp" value="'+esc(d.dtj||'')+'" placeholder="Тавсиф TJ" onchange="mset('+i+',\'dtj\',this.value)">'+
      '<input class="inp" value="'+esc(d.ingredients||'')+'" placeholder="Ingredients / состав" onchange="mset('+i+',\'ingredients\',this.value)">'+
      '<input class="inp" value="'+esc(d.allergens||'')+'" placeholder="Allergens / аллергены" onchange="mset('+i+',\'allergens\',this.value)">'+
      '<input class="inp" value="'+esc(d.modifiers||'[]')+'" placeholder="Modifiers JSON" onchange="mset('+i+',\'modifiers\',this.value)">'+
      '<input class="inp" value="'+esc(d.img||'')+'" placeholder="img/foto.jpg" title="Фото" onchange="mset('+i+',\'img\',this.value)">'+
      '<button class="btn-sm" onclick="uploadDishImage('+i+')">📷 '+T('Фото','Сурат')+'</button>'+
      '<label class="chk"><input type="checkbox" '+(d.hot?'checked':'')+' onchange="mset('+i+',\'hot\',this.checked?1:0)"> '+T('Хит','Хит')+'</label>'+
      '<label class="chk"><input type="checkbox" '+(off?'checked':'')+' onchange="mset('+i+',\'off\',this.checked?1:0)"> '+T('Скрыто','Пинҳон')+'</label>'+
      '<button class="del" onclick="mdel('+i+')" title="'+T('Удалить','Нест кардан')+'">🗑</button>'+
    '</div></div>';
  }).join('')||'<div class="chart-empty">—</div>';
}
function mset(i,k,v){if(k==='price')v=Math.max(0,+v||0);if(k==='hot'||k==='off')v=v?1:0;MENU[i][k]=v;MENU_DIRTY=true;renderMenuQuality();loadBadges()}
function mdel(i){if(!confirm(T('Удалить блюдо «'+(MENU[i].ru||'')+'»?','Таоми «'+(MENU[i].tj||'')+'»-ро нест кунем?')))return;MENU.splice(i,1);MENU_DIRTY=true;renderMenuRows();loadBadges()}
function loadBadges(){$('#saveMenuBtn').innerHTML='💾 '+T('Сохранить меню','Сабти меню')+(MENU_DIRTY?' •':'');}
async function uploadDishImage(i){
  const f=await pickFile('image/png,image/jpeg,image/webp'); if(!f)return;
  try{const j=await uploadAsset('dish',f,MENU[i].id||('dish-'+i));MENU[i].img=j.url;MENU_DIRTY=true;renderMenuRows();toast(T('✓ Фото блюда загружено','✓ Сурати таом бор шуд'))}catch(e){toast(T('Ошибка загрузки фото','Хатои боркунии сурат'))}
}
function exportMenu(){dl('bosfor-menu.json',JSON.stringify({version:1,exported_at:new Date().toISOString(),items:MENU},null,2),'application/json')}
async function importMenuFile(file){
  try{const txt=await file.text();const obj=JSON.parse(txt);const items=Array.isArray(obj)?obj:obj.items;if(!Array.isArray(items)||!items.length)throw new Error();MENU=items.map((d,i)=>({id:String(d.id||('dish'+Date.now()+i)),cat:d.cat||'fast',price:+d.price||0,ru:d.ru||'',tj:d.tj||d.ru||'',dru:d.dru||'',dtj:d.dtj||'',img:d.img||'',hot:d.hot?1:0,off:d.off?1:0,allergens:d.allergens||'',ingredients:d.ingredients||'',modifiers:d.modifiers||'[]'}));MENU_DIRTY=true;renderMenuRows();toast(T('✓ Меню импортировано. Проверьте и сохраните.','✓ Меню импорт шуд. Санҷед ва сабт кунед.'))}catch(e){toast(T('Неверный JSON меню','JSON-и меню нодуруст аст'))}
}
$('#addDishBtn').onclick=()=>{
  MENU.push({id:'d'+Date.now(),cat:'fast',price:0,ru:'Новое блюдо',tj:'Таоми нав',dru:'',dtj:''});
  MENU_DIRTY=true;renderMenuRows();
  window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'});
};
$('#saveMenuBtn').onclick=async()=>{
  try{
    const clean=MENU.map(d=>{const o={id:d.id,cat:d.cat,price:+d.price||0,ru:d.ru||'',tj:d.tj||d.ru||'',dru:d.dru||'',dtj:d.dtj||d.dru||'',allergens:d.allergens||'',ingredients:d.ingredients||'',modifiers:d.modifiers||'[]'};if(d.img)o.img=d.img;if(d.hot)o.hot=1;if(d.off)o.off=1;return o});
    const j=await adminPost('/api/dishes',{items:clean});
    if(j.ok){MENU_DIRTY=false;loadBadges();toast(T('✓ Меню сохранено — сайт обновлён!','✓ Меню сабт шуд — сайт нав гардид!'))}
  }catch(e){toast(T('Ошибка сохранения','Хатои сабт'))}
};


/* ================= ASSETS, QR & MENU FILES ================= */
function applyBrand(st){
  if(!st)return;
  const logo=st.logo_url||'img/logo.png', fav=st.favicon_url||'icons/favicon-64.png';
  $$('[data-brand-logo]').forEach(img=>{if(img.getAttribute('src')!==logo)img.src=logo});
  $$('[data-brand-favicon], link[rel="icon"]').forEach(l=>{if(l.getAttribute('href')!==fav)l.href=fav});
  const bp=$('#brandLogoPath'); if(bp)bp.textContent=logo+' · favicon: '+fav;
}
function pickFile(accept){return new Promise(resolve=>{const i=document.createElement('input');i.type='file';i.accept=accept;i.onchange=()=>resolve(i.files&&i.files[0]);i.click()})}
function fileToDataURL(file){return new Promise((resolve,reject)=>{if(!file||file.size>2500000)return reject(new Error('size'));const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file)})}
async function uploadAsset(kind,file,name){const data=await fileToDataURL(file);return adminPost('/api/assets',{kind,data,name:name||file.name})}
async function uploadBrand(kind,file){const j=await uploadAsset(kind,file,kind);SETTINGS=await api('/api/settings');applyBrand(SETTINGS);toast(kind==='logo'?T('✓ Логотип обновлён','✓ Лого нав шуд'):T('✓ Favicon обновлён','✓ Favicon нав шуд'));return j}
/* ================= SETTINGS ================= */
function updateSettingsUI(){
  if(!SETTINGS)return;
  applyBrand(SETTINGS);
  const on=SETTINGS.ordering!==false;
  const sw=$('#orderingSw');
  if(document.activeElement!==sw)sw.checked=on;
  const st=$('#orderingState');
  st.textContent=on?'ON':'OFF';st.className='set-state '+(on?'on':'off');
  $('#tgState').textContent=SETTINGS.tg_configured?'✅ '+T('подключено','пайваст'):T('не настроено','танзим нашудааст');
  if(SETTINGS.tg_chat&&document.activeElement!==$('#tgChat')&&!$('#tgChat').value)$('#tgChat').value=SETTINGS.tg_chat;
  if($('#deliveryFee'))$('#deliveryFee').value=SETTINGS.delivery_fee??0; if($('#minOrder'))$('#minOrder').value=SETTINGS.min_order??0; if($('#loyaltyPercent'))$('#loyaltyPercent').value=SETTINGS.loyalty_percent??3;
  $('#maxBookings').value=SETTINGS.max_bookings_per_slot??8;
  $('#deliveryZoneNote').value=SETTINGS.delivery_zone_note||'';
  $('#openingTime').value=SETTINGS.opening_time||'07:00';
  $('#closingTime').value=SETTINGS.closing_time||'22:30'; if($('#scheduledSw'))$('#scheduledSw').checked=SETTINGS.scheduled_orders!==false;
}
$('#orderingSw').onchange=async e=>{
  const on=e.target.checked;
  try{
    await adminPost('/api/settings',{ordering:on});
    SETTINGS.ordering=on;updateSettingsUI();
    toast(on?T('✓ Приём заказов включён','✓ Қабули фармоиш фаъол шуд'):T('⏸ Приём заказов приостановлен','⏸ Қабули фармоиш қатъ шуд'));
  }catch(err){toast(T('Ошибка','Хатогӣ'))}
};
$('#commerceSave').onclick=async()=>{try{await adminPost('/api/settings',{delivery_fee:+$('#deliveryFee').value||0,min_order:+$('#minOrder').value||0,loyalty_percent:+$('#loyaltyPercent').value||0,max_bookings_per_slot:+$('#maxBookings').value||8,delivery_zone_note:$('#deliveryZoneNote').value,opening_time:$('#openingTime').value||'07:00',closing_time:$('#closingTime').value||'22:30',scheduled_orders:$('#scheduledSw').checked});SETTINGS=await api('/api/settings');updateSettingsUI();toast(T('✓ Настройки продаж сохранены','✓ Танзимоти фурӯш сабт шуд'))}catch(e){toast(T('Ошибка сохранения','Хатои сабт'))}};
$('#promoSave').onclick=async()=>{try{const body={code:$('#promoCode').value,discount_type:$('#promoType').value,value:+$('#promoValue').value,min_total:+$('#promoMin').value||0,active:$('#promoActive').checked};await adminPost('/api/promotions',body);DATA.promos=await api('/api/promotions');renderPromos();$('#promoCode').value='';$('#promoValue').value='';toast(T('✓ Промокод сохранён','✓ Промокод сабт шуд'))}catch(e){toast(T('Проверьте промокод и значение','Промокод ва қиматро санҷед'))}};
$('#addTableBtn').onclick=()=>{TABLES.push({code:String((TABLES.length||0)+1),label:'',capacity:2,zone:'',active:1});TABLES_DIRTY=true;renderTables()};
$('#saveTablesBtn').onclick=async()=>{try{await adminPost('/api/tables',{items:TABLES});TABLES=await api('/api/tables');TABLES_DIRTY=false;renderTables();toast(T('✓ Столы сохранены','✓ Мизҳо сабт шуданд'))}catch(e){toast(T('Проверьте список столов','Рӯйхати мизҳоро санҷед'))}};
$('#tgSave').onclick=async()=>{
  try{
    await adminPost('/api/settings',{tg_bot:$('#tgBot').value,tg_chat:$('#tgChat').value});
    SETTINGS=await api('/api/settings');
    updateSettingsUI();toast(T('✓ Telegram настроен','✓ Telegram танзим шуд'));
  }catch(e){toast(T('Ошибка сохранения','Хатои сабт'))}
};
$('#tgTest').onclick=async()=>{
  try{
    await $('#tgSave').onclick();
    const j=await adminPost('/api/telegram/test',{});
    if(j.ok)toast(T('📨 Тест отправлен в Telegram!','📨 Санҷиш ба Telegram фиристода шуд!'));
    else toast(T('⚠️ '+(j.hint||'Ошибка отправки'),'⚠️ Хатои фиристодан'));
  }catch(e){toast(T('Сервер не отвечает','Сервер посух намекунад'))}
};
$('#expJson').onclick=()=>{
  dl('bosfor-data.json',JSON.stringify({orders:DATA.orders,bookings:DATA.bookings},null,1),'application/json');
};
$('#expCsv').onclick=()=>{
  const rows=[['id','date','name','phone','total','items','status']];
  DATA.orders.forEach(o=>rows.push([o.id,fmtTime(o.ts),o.name||'',o.phone||'',o.total||0,(o.items||[]).map(i=>i.q+'x '+i.n).join('; '),o.status||'']));
  const csv='﻿'+rows.map(r=>r.map(c=>'"'+String(c).replace(/"/g,'""')+'"').join(',')).join('\n');
  dl('bosfor-orders.csv',csv,'text/csv;charset=utf-8');
};
function dl(name,content,type){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([content],{type}));
  a.download=name;a.click();URL.revokeObjectURL(a.href);
  toast(T('⬇️ Файл скачан','⬇️ Файл боргирӣ шуд'));
}
$('#uploadLogoBtn').onclick=()=>$('#logoFile').click();
$('#uploadFaviconBtn').onclick=()=>$('#faviconFile').click();
$('#logoFile').onchange=e=>{const f=e.target.files&&e.target.files[0];if(f)uploadBrand('logo',f).catch(()=>toast(T('Ошибка загрузки logo','Хатои боркунии logo')));e.target.value=''};
$('#faviconFile').onchange=e=>{const f=e.target.files&&e.target.files[0];if(f)uploadBrand('favicon',f).catch(()=>toast(T('Ошибка загрузки favicon','Хатои боркунии favicon')));e.target.value=''};
$('#exportMenuBtn').onclick=()=>exportMenu();
$('#importMenuBtn').onclick=()=>$('#importMenuFile').click();
$('#importMenuFile').onchange=e=>{const f=e.target.files&&e.target.files[0];if(f)importMenuFile(f);e.target.value=''};
$('#checkMenuBtn').onclick=()=>{renderMenuQuality();const bad=menuProblems();toast(bad.length?T('Меню требует доработки','Меню такмил мехоҳад'):T('Меню готово','Меню тайёр аст'))};
$('#printQrBtn').onclick=()=>printQrCards(activeTables());
$('#exportTablesBtn').onclick=()=>dl('bosfor-tables.json',JSON.stringify({base:getQrBase(),items:TABLES},null,2),'application/json');
if($('#qrBaseUrl')){$('#qrBaseUrl').value=location.origin;$('#qrBaseUrl').oninput=()=>{if(TAB==='tables')renderTables()}}
$('#clearOrders').onclick=()=>clearData('orders');
$('#clearBooks').onclick=()=>clearData('bookings');
async function clearData(what){
  if(!confirm(T('Точно очистить '+ (what==='orders'?'все заказы':'все брони') +'? Это необратимо!','Ҳақиқатан '+(what==='orders'?'ҳамаи фармоишҳо':'ҳамаи бронҳо')+' тоза шавад? Бебаргардон аст!')))return;
  try{
    await adminPost('/api/clear',{what});
    toast(T('✓ Очищено','✓ Тоза шуд'));loadAll(true);
  }catch(e){toast(T('Ошибка','Хатогӣ'))}
}

/* ================= TABS & EVENTS ================= */
$$('.tab').forEach(t=>t.onclick=()=>{
  TAB=t.dataset.tab;
  $$('.tab').forEach(x=>x.classList.toggle('on',x===t));
  render();
});
$('#searchInp').oninput=e=>{QUERY=e.target.value;if(TAB==='orders')renderOrders();
  if(TAB==='kitchen')renderKitchen();else if(TAB==='books')renderBooks();else if(TAB==='customers')renderCustomers();};
$('#refreshBtn').onclick=()=>{MENU_LOADED=false;loadAll(true);toast(T('⟳ Обновлено','⟳ Нав шуд'))};
$('#demoBtn').onclick=sendDemo;
$('#logoutBtn').onclick=logout;
$('#soundBtn').onclick=()=>{SOUND=!SOUND;localStorage.setItem('bosfor_sound',SOUND?'1':'0');$('#soundBtn').textContent=SOUND?'🔔':'🔕';toast(SOUND?T('Звук включён','Садо фаъол'):T('Звук выключен','Садо хомӯш'))};

/* ================= LOGIN ================= */
let retryT=null, pollT=null;
async function autoRetry(){
  clearInterval(retryT);
  retryT=setInterval(async()=>{
    if(LOGGED_IN){clearInterval(retryT);return}
    try{
      const r=await fetch('/api/admin/session',{cache:'no-store',credentials:'same-origin'});const j=await r.json();
      if(j.authenticated){CSRF=j.csrf;PRINCIPAL_ROLE=j.role||'owner';PRINCIPAL_NAME=j.name||'';clearInterval(retryT);enterApp()}
    }catch(e){}
  },7000);
}
$('#loginForm').addEventListener('submit',async e=>{
  e.preventDefault(); const password=$('#pinInput').value; const username=$('#usernameInput')?.value||'';
  try{
    const r=await fetch('/api/admin/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
    const j=await r.json().catch(()=>({}));
    if(!r.ok)throw new Error(r.status===429?'rate':'auth');
    CSRF=j.csrf||'';PRINCIPAL_ROLE=j.role||'owner';PRINCIPAL_NAME=j.name||'';$('#pinInput').value='';enterApp();
  }catch(err){
    const c=$('.login-card');c.classList.remove('shake');void c.offsetWidth;c.classList.add('shake');
    $('#loginErr').textContent=err.message==='rate'?T('⏳ Слишком много попыток. Попробуйте позже.','⏳ Кӯшишҳо зиёд шуданд. Баъдтар санҷед.'):T('❌ Неверный пароль','❌ Парол нодуруст аст');
    $('#pinInput').value='';$('#pinInput').focus();
  }
});
function enterApp(){
  LOGGED_IN=true;clearInterval(retryT);
  $('#loginView').style.display='none';$('#appView').classList.add('on');$('#soundBtn').textContent=SOUND?'🔔':'🔕';
  setLang(LANG);clearInterval(pollT);
  if(['owner','manager'].includes(PRINCIPAL_ROLE)){loadAll(true);pollT=setInterval(()=>loadAll(false),15000)}
  window.dispatchEvent(new CustomEvent('bosfor:authenticated',{detail:{role:PRINCIPAL_ROLE,name:PRINCIPAL_NAME}}));
}
async function initAuth(){
  let networkFailed=false;
  try{const r=await fetch('/api/admin/session',{cache:'no-store',credentials:'same-origin'});const j=await r.json();if(j.authenticated){CSRF=j.csrf;PRINCIPAL_ROLE=j.role||'owner';PRINCIPAL_NAME=j.name||'';enterApp();return}}catch(e){networkFailed=true}
  showLogin(); if(networkFailed)autoRetry();
}

/* ================= LANG ================= */
function setLang(l){
  LANG=l;localStorage.setItem('bosfor_adm_lang',l);
  document.documentElement.lang=l==='tj'?'tg':'ru';
  $$('[data-ru]').forEach(el=>{
    if(el.dataset.ruTitle){el.title=T(el.dataset.ruTitle,el.dataset.tjTitle)}else{el.textContent=T(el.dataset.ru,el.dataset.tj)}
  });
  $$('input[data-ru-ph]').forEach(el=>el.placeholder=T(el.dataset.ruPh,el.dataset.tjPh));
  $('#langTj').classList.toggle('on',l==='tj');
  $('#langRu').classList.toggle('on',l==='ru');
  if(ready)render();
}
$('#langTj').onclick=()=>setLang('tj');
$('#langRu').onclick=()=>setLang('ru');

/* ================= OPERATIONS MODULE BRIDGE ================= */
window.BosforAdminBridge={getCsrf:()=>CSRF,getLang:()=>LANG,getRole:()=>PRINCIPAL_ROLE,getName:()=>PRINCIPAL_NAME,t:(ru,tj)=>T(ru,tj),toast,showLogin,esc};

/* ================= INIT ================= */
setLang(LANG);
initAuth();
