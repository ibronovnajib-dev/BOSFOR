export const roleTabs={
  owner:['dash','orders','pos','floor','kitchen','books','reservations','staff','finance','crm','delivery','tasks','menu','inventory','purchasing','customers','promos','tables','reports','users','audit','settings'],
  manager:['dash','orders','pos','floor','kitchen','books','reservations','staff','finance','crm','delivery','tasks','menu','inventory','purchasing','customers','promos','tables','reports','settings'],
  waiter:['pos','floor','reservations','tasks'],
  cashier:['pos','finance','tasks'],
  kitchen:['kitchen','tasks'],
  courier:['delivery']
};
export function allowedTabs(role){return roleTabs[role]||[];}
export function applyRoleNavigation(role){
  const preferredTabs=allowedTabs(role);
  const allowed=new Set(preferredTabs);
  document.querySelectorAll('.tab[data-tab]').forEach(el=>{el.hidden=!allowed.has(el.dataset.tab);});
  document.querySelectorAll('.view[id^="v-"]').forEach(el=>{const tab=el.id.slice(2);if(!allowed.has(tab))el.classList.remove('on');});
  const active=document.querySelector('.tab.on:not([hidden])');
  if(active)return active.dataset.tab;
  const first=preferredTabs.map(tab=>document.querySelector(`.tab[data-tab="${tab}"]`)).find(el=>el&&!el.hidden);
  if(first){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));first.classList.add('on');first.click();return first.dataset.tab;}
  return '';
}
