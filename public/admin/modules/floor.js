import {v1Get,v1Post,routes} from '../api.js';
import {esc,statePill,empty,t,toast} from './common.js';
const NEXT={reserved:'seated',seated:'ordering',ordering:'preparing',preparing:'eating',eating:'bill',bill:'cleaning',cleaning:'free',out_of_service:'free'};
let rows=[];
async function act(fn){try{await fn();await renderFloor();toast(t('✓ План зала обновлён','✓ Нақшаи толор нав шуд'));}catch(e){toast(`⚠ ${e.message}`);}}
export async function renderFloor(){
 const root=document.querySelector('#opsFloorApp');if(!root)return;root.innerHTML='<div class="ops-loading">⏳ Floor</div>';
 try{rows=await v1Get(routes.floorTables);}catch(e){root.innerHTML=empty(e.message);return;}
 root.innerHTML=`<div class="ops-toolbar"><div><h2>${t('Живой план зала','Нақшаи зиндаи толор')}</h2><p>${t('Состояние каждого стола в реальном времени','Ҳолати ҳар миз дар вақти воқеӣ')}</p></div><button class="ops-btn" id="opsFloorRefresh">⟳</button></div><div class="ops-floor">${rows.map(x=>`<article class="ops-table ops-table-${esc(x.state)}"><div class="ops-table-top"><b>${esc(x.label||x.code)}</b>${statePill(x.state)}</div><small>${esc(x.zone||'')} · 👥 ${x.capacity}</small><div class="ops-table-actions">${x.state==='free'?`<button class="ops-btn ops-primary" data-seat="${esc(x.code)}">${t('Посадить','Шинондан')}</button>`:''}${NEXT[x.state]&&!(NEXT[x.state]==='free'&&x.active_order_id)?`<button class="ops-btn" data-next="${esc(x.code)}" data-state="${NEXT[x.state]}">→ ${esc(NEXT[x.state])}</button>`:''}${x.active_order_id?`<button class="ops-btn" data-open-order="${esc(x.active_order_id)}">POS</button>`:''}</div></article>`).join('')||empty(t('Столы не настроены','Мизҳо танзим нашудаанд'))}</div>`;
 root.querySelector('#opsFloorRefresh')?.addEventListener('click',renderFloor);
 root.querySelectorAll('[data-seat]').forEach(b=>b.addEventListener('click',()=>act(()=>v1Post(routes.floorSeat,{table_id:b.dataset.seat}))));
 root.querySelectorAll('[data-next]').forEach(b=>b.addEventListener('click',()=>act(()=>v1Post(routes.floorState,{table_id:b.dataset.next,target:b.dataset.state}))));
 root.querySelectorAll('[data-open-order]').forEach(b=>b.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('bosfor:open-order',{detail:{id:b.dataset.openOrder}}))));
}
