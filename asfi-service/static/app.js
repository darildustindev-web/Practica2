'use strict';
const $ = id => document.getElementById(id);
const names = ['Unión','Mercantil Santa Cruz','Nacional de Bolivia','Crédito de Bolivia','BISA','Ganadero','Económico','Prodem','Solidario','Fortaleza','FIE','PYME de la Comunidad','Desarrollo Productivo','Nación Argentina'];
const counts = new Intl.NumberFormat('es-BO');
const seconds = new Intl.NumberFormat('es-BO', {minimumFractionDigits:2, maximumFractionDigits:2});
const history = [];
let serviceState=null;
let lastStartedRate=null;
let lastRateTimestamp = null, wasRunning = false, isStarting = false, lastRecentKey = '', manualRecords = false;
function escapeText(value) { return String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function time(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString('es-BO'); }
function message(text, success=false) { $('notice').hidden=false; $('notice').textContent=text; $('notice').className=success?'success':''; }
async function api(path, options={}) {
  const response = await fetch('/api/panel/'+path, {...options, headers:{'Content-Type':'application/json', ...options.headers}, signal:AbortSignal.timeout(12000)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail==='string' ? data.detail : 'No se pudo completar la solicitud.');
  return data;
}
function drawChart() {
  if (!history.length) return;
  const rates=history.map(p=>p.rate), low=Math.min(...rates)-0.05, high=Math.max(...rates)+0.05;
  const left=68,right=973,top=16,bottom=186;
  const y=v=>bottom-(v-low)/(high-low)*(bottom-top);
  const x=i=>left+i/Math.max(1,history.length-1)*(right-left);
  const points=history.map((p,i)=>`${x(i)},${y(p.rate)}`).join(' ');
  let svg='<defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#12a27d" stop-opacity=".18"/><stop offset="100%" stop-color="#12a27d" stop-opacity="0"/></linearGradient></defs>';
  for(let i=0;i<4;i++) { const v=low+(high-low)*i/3, yy=y(v); svg+=`<line x1="${left}" x2="${right}" y1="${yy}" y2="${yy}" stroke="#e9eef2" stroke-dasharray="4 5"/><text x="55" y="${yy+4}" text-anchor="end" fill="#8290a2">${v.toFixed(4)}</text>`; }
  svg+=`<polygon points="${left},${bottom} ${points} ${x(history.length-1)},${bottom}" fill="url(#fill)"/><polyline points="${points}" fill="none" stroke="#008c70" stroke-width="2.8" stroke-linejoin="round"/><circle cx="${x(history.length-1)}" cy="${y(rates.at(-1))}" r="4" fill="#008c70"/>`;
  svg+=`<text x="${left}" y="218" fill="#8290a2">${escapeText(time(history[0].timestamp))}</text><text x="${right}" y="218" text-anchor="end" fill="#8290a2">${escapeText(time(history.at(-1).timestamp))}</text>`;
  $('chart').innerHTML=svg;
  $('chart-range').textContent=`${history.length} cotizaciones observadas · ${time(history[0].timestamp)} — ${time(history.at(-1).timestamp)}`;
}
async function pollRate() {
  try {
    const data=await api('cotizacion');
    $('rate').textContent=data.tipo_cambio_formateado;
    $('rate-time').textContent='Actualizada a las '+time(data.timestamp);
    $('interval-label').textContent='BCB cada '+data.intervalo_actual_segundos+' s';
    $('connection').className='connection online'; $('connection').innerHTML='<i></i> BCB conectado';
    document.querySelectorAll('[data-seconds]').forEach(button=>button.classList.toggle('selected',Number(button.dataset.seconds)===data.intervalo_actual_segundos));
    if(data.timestamp!==lastRateTimestamp) {
      lastRateTimestamp=data.timestamp;
      history.push({timestamp:data.timestamp,rate:Number(data.tipo_cambio_formateado)});
      const cutoff=Date.now()-600000;
      while(history.length>600 || (history.length>1 && new Date(history[0].timestamp).getTime()<cutoff)) history.shift();
      drawChart();
    }
  } catch(error) {
    $('connection').className='connection offline'; $('connection').innerHTML='<i></i> BCB sin conexión';
    $('rate-time').textContent='Sin actualización · último valor observado';
  } finally { setTimeout(pollRate,1000); }
}
function banks(rows) {
  const byId=new Map(rows.map(b=>[b.banco_id,b]));
  $('banks').innerHTML=names.map((name,index)=>{
    const b=byId.get(index+1), service=serviceState?.bancos.find(s=>s.banco_id===index+1);
    const phase=service && !service.disponible?'Sin conexión':b?.fase||(service?.disponible?(service.total===0?'Sin cuentas':'Disponible'):'Comprobando');
    const kind=phase==='Completado'?'done':['Con errores','Sin conexión'].includes(phase)?'error':b?'working':'';
    return `<tr><td><div class="bank-name"><span class="bank-id">${String(index+1).padStart(2,'0')}</span><strong>${name}</strong></div></td><td><span class="phase ${kind}" title="${escapeText(b?.error_banco||'')}">${escapeText(phase)}</span></td><td>${b?counts.format(b.leidas):'—'}</td><td>${b?counts.format(b.confirmadas):'—'}</td><td>${b?counts.format(b.ya_confirmadas):'—'}</td><td>${b?counts.format(b.errores):'—'}</td><td>${b?seconds.format(b.segundos||0)+' s':'—'}</td></tr>`;
  }).join('');
}
function renderRecords(records) {
  if(!records.length) { $('records').innerHTML='<tr><td colspan="7" class="empty">No hay cuentas consolidadas para mostrar todavía.</td></tr>'; return; }
  $('records').innerHTML=records.slice(0,30).map(r=>`<tr><td>${escapeText(names[Number(r.banco_id)-1]||r.banco_id)} <span class="code">/ ${escapeText(r.cuenta_id)}</span></td><td>${escapeText(r.saldo_usd)}</td><td class="number">${escapeText(r.tipo_cambio)}</td><td>${escapeText(r.saldo_bs)}</td><td class="code">${escapeText(r.codigo_verificacion)}</td><td><span class="phase ${r.estado==='CONFIRMADA'?'done':'error'}" title="${escapeText(r.detail||'')}">${escapeText(r.estado)}</span>${r.detail?`<small class="error-detail">${escapeText(r.detail)}</small>`:''}</td><td>${r.codigo_verificacion?`<button class="verify-button" data-bank="${escapeText(r.banco_id)}" data-account="${escapeText(r.cuenta_id)}">Comparar ↗</button>`:'—'}</td></tr>`).join('');
}
async function pollState() {
  try {
    const data=await api('estado'), totals=data.totales;
    $('elapsed').textContent=seconds.format(data.segundos);
    $('confirmed').textContent=counts.format(totals.confirmadas);
    $('previous').textContent=counts.format(totals.ya_confirmadas);
    $('errors').textContent=counts.format(totals.errores);
    $('read').textContent=counts.format(totals.leidas); $('batches').textContent=counts.format(totals.lotes);
    $('run-state').textContent=data.en_ejecucion?'Barrido en curso':data.error?'Ejecución interrumpida':data.resultado?data.resultado.status==='PARCIAL'?'Finalizó con errores':'Barrido completado':'Listo para iniciar';
    $('active-banks').textContent=serviceState?`${serviceState.bancos.filter(b=>b.disponible).length}/${serviceState.bancos.length} bancos disponibles`:'Comprobando servicios';
    $('run').disabled=data.en_ejecucion||isStarting||!serviceState?.listo;
    $('run').textContent=data.en_ejecucion?'⏳ Barrido en curso':'▶ Ejecutar nuevo barrido';
    banks(data.bancos);
    const key=JSON.stringify(data.recientes);
    if(!manualRecords && data.recientes.length && key!==lastRecentKey) { renderRecords(data.recientes); lastRecentKey=key; }
    if(wasRunning && !data.en_ejecucion) {
      message(data.error||`Barrido finalizado: ${counts.format(totals.confirmadas)} nuevas confirmaciones, ${counts.format(totals.ya_confirmadas)} previas y ${counts.format(totals.errores)} errores.`,!data.error&&!totals.errores);
    }
    if(wasRunning && !data.en_ejecucion && (data.error || totals.errores)) $('auto-run').checked=false;
    wasRunning=data.en_ejecucion;
    if($('auto-run').checked && !wasRunning && !isStarting && serviceState?.listo && lastRateTimestamp && lastStartedRate!==lastRateTimestamp) await startSweep();
  } catch(error) { $('run-state').textContent='ASFI sin conexión'; $('run').disabled=true; }
  finally {setTimeout(pollState,1000);}
}
$('interval-form').addEventListener('submit',async event=>{
  event.preventDefault(); $('apply').disabled=true;
  try {const value=Number($('seconds').value); await api('intervalo',{method:'PUT',body:JSON.stringify({segundos:value})}); message(`BCB actualizará su cotización cada ${value} segundo${value===1?'':'s'}.`,true);}
  catch(error) {message(error.message);} finally {$('apply').disabled=false;}
});
document.querySelectorAll('[data-seconds]').forEach(button=>button.addEventListener('click',()=>{$('seconds').value=button.dataset.seconds; $('interval-form').requestSubmit();}));
async function startSweep() {
  if(isStarting || wasRunning) return;
  lastStartedRate=lastRateTimestamp;
  isStarting=true; $('run').disabled=true; manualRecords=false; $('verification').hidden=true;
  try {await api('ejecutar',{method:'POST'}); message('Barrido solicitado. Puedes observar los bancos y la cotización mientras avanza.',true);}
  catch(error) {$('auto-run').checked=false; message(error.message);} finally {isStarting=false;}
}
$('run').addEventListener('click',startSweep);
$('refresh-records').addEventListener('click',async()=>{
  $('refresh-records').disabled=true;
  try {const data=await api('consolidadas');manualRecords=true;renderRecords(data.cuentas);}
  catch(error) {message(error.message);} finally {$('refresh-records').disabled=false;}
});
$('records').addEventListener('click',async event=>{
  const button=event.target.closest('[data-account]'); if(!button) return;
  button.disabled=true; button.textContent='Consultando…';
  try {
    const data=await api('verificar?'+new URLSearchParams({banco:button.dataset.bank,cuenta:button.dataset.account}));
    const a=data.asfi,b=data.banco;
    $('verification').hidden=false; $('verification').className=data.coincide?'':'bad';
    $('verification').innerHTML=`<h3>${data.coincide?'✓ Coincidencia verificada':'! Diferencias detectadas'} · Cuenta ${escapeText(a.cuenta_id)}</h3><div class="comparison"><div><strong>Consolidación ASFI</strong><p>Saldo Bs. <span class="number">${escapeText(a.saldo_bs)}</span></p><p>Tasa <span class="number">${escapeText(a.tipo_cambio)}</span> · Código <span class="code">${escapeText(a.codigo_verificacion)}</span></p><p>Convertida a las ${escapeText(time(a.timestamp))}</p></div><div><strong>Consulta directa al banco</strong><p>Saldo Bs. <span class="number">${escapeText(b.saldo_bs)}</span></p><p>Tasa <span class="number">${escapeText(b.tipo_cambio)}</span> · Código <span class="code">${escapeText(b.codigo_verificacion)}</span></p></div></div><p class="result-formula">${escapeText(a.saldo_usd)} USD × ${escapeText(a.tipo_cambio)} = ${escapeText(a.saldo_bs)} Bs.</p><div class="check-list">${Object.entries(data.verificaciones).map(([k,v])=>`<span>${v?'✓':'✗'} ${escapeText(k)}</span>`).join('')}</div>`;
  } catch(error) {message(error.message);} finally {button.disabled=false;button.textContent='Comparar ↗';}
});
async function pollServices() {
  try {
    if(!wasRunning) serviceState=await api('servicios');
    if(serviceState && !serviceState.listo && !wasRunning) {
      const missing=serviceState.bancos.filter(b=>!b.disponible).map(b=>b.banco_id).join(', ');
      message('Servicios pendientes: '+(missing?'bancos '+missing+'. ':'')+(!serviceState.bcb?'BCB. ':'')+'Inicia: .venv/bin/python scripts/run_panel.py');
    }
  } catch(error) {serviceState=null;}
  finally {setTimeout(pollServices,5000);}
}
banks([]);pollRate();pollServices();pollState();
