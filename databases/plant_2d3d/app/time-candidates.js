// Scene-level time candidates remain separate from individual-pot image/CSV links.
const loadSingleScenes = load;
const renderSingleGallery = gallery;
function deltaLabel(value) {
  const seconds = Math.abs(Math.round(Number(value)));
  if (seconds === 0) return '時間一致';
  const minutes = Math.floor(seconds / 60), remainder = seconds % 60;
  return `相差 ${minutes} 分 ${remainder} 秒`;
}
function candidateAsset(context, id) {
  return `${base}candidate-asset/${context.ply_session_id}/${context.rgb_session_id}/${id}`;
}
overview = async function () {
  const data = await api('overview');
  $('nobs').textContent = num(data.observations);
  $('ntime').textContent = num(data.time_candidate_scenes);
  $('nlinked').textContent = num(data.linked_observations);
  $('nviews').textContent = num(data.linked_views);
  $('nready').textContent = num(data.proxy_training_scenes);
  $('foot').textContent = `時間候選以 PLY 拍攝場次去重，多個候選 RGB 場次、PLY 區塊及圖片角度都不重複計為植株。自動處理 ${num(data.processed_images)} 張來源影像。`;
};
load = async function () {
  const timeMode = $('scope').value === 'time';
  $('linked-control').hidden = timeMode;
  $('linked-control').style.display = timeMode ? 'none' : 'flex';
  if (!timeMode) return loadSingleScenes();
  try {
    $('errors').textContent = '';
    $('count').textContent = '讀取時間候選…';
    const query = new URLSearchParams({crop: $('crop').value, date: $('date').value});
    const rows = await api('time-candidates?' + query);
    if ($('scope').value !== 'time') return;
    $('count').textContent = `顯示 ${rows.length} 個 PLY 時間候選場次`;
    $('cards').innerHTML = rows.length ? rows.map(row => {
      const context = {ply_session_id: row.ply_session_id, rgb_session_id: row.nearest_rgb_session_id};
      return `<button class="card" data-scene="${row.ply_session_id}"><div class="photo">${row.thumbnail_asset_id ? `<img loading="lazy" src="${candidateAsset(context, row.thumbnail_asset_id)}" alt="拍攝場次裁切候選預覽，盆栽尚待確認">` : '目前無裁切預覽'}</div><div class="body"><div class="date">PLY ${esc(row.captured_at)}</div><span class="pill">${cropName(row.crop)}</span><span class="pill warn">時間候選・盆栽待確認</span><div class="subtle">最近 RGB：${esc(row.nearest_rgb_capture_code)}</div><div>${deltaLabel(row.nearest_delta_seconds)}</div><div class="subtle">${num(row.rgb_candidates.length)} 個 RGB 場次候選 · ${num(row.csv_component_candidates)} 個 PLY 區塊 CSV</div></div></button>`;
    }).join('') : '<div class="empty">此篩選條件沒有時間候選場次。</div>';
    document.querySelectorAll('[data-scene]').forEach(card => card.onclick = () => timeDetail(card.dataset.scene));
  } catch (error) {
    $('errors').textContent = error.message;
    $('count').textContent = '';
  }
};
gallery = function () {
  if (!detailData.candidate_context) return renderSingleGallery();
  const mode = $('mode').value;
  $('gallery').innerHTML = detailData.images.slice(0, shown).map(view => {
    const id = mode === 'mask' ? view.mask_asset_id : mode === 'segmented' ? view.segmented_asset_id : view.asset_id;
    const url = candidateAsset(detailData.candidate_context, id);
    return `<figure><a href="${url}" target="_blank" rel="noopener"><img loading="lazy" src="${url}" alt="時間候選場次圖片"></a><figcaption>CAM${esc(view.camera_code)} · 視角 ${view.frame_index} · 區域 ${view.instance_local_id}（非實體盆號）</figcaption></figure>`;
  }).join('');
  $('loadmore').hidden = shown >= detailData.images.length;
};
async function timeDetail(plyId, rgbId) {
  try {
    const row = await api(`time-candidates/${plyId}` + (rgbId ? `/rgb/${rgbId}` : ''));
    detailData = row;
    shown = Math.min(16, row.images.length);
    $('detail-title').textContent = `PLY ${row.ply_capture_code} · ${cropName(row.crop)}`;
    $('detail-sub').textContent = '時間候選場次連結；尚未指定每株 RGB 對應哪份 CSV';
    $('detail-body').innerHTML = `<div class="notice"><b>${deltaLabel(row.selected_rgb.delta_seconds)}</b>。此處展示同一候選拍攝場次中的裁切區域，不代表每張圖片都對應下列全部 CSV；問題標記與缺值保留。</div><label>RGB 候選場次 <select id="candidate-rgb">${row.rgb_candidates.map(candidate => `<option value="${candidate.rgb_session_id}" ${candidate.rgb_session_id === row.selected_rgb.rgb_session_id ? 'selected' : ''}>${esc(candidate.rgb_capture_code)} · ${deltaLabel(candidate.delta_seconds)}</option>`).join('')}</select></label><h3>此 PLY 的區塊 CSV 候選</h3><table class="metric-table"><thead><tr><th>候選區塊</th><th>數值</th><th>審核狀態</th><th>下載</th></tr></thead><tbody>${row.observations.map((observation, index) => `<tr><td>區塊 ${index + 1}<br><span class="subtle">${esc(observation.observation_key)}</span></td><td>株高代理值 ${num(observation.pGH_proxy)}<br>冠幅代理值 ${num(observation.pMW_proxy)}</td><td>${status(observation.visual_review_status)}<br><span class="subtle">${esc(observation.review_notes)}</span></td><td><a href="${base}api/observations/${observation.observation_id}/csv">CSV</a></td></tr>`).join('')}</tbody></table><div class="section-head"><h3>候選 RGB 場次的裁切區域（${row.images.length}）</h3><select id="mode" aria-label="圖片類型"><option value="rgb">RGB 裁切</option><option value="segmented">去背圖</option><option value="mask">遮罩</option></select></div><div id="gallery" class="thumbs"></div><button id="loadmore" class="btn">顯示更多視角</button>`;
    $('candidate-rgb').onchange = () => timeDetail(plyId, $('candidate-rgb').value);
    $('mode').onchange = gallery;
    $('loadmore').onclick = () => { shown += 24; gallery(); };
    gallery();
    if (!$('detail').open) $('detail').showModal();
  } catch (error) {
    $('errors').textContent = error.message;
  }
}
['scope', 'linked', 'crop', 'date'].forEach(id => $(id).onchange = load);
$('clear').onclick = () => { $('date').value = ''; load(); };
if ($('scope').value !== 'confirmed') Promise.all([overview(), load()]).catch(error => $('errors').textContent = error.message);
