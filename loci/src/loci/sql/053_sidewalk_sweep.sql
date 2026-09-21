-- ---------------------------------------------------------------------------
-- 053_sidewalk_sweep.sql -- the WEEKLY SWEEP extension of analysis.sidewalk_count
-- (scope memo 2026-09-17 §1, owner rulings the same day).
--
-- Two additions, both at the EXISTING grain (camera x frame x model x version):
--
--   1. THE FREE EXTRA CLASSES. YOLO11n scores every COCO class in the same
--      forward pass, so car / truck / bus / bicycle counts cost nothing
--      (memo §1c). They are stored as four more INTEGER columns and are
--      validated against NOTHING -- DOT hand-counts pedestrians only -- so
--      they are context, never a measure. NULL on rows written before this
--      migration (the detector then read one class), never back-filled to 0.
--
--   2. THE SCENE HASH. DOT staff "may reposition [cameras] to view traffic
--      from varying directions" (memo §1a, atis.shtml) and announce nothing.
--      A camera compared with its own history after a re-aim is a different
--      instrument wearing the same id. So every sweep computes a perceptual
--      hash of the camera's MEAN frame over the run (the static background,
--      people averaged out), stores it on each row as `scene_hash`, and sets
--      `scene_changed` TRUE when its Hamming distance to the camera's
--      previous run exceeds SCENE_CHANGE_BITS. The report reads the flag and
--      refuses to draw a "vs own history" comparison across it. It is a
--      dHash (64 bit) of the mean frame, NOT a hash of bytes: `frame_hash`
--      answers "same file?", `scene_hash` answers "same view?".
--
-- `run_id` groups the rows of one sweep window (one launchd invocation) so a
-- scene hash is a property of a run rather than of a frame.
--
-- ALTER ... ADD COLUMN IF NOT EXISTS is idempotent, which init_schema's replay
-- needs; the INSERT in sidewalk_count.write_rows names its columns on both
-- sides (tests/test_no_positional_inserts.py), so the column ORDER a
-- CREATE-then-ALTER produces is not load-bearing.
--
-- PRIVACY RULE (memo §1e, verbatim): persons are counted in memory and never
-- stored; no frame is kept without `--keep-frames` (QA-only, gitignored,
-- local); no face, plate or track is ever produced; rows are aggregate per
-- camera x timestamp. Nothing in this migration stores pixels.
-- ---------------------------------------------------------------------------

ALTER TABLE analysis.sidewalk_count ADD COLUMN IF NOT EXISTS n_car     INTEGER;
ALTER TABLE analysis.sidewalk_count ADD COLUMN IF NOT EXISTS n_truck   INTEGER;
ALTER TABLE analysis.sidewalk_count ADD COLUMN IF NOT EXISTS n_bus     INTEGER;
ALTER TABLE analysis.sidewalk_count ADD COLUMN IF NOT EXISTS n_bicycle INTEGER;
ALTER TABLE analysis.sidewalk_count ADD COLUMN IF NOT EXISTS run_id        VARCHAR;
ALTER TABLE analysis.sidewalk_count ADD COLUMN IF NOT EXISTS scene_hash    VARCHAR;  -- 16 hex, dHash of the run's mean frame
ALTER TABLE analysis.sidewalk_count ADD COLUMN IF NOT EXISTS scene_changed BOOLEAN;  -- Hamming(prev run) > SCENE_CHANGE_BITS
