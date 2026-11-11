// Human-confirmed single-pot image collections, with native and proxy sources kept separate.
const loadPriorScope = load;
const renderPriorGallery = gallery;
overview = async function () {
  const v = await api('overview');
  $('nobs').textContent = num(v.observations);
  $('ntime').textContent = num(v.time_candidate_scenes);
  $('nlinked').textContent = num(v.user_confirmed_samples);
  $('nviews').textContent = num(v.user_confirmed_images);
  $('nready').textContent = num(v.user_trial_samples);
  $('foot').textContent = `人工確認單株 ${num(v.user_confirmed_samples)} 組；具原廠七項標籤 ${num(v.user_native_trial_samples)} 組、具兩項代理值標籤 ${num(v.user_proxy_trial_samples)} 組，兩類有重疊，不能相加。相機與旋轉角度不另算樣本。`;
};
load = async function () {
  if ($('scope').value !== 'confirmed') return loadPriorScope();
  $('linked-control').hidden = true;
  $('linked-control').style.display = 'none';
  try {
    $('errors').textContent = '';
    const query = new URLSearchParams({crop: $('crop').value, date: $('date').value});
    const rows = await api('user-samples?' + query);
    if ($('scope').value !== 'confirmed') return;
    $('count').textContent = `顯示 ${rows.length} 組人工確認單株`;
    $('cards').innerHTML = rows.map(r => {
      const native = r.primary_kind === 'VENDOR_NATIVE';
      const source = native ? r.sources.native : r.sources.proxy;
      const values = source.numeric_values;
      return `<button class="card" data-user-sample="${r.sample_id}"><div class="photo"><img loading="lazy" src="${base}user-asset/${r.sample_id}/${r.thumbnail_asset_id}" alt="四台相機拍攝同一株的原始影像"></div><div class="body"><div class="date">${esc(r.capture_code)}</div><span class="pill">${cropName(r.crop)}</span><span class="pill ${r.trial_eligible ? '' : 'warn'}">${r.trial_eligible ? '單株已確認' : '單株已確認・數值待處理'}</span><div class="subtle">${num(r.image_count)} 張原圖 · CAM1～4同一株</div><div class="subtle">${deltaLabel(r.csv_minus_rgb_seconds)} · ${native ? '原廠CSV' : 'PLY轉出CSV'}</div><div class="metrics"><div><strong>${num(values[native ? 'pGH' : 'pGH_proxy'])}</strong><span>${native ? '原廠株高 pGH' : '株高代理值'}</span></div><div><strong>${num(values[native ? 'pMW' : 'pMW_proxy'])}</strong><span>${native ? '原廠冠幅 pMW' : '冠幅代理值'}</span></div></div></div></button>`;
    }).join('') || '<div class="empty">此篩選條件沒有人工確認資料。</div>';
    document.querySelectorAll('[data-user-sample]').forEach(card => card.onclick = () => userSampleDetail(card.dataset.userSample));
  } catch (error) { $('errors').textContent = error.message; }
};
gallery = function () {
  if (!detailData.user_sample_context) return renderPriorGallery();
  $('gallery').innerHTML = detailData.images.slice(0, shown).map(v => {
    const url = `${base}user-asset/${detailData.sample_id}/${v.asset_id}`;
    return `<figure><a href="${url}" target="_blank" rel="noopener"><img loading="lazy" src="${url}" alt="單株原始多角度影像"></a><figcaption>CAM${esc(v.camera_code)} · 第${v.frame_index}視角 · 同一株</figcaption></figure>`;
  }).join('');
  $('loadmore').hidden = shown >= detailData.images.length;
};
async function userSampleDetail(id) {
  try {
    const r = await api('user-samples/' + id);
    detailData = {...r, user_sample_context: true}; shown = Math.min(16, r.images.length);
    $('detail-title').textContent = r.capture_code + ' · 人工確認單株';
    $('detail-sub').textContent = 'CAM1、CAM2、CAM3、CAM4為同一株，旋轉角度不另加算';
    $('detail-body').innerHTML = `<div class="notice">圖片時間 ${esc(r.capture_code)}；CSV時間 ${esc(r.csv_capture_code)}，${deltaLabel(r.csv_minus_rgb_seconds)}。${Math.abs(r.csv_minus_rgb_seconds) > 1 ? '<b>近時間CSV候選，時間關係仍保留註記。</b>' : ''}單株影像由使用者人工確認；光照、跨日盆號與數值校正另外記錄。</div>${Object.entries(r.sources).map(([kind, s]) => `<h3>${kind === 'native' ? '原廠表型CSV' : 'PLY轉出的幾何代理值CSV'}</h3><p class="subtle">${s.trial_eligible ? '此來源可作條件式試訓；單位及定義待核對。' : '此來源有既有幾何問題，暫不作試訓標籤。'} ${esc(s.quality_notes || '')}</p><a class="btn" href="${base}api/user-samples/${r.sample_id}/csv?source=${kind}">下載此來源CSV</a><table class="metric-table"><thead><tr><th>原始欄位</th><th>原始數值</th></tr></thead><tbody>${Object.entries(s.raw_values).filter(([name]) => kind === 'native' || ['pGH_proxy', 'pMW_proxy', 'point_count', 'coordinate_unit', 'vertical_axis'].includes(name)).map(([name, value]) => `<tr><td>${esc(name)}</td><td>${esc(value)}</td></tr>`).join('')}</tbody></table>`).join('')}<h3>原始相機影像（${r.images.length}張）</h3><div id="gallery" class="thumbs"></div><button id="loadmore" class="btn">顯示更多視角</button>`;
    $('loadmore').onclick = () => { shown += 24; gallery(); }; gallery();
    if (!$('detail').open) $('detail').showModal();
  } catch (error) { $('errors').textContent = error.message; }
}
['scope', 'linked', 'crop', 'date'].forEach(id => $(id).onchange = load);
$('clear').onclick = () => { $('date').value = ''; load(); };
Promise.all([overview(), load()]).catch(error => $('errors').textContent = error.message);
