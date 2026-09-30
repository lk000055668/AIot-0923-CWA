/* Single zoom-based rendering pipeline for every observed weather metric. */
(function () {
  const map = __WEATHER_MAP__, data = __WEATHER_DATA__;
  const groups = {county:L.layerGroup(), district:L.layerGroup()};
  const caches = {county:new Map(), district:new Map()};
  const locations = L.layerGroup(), locationCache = new Map(), selection = L.layerGroup().addTo(map);
  const boundaryLayers = {}, boundaryLookup = {county:new Map(), district:new Map()};
  let metric = Object.keys(data.layers)[0] || null, selectedStation = null, selectedRegion = null, pendingFocus = null;
  const overlays = {stations:false, county:false, district:false};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const norm = value => String(value || '').replaceAll('台','臺').trim().toLowerCase();
  const regionKey = (county, district='') => norm(county) + '|' + norm(district);
  const valueOf = item => item.kind === 'station' ? item[metric] : item.value;
  function color(value) {
    if (!Number.isFinite(value) || !metric) return '#64748b';
    const spec = data.layers[metric], index = spec.breaks.findIndex(limit => value < limit);
    return spec.colors[index < 0 ? spec.colors.length - 1 : index];
  }
  function level() {
    return map.getZoom() <= data.thresholds.county ? 'county' : 'district';
  }
  const stationById = new Map(data.stations.map(station=>[station.id,station]));
  function readings(values, counts) {
    let html='<div class="popup-observations">';
    Object.entries(data.layers).forEach(([key,spec])=>{
      if(Number.isFinite(values[key]))html+='<span>'+esc(spec.title)+' <b>'+values[key].toFixed(1)+' '+esc(spec.unit)+'</b>'+(counts?' · '+counts[key]+' 站':'')+'</span>';
    });return html+'</div>';
  }
  function popup(item) {
    const value=valueOf(item), spec=data.layers[metric], isStation=item.kind==='station';
    const title=isStation?(item.district || '行政區未確認'):item.name;
    let html='<div class="station-popup"><small>'+esc(item.county)+'</small><h3>'+esc(title)+'</h3>';
    if(isStation)html+='<p>來源測站觀測（非行政區平均）</p>';
    if(spec&&Number.isFinite(value))html+='<small>目前'+esc(spec.title)+'</small><br><strong>'+value.toFixed(1)+'<small> '+esc(spec.unit)+'</small></strong>';
    else html+='<p>此地點沒有目前圖層的有效觀測</p>';
    html+=readings(isStation?item:(item.values||{}),isStation?null:item.counts);
    if(isStation){
      html+='<details class="popup-sources"><summary>資料來源：'+esc(item.name)+'</summary><p>測站 '+esc(item.stationId)+'<br>'+esc(item.weather)+'<br>觀測 '+esc(item.obsTime);
      if(Number.isFinite(item.dailyHigh))html+='<br>今日最高 '+item.dailyHigh.toFixed(1)+' °C';
      if(Number.isFinite(item.dailyLow))html+='<br>今日最低 '+item.dailyLow.toFixed(1)+' °C';
      html+='<br>行政區判定：'+esc(item.mappingMethod)+'</p></details>';
    }else{
      const sources=(item.station_ids||[]).map(id=>stationById.get(id)).filter(Boolean);
      if(sources.length){
        html+='<p>有效測站平均，非全區插值或雨量總和。</p><details class="popup-sources"><summary>資料來源：'+(sources.length===1?esc(sources[0].name):sources.length+' 個氣象測站')+'</summary><div class="source-list">';
        sources.forEach(station=>{
          html+='<article><b>'+esc(station.name)+'</b><small> '+esc(station.stationId)+'</small>'+readings(station,null)+'<small>觀測 '+esc(station.obsTime)+'</small>';
          if(station.mappingMethod!=='polygon')html+='<p>行政區採 CWA 既有欄位確認（界線參考圖資未能唯一定位）。</p>';
          html+='</article>';
        });html+='</div></details>';
      }
    }
    return html+'</div>';
  }
  function makeMarker(item) {
    const value = valueOf(item), unit = data.layers[metric]?.unit || '';
    const html = '<div class="weather-value '+item.kind+'" style="--weather-color:'+color(value)+'">'+
      (item.kind !== 'station' ? '<span>'+esc(item.name)+'</span>' : '')+
      '<b>'+value.toFixed(1)+'<small>'+esc(unit)+'</small></b></div>';
    return L.marker([item.lat,item.lon], {title:item.name,icon:L.divIcon({className:'weather-label',html,iconSize:[68,36],iconAnchor:[34,18]})})
      .bindTooltip(esc(item.name)+' '+value.toFixed(1)+' '+esc(unit)).bindPopup(popup(item), {maxWidth:310});
  }
  function sync(items, cache, group, factory, predicate=()=>true) {
    const visible = new Set(), bounds = map.getBounds().pad(.08);
    items.forEach(item => {
      if (!predicate(item) || !bounds.contains([item.lat,item.lon])) return;
      visible.add(item.id);
      if (!cache.has(item.id)) cache.set(item.id, factory(item));
      if (!group.hasLayer(cache.get(item.id))) group.addLayer(cache.get(item.id));
    });
    cache.forEach((marker,id) => {if (!visible.has(id)) group.removeLayer(marker);});
  }
  function regionValue(kind, county, district) {
    const matches=item=>regionKey(item.county,item.district)===regionKey(county,district);
    const current=data.datasets[metric]?.[kind].find(matches);
    if(current)return current;
    // A missing active metric must not hide other valid district observations.
    for(const dataset of Object.values(data.datasets)){
      const item=dataset[kind].find(matches);
      if(item)return {...item,value:null,station_count:0};
    }
  }
  function boundaryStyle(kind, feature) {
    const p = feature.properties, item = regionValue(kind,p.COUNTYNAME,kind === 'district' ? p.TOWNNAME : '');
    const painted = kind === level() && item && Number.isFinite(item.value);
    return {color:painted ? color(item.value) : kind === 'county' ? '#94c8ec' : '#94a3b8', weight:kind === 'county' ? 1.6 : .8,
      opacity:.7, fillColor:painted ? color(item.value) : '#64748b', fillOpacity:painted ? .16 : 0};
  }
  Object.entries(data.boundaries).forEach(([kind, geojson]) => {
    boundaryLayers[kind] = L.geoJSON(geojson, {style:feature=>boundaryStyle(kind,feature), onEachFeature:(feature, layer) => {
      const p = feature.properties, county = p.COUNTYNAME, district = kind === 'district' ? p.TOWNNAME : '';
      boundaryLookup[kind].set(regionKey(county,district),layer);
      layer.bindTooltip(esc(county)+(district ? ' · '+esc(district) : ''));
      layer.bindPopup(() => popup(regionValue(kind,county,district) || {kind,county,district,name:district || county}),{maxWidth:310});
    }});
  });
  function updateWeatherLayers() {
    const active = level();
    Object.entries(groups).forEach(([kind, group]) => {
      if (kind === active && metric) {
        if (!map.hasLayer(group)) map.addLayer(group);
        const items = data.datasets[metric][kind];
        sync(items,caches[kind],group,makeMarker,item=>Number.isFinite(valueOf(item)));
      } else if (map.hasLayer(group)) map.removeLayer(group);
    });
    if (overlays.stations) {
      if (!map.hasLayer(locations)) map.addLayer(locations);
      sync(data.stations,locationCache,locations,item=>L.circleMarker([item.lat,item.lon],{radius:3,color:'#e2e8f0',weight:1,fillColor:'#334155',fillOpacity:.8})
        .bindTooltip(esc(item.district || '行政區未確認')+' · 資料來源：'+esc(item.name)).bindPopup(()=>popup(item),{maxWidth:310}));
    } else map.removeLayer(locations);
    Object.entries(boundaryLayers).forEach(([kind, layer])=>{
      if (overlays[kind]) {if (!map.hasLayer(layer)) map.addLayer(layer);layer.setStyle(feature=>boundaryStyle(kind,feature));}
      else map.removeLayer(layer);
    });
    map.fire('weather:change',{metric,level:active});
  }
  function openStation(item) {
    selection.clearLayers();updateWeatherLayers();
    L.circleMarker([item.lat,item.lon],{radius:5,color:'#f8fafc',fillOpacity:.8}).addTo(selection).bindPopup(popup(item),{maxWidth:330}).openPopup();
  }
  function openRegion(item) {
    const district=item.kind==='district'?item.name:'';
    const observed=regionValue(item.kind,item.county,district);
    const marker=observed && caches[item.kind].get(observed.id);
    if(marker && groups[item.kind].hasLayer(marker))marker.openPopup();
    else L.popup({maxWidth:330}).setLatLng(item.bounds.getCenter()).setContent(popup(observed || {kind:item.kind,county:item.county,district,name:item.name})).openOn(map);
  }
  // Search index uses the already-loaded geometry and observations, never APIs.
  const index = [], seen = new Set();
  Object.entries(boundaryLookup).forEach(([kind, lookup]) => lookup.forEach((layer,key) => {
    const p=layer.feature.properties, name=kind==='county'?p.COUNTYNAME:p.TOWNNAME;
    index.push({id:kind+':'+key,kind,name,county:p.COUNTYNAME,bounds:layer.getBounds()});seen.add(kind+':'+key);
  }));
  ['county','district'].forEach(kind => {
    const grouped = new Map();
    data.stations.forEach(station=>{
      const name=kind==='county'?station.county:station.district;
      if (!name) return;
      const key=regionKey(station.county,kind==='district'?name:'');
      if (!grouped.has(key)) grouped.set(key,{id:kind+':'+key,kind,name,county:station.county,bounds:L.latLngBounds([])});
      grouped.get(key).bounds.extend([station.lat,station.lon]);
    });
    grouped.forEach(item=>{if(!seen.has(item.id)) index.push(item);});
  });
  index.push(...data.stations);
  const api = {
    data, groups, overlays, boundaryLayers, locations, index, level, color, popup,
    get metric(){return metric;},
    setMetric(key) {
      if (!(key in data.layers)) return;
      metric=key;map.closePopup();selection.clearLayers();
      Object.keys(groups).forEach(kind=>{groups[kind].clearLayers();caches[kind].clear();});
      updateWeatherLayers();
      if(selectedStation)openStation(selectedStation);
      else if(selectedRegion)openRegion(selectedRegion);
    },
    setOverlay(key, enabled){if(key in overlays){overlays[key]=!!enabled;updateWeatherLayers();}},
    search(query) {
      const q=norm(query);if(!q)return [];
      return index.filter(item=>norm(item.name+' '+item.county+' '+(item.district||'')+' '+(item.stationId||'')).includes(q))
        .sort((a,b)=>({county:0,district:1,station:2}[a.kind]-{county:0,district:1,station:2}[b.kind]) || Number(norm(b.name).startsWith(q))-Number(norm(a.name).startsWith(q))).slice(0,30);
    },
    focus(item) {
      if(pendingFocus){map.off('moveend',pendingFocus);pendingFocus=null;}
      map.closePopup();selection.clearLayers();selectedStation=null;selectedRegion=null;
      if(item.kind==='station') {
        selectedStation=item;
        pendingFocus=()=>{pendingFocus=null;openStation(item);};map.once('moveend',pendingFocus);
        map.flyTo([item.lat,item.lon],Math.max(12,data.thresholds.district+1),{duration:.5});
        if(pendingFocus && map.getCenter().equals([item.lat,item.lon]) && map.getZoom()===12){map.off('moveend',pendingFocus);pendingFocus();}
      } else {
        map.fitBounds(item.bounds,{padding:[65,65],maxZoom:item.kind==='county'?data.thresholds.county:data.thresholds.district,animate:false});
        if(item.kind==='district' && map.getZoom()<=data.thresholds.county)map.setZoom(data.thresholds.county+.5);
        selectedRegion=item;updateWeatherLayers();openRegion(item);
      }
    }
  };
  map.weather = api;
  map.weatherLayers = [groups.county,groups.district];
  map.on('zoomend moveend',updateWeatherLayers);
  updateWeatherLayers();
})();
