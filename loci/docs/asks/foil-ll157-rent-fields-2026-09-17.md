# FOIL draft to NYC Department of Finance: LL157 storefront rent and lease fields

*Draft for the owner to send; prepared 2026-09-17. Do not submit automatically. This is the
owner-ruling path from `docs/retail-space-search-market-2026-09-17.md`: FOIL only; no
tenant-facing listings product, vacancy-rent card line, or dossier is authorized by this ask.*

## Why file

Loci is an independent, address-level retail research tool for Manhattan and Brooklyn. The
Department of Finance (DOF) requires covered storefront owners to report a lease's start and
expiration/renewal dates, whether it contains scheduled rent increases, concessions, average
monthly rent per square foot, and activity type. Yet the public storefront dataset does not
carry the address-level rent and lease fields. A premises-grain release of the rent-per-square-foot
field is the one result that would reopen research on a tenant-side dossier; any lesser outcome
does not authorize that product.

## Verified legal and procedural facts

- **LL157 / Administrative Code §§11-3001 et seq.** Local Law 157 (2019) adds the ground-
  and second-floor commercial-premises registry. Its operative reporting rule requires lease
  dates, rent-escalation information, concessions, and average monthly rent per square foot.
  The law requires a public searchable address-and-vacancy dataset and a tract/council-district
  aggregate dataset, explicitly “notwithstanding subdivision f of section 11-208.1.” It does
  not plainly require publication of every reported lease field. [LL157 text](https://www.nyc.gov/assets/finance/downloads/pdf/19pdf/local-law-157.pdf)
- **Confidentiality risk.** The registry is filed with RPIE. A DOF procurement document says
  RPIE income-and-expense statements may not be disclosed to people not authorized by
  Administrative Code §11-208.1(f). That is the likeliest specific-statute denial; it is now
  evidence-backed rather than inferred, but this draft does not opine on its legal reach.
  [DOF confidentiality provision](https://www.nyc.gov/assets/finance/downloads/pdf/23pdf/83622b0003-debt-collection-services-ifb.pdf)
- **Int 0090-2026.** The Council's proposed *Storefront Business Bill of Rights* was heard and
  laid over on 2026-09-16; it is not enacted. It would require owners to give a prospective
  tenant two years of itemized operating-cost history and two years of expected costs, among
  other protections. It does **not** require public posting of asking or signed rent. This is
  useful context, not a basis for the request. [Council bill record and text](https://legistar.council.nyc.gov/LegislationDetail.aspx?GUID=C6FBEBDA-F7D4-49C1-B513-936830AC6AD4&ID=7861496)
- **FOIL mechanics.** Submit to DOF through [NYC OpenRecords](https://a856-openrecords.nyc.gov/)
  (select Department of Finance). Under FOIL, an agency normally grants, denies, or acknowledges
  a request within five business days; an acknowledgement should give a reasonable approximate
  date, generally no more than 20 business days. A final whole/partial denial may be appealed
  within 30 days. [NYC FOIL manual](https://www.nyc.gov/assets/actuary/downloads/pdf/FOILPolicy2025.pdf)
- **Electronic records.** FOIL covers electronically maintained records. The State's Committee
  on Open Government says an agency that can transfer data to the requested format should do so
  on payment of the lawful fee. [Committee guidance](https://opengovernment.ny.gov/your-right-know)

Accessed 2026-09-17. No located source identified a prior DOF OpenRecords/MuckRock request
that obtained the nonpublic LL157 lease fields; that absence is not evidence that none exists.

## Filing checklist

1. Sign in or create an NYC.ID account, open **Request a Record**, and choose **Department of
   Finance** at [NYC OpenRecords](https://a856-openrecords.nyc.gov/).
2. Paste the letter below as the record description. Use the subject line below. Include Avi's
   email and phone number so DOF can clarify scope.
3. Select electronic delivery. State that Avi agrees to be contacted before any charge above
   $100. Save the request number and acknowledgement.
4. Calendar five business days from submission. If DOF acknowledges but gives no date, use the
   portal's contact function. If it denies all or part, calendar the 30-day appeal deadline and
   preserve the cited exemption and any redaction log.
5. Do not broaden the request during a call. The fallback hierarchy below is intentional: it
   distinguishes an address-level release from a useful aggregate release.

## Letter to paste into NYC OpenRecords

**Subject:** FOIL request — LL157 storefront registry lease and rent fields, filing years 2020–2026

Dear Department of Finance Records Access Officer,

Pursuant to the New York Freedom of Information Law, I request existing electronic records
containing the following fields reported in the Ground Floor and Second Floor Commercial
Premises Registry (Administrative Code §11-3001 et seq.) for filing years 2020 through 2026:

1. premises identifier and location fields already used by the registry (including BBL, address,
   borough, and unit/premises identifier where maintained);
2. reporting/filing year and occupancy or vacancy status;
3. for tenant leases: lease start date; expiration or renewal date; whether scheduled rent
   increases are contained in the lease; the schedule of rent escalations where maintained;
   whether concessions were granted and the reported concession category/value where maintained;
   average monthly rent per square foot; and reported economic activity; and
4. for a previously leased but currently vacant or owner-occupied premises: the monthly rent per
   square foot paid by the most recent tenant, with the vacancy/owner-occupancy dates where
   maintained.

Please provide the existing record export or database extract in a machine-readable format such
as CSV, XLSX, JSON, or Parquet, with a data dictionary or field definitions if one exists. I do
not request that DOF create a new analysis or calculate new values. If responsive records are
maintained in separate annual tables, extracts by year are welcome.

Local Law 157 requires a public searchable registry and an aggregate open-data dataset despite
the RPIE filing relationship. I recognize that DOF may determine that some fields or identifiers
are exempt. If so, please release every reasonably segregable non-exempt portion, identify each
withheld field or record category, and state the specific statutory basis for each withholding.

If DOF cannot release the requested premises-level fields, please treat the following as ordered
fallbacks rather than deny the request in full:

1. average monthly rent-per-square-foot bands at BBL or census-tract grain, by filing year;
2. annual council-district or census-tract medians/averages of monthly rent per square foot,
   subject to the statutory minimum-cell rule, with counts of reported leases;
3. annual counts by census tract or NTA of reported scheduled-rent-increase and concession flags;
   and
4. any existing data dictionary, schema, publication policy, or determination explaining which
   LL157 fields are public and which are withheld.

Please contact me before incurring fees above $100. Electronic delivery through OpenRecords or
by download link is preferred.

Thank you,

Avi Benmayor
Loci
avibenmayor@gmail.com

## Anticipated denial and response

| Ground | Likelihood | Reply | Appeal-worthy? |
|---|---:|---|---|
| Administrative Code §11-208.1(f) / RPIE confidentiality | High for raw premises-level fields | Ask DOF to identify whether the requested registry extract is treated as an RPIE statement, then release segregable non-exempt fields or the ranked fallbacks. LL157 expressly makes the aggregate dataset public despite the RPIE connection. | Yes, for the legal interpretation and segregability; stop if a clear statutory bar applies to every requested premises field. |
| POL §87(2)(d), trade secret / competitive injury | Medium | Ask for field-specific reasoning, not a blanket assertion. A public asking rent is not necessarily a signed rent, but the request seeks records DOF holds; banded or aggregate output can reduce competitive injury. | Yes, if DOF gives only conclusory reasoning or declines all aggregation. |
| Privacy / tax-return information | Medium | Remove owner/tenant names and contacts; retain premises, date, and numerical fields only where lawful. | Yes, for de-identified or aggregate alternatives. |
| Burden, breadth, or unavailable format | Medium | Accept annual extracts and the narrowed fallbacks; no new analysis is requested. | Usually no; narrow first. |

## What Loci does with each outcome

- **Premises-grain rent:** validate coverage and vintages; ask the owner whether to reopen the
  tenant-dossier decision. It is not an automatic product launch.
- **Banded or BBL-grain rent:** use only as an evidence-grade context range after checking
  re-identification and coverage; no individual signed-rent claim.
- **Aggregate only:** retain as market context; do not add a storefront rent line or restart the
  dossier work.
- **Denial:** record the citation, close the FOIL branch, and return capacity to AC-1 and the
  survival gate. Do not litigate or lobby without a new owner decision.
