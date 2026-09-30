"""Coordinate-based station assignment, including holes and MultiPolygons.

No station-name heuristics. CWA's explicit county/town fields are retained as
an identified fallback when the bundled reference geometry cannot locate a point.
"""
from functools import lru_cache
from region_names import normalizeCountyName, normalizeDistrictName


def _ring_relation(x, y, ring):
    """Return 0 outside, 1 inside, 2 on an edge (coordinates are lon, lat)."""
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        ax, ay = a[:2]
        bx, by = b[:2]
        cross = (x-ax)*(by-ay) - (y-ay)*(bx-ax)
        if abs(cross) <= 1e-12 and min(ax,bx)-1e-12 <= x <= max(ax,bx)+1e-12 and min(ay,by)-1e-12 <= y <= max(ay,by)+1e-12:
            return 2
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
    return int(inside)


def _covers(x, y, polygon):
    if not polygon or not _ring_relation(x, y, polygon[0]):
        return False
    # Hole interiors are excluded; their edges still belong to the polygon.
    return not any(_ring_relation(x,y,hole) == 1 for hole in polygon[1:])


class DistrictIndex:
    def __init__(self, geojson):
        self.parts = []
        self.names = {}
        for feature in geojson.get("features", []):
            props, geometry = feature["properties"], feature.get("geometry") or {}
            pair = self.normalized((props["COUNTYNAME"], props.get("TOWNNAME", "")))
            self.names[self.normalized(pair)] = pair
            polygons = [geometry["coordinates"]] if geometry.get("type") == "Polygon" else geometry.get("coordinates", []) if geometry.get("type") == "MultiPolygon" else []
            for polygon in polygons:
                if not polygon or not polygon[0]:
                    continue
                xs, ys = zip(*(point[:2] for point in polygon[0]))
                self.parts.append(((min(xs),min(ys),max(xs),max(ys)),polygon,pair))

    @staticmethod
    def normalized(pair):
        return normalizeCountyName(pair[0]), normalizeDistrictName(pair[1])

    @lru_cache(maxsize=8192)
    def candidates(self, lon, lat):
        hits = set()
        for (left,bottom,right,top), polygon, pair in self.parts:
            if left-1e-12 <= lon <= right+1e-12 and bottom-1e-12 <= lat <= top+1e-12 and _covers(lon,lat,polygon):
                hits.add(pair)
        return tuple(sorted(hits))

    def locate(self, lon, lat, county="", district=""):
        hits = self.candidates(float(lon),float(lat))
        explicit = self.names.get(self.normalized((county,district)))
        if len(hits) == 1:
            return *hits[0], "polygon"
        if len(hits) > 1:
            if explicit in hits:
                return *explicit, "boundary_cwa"
            return "", "", "ambiguous"
        if explicit:
            return *explicit, "cwa_fallback"
        return "", "", "unmapped"

    @lru_cache(maxsize=1024)
    def label_point(self, county, district):
        """Find an interior label point on the largest island, not a hole."""
        parts = [part for part in self.parts if part[2] == (county,district)]
        for bounds, polygon, _ in sorted(parts, key=lambda part:(part[0][2]-part[0][0])*(part[0][3]-part[0][1]), reverse=True):
            y = (bounds[1]+bounds[3])/2
            intersections = []
            for ring in polygon:
                for a,b in zip(ring,ring[1:]+ring[:1]):
                    if (a[1]>y) != (b[1]>y):
                        intersections.append(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
            intersections.sort()
            spans = list(zip(intersections[::2],intersections[1::2]))
            if spans:
                left,right = max(spans,key=lambda span:span[1]-span[0])
                x = (left+right)/2
                if _covers(x,y,polygon):
                    return y,x
        return None


def assign_station_districts(df, index):
    result = df.copy()
    result["sourceCountyName"] = result["countyName"]
    result["sourceTownName"] = result["townName"]
    result["mappingMethod"] = ""
    for i, row in result.iterrows():
        county, district, method = index.locate(row["lon"],row["lat"],row["countyName"],row["townName"])
        result.loc[i, ["countyName","townName","mappingMethod"]] = [county,district,method]
    return result
