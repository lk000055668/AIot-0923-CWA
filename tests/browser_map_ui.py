"""Live browser regression: python tests/browser_map_ui.py.
Requires dev-only Playwright and installed Edge. Runs the actual app with CWA/SQLite.
"""
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root=Path(__file__).resolve().parents[1]
work=Path(tempfile.mkdtemp(prefix='weather-live-check-'))
app_python=root/'.venv'/'Scripts'/'python.exe'
empty_mode='--empty' in sys.argv
app_path=root/'app.py'
if empty_mode:
    app_path=work/'empty_app.py'
    app_path.write_text("import sys,runpy\nsys.path.insert(0,"+repr(str(root))+")\nimport cwa_api,database,pandas as pd\ncwa_api.get_api_key=lambda:None\ndatabase.init_db=lambda:None\ndatabase.init_station_db=lambda:None\ndatabase.get_station_observations=lambda:pd.DataFrame()\nrunpy.run_path("+repr(str(root/'app.py'))+",run_name='__main__')\n",encoding='utf-8')
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
log=(work/'server.log').open('w',encoding='utf-8')
proc=subprocess.Popen([str(app_python),'-m','streamlit','run',str(app_path),'--server.port',str(port),'--server.headless','true','--browser.gatherUsageStats','false'],cwd=root,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':900})
        errors=[];console_errors=[]
        page.on('pageerror',lambda err:errors.append(str(err)))
        page.on('console',lambda msg:console_errors.append(msg.text) if msg.type=='error' else None)
        for attempt in range(50):
            try:
                page.goto(f'http://localhost:{port}',wait_until='domcontentloaded');break
            except Exception:time.sleep(.25)
        print('Actual app started; waiting for CWA and Leaflet',flush=True)
        frame=page.frame_locator('.st-key-weather_map iframe')
        frame.locator('.weather-controls').wait_for(timeout=180000)
        def document():return page.locator('.st-key-weather_map iframe').element_handle().content_frame()
        map_expr='Object.values(window).find(v=>v instanceof L.Map)'
        def evaluate(expression):
            # Never serialize Leaflet's cyclic Map object back to Python.
            if expression.startswith(('map.setView(', 'map.setZoom(')):
                expression = '(' + expression + ', null)'
            return document().evaluate('(()=>{const map='+map_expr+';return '+expression+';})()')

        try:
            if empty_mode:
                assert evaluate('Object.keys(map.weather.data.layers).length') == 0
                assert frame.locator('#weather-layer').is_disabled()
                assert not frame.locator('.weather-legend').is_visible()
                assert not frame.locator('.summary-reading').count()
                assert not frame.locator('.weather-label').count()
                frame.locator('#overlay-county').check()
                frame.locator('#weather-search').fill('淡')
                frame.locator('[role="option"]').filter(has_text='｜行政區').first.click()
                assert evaluate('map.weather.level()') == 'district'
                assert not errors and not console_errors
                print('Empty data: no weather values/options/legend, boundaries and search still usable; no JS errors',flush=True)
                raise SystemExit(0)
            assert not page.locator('[data-testid="stException"]').count()
            assert not frame.locator('.weather-error').inner_text().strip(),frame.locator('.weather-error').inner_text()
            stations=evaluate('map.weather.data.stations')
            assert stations,'Live CWA observations were not loaded'
            print('Live stations',len(stations),'metrics',evaluate('Object.keys(map.weather.data.layers)'),flush=True)
            print('Spatial mapping', {method:sum(station['mappingMethod']==method for station in stations) for method in set(station['mappingMethod'] for station in stations)},flush=True)
            for width,height in [(1920,1080),(1440,900),(1366,768),(390,844)]:
                page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(300)
                box=page.locator('.st-key-weather_map iframe').bounding_box()
                assert abs(box['width']-width)<2 and abs(box['height']-height)<2 and box['x']==0 and box['y']==0,box
                assert page.evaluate('document.documentElement.scrollHeight<=innerHeight')
                boxes={key:frame.locator(selector).bounding_box() for key,selector in [('layers','.weather-controls'),('search','.search-host'),('summary','.weather-summary'),('legend','.weather-legend'),('zoom','.leaflet-control-zoom')]}
                for key,b in boxes.items():
                    assert b['x']>=0 and b['x']+b['width']<=width+1 and b['y']>=0 and b['y']+b['height']<=height+1,(key,b)
                for a,b in [('layers','search'),('summary','search'),('layers','legend'),('legend','zoom'),('summary','layers')]:
                    x,y=boxes[a],boxes[b]
                    assert x['x']+x['width']<=y['x'] or y['x']+y['width']<=x['x'] or x['y']+x['height']<=y['y'] or y['y']+y['height']<=x['y'],(a,b,x,y)
                print('viewport and overlay spacing OK',width,height,flush=True)
            page.set_viewport_size({'width':1440,'height':900})
            generation=evaluate('(map.__generation=crypto.randomUUID())')
            for metric in evaluate('Object.keys(map.weather.data.layers)'):
                frame.locator('#weather-layer').select_option(metric)
                assert evaluate('map.weather.metric')==metric
                spec=evaluate('map.weather.data.layers[map.weather.metric]')
                expect(frame.locator('.legend-title')).to_contain_text(spec['title'])
                expect(frame.locator('.legend-title')).to_contain_text(spec['unit'])
                for zoom,kind in [(7.5,'county'),(8,'county'),(8.5,'district'),(10,'district'),(10.5,'district'),(12,'district'),(14,'district')]:
                    evaluate('map.setView([25.04,121.52],'+str(zoom)+',{animate:false})');page.wait_for_timeout(80)
                    assert evaluate('map.weather.level()')==kind
                    active=evaluate('Object.entries(map.weather.groups).filter(([k,g])=>map.hasLayer(g)).map(([k])=>k)')
                    assert active==[kind],active
                    values=evaluate('map.weather.groups.'+kind+'.getLayers().map(m=>m.getTooltip().getContent())')
                    assert values and all(spec['unit'] in value for value in values)
                assert evaluate('map.__generation')==generation,'Layer change reloaded map'
                print('metric, legend, all zoom thresholds OK',metric,flush=True)
            for key in ['stations','county','district']:frame.locator('#overlay-'+key).check()
            assert evaluate('Object.values(map.weather.overlays).every(Boolean)')
            assert evaluate('map.hasLayer(map.weather.locations)&&map.hasLayer(map.weather.boundaryLayers.county)&&map.hasLayer(map.weather.boundaryLayers.district)')
            for zoom in [7.5,9,12]:
                evaluate('map.setZoom('+str(zoom)+',{animate:false})')
                assert evaluate('map.hasLayer(map.weather.boundaryLayers.county)&&map.hasLayer(map.weather.boundaryLayers.district)')
            evaluate('map.setView([23.75,120.95],7.5,{animate:false})')
            for key in evaluate('Object.keys(map.weather.data.layers)'):
                frame.locator('#weather-layer').select_option(key)
                assert evaluate("map.weather.boundaryLayers.county.getLayers().some(layer=>layer.options.fillOpacity>0)")
                assert evaluate("map.weather.boundaryLayers.district.getLayers().every(layer=>layer.options.fillOpacity===0)")
            for key in ['stations','county','district']:frame.locator('#overlay-'+key).uncheck()
            print('independent overlays preserve zoom-based rendering OK',flush=True)
            frame.locator('#weather-layer').select_option('temp')
            summary=frame.locator('.weather-summary-body').inner_text()
            valid=[s for s in stations if s['temp'] is not None]
            for station in [max(valid,key=lambda x:x['temp']),min(valid,key=lambda x:x['temp'])]:
                assert f"{station['temp']:.1f}" in summary and station['stationName'] in summary
            assert '示範' not in summary
            print('summary extrema and place names match actual CWA payload OK',flush=True)
            search=frame.locator('#weather-search')
            for query,kind in [('台北','county'),('淡','district')]:
                search.fill(query)
                label={'county':'縣市','district':'行政區'}[kind]
                frame.locator('[role="option"]').filter(has_text='｜'+label).first.click()
                assert evaluate('map.weather.level()')==kind
            for query in ['淡水','西屯','信義']:
                search.fill(query)
                results=evaluate('map.weather.search('+repr(query)+').map(item=>item.kind)')
                assert results and results[0]=='district',results
                frame.locator('[role="option"]').filter(has_text='｜行政區').first.click()
                expect(frame.locator('.station-popup h3')).to_have_count(1)
                expect(frame.locator('.station-popup h3')).to_contain_text(query)
                expect(frame.locator('.station-popup')).to_be_visible()
            search.fill('淡水')
            frame.locator('[role="option"]').filter(has_text='｜行政區').first.click()
            expect(frame.locator('.station-popup h3')).to_have_count(1)
            expect(frame.locator('.station-popup h3')).to_have_text('淡水區')
            expect(frame.locator('.popup-sources>summary')).to_contain_text('資料來源')
            frame.locator('.popup-sources>summary').click()
            expect(frame.locator('.source-list')).to_contain_text('觀測')
            region=evaluate("map.weather.data.datasets.temp.district.find(item=>item.county==='新北市'&&item.name==='淡水區')")
            assert region and region['station_ids']
            matched=[station for station in stations if station['id'] in region['station_ids']]
            for key,value in region['values'].items():
                readings=[station[key] for station in matched if station[key] is not None]
                assert abs(value-sum(readings)/len(readings))<1e-8
                assert region['counts'][key]==len(readings)
            for zoom in [10,12,14]:
                evaluate('map.setView(['+str(region['lat'])+','+str(region['lon'])+'],'+str(zoom)+',{animate:false})')
                assert evaluate('map.weather.level()')=='district'
                titles=evaluate('map.weather.groups.district.getLayers().map(marker=>marker.options.title)')
                assert '淡水區' in titles
                assert all(title in {item['district'] for item in stations} for title in titles)
            print('District labels at medium/high zoom, prioritized district search, source readings and independent averages OK',flush=True)
            search.fill('淡')
            station_results=frame.locator('[role="option"]').filter(has_text='｜測站')
            if station_results.count():station_results.first.click()
            else:
                search.fill(valid[0]['stationName']);frame.locator('[role="option"]').filter(has_text='｜測站').first.click()
            expect(frame.locator('.station-popup')).to_have_count(1)
            expect(frame.locator('.station-popup')).to_be_visible(timeout=10000)
            assert evaluate('map.weather.level()')=='district'
            selected_name=search.input_value()
            search.fill(selected_name);frame.locator('[role="option"]').filter(has_text='｜測站').first.click()
            expect(frame.locator('.station-popup')).to_have_count(1)
            expect(frame.locator('.station-popup')).to_be_visible()
            frame.locator('.station-popup summary').click();expect(frame.locator('.station-popup')).to_contain_text('觀測')
            search.fill('不存在XYZ');expect(frame.locator('.search-empty')).to_be_visible()
            search.fill('台北');search.press('ArrowDown');search.press('Enter')
            assert search.get_attribute('aria-expanded')=='false'
            print('Chinese partial search, Taiwan name normalization, location, station popup, keyboard and no-results OK',flush=True)
            frame.locator('.weather-options>summary').click()
            frame.locator('#weather-theme').select_option('street');assert 'weather-dark' not in frame.locator('.folium-map').get_attribute('class')
            frame.locator('#weather-theme').select_option('dark')
            frame.locator('#weather-labels').uncheck();assert 'weather-hide-labels' in frame.locator('.folium-map').get_attribute('class')
            frame.locator('#weather-labels').check()
            frame.locator('#weather-layer').select_option('humid');evaluate('map.setZoom(10,{animate:false})')
            page.get_by_role('button',name='⚙ 資料與設定').click();page.get_by_role('dialog').wait_for()
            page.get_by_role('tab',name='測站資料').click();page.get_by_role('button',name='下載測站 CSV').wait_for()
            page.get_by_role('tab',name='預報趨勢').click();page.locator('[data-testid="stPlotlyChart"]').wait_for()
            page.get_by_role('tab',name='資料同步').click();page.get_by_role('button',name='套用並回到地圖').click()
            frame.locator('.weather-controls').wait_for();page.wait_for_timeout(600)
            assert evaluate('map.weather.metric')=='humid' and evaluate('map.getZoom()')==10
            print('settings, real forecast, CSV, labels/theme, metric and view persistence OK',flush=True)
            frame.locator('#weather-layer').select_option('temp');frame.locator('#search-clear').click()
            evaluate('map.setView([23.75,120.95],7.5,{animate:false})')
            page.get_by_role('button',name='⚙ 資料與設定').evaluate('(el)=>el.blur()');page.mouse.move(700,700);page.wait_for_timeout(500)
            assert not page.locator('[data-testid="stException"]').count()
            print('JS errors',errors,'console errors',console_errors,flush=True)
            assert not errors and not console_errors
        finally:
            page.screenshot(path=str(work/'empty.png' if empty_mode else root/'assets'/'map-first-preview.png'))
            browser.close()
finally:
    proc.terminate();proc.wait(timeout=15);log.close()
