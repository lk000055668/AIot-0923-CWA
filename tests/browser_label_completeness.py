"""Compare saved pre-fix HTML against the actual Streamlit app on one CWA snapshot.

Run after saving data/label-audit/observations.json and before.html.
Requires development-only Playwright and Microsoft Edge.
"""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "data" / "label-audit"
EXPR = "Object.values(window).find(v=>v instanceof L.Map)"


def run():
    # Only freeze the input and disable synchronization; run the real app/UI.
    wrapper = WORK / "snapshot_app.py"
    wrapper.write_text(
        "import sys,runpy\n"
        f"sys.path.insert(0,{str(ROOT)!r})\n"
        "import cwa_api,database,pandas as pd\n"
        "cwa_api.get_api_key=lambda:None\n"
        f"database.get_station_observations=lambda:pd.read_json({str(WORK/'observations.json')!r})\n"
        f"runpy.run_path({str(ROOT/'app.py')!r},run_name='__main__')\n", encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    report = {"before": {}, "after": {}, "checks": []}
    with (WORK / "server.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(wrapper),
                                 "--server.port", str(port), "--server.headless", "true",
                                 "--browser.gatherUsageStats", "false"], cwd=ROOT, stdout=log, stderr=log,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.goto((WORK / "before.html").as_uri())
                page.wait_for_function(f"typeof L !== 'undefined' && {EXPR}?.weather")
                for kind, zoom in [("county", 7.5), ("district", 9)]:
                    page.evaluate(f"()=>{{const map={EXPR};map.setView([23.75,120.95],{zoom},{{animate:false}});}}")
                    report["before"][kind] = page.evaluate(f"""()=>{{
                      const map={EXPR},kind='{kind}',items=map.weather.data.datasets.temp[kind];
                      const markers=map.weather.groups[kind].getLayers();
                      const trace=items.map(item=>{{const marker=markers.find(m=>m.options.title===item.name&&m.getLatLng().equals([item.lat,item.lon]));
                        return {{id:item.id,county:item.county,name:item.name,value:item.value,station_count:item.station_count,
                          geometry:true,label_position:[item.lat,item.lon],marker_created:!!marker,added_to_layer:!!marker,
                          rendered:!!marker&&map.hasLayer(marker)&&!!marker.getElement()?.isConnected}};}});
                      return {{PAYLOAD_ITEMS:items.length,MARKERS_CREATED:markers.length,
                        MARKERS_RENDERED:trace.filter(t=>t.rendered).length,TRACE:trace}};
                    }}""")
                for attempt in range(60):
                    try:
                        page.goto(f"http://localhost:{port}", wait_until="domcontentloaded")
                        break
                    except Exception:
                        time.sleep(.25)
                frame_locator = page.frame_locator(".st-key-weather_map iframe")
                frame_locator.locator(".weather-controls").wait_for(timeout=120000)
                frame = page.locator(".st-key-weather_map iframe").element_handle().content_frame()

                def evaluate(expression):
                    return frame.evaluate(f"()=>{{const map={EXPR};return ({expression});}}")

                def check(label):
                    debug = evaluate("map.weather.debug()")
                    assert debug["WITH_VALID_DATA"] == debug["MARKERS_CREATED"] == debug["MARKERS_RENDERED"], debug
                    assert not debug["MISSING"]
                    assert evaluate("Object.entries(map.weather.groups).filter(([k,g])=>map.hasLayer(g)).length") == 1
                    assert frame_locator.locator(".weather-label").count() == debug["WITH_VALID_DATA"]
                    report["checks"].append({"label": label, **{k:v for k,v in debug.items() if k not in ("TRACE", "NO_DATA")}})
                    return debug

                report["after"]["county"] = check("initial Taiwan")
                for cycle in range(5):
                    for zoom in (9, 7.5):
                        evaluate(f"(map.setZoom({zoom},{{animate:false}}),null)")
                        check(f"cycle {cycle+1} zoom {zoom}")
                evaluate("(map.setZoom(9,{animate:false}),null)")
                report["after"]["district"] = check("all districts")
                for center in ([25.04,121.52], [22.63,120.3], [24.44,118.37]):
                    evaluate(f"(map.panTo({center},{{animate:false}}),null)")
                    check(f"pan {center}")
                for metric in evaluate("Object.keys(map.weather.data.layers)"):
                    frame_locator.locator("#weather-layer").select_option(metric)
                    for zoom in (7.5, 8, 8.5, 10, 12, 14):
                        evaluate(f"(map.setZoom({zoom},{{animate:false}}),null)")
                        check(f"metric {metric} zoom {zoom}")
                frame_locator.locator("#weather-layer").select_option("temp")
                for key in ("stations", "county", "district"):
                    frame_locator.locator(f"#overlay-{key}").check()
                    check(f"overlay {key}")
                    frame_locator.locator(f"#overlay-{key}").uncheck()
                for query in ("台北", "西屯", "信義", "淡水"):
                    search = frame_locator.locator("#weather-search")
                    search.fill(query)
                    frame_locator.locator('[role="option"]').first.click()
                    expect(frame_locator.locator(".station-popup")).to_have_count(1)
                    expect(frame_locator.locator(".station-popup")).to_be_visible()
                    check(f"search/popup {query}")
                evaluate("(map.closePopup(),map.setView([23.75,120.95],7.5,{animate:false}),null)")
                check("final Taiwan")
                expect(frame_locator.locator(".station-popup")).to_have_count(0)
                page.wait_for_timeout(400)
                page.screenshot(path=str(WORK / "after.png"))
                report["errors"] = errors
                assert not errors, errors
                browser.close()
        finally:
            proc.terminate()
            proc.wait(timeout=15)
            (WORK / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"before": {k: {a:b for a,b in v.items() if a != "TRACE"} for k,v in report["before"].items()},
                      "after": {k: {a:b for a,b in v.items() if a not in ("TRACE", "NO_DATA")} for k,v in report["after"].items()},
                      "checks": len(report["checks"]), "errors": report["errors"]}))


if __name__ == "__main__":
    run()
