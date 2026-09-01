-- Loci: connection bootstrap. Run on every connection before anything else.
--
-- DuckDB extensions are per-connection, not per-database: unlike PostGIS there
-- is no persistent CREATE EXTENSION. loci.db.connect() applies this file.

INSTALL spatial;
LOAD spatial;

-- H3 is a community extension. Provides h3_latlng_to_cell, h3_cell_to_boundary_wkt,
-- h3_h3_to_string (15-char cell ids), h3_grid_disk, etc.
INSTALL h3 FROM community;
LOAD h3;
