import {v1Get,v1Post,routes} from '../api.js';
import {esc,statePill,empty,t,toast} from './common.js';
let tickets=[];
async function act(fn){try{await fn();await renderKitchen();toast(t('✓ Кухня обновлена','✓ Ошхона нав шуд'));}catch(e){toast(`⚠ ${e.message}`);}}
function ticket(x){return `<article class="ops-kds-ticket ${x.overdue?'overdue':''}"><header><div><small>${esc(x.station_id)} · #${x.id}</small><b>${statePill(x.state)}</b></div><strong>${x.elapsed_minutes}m</strong></header><div>${(x.items||[]).map(i=>`<div class="ops-line"><span>${i.qty}× ${esc(i.name_ru)}</span><small>${esc(i.note||'')}</small></div>`).join('')}</div><footer>${x.state==='queued'?`<button class="ops-btn ops-primary" data-kstate="preparing" data-ticket="${x.id}">▶ ${t('Готовить','Омода кардан')}</button>`:''}${x.state==='preparing'?`<button class="ops-btn ops-primary" data-kstate="ready" data-ticket="${x.id}">✓ READY</button>`:''}${x.state==='ready'?`<button class="ops-btn" data-kstate="recalled" data-ticket="${x.id}">↩ Recall</button>`:''}</footer></article>`;}
export async function renderKitchen(){
 const root=document.querySelector('#opsKdsApp');if(!root)return;root.innerHTML='<div class="ops-loading">⏳ KDS</div>';
 try{tickets=await v1Get(routes.kitchenTickets);}catch(e){root.innerHTML=empty(e.message);return;}
 const groups=Object.groupBy?Object.groupBy(tickets,x=>x.station_id):tickets.reduce((a,x)=>((a[x.station_id]??=[]).push(x),a),{});
 root.innerHTML=`<div class="ops-toolbar"><div><h2>KDS Pro</h2><p>${t('Очередь, таймер и станции кухни','Навбат, таймер ва стансияҳои ошхона')}</p></div><button class="ops-btn" id="opsKdsRefresh">⟳</button></div><div class="ops-kds">${Object.entries(groups).map(([station,items])=>`<section class="ops-kds-col"><h3>${esc(station)} <span>${items.length}</span></h3>${items.map(ticket).join('')}</section>`).join('')||empty(t('Активных кухонных тикетов нет','Тикети фаъоли ошхона нест'))}</div>`;
 root.querySelector('#opsKdsRefresh')?.addEventListener('click',renderKitchen);
 root.querySelectorAll('[data-kstate]').forEach(b=>b.addEventListener('click',()=>act(()=>v1Post(routes.kitchenState,{ticket_id:Number(b.dataset.ticket),target:b.dataset.kstate}))));
}
export async function setAvailability(dishId,available,reason=''){return v1Post(routes.kitchenAvailability,{dish_id:dishId,available,reason});}
