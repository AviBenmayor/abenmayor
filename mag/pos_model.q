/ ---- load ----
fills:  ("SPSSSSFFJSF"; enlist csv) 0: `:data/fills.csv
marks:  ("SDSF";        enlist csv) 0: `:data/marks.csv
quotes: ("SSSJS";       enlist csv) 0: `:data/quotes.csv

/ venue-level collateral — different grain (venue x day), deliberately NOT joined into the position model
venue_cash: ("SDSFFF"; enlist csv) 0: `:data/venue_cash.csv

/ latest mark per position: sort by date, take last per fill
lm: select current_mark: last mark_value, mark_as_of: last as_of
    by fill_id from `as_of xasc marks

/ quotes keyed on fill_id, unfilled quotes dropped
/ (verified 1:1 on this dataset — no fill_id is quoted more than once)
qk: select theoretical_hold_bps by fill_id from quotes where not null fill_id

/ unified position model: fills is the table the additional values join on to
pos: fills lj qk lj lm

pos: update
  realized_pnl:   ?[status in `WON`LOST`VOID; settle_value - mag_stake; 0n],
  unrealized_pnl: ?[status = `OPEN; current_mark - mag_stake; 0n]
  from pos

pos: update
  realized_hold_bps: ?[status in `WON`LOST; 1e4 * realized_pnl % mag_stake; 0n]
  from pos
