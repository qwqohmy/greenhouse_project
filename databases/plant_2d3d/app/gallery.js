'use strict';
const root=location.pathname.replace(/(?:gallery|records)\/?$/,'').replace(/\/?$/,'/');
const $=id=>document.getElementById(id),escapeText=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let generation=0;
async function load(crop){
 const current=++generation;$('error').hidden=true;$('status').textContent='讀取影像…';
 try{
  const response=await fetch(root+'api/dataset-gallery?crop='+crop,{cache:'no-store'});if(!response.ok)throw Error('影像暫時無法讀取');const data=await response.json();if(current!==generation)return;
  const name=crop==='lettuce'?'生菜（萵苣）':'番茄',kind=data.kind==='2d'?'2D':'多光譜';
  document.title=name+kind+'影像資料集｜Greenhouse';$('title').textContent=name+kind+'：'+data.count+'筆拍攝觀測';
  $('subtitle').textContent=data.kind==='2d'?'每個單盆拍攝場次選一張RGB影像；同一株跨日可作不同觀測。':'每格為不同植株當日觀測，固定同一波段（540 nm），不以不同波段重複計數。';
  $('records').textContent=data.kind==='2d'?'表型資料與 CSV':'波段、NDVI 與 CSV';$('records').href=root+'records';
  $('spectral-note').hidden=data.kind!=='spectral';$('lettuce').setAttribute('aria-pressed',crop==='lettuce');$('tomato').setAttribute('aria-pressed',crop==='tomato');
  $('sheet').href=root+'gallery/sheet/'+crop;$('jpgs').href=root+'gallery/download/'+crop+'.zip';
  $('status').textContent='展示 '+data.count+' 筆觀測，每筆對應一張 JPG'+(data.count<12?'；其餘日期待補，未重複充數。':'。');
  const cards=data.rows.map(r=>`<figure><a class="image-area" href="${root+escapeText(r.image_url)}" target="_blank" rel="noopener"><img src="${root+escapeText(r.image_url)}" alt="${name} ${escapeText(r.date)} ${escapeText(r.plant_label)}"></a><figcaption><span class="name">${escapeText(r.plant_label)}</span><span class="meta">${escapeText(r.date)} · ${escapeText(r.channel)}</span></figcaption></figure>`);
  while(cards.length<12)cards.push('<figure class="placeholder"><div class="image-area">其他日期待補</div><figcaption><span class="name">待補樣本</span><span class="meta">不以重複角度充數</span></figcaption></figure>');
  $('gallery').innerHTML=cards.join('');const query=new URLSearchParams(location.search);query.set('crop',crop);history.replaceState(null,'',location.pathname+'?'+query);
 }catch(error){$('error').hidden=false;$('error').textContent=error.message;$('status').textContent='讀取失敗';}
}
$('lettuce').onclick=()=>load('lettuce');$('tomato').onclick=()=>load('tomato');
load(new URLSearchParams(location.search).get('crop')==='tomato'?'tomato':'lettuce');
