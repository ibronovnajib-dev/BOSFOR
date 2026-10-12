const bridge=()=>window.BosforAdminBridge||{};

async function parse(r){
  const data=await r.json().catch(()=>({}));
  if(r.status===401){bridge().showLogin?.();throw new Error('auth');}
  if(!r.ok){const e=new Error(data?.error?.message||data?.error||`HTTP ${r.status}`);e.code=data?.error?.code||'http_error';e.status=r.status;throw e;}
  return data?.data ?? data;
}
export async function v1Get(path){return parse(await fetch(path,{cache:'no-store',credentials:'same-origin'}));}
export async function v1Post(path,body={},idempotencyKey=''){
  const headers={'Content-Type':'application/json','X-CSRF-Token':bridge().getCsrf?.()||''};
  if(idempotencyKey)headers['X-Idempotency-Key']=idempotencyKey;
  return parse(await fetch(path,{method:'POST',credentials:'same-origin',headers,body:JSON.stringify(body)}));
}
export const routes={
  posOrders:'/api/admin/v1/pos/orders',posItems:'/api/admin/v1/pos/items',posSend:'/api/admin/v1/pos/send',posPayments:'/api/admin/v1/pos/payments',posTransition:'/api/admin/v1/pos/transition',posClose:'/api/admin/v1/pos/close',
  floorTables:'/api/admin/v1/floor/tables',floorSeat:'/api/admin/v1/floor/seat',floorState:'/api/admin/v1/floor/state',floorMove:'/api/admin/v1/floor/move',floorMerge:'/api/admin/v1/floor/merge',
  kitchenTickets:'/api/admin/v1/kitchen/tickets',kitchenState:'/api/admin/v1/kitchen/state',kitchenAvailability:'/api/admin/v1/kitchen/availability'
};
