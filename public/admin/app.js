import {renderPos,selectOrder} from './modules/pos.js';
import {renderFloor} from './modules/floor.js';
import {renderKitchen} from './modules/kitchen.js';
import {renderInventory} from './modules/inventory.js';
import {renderPurchasing} from './modules/purchasing.js';
import {renderReservations} from './modules/reservations.js';
import {renderStaff} from './modules/staff.js';
import {renderFinance} from './modules/finance.js';
import {renderGuests} from './modules/guests.js';
import {renderDelivery} from './modules/delivery.js';
import {renderTasks} from './modules/tasks.js';
import {renderReports} from './modules/reports.js';
import {renderUsers} from './modules/users.js';
import {renderAudit} from './modules/audit.js';
import {applyRoleNavigation} from './router.js';
import {messages} from './i18n.js';
window.BosforOpsModules=true;
const renderers={pos:renderPos,floor:renderFloor,kitchen:renderKitchen,inventory:renderInventory,purchasing:renderPurchasing,reservations:renderReservations,staff:renderStaff,finance:renderFinance,crm:renderGuests,delivery:renderDelivery,tasks:renderTasks,reports:renderReports,users:renderUsers,audit:renderAudit};
function currentTab(){return document.querySelector('.tab.on')?.dataset.tab||'';}
async function renderCurrent(){const fn=renderers[currentTab()];if(fn)await fn();}
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>queueMicrotask(renderCurrent)));
window.addEventListener('bosfor:open-order',async e=>{
  const tab=document.querySelector('.tab[data-tab="pos"]'); if(tab)tab.click();
  await selectOrder(e.detail?.id||'');
});
window.addEventListener('bosfor:ops-refresh',renderCurrent);
setInterval(()=>{if(document.visibilityState==='visible'&&renderers[currentTab()])renderCurrent();},15000);

async function refreshPrincipal(){
  try{
    const r=await fetch('/api/admin/v1/me',{cache:'no-store',credentials:'same-origin'});
    if(!r.ok)return;
    const j=await r.json();const p=j.data||{};
    applyRoleNavigation(p.role||window.BosforAdminBridge?.getRole?.()||'owner');
    queueMicrotask(renderCurrent);
  }catch{}
}
window.addEventListener('bosfor:authenticated',refreshPrincipal);
if(window.BosforAdminBridge?.getCsrf?.())refreshPrincipal();
void messages;
