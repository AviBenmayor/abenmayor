# Data-sharing ask to NYC DOT: traffic-camera research use and VivaCity sensor data

*Draft for the owner to send, 2026-09-17. Two asks in one letter because they go to the
same office and rest on the same argument: Loci needs a small number of aggregate
pedestrian-activity numbers at points DOT already instruments, and it wants to obtain them
on terms DOT sets rather than on terms it assumes. The VivaCity ask is the one already
ticketed (GTM-159, D86); the camera ask is new and exists because of the facts in the
scope memo of 2026-09-17 §1b.*

**Facts this letter relies on (from the memo and the project's own probes):**

- The NYCTMC camera feed (`https://webcams.nyctmc.org/api/cameras`, 969 cameras; 376 in
  Manhattan, 204 in Brooklyn) serves a still JPEG per request with no key, no Referer check
  and no published cadence (verified 2026-09-13). It is **not** on NYC Open Data and carries no
  published terms of use.
- DOT sent Traffic Cam Photobooth a cease-and-desist on 2024-11-06 for "unauthorized use of
  NYC traffic cameras" (https://www.404media.co/traffic-cam-photobooth-cease-and-desist).
- DOT's own page says staff "may reposition [cameras] to view traffic from varying directions"
  (https://www.nyc.gov/html/dot/html/motorist/atis.shtml); no bearing or field of view is
  published.
- What Loci wants from a frame is one integer: persons visible. The pipeline counts in
  memory and discards the image; no frame is retained, no face, plate or track is produced;
  rows are aggregate per camera per timestamp. The full weekly plan is one frame per camera
  every 10 minutes inside DOT's own three count windows (07–09, 12–14, 16–19), two weekdays a
  week: about 21,000 requests and 0.5 GB a week across Manhattan and Brooklyn, far below what
  the public map page itself generates.
- DOT's bi-annual pedestrian counts (114 screenlines, Open Data) are the yardstick the camera
  counts are validated against; the first validation round (N = 30 matched camera × window
  observations, weekday midday and PM, 15 co-located cameras) gives a Spearman rank
  correlation of +0.42 against people per counted hour. Nothing derived from the cameras
  enters any published score; it is context on a site card.
- VivaCity sensors: DOT announced ~100 sites including residential blocks (2026-06-04). Those
  are exactly the non-corridor points the project's foot-traffic validation lacks — the
  bi-annual counts sit on arterials, and 83% of Manhattan + Brooklyn addresses have no camera
  within 250 m.

---

**To:** NYC Department of Transportation — Traffic Management Center / Office of Research,
Implementation & Safety; cc: Office of Technology & Innovation (Open Data)

**From:** Avi Benmayor, Loci (independent research project on neighborhood retail supply,
Manhattan and Brooklyn)

**Subject:** Request for (1) research-use terms for the public traffic-camera stills at a
weekly cadence with aggregate-only retention, and (2) access to VivaCity pedestrian sensor
data

Dear colleagues,

I am writing to ask for two things, and to describe exactly what I would do with each so that
you can say yes, no, or "yes with conditions" from a position of knowing.

**1. Traffic-camera stills, research use, aggregate-only.**

Loci is a non-commercial research project that screens Manhattan and Brooklyn addresses for
missing daily-needs retail (grocery, pharmacy, laundry, childcare and the like). One thing
the project cannot get from any open dataset is *relative sidewalk activity by time of day*
at a fixed point. Your bi-annual pedestrian counts (which I already use, with thanks) give
that twice a year at 114 screenlines. Your public camera feed could give it weekly.

What I would do, if you permit it:

- Fetch one still per camera every 10 minutes inside your three count windows (07:00–09:00,
  12:00–14:00, 16:00–19:00) on two weekdays a week, for the Manhattan and Brooklyn cameras
  (580). That is about 21,000 requests and roughly 0.5 GB a week — less than a handful of
  users leaving the public map page open.
- Run a local person detector on each frame **in memory**, store the integer count (and the
  vehicle counts the same model produces for free), and discard the image. No frame is
  retained. No face, licence plate or track is ever produced or stored. The stored row is
  `camera, timestamp, count`.
- Use the counts only to compare a camera with its own history by time of day. I do not
  compare cameras with each other (the field of view is unpublished and can change), do not
  convert counts to pedestrians per hour, and publish nothing derived from them as a score.
  Each camera's frames are hashed so that a re-aimed camera is flagged and its history reset
  rather than silently compared.
- Identify the requests with a fixed User-Agent (`loci-sidewalk-count`) and a contact address,
  honour any rate or window you set, and stop on request.

I am aware that the feed is not on Open Data, that it carries no published terms, and that DOT
has previously objected to unauthorised uses of the cameras. I would rather have terms than
assume them. If a research licence, an MOU, or a simple written acknowledgement with
conditions is the right instrument, I will sign it. If the answer is no, I will stop sampling
the feed and rely on the bi-annual counts alone.

**2. VivaCity sensor data.**

DOT's VivaCity deployment (~100 sites, including residential blocks) measures the thing the
bi-annual counts and the cameras structurally cannot: pedestrian volume off the arterials.
For the project's validation I need only hourly (or coarser) pedestrian totals per sensor,
with the sensor location and installation date — no video, no classifications beyond
pedestrian/cyclist if those are what the sensors emit. Historical data from installation to
date, and a monthly refresh if that is practical, would let me test whether an address-level
foot-traffic proxy built from open data holds up on residential blocks, and publish that
test either way.

I would accept the data under a research agreement with attribution to DOT, no
redistribution of the raw series, and any embargo you need; I would share the validation
write-up with your office before publishing it.

**What you get.** A written, reproducible validation of your own instruments against each
other (camera stills vs. screenline counts vs. VivaCity), the code for the count pipeline
(open source, no images retained), and a standing offer to run any count or comparison your
office would find useful on the same infrastructure.

I am happy to meet, to demonstrate the pipeline, or to adjust any of the above. Thank you for
the counts programme and for maintaining the feed; both are more useful to the city's small
businesses than they may appear from inside.

With thanks,

Avi Benmayor
Loci — avibenmayor@gmail.com

---

*Attachments the owner can add: the memo's coverage table (§1d), the validation report
(`loci sidewalk-count validate --round 2026-05`), and the sampler module docstring
(`src/loci/model/sidewalk_count.py`), which records the legal exposure and the privacy rule
verbatim.*
