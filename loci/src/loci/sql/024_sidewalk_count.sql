-- ---------------------------------------------------------------------------
-- 024_sidewalk_count.sql -- analysis.sidewalk_count: PERSONS VISIBLE IN ONE
-- FRAME of a public NYC DOT traffic camera, one row per frame.
--
-- Owner request 2026-09-13: "we need NYC DOT data, both the bi-annual and the
-- camera data." The bi-annual hand counts (staging.dot_pedestrian_count) are
-- the yardstick -- 114 screenlines, two hours, three windows, twice a year.
-- The cameras are the other half: 969 public still-image feeds that refresh
-- every few seconds, everywhere, all day. This table is what the cameras
-- produce.
--
-- Numbered 024 rather than 022: the concurrent DOT-registry work takes 022 and
-- 023 (staging.dot_camera, staging.dot_pedestrian_count). init_schema() globs
-- and sorts, so a gap costs nothing and a collision would cost a migration.
--
-- ---------------------------------------------------------------------------
-- WHAT A ROW IS -- AND THE ONE SENTENCE THAT MUST TRAVEL WITH EVERY NUMBER
-- ---------------------------------------------------------------------------
-- `n_persons` is the number of people a COCO person detector found in ONE
-- 352x240 JPEG. It is a STOCK (people standing in a cone of view at an
-- instant), not a FLOW (people crossing a line per hour). The DOT bi-annual
-- count is a FLOW. They are different physical quantities and Little's law is
-- the only bridge between them -- stock = flow x dwell -- and nothing here
-- measures dwell. So `loci sidewalk-count validate` reports a RANK
-- correlation and refuses to report a ratio or a calibration factor.
--
-- ---------------------------------------------------------------------------
-- WHY FRAMES ARE NOT STORED
-- ---------------------------------------------------------------------------
-- The imagery is public and the counts are aggregate, but a stored frame is a
-- photograph of identifiable people on a public street, kept by us. Nothing
-- downstream needs the pixels: the count, the confidence-50 count and the
-- frame hash are enough to reproduce every statement this project will make.
-- `--keep-frames` writes to data/frames/<camera>/ for QA only, that path is
-- gitignored, and no column here points at it.
--
-- `frame_hash` is the sha256 of the JPEG BYTES. It is the deduplication key:
-- the feed serves the last decoded still, so two fetches four seconds apart
-- often return the identical file, and counting it twice would inflate a
-- camera's mean by exactly the duplicate rate. Hashing the bytes (not the
-- decoded pixels) is deliberate -- a re-encode of the same scene is a new
-- image to the camera and we have no way to tell it from a real refresh.
--
-- ---------------------------------------------------------------------------
-- day_type x daypart ARE NOT DERIVED IN SQL
-- ---------------------------------------------------------------------------
-- They are written by the sampler from
-- sources/cities/nyc/mta_ridership.daypart_of / day_type_of -- the SAME five
-- boundaries the D76 transit profile uses (early 0-6, am_peak 6-10, midday
-- 10-15, pm_peak 15-19, evening 19-24). Recomputing them here with a CASE on
-- EXTRACT(hour ...) would be a second definition of the project's dayparts
-- waiting to drift from the first, which is the mistake 021's header calls
-- out. They are stored, not computed on read, because `sampled_at` is stored
-- in UTC and the daypart is a question about the LOCAL clock.
--
-- NOT A SCORE INPUT. Like its parent D76 layer, nothing here enters
-- gap_score, supply_ratio_vs_base or any recommendation grade. It is card
-- context and an external check, until a validation says otherwise.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS analysis;

CREATE TABLE IF NOT EXISTS analysis.sidewalk_count (
    camera_id         VARCHAR NOT NULL,   -- staging.dot_camera.camera_id
    sampled_at        TIMESTAMP NOT NULL, -- UTC, when the fetch RETURNED
    n_persons         INTEGER NOT NULL,   -- boxes at confidence >= 0.25
    n_persons_conf50  INTEGER NOT NULL,   -- boxes at confidence >= 0.50
    model             VARCHAR NOT NULL,   -- 'yolo11n' | 'hog_opencv'
    model_version     VARCHAR NOT NULL,   -- first 12 hex of the weights' sha256
    frame_hash        VARCHAR NOT NULL,   -- sha256 of the JPEG bytes
    daypart           VARCHAR NOT NULL,   -- early|am_peak|midday|pm_peak|evening
    day_type          VARCHAR NOT NULL,   -- weekday|saturday|sunday
    PRIMARY KEY (camera_id, frame_hash, model, model_version)
);

-- The PK is (camera, frame, model, version), NOT (camera, sampled_at): the
-- duplicate a run must not double-count is the same BYTES arriving twice, and
-- two runs on different days that happen to fetch a byte-identical still are
-- the same observation of the same instant too. `model` and `model_version`
-- are in the key so re-scoring the archive with a better detector is an INSERT
-- rather than a destructive overwrite -- and so counts from two graphs can
-- never be silently pooled, because they are different rows.

CREATE INDEX IF NOT EXISTS sidewalk_count_camera_time
    ON analysis.sidewalk_count (camera_id, sampled_at);
