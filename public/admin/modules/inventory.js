import {v1Get,v1Post} from '../api.js';
import {esc,empty,t,toast} from './common.js';

const R={
 items:'/api/admin/v1/inventory/items',low:'/api/admin/v1/inventory/low-stock',recipe:'/api/admin/v1/inventory/recipe',
 count:'/api/admin/v1/inventory/count',waste:'/api/admin/v1/inventory/waste'
};
let items=[],low=[],dishes=[],recipe={components:[],cost:{}};
const root=()=>document.querySelector('#opsInventoryApp');

async function load(){
 [items,low,dishes]=await Promise.all([v1Get(R.items),v1Get(R.low),fetch('/api/dishes',{cache:'no-store'}).then(r=>r.json())]);
}
async function loadRecipe(dishId){recipe=dishId?await v1Get(`${R.recipe}?dish_id=${encodeURIComponent(dishId)}`):{components:[],cost:{}};}
function n(v){return Number(v||0).toLocaleString('ru-RU',{maximumFractionDigits:3});}
function row(c={}){return `<div class="ops-line inv-recipe-row"><select class="inv-ri">${items.map(i=>`<option value="${esc(i.id)}" ${i.id===c.item_id?'selected':''}>${esc(i.name)} · ${esc(i.base_unit)}</option>`).join('')}</select><input class="inv-rq" type="number" min="0.000001" step="0.001" value="${esc(c.qty_base||'1')}"><button class="ops-btn inv-rm" type="button">×</button></div>`;}
function html(){
 const lowIds=new Set(low.map(x=>x.item_id));
 const rows=items.length?items.map(i=>`<div class="ops-line inv-stock ${lowIds.has(i.id)?'ops-alert':''}"><div><b>${esc(i.name)}</b><small>${esc(i.id)} · ${esc(i.base_unit)}</small></div><span>${t('Остаток','Боқимонда')}: <b>${n(i.on_hand)}</b></span><span>${t('Резерв','Захира')}: ${n(i.reserved)}</span><span>${t('Доступно','Дастрас')}: <b>${n(i.available)}</b></span><button class="ops-btn" data-waste="${esc(i.id)}">♻ ${t('Списание','Талафот')}</button><button class="ops-btn" data-count="${esc(i.id)}"># ${t('Пересчёт','Ҳисоб')}</button></div>`).join(''):empty(t('Ингредиенты не добавлены','Компонентҳо илова нашудаанд'));
 return `<div class="ops-toolbar"><div><h2>Inventory · Recipe Cost</h2><p>${t('Остатки, резерв, списания и себестоимость','Боқимонда, захира, талафот ва арзиши аслӣ')}</p></div><button class="ops-btn" id="invRefresh">⟳</button></div>
 <div class="ops-kpis"><div><b>${items.length}</b><span>${t('ингредиентов','компонент')}</span></div><div class="${low.length?'ops-danger':''}"><b>${low.length}</b><span>${t('низкий запас','захираи кам')}</span></div></div>
 <div class="ops-grid"><section class="ops-panel"><h3>📦 ${t('Склад','Анбор')}</h3><div class="ops-form-row"><input id="invId" placeholder="ID: rice"><input id="invName" placeholder="${t('Название','Ном')}"><select id="invUnit"><option>kg</option><option>g</option><option>l</option><option>ml</option><option>pcs</option></select><input id="invReorder" type="number" step="0.001" min="0" placeholder="Reorder"><input id="invTarget" type="number" step="0.001" min="0" placeholder="Target"><button class="ops-btn ops-primary" id="invAdd">＋</button></div><div class="ops-stack">${rows}</div></section>
 <section class="ops-panel"><h3>🍲 ${t('Рецептура / BOM','Рецепт / BOM')}</h3><select id="invDish">${dishes.map(d=>`<option value="${esc(d.id)}">${esc(d.ru)} · ${d.price}с</option>`).join('')}</select><div id="invRecipeCost" class="ops-note"></div><div id="invRecipeRows"></div><div class="ops-actions"><button class="ops-btn" id="invAddComp">＋ ${t('Компонент','Компонент')}</button><button class="ops-btn ops-primary" id="invSaveRecipe">💾 ${t('Сохранить рецепт','Сабти рецепт')}</button></div></section></div>`;
}
function renderRecipe(){
 const box=document.querySelector('#invRecipeRows');if(!box)return;box.innerHTML=(recipe.components||[]).map(row).join('')||row();
 const c=recipe.cost||{};document.querySelector('#invRecipeCost').textContent=c.total_components?`${t('Известная себестоимость','Арзиши маълум')}: ${n(c.known_cost)}с · ${t('покрытие','фарогирӣ')} ${Math.round(Number(c.coverage||0)*100)}%${c.food_cost_percent?` · Food cost ${Number(c.food_cost_percent).toFixed(1)}%`:''}`:t('Рецепт ещё не настроен','Рецепт ҳоло танзим нашудааст');
 box.querySelectorAll('.inv-rm').forEach(b=>b.onclick=()=>b.closest('.inv-recipe-row').remove());
}
async function refresh(){const r=root();if(!r)return;r.innerHTML='<div class="ops-loading">⏳ Inventory</div>';try{await load();r.innerHTML=html();bind();const d=document.querySelector('#invDish')?.value;if(d)await loadRecipe(d);renderRecipe();}catch(e){r.innerHTML=empty(e.message)}}
function bind(){
 document.querySelector('#invRefresh')?.addEventListener('click',refresh);
 document.querySelector('#invAdd')?.addEventListener('click',async()=>{try{await v1Post(R.items,{id:document.querySelector('#invId').value,name:document.querySelector('#invName').value,base_unit:document.querySelector('#invUnit').value,reorder_point:document.querySelector('#invReorder').value||0,target_stock:document.querySelector('#invTarget').value||0});toast(t('✓ Ингредиент добавлен','✓ Компонент илова шуд'));await refresh()}catch(e){toast(`⚠ ${e.message}`)}});
 document.querySelectorAll('[data-waste]').forEach(b=>b.onclick=async()=>{const q=prompt(t('Количество списания','Миқдори талафот'));if(!q)return;const reason=prompt(t('Причина списания','Сабаби талафот'));if(!reason||!confirm(t('Подтвердить списание?','Талафот тасдиқ шавад?')))return;const i=items.find(x=>x.id===b.dataset.waste);try{await v1Post(R.waste,{item_id:i.id,quantity:q,unit:i.base_unit,reason});await refresh();toast(t('✓ Списание записано','✓ Талафот сабт шуд'))}catch(e){toast(`⚠ ${e.message}`)}});
 document.querySelectorAll('[data-count]').forEach(b=>b.onclick=async()=>{const i=items.find(x=>x.id===b.dataset.count);const q=prompt(t('Фактический остаток','Боқимондаи воқеӣ'),i.on_hand);if(q===null)return;const reason=prompt(t('Причина/смена пересчёта','Сабаби ҳисоб'),'stock count');if(!reason||!confirm(t('Применить корректировку по пересчёту?','Ислоҳи ҳисоб татбиқ шавад?')))return;try{await v1Post(R.count,{reason,counts:[{item_id:i.id,quantity:q,unit:i.base_unit}]});await refresh();toast(t('✓ Пересчёт сохранён','✓ Ҳисоб сабт шуд'))}catch(e){toast(`⚠ ${e.message}`)}});
 document.querySelector('#invDish')?.addEventListener('change',async e=>{try{await loadRecipe(e.target.value);renderRecipe()}catch(x){toast(`⚠ ${x.message}`)}});
 document.querySelector('#invAddComp')?.addEventListener('click',()=>{document.querySelector('#invRecipeRows').insertAdjacentHTML('beforeend',row());renderRecipeRemovers()});
 document.querySelector('#invSaveRecipe')?.addEventListener('click',async()=>{const dish_id=document.querySelector('#invDish').value;const components=[...document.querySelectorAll('.inv-recipe-row')].map(x=>({item_id:x.querySelector('.inv-ri').value,quantity:x.querySelector('.inv-rq').value,unit:items.find(i=>i.id===x.querySelector('.inv-ri').value)?.base_unit}));try{await v1Post(R.recipe,{dish_id,components});await loadRecipe(dish_id);renderRecipe();toast(t('✓ Рецепт сохранён','✓ Рецепт сабт шуд'))}catch(e){toast(`⚠ ${e.message}`)}});
}
function renderRecipeRemovers(){document.querySelectorAll('.inv-rm').forEach(b=>b.onclick=()=>b.closest('.inv-recipe-row').remove())}
export async function renderInventory(){await refresh()}
