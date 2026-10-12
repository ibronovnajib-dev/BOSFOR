export const B=()=>window.BosforAdminBridge||{};
export const t=(ru,tj)=>B().t?B().t(ru,tj):ru;
export const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const money=n=>`${Number(n||0).toLocaleString('ru-RU')} с`;
export function toast(msg){B().toast?.(msg);}
export function busy(el,on){if(!el)return;el.toggleAttribute('disabled',!!on);el.classList.toggle('ops-busy',!!on);}
export function statePill(state){return `<span class="ops-state ops-${esc(state)}">${esc(state)}</span>`;}
export function empty(msg){return `<div class="ops-empty">${esc(msg)}</div>`;}
export function idem(prefix='op'){return `${prefix}-${Date.now()}-${crypto.getRandomValues(new Uint32Array(1))[0].toString(16)}`;}
