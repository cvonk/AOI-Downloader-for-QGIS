# Present so pytest adds the repo root to sys.path, making `import aoi_downloader`
# work. aoi_downloader/__init__.py imports nothing at module load (classFactory
# imports QGIS lazily), and aoi_downloader/tilemath.py is pure Python, so the
# tilemath tests run without a QGIS install.
