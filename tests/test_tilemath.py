"""Unit tests for the pure Web-Mercator tile math (no QGIS/GDAL needed).

Run from the repo root:  pytest
"""
from aoi_downloader import tilemath as tm


def test_resolution_halves_each_zoom():
    assert tm.tile_resolution_m(1) == tm.tile_resolution_m(0) / 2
    assert tm.tile_resolution_m(10) == tm.tile_resolution_m(9) / 2


def test_resolution_matches_formula():
    for z in (0, 5, 18, 22):
        assert tm.tile_resolution_m(z) == (2.0 * tm.WM_ORIGIN) / (2 ** z) / tm.TILE_PIXELS


def test_zoom18_resolution_approx():
    # Classic ~0.597 m/px at zoom 18 (equator).
    assert abs(tm.tile_resolution_m(18) - 0.5971642835) < 1e-6


def test_tile_bounds_z0_covers_world():
    ulx, uly, lrx, lry = tm.tile_bounds_3857(0, 0, 0)
    assert ulx == -tm.WM_ORIGIN
    assert uly == tm.WM_ORIGIN
    assert lrx == tm.WM_ORIGIN
    assert lry == -tm.WM_ORIGIN


def test_tile_bounds_z1_quadrants():
    # Upper-left tile (0,0)
    assert tm.tile_bounds_3857(0, 0, 1) == (-tm.WM_ORIGIN, tm.WM_ORIGIN, 0.0, 0.0)
    # Lower-right tile (1,1)
    assert tm.tile_bounds_3857(1, 1, 1) == (0.0, 0.0, tm.WM_ORIGIN, -tm.WM_ORIGIN)


def test_xyz_url_basic():
    assert tm.xyz_url("https://s/{z}/{x}/{y}.png", 3, 5, 7) == "https://s/7/3/5.png"


def test_xyz_url_tms_flip():
    # zoom 2 -> n=4; {-y} for y=1 is 4-1-1 = 2
    assert tm.xyz_url("https://s/{z}/{x}/{-y}", 0, 1, 2) == "https://s/2/0/2"


def test_tile_range_center_maps_back():
    # The centre of a known tile must resolve back to exactly that tile.
    z, x, y = 12, 2200, 1500
    ulx, uly, lrx, lry = tm.tile_bounds_3857(x, y, z)
    cx, cy = (ulx + lrx) / 2, (uly + lry) / 2
    assert tm.tile_range(cx, cy, cx, cy, z) == (x, x, y, y)


def test_tile_range_spans_multiple_tiles():
    z = 10
    # A bbox spanning tiles (100..102) x (200..201)
    ulx0, uly0, _, _ = tm.tile_bounds_3857(100, 200, z)
    _, _, lrx1, lry1 = tm.tile_bounds_3857(102, 201, z)
    xmin, xmax, ymin, ymax = tm.tile_range(ulx0 + 1, lry1 + 1, lrx1 - 1, uly0 - 1, z)
    assert (xmin, xmax, ymin, ymax) == (100, 102, 200, 201)


def test_tile_range_clamped_to_grid():
    z = 3
    xmin, xmax, ymin, ymax = tm.tile_range(-9e7, -9e7, 9e7, 9e7, z)
    assert (xmin, ymin) == (0, 0)
    assert (xmax, ymax) == (2 ** z - 1, 2 ** z - 1)
