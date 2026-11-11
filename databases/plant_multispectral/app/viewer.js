'use strict';
const $=s=>document.querySelector(s),form=$('#filters'),dialog=$('#detail');
const state={page:1,size:24,total:0,overview:null,listAbort:null,detailAbort:null,detail:null};
const num=x=>Number(x).toLocaleString('zh-TW'),fixed=(x,n=4)=>x===null||x===undefined?'—':Number(x).toFixed(n);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const quality={ok:['正常',''],tiny_or_sparse_plant:['極小／稀疏','warn'],no_visible_plant:['未見植株','empty-tag']};
const statusName={COMPUTED:'已計算',EMPTY_MASK:'空遮罩',NO_VISIBLE_PLANT:'未見植株',NO_VALID_PIXELS:'無有效像素',NON_SCALAR_BAND:'波段格式待確認',SHAPE_MISMATCH:'波段尺寸不符',MISSING_BAND_OR_MASK:'缺少波段或遮罩'};
function qualityTag(value){const q=quality[value]||[value,'warn'];return `<span class="tag ${q[1]}">${esc(q[0])}</span>`;}
async function api(path,signal){const response=await fetch(path,{signal,cache:'no-store'});const body=await response.json();if(!response.ok)throw Error(body.error||'資料讀取失敗');return body;}
function params(){const p=new URLSearchParams();for(const [k,v] of new FormData(form))if(v)p.set(k,v);return p;}
function updateUrl(observation){const p=params();if(state.page>1)p.set('page',state.page);if(observation)p.set('observation',observation);history.replaceState(null,'',location.pathname+(p.size?'?'+p:''));}
function showError(message){$('#error').textContent=message;$('#error').hidden=false;}
function updateDates(keep=false){const previous=keep?$('#date').value:'';const batch=$('#batch').value;const dates=[...new Set(state.overview.dates.filter(r=>!batch||String(r.batch_no)===batch).map(r=>r.date))];$('#date').innerHTML='<option value="">全部日期</option>'+dates.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join('');if(dates.includes(previous))$('#date').value=previous;form.elements.plant.max=batch==='1'?'12':'21';}
async function loadRows(){
 if(state.listAbort)state.listAbort.abort();state.listAbort=new AbortController();$('#error').hidden=true;$('#list-status').textContent='讀取篩選結果…';
 const p=params();p.set('page',state.page);p.set('size',state.size);$('#export').href='api/export.csv?'+params();updateUrl(dialog.open&&state.detail?.observation_id);
 try{const data=await api('api/observations?'+p,state.listAbort.signal);state.total=data.total;
  $('#rows').innerHTML=data.rows.length?data.rows.map(r=>`<tr><td><button type="button" class="row-button" data-open="${r.observation_id}" aria-label="查看第${r.batch_no}批 ${esc(r.light_code)} 單株${r.plant_number}">${r.thumbnail_id?`<img class="thumbnail" src="preview/${r.thumbnail_id}?size=120" alt="單株${r.plant_number}裁切預覽" loading="lazy">`:'—'}</button></td><td><span class="primary-cell">${esc(r.light_code)}</span><span class="secondary-cell">${esc(r.batch_name)}</span></td><td class="numeric">${esc(r.captured_at.slice(0,10))}<span class="secondary-cell">${esc(r.captured_at.slice(11))}</span></td><td>plant-${String(r.plant_number).padStart(2,'0')}</td><td><span class="ndvi-number numeric">${fixed(r.ndvi_mean)}</span><span class="secondary-cell">${r.ndvi_mean===null?esc(statusName[r.ndvi_status]||r.ndvi_status):'DN基礎 · 未校正'}</span></td><td>${qualityTag(r.quality_status)}</td><td><button class="row-button" type="button" data-open="${r.observation_id}">查看 →</button></td></tr>`).join(''):'<tr><td class="empty" colspan="7">找不到符合條件的紀錄，請調整篩選條件。</td></tr>';
  const pages=Math.max(1,Math.ceil(data.total/state.size));$('#list-status').textContent=`找到 ${num(data.total)} 筆單株拍攝紀錄`;
  $('#page-status').textContent=`第 ${state.page} / ${pages} 頁`;$('#range').textContent=data.total?`顯示 ${num((state.page-1)*state.size+1)}–${num(Math.min(state.page*state.size,data.total))} 筆`:'沒有資料';
  $('#previous').disabled=state.page<=1;$('#next').disabled=state.page>=pages;
 }catch(error){if(error.name!=='AbortError'){showError(error.message);$('#list-status').textContent='資料讀取失敗';}}
}
function setImage(id){
 const image=state.detail.images.find(i=>i.id===Number(id));if(!image)return;
 $('#main-image').src=`preview/${image.id}?size=640`;$('#main-image').alt=image.channel_code+'單株波段預覽';
 $('#channel-name').textContent=image.channel_code+(image.image_kind==='SPECTRAL'?' nm波段'.replace(' nm',''):'');
 $('#download-image').href='asset/'+image.id;$('#image-path').textContent=image.file_path;
 document.querySelectorAll('.band-item').forEach(b=>b.classList.toggle('active',Number(b.dataset.image)===image.id));
}
async function openDetail(id){
 if(state.detailAbort)state.detailAbort.abort();state.detailAbort=new AbortController();state.detail=null;
 $('#detail-title').textContent='單株明細';$('#detail-content').innerHTML='<p>讀取中…</p>';if(!dialog.open)dialog.showModal();updateUrl(id);
 try{const row=await api('api/observations/'+Number(id),state.detailAbort.signal);state.detail=row;
  $('#detail-title').textContent=`${row.batch_name} · ${row.light_code} · plant-${String(row.plant_number).padStart(2,'0')}`;
  const m=row.measurement||{},image=row.images.find(i=>i.image_kind==='COLOR')||row.images.find(i=>i.channel_code==='L540')||row.images[0];
  $('#detail-content').innerHTML=`<div class="detail-grid"><div><div class="main-preview"><img id="main-image" alt="單株圖片"></div><div class="image-toolbar"><strong id="channel-name"></strong><a class="button secondary" id="download-image" href="#">下載原始PNG ↗</a></div><p class="display-note">16位元灰階預覽僅調整顯示亮度；下載保留原始像素。</p></div><div><p class="observation-meta">${esc(row.captured_at)}<br>${row.band_count}個波段 · ${qualityTag(row.quality_status)}</p><div class="ndvi-feature"><span>NDVI平均值 · ${esc(statusName[row.ndvi_status]||row.ndvi_status)}</span><strong>${fixed(row.ndvi_mean,6)}</strong><small>原始DN計算，反射率校正尚未確認。</small></div><div class="stats"><div><span>中位數</span><b>${fixed(m.index_median)}</b></div><div><span>標準差</span><b>${fixed(m.index_std)}</b></div><div><span>有效像素</span><b>${num(m.valid_pixel_count||0)}</b></div><div><span>最小值</span><b>${fixed(m.index_min)}</b></div><div><span>最大值</span><b>${fixed(m.index_max)}</b></div><div><span>遮罩像素</span><b>${num(m.mask_pixel_count||0)}</b></div></div><p class="detail-note">公式：(L800 − L680) / (L800 + L680)<br>遮罩內逐像素計算後取平均，排除零分母及飽和像素。跨波段配準尚未另外驗證。</p></div></div><h3 class="gallery-heading">切換波段與遮罩</h3><div class="band-grid">${row.images.map(i=>`<button class="band-item" type="button" data-image="${i.id}" aria-label="查看${esc(i.channel_code)}"><img src="preview/${i.id}?size=120" alt="${esc(i.channel_code)}預覽" loading="lazy"><span>${esc(i.channel_code)}</span></button>`).join('')}</div><details class="path-section"><summary>檔案路徑</summary><code id="image-path"></code><button type="button" class="button secondary" id="copy-path">複製路徑</button><span id="copy-status" role="status"></span></details>`;
  setImage(image.id);$('#copy-path').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#image-path').textContent);$('#copy-status').textContent=' 已複製';}catch{$('#copy-status').textContent=' 請選取上方文字複製';}});
 }catch(error){if(error.name!=='AbortError')$('#detail-content').innerHTML=`<p class="detail-error">${esc(error.message)}</p>`;}
}
form.addEventListener('submit',event=>{event.preventDefault();state.page=1;loadRows();});
form.addEventListener('reset',()=>setTimeout(()=>{updateDates();state.page=1;loadRows();},0));
$('#batch').addEventListener('change',()=>updateDates(true));
$('#previous').addEventListener('click',()=>{if(state.page>1){state.page--;loadRows();}});
$('#next').addEventListener('click',()=>{if(state.page*state.size<state.total){state.page++;loadRows();}});
document.addEventListener('click',event=>{const open=event.target.closest('[data-open]');if(open)openDetail(open.dataset.open);const image=event.target.closest('[data-image]');if(image)setImage(image.dataset.image);});
$('#close-detail').addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>{if(state.detailAbort)state.detailAbort.abort();updateUrl();});
async function init(){try{state.overview=await api('api/overview');const o=state.overview;
 $('#metric-observations').textContent=num(o.observations);$('#metric-bands').textContent=num(o.band_images);$('#metric-computed').textContent=num(o.computed);$('#metric-empty').textContent=num(o.empty_masks);
 $('#batch').insertAdjacentHTML('beforeend',o.batches.map(b=>`<option value="${b.batch_no}">${esc(b.display_name)}</option>`).join(''));
 $('#light').insertAdjacentHTML('beforeend',o.lights.map(l=>`<option value="${esc(l.code)}">${esc(l.code)}</option>`).join(''));
 $('#batch-summary').innerHTML=o.batches.map(b=>`<div class="batch-line"><strong>${esc(b.display_name)}</strong><span>${esc(b.first_captured_on)} ～ ${esc(b.last_captured_on)}</span><span>每光 ${num(b.plants_per_light)} 個配置盆號</span><span>${num(b.plant_observations)} 筆拍攝紀錄</span></div>`).join('');
 const url=new URLSearchParams(location.search);for(const name of ['batch','light','plant','quality','sort'])if(url.has(name))form.elements[name].value=url.get(name);form.elements.computed.checked=url.get('computed')==='1';
 updateDates();if(url.has('date'))$('#date').value=url.get('date');state.page=Math.max(1,Number(url.get('page'))||1);const observation=url.get('observation');await loadRows();if(observation&&/^\d+$/.test(observation))openDetail(observation);
}catch(error){showError(error.message);$('#list-status').textContent='無法連接資料庫';}}
init();
