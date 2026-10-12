import {v1Get,v1Post,routes} from '../api.js';
import {esc,money,statePill,empty,t,toast,idem} from './common.js';
let selected=''; let cache=[]; let dishes=[]; let tables=[];

async function load(){
  [cache,dishes,tables]=await Promise.all([
    v1Get(routes.posOrders),fetch('/api/dishes',{cache:'no-store'}).then(r=>r.json()),v1Get(routes.floorTables)
  ]);
  if(selected&&!cache.some(o=>o.id===selected))selected='';
  if(!selected&&cache[0])selected=cache[0].id;
}
function order(){return cache.find(o=>o.id===selected);}
function options(arr,val,label){return arr.map(x=>`<option value="${esc(x[val])}">${esc(label(x))}</option>`).join('');}
function shell(){
 const root=document.querySelector('#opsPosApp'); if(!root)return null;
 const o=order();
 const orderList=cache.length?cache.map(x=>`<button class="ops-order-row ${x.id===selected?'on':''}" data-order="${esc(x.id)}"><b>${esc(x.table_id||x.order_type)}</b><span>${money(x.total)}</span>${statePill(x.state)}</button>`).join(''):empty(t('Нет открытых POS-заказов','Фармоиши кушода нест'));
 const itemRows=o?.items?.length?o.items.map(i=>`<div class="ops-line"><span>${esc(i.qty)}× ${esc(i.name_ru)}</span><b>${money(i.qty*i.unit_price)}</b></div>`).join(''):empty(t('Добавьте блюда','Таом илова кунед'));
 const due=o?.payment?.due??0;
 root.innerHTML=`<div class="ops-toolbar"><div><h2>POS · Table Service</h2><p>${t('Заказ → кухня → оплата → закрытие','Фармоиш → ошхона → пардохт → бастан')}</p></div><button class="ops-btn" id="opsPosRefresh">⟳</button></div>
 <div class="ops-grid ops-pos-grid"><aside class="ops-panel"><h3>${t('Открытые счета','Ҳисобҳои кушода')}</h3>${orderList}<hr><label>${t('Тип заказа','Навъи фармоиш')}</label><select id="opsNewType"><option value="dinein">Dine-in</option><option value="pickup">Pickup</option></select><label>${t('Стол','Миз')}</label><select id="opsNewTable">${options(tables.filter(x=>x.active), 'code', x=>`${x.label||x.code} · ${x.state}`)}</select><button class="ops-btn ops-primary" id="opsCreateOrder">＋ ${t('Открыть заказ','Кушодани фармоиш')}</button></aside>
 <section class="ops-panel ops-ticket">${o?`<div class="ops-ticket-head"><div><small>${esc(o.id)}</small><h3>${esc(o.table_id||o.order_type)} · ${statePill(o.state)}</h3></div><b>${money(o.total)}</b></div>${itemRows}<div class="ops-add"><select id="opsDish">${options(dishes.filter(d=>!d.off),'id',d=>`${d.ru} · ${money(d.price)}`)}</select><input id="opsQty" type="number" min="1" max="20" value="1"><button class="ops-btn" id="opsAddItem">＋ ${t('Добавить','Илова')}</button></div><div class="ops-actions"><button class="ops-btn ops-primary" id="opsSend">🔥 ${t('На кухню','Ба ошхона')}</button>${o.state==='ready'?`<button class="ops-btn" id="opsServe">🍽 ${t('Подано','Супорида шуд')}</button>`:''}${['served','out_for_delivery'].includes(o.state)&&due===0?`<button class="ops-btn" id="opsClose">✓ ${t('Закрыть','Бастан')}</button>`:''}</div><div class="ops-pay"><b>${t('К оплате','Барои пардохт')}: ${money(due)}</b><button class="ops-btn" data-pay="cash">💵 Cash</button><button class="ops-btn" data-pay="card">💳 Card</button><button class="ops-btn" data-pay="qr">▦ QR</button></div>`:empty(t('Выберите или откройте заказ','Фармоишро интихоб ё кушоед'))}</section></div>`;
 return root;
}
async function act(fn){try{await fn();await render();toast(t('✓ Готово','✓ Тайёр'));}catch(e){toast(`⚠ ${e.message}`);}}
function bind(root){
 root.querySelector('#opsPosRefresh')?.addEventListener('click',()=>render());
 root.querySelectorAll('[data-order]').forEach(b=>b.addEventListener('click',()=>{selected=b.dataset.order;shell();bind(root);}));
 root.querySelector('#opsCreateOrder')?.addEventListener('click',()=>act(async()=>{const type=root.querySelector('#opsNewType').value;const table=root.querySelector('#opsNewTable').value;const x=await v1Post(routes.posOrders,{order_type:type,table_id:type==='dinein'?table:null});selected=x.id;}));
 root.querySelector('#opsAddItem')?.addEventListener('click',()=>act(()=>v1Post(routes.posItems,{order_id:selected,dish_id:root.querySelector('#opsDish').value,qty:Number(root.querySelector('#opsQty').value||1),modifiers:{},note:''})));
 root.querySelector('#opsSend')?.addEventListener('click',()=>act(()=>v1Post(routes.posSend,{order_id:selected})));
 root.querySelector('#opsServe')?.addEventListener('click',()=>act(()=>v1Post(routes.posTransition,{order_id:selected,target:'served'})));
 root.querySelector('#opsClose')?.addEventListener('click',()=>act(()=>v1Post(routes.posClose,{order_id:selected})));
 root.querySelectorAll('[data-pay]').forEach(b=>b.addEventListener('click',()=>act(async()=>{const o=order();const due=o?.payment?.due||0;if(!due)throw new Error(t('Нет суммы к оплате','Маблағ барои пардохт нест'));await v1Post(routes.posPayments,{order_id:selected,method:b.dataset.pay,amount:due},idem('pay'));})));
}
export async function renderPos(){const root=document.querySelector('#opsPosApp');if(!root)return;root.innerHTML='<div class="ops-loading">⏳ POS</div>';try{await load();bind(shell());}catch(e){root.innerHTML=empty(e.message);}}
export function selectOrder(id){selected=id;return renderPos();}
