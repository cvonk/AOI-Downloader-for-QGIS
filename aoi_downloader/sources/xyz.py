# -*- coding: utf-8 -*-
"""XYZ source backend for the AOI Downloader ({z}/{x}/{y} in Web Mercator)."""

import urllib.parse

from qgis.core import (
    QgsProject, QgsRectangle, QgsGeometry, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsRasterLayer, QgsDataSourceUri,
)

from .. import engine
from ..engine import DownloaderError, TileFetchError
# Pure Web-Mercator math (QGIS-free, unit-tested in tests/test_tilemath.py).
# tile_resolution_m is re-exported here so callers can use xyz.tile_resolution_m.
from ..tilemath import (
    tile_resolution_m, tile_bounds_3857, xyz_url, tile_range,
)

SOURCE_NAME = "XYZ"
INITIAL_DELAY_SEC = 0.25       # tile servers usually tolerate a faster start

WEBMERC = "EPSG:3857"


# ─────────────────────────────────────────────
# DETECTION / PARAMS
# ─────────────────────────────────────────────
def detect(layer):
    if not isinstance(layer, QgsRasterLayer) or layer.providerType() != "wms":
        return False
    uri = QgsDataSourceUri(); uri.setEncodedUri(layer.source())
    return (uri.param("type") or "").lower() == "xyz"


def extract_params(layer):
    uri = QgsDataSourceUri(); uri.setEncodedUri(layer.source())
    template = urllib.parse.unquote((uri.param("url") or "").strip())
    if not template or "{z}" not in template:
        raise DownloaderError(
            "Could not extract a {z}/{x}/{y} URL template from the XYZ layer source.")

    def _int(v, default):
        try: return int(v)
        except (TypeError, ValueError): return default
    return {"template": template,
            "zmin": _int(uri.param("zmin"), 0),
            "zmax": _int(uri.param("zmax"), 22)}


def native_crs(params, opts):
    return WEBMERC

def default_out_crs(params):
    return WEBMERC

def fingerprint_parts(params, opts):
    return [params["template"], opts.get("zoom")]


# ─────────────────────────────────────────────
# TILE GRID
# ─────────────────────────────────────────────
def build_tile_grid(aoi_layer, params, opts, logger):
    zoom = int(opts.get("zoom", 18))
    web  = QgsCoordinateReferenceSystem(WEBMERC)
    ctx  = QgsProject.instance().transformContext()
    aoi_crs = aoi_layer.crs()
    xform = None if aoi_crs == web else QgsCoordinateTransform(aoi_crs, web, ctx)

    geoms = []
    for feat in aoi_layer.getFeatures():
        g = QgsGeometry(feat.geometry())
        if g.isNull() or g.isEmpty():
            continue
        if xform and g.transform(xform) != 0:
            logger.warning("Could not reproject feature id=%s; skipping.", feat.id())
            continue
        geoms.append(g)
    if not geoms:
        raise DownloaderError("AOI layer has no usable polygon geometries.")

    union = QgsGeometry.unaryUnion(geoms)
    bb    = union.boundingBox()
    xmin, xmax, ymin, ymax = tile_range(
        bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum(), zoom)

    logger.info("AOI bbox (EPSG:3857): %s", bb.toString())
    logger.info("Zoom %d → %.3f m/px; tiles x[%d..%d] y[%d..%d]",
                zoom, tile_resolution_m(zoom), xmin, xmax, ymin, ymax)

    tiles, tid = [], 0
    for ty in range(ymin, ymax + 1):
        for tx in range(xmin, xmax + 1):
            ulx, uly, lrx, lry = tile_bounds_3857(tx, ty, zoom)
            if QgsGeometry.fromRect(QgsRectangle(ulx, lry, lrx, uly)).intersects(union):
                tiles.append({"id": tid, "z": zoom, "x": tx, "y": ty})
                tid += 1

    logger.info("Kept %d tiles intersecting the AOI.", len(tiles))
    if not tiles:
        raise DownloaderError("No tiles intersect the AOI polygon.")
    return tiles


# ─────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────
def fetch_one_tile(params, opts, tile, out_path, logger):
    url = xyz_url(params["template"], tile["x"], tile["y"], tile["z"])
    logger.debug("GET tile %d (z%d/%d/%d): %s",
                 tile["id"], tile["z"], tile["x"], tile["y"], url)
    if tile["id"] == 0:
        logger.info("FIRST TILE URL (paste into a browser to verify): %s", url)

    status, headers, body, err, timed_out = engine.blocking_get(url)
    if timed_out:
        raise TileFetchError("Request timed out.")
    if err and status not in (404, 204):
        raise TileFetchError(f"Network error: {err}")
    if status in (404, 204) or not body:
        return None                       # missing tile → legitimate gap
    if status in (429, 403):
        # Some tile servers use 403 to signal rate-limiting / over-use, so treat
        # it as a throttle: back off and retry. A genuinely forbidden resource
        # still fails once the per-tile attempt cap is reached.
        raise TileFetchError(f"HTTP {status} (rate-limited?).",
                             retry_after=engine.parse_retry_after(headers.get("retry-after")),
                             is_throttle=True)
    if status in (500, 503):
        raise TileFetchError(f"HTTP {status}.",
                             retry_after=engine.parse_retry_after(headers.get("retry-after")),
                             is_throttle=True)
    if status and status >= 400:
        raise TileFetchError(f"HTTP {status}.")

    bounds  = tile_bounds_3857(tile["x"], tile["y"], tile["z"])
    problem = engine.georeference(body, out_path, bounds, WEBMERC)
    if problem:
        raise TileFetchError(problem)
    return out_path
