(function () {
  const map = __WEATHER_MAP__, config = __WEATHER_CONFIG__, weather=map.weather;
  const container=map.getContainer();container.setAttribute('aria-label','台灣互動氣象地圖');
  const positions={topLeft:'topleft',topRight:'topright',bottomLeft:'bottomleft'};
  function stopMapEvents(node){L.DomEvent.disableClickPropagation(node);L.DomEvent.disableScrollPropagation(node);node.addEventListener('keydown',event=>event.stopPropagation());}
  Object.entries(config.panels).forEach(([key,html])=>{
    const Control=L.Control.extend({options:{position:positions[key]},onAdd(){const node=L.DomUtil.create('div','weather-overlay');node.innerHTML=html;stopMapEvents(node);return node;}});new Control().addTo(map);
  });
  const searchHost=L.DomUtil.create('div','search-host',container);searchHost.innerHTML=config.search;stopMapEvents(searchHost);
  L.control.zoom({position:'bottomright',zoomInTitle:'放大地圖',zoomOutTitle:'縮小地圖'}).addTo(map);
  map.attributionControl.addAttribution('<a href="https://github.com/dkaoster/taiwan-atlas" target="_blank" rel="noopener">界線：MOI / Taiwan Atlas</a>');
  const layerSelect=document.getElementById('weather-layer'),legend=document.querySelector('.weather-legend');
  const theme=document.getElementById('weather-theme'),labels=document.getElementById('weather-labels'),summary=document.querySelector('.weather-summary');
  const storageKey='taiwan-weather-map-view-v2';
  function updateLegend(){
    const spec=weather.data.layers[weather.metric];legend.hidden=!spec;if(!spec)return;layerSelect.value=weather.metric;
    const title=document.createElement('div');title.className='legend-title';
    const name=document.createElement('b');name.textContent=spec.title;title.append(name);
    const unit=document.createElement('span');unit.textContent=spec.unit;title.append(unit);
    const scale=document.createElement('div');scale.className='legend-scale';
    spec.colors.forEach((color,index)=>{const bin=document.createElement('span');bin.style.background=color;bin.title=(index===0?'＜'+spec.breaks[0]:index===spec.breaks.length?'≥'+spec.breaks[index-1]:spec.breaks[index-1]+'–＜'+spec.breaks[index])+' '+spec.unit;scale.append(bin);});
    const ticks=document.createElement('div');ticks.className='weather-ticks';spec.breaks.forEach(value=>{const tick=document.createElement('span');tick.textContent=value;ticks.append(tick);});
    const note=document.createElement('small');note.textContent='區域有效測站平均 · 非全區插值';legend.replaceChildren(title,scale,ticks,note);
  }
  function save(){try{sessionStorage.setItem(storageKey,JSON.stringify({center:map.getCenter(),zoom:map.getZoom(),metric:weather.metric,theme:theme.value,labels:labels.checked,summary:summary.open,overlays:weather.overlays}));}catch(_){}}
  function applyTheme(){container.classList.toggle('weather-dark',theme.value==='dark');}
  function applyLabels(){container.classList.toggle('weather-hide-labels',!labels.checked);}
  theme.value=weather.data.initial.theme;labels.checked=weather.data.initial.labels;
  try{const state=JSON.parse(sessionStorage.getItem(storageKey));if(state){
    if(state.center&&Number.isFinite(state.zoom))map.setView(state.center,state.zoom,{animate:false});
    if(state.metric in weather.data.layers)weather.setMetric(state.metric);
    theme.value=state.theme==='street'?'street':'dark';labels.checked=state.labels!==false;summary.open=state.summary!==false;
    Object.entries(state.overlays||{}).forEach(([key,enabled])=>weather.setOverlay(key,enabled));
  }}catch(_){}
  if(innerWidth<900)summary.open=false;if(innerWidth<600)document.querySelector('.weather-controls').open=false;
  applyTheme();applyLabels();updateLegend();
  layerSelect.addEventListener('change',()=>{weather.setMetric(layerSelect.value);save();});
  theme.addEventListener('change',()=>{applyTheme();save();});labels.addEventListener('change',()=>{applyLabels();save();});
  ['stations','county','district'].forEach(key=>{const checkbox=document.getElementById('overlay-'+key);if(!checkbox)return;checkbox.checked=weather.overlays[key];checkbox.addEventListener('change',()=>{weather.setOverlay(key,checkbox.checked);save();});});
  summary.addEventListener('toggle',save);map.on('weather:change',updateLegend);map.on('moveend zoomend',save);
  const input=document.getElementById('weather-search'),results=document.getElementById('weather-results'),status=document.getElementById('search-status');let matches=[],active=-1;
  const kindNames={county:'縣市',district:'行政區',station:'測站來源'};
  function closeResults(){results.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;}
  function choose(index){if(!matches[index])return;const item=matches[index];input.value=item.name;closeResults();weather.focus(item);status.textContent='已定位 '+item.name;}
  function renderResults(){
    matches=weather.search(input.value);active=-1;results.replaceChildren();input.removeAttribute('aria-activedescendant');
    if(!input.value.trim()){closeResults();return;}results.hidden=false;input.setAttribute('aria-expanded','true');
    if(!matches.length){const empty=document.createElement('p');empty.className='search-empty';empty.textContent='找不到符合的地點';results.append(empty);}
    matches.forEach((item,index)=>{const option=document.createElement('button');option.type='button';option.id='search-result-'+index;option.setAttribute('role','option');option.setAttribute('aria-selected','false');
      const name=document.createElement('span');name.textContent=item.name+'｜'+kindNames[item.kind];const detail=document.createElement('small');detail.textContent=item.kind==='station'?item.county+' '+item.district+' · '+item.stationId:item.county;
      option.append(name,detail);option.addEventListener('click',()=>choose(index));results.append(option);
    });status.textContent=matches.length+' 筆搜尋結果';
  }
  input.addEventListener('input',renderResults);input.addEventListener('focus',()=>{if(input.value.trim())renderResults();});
  input.addEventListener('keydown',event=>{
    if(event.isComposing)return;if(event.key==='Escape'){closeResults();return;}
    if(['ArrowDown','ArrowUp'].includes(event.key)&&matches.length){event.preventDefault();if(results.hidden)renderResults();active=(active+(event.key==='ArrowDown'?1:-1)+matches.length)%matches.length;results.querySelectorAll('[role="option"]').forEach((node,index)=>node.setAttribute('aria-selected',String(index===active)));input.setAttribute('aria-activedescendant','search-result-'+active);document.getElementById('search-result-'+active).scrollIntoView({block:'nearest'});}
    if(event.key==='Enter'&&!results.hidden&&matches.length){event.preventDefault();choose(active<0?0:active);}
  });
  document.getElementById('search-clear').addEventListener('click',()=>{input.value='';closeResults();input.focus();});
  document.addEventListener('pointerdown',event=>{if(!searchHost.contains(event.target))closeResults();});
  new ResizeObserver(()=>map.invalidateSize({pan:false})).observe(container);requestAnimationFrame(()=>map.invalidateSize({pan:false}));
})();
