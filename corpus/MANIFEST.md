# corpus/MANIFEST.md — RAHBAR corpus manifest

> Corpus: FAST-NUCES public site (nu.edu.pk), fetched by `scripts/fetch_corpus.py`.
> **PDFs themselves are NOT committed** — only this manifest and the fetch
> script are. Reproduce the corpus with `python3 scripts/fetch_corpus.py`
> (downloads go to `corpus/raw/`, which is gitignored).
>
> Hashes below were computed live on 2026-11-05 by AGENT_CORPUS by actually
> downloading each file (see `docs/CORPUS.md` for the verification log).
> Re-run the fetch script to re-verify them; the script warns on any mismatch.
> HTML pages have no pinned expected hash (the site's chrome changes
> between fetches) — the hash recorded is the hash of the saved copy in
> `corpus/raw/` at fetch time; re-running the script updates it.
>
> Deliberately ABSENT (property 6): the Prospectus 2026
> `Transport and Hostel Facilities` PDF is excluded on purpose — see
> `EXCLUDED` in `scripts/fetch_corpus.py` and `docs/CORPUS.md`. Do not add it.


| file | source URL | SHA-256 | pages | properties satisfied |
|---|---|---|---|---|
| `Academic_Rules_Handbook_2026.pdf` | https://nu.edu.pk/public/downloads/Academic_Rules_Handbook_2026.pdf | `sha256:4cfee3e191b84aeb9168f17656c7642212ff52b90f2780d028b33c154aa74b62` | 58 | 1, 2, 7 |
| `Undergraduate_Academic_Rules_Aug_2023.pdf` | http://nu.edu.pk/public/downloads/Academic-Rules-Undergrad-Aug-2023.pdf | `sha256:cddfe1f5e9770132e27d686abd1c2e6742ef4732f0c2f431ed514bc1691d2004` | 26 | 1, 2 |
| `Prospectus_2026_Academic_Rules_and_Regulations.pdf` | https://nu.edu.pk/Admissions/ProspectusUpload/Academic Rules and Regulations.pdf | `sha256:a7e7f6896a59eb9413c9e8826e6c4c018ebe52045d10cebfcba92ded10a3174a` | 5 | 1, 2, 7 |
| `Student_Handbook_2026.pdf` | https://nu.edu.pk/public/downloads/Student_Handbook_2026.pdf | `sha256:717eb4b8d37e50185ffe952735c08ef19edd16074d547f10ebd22cf23da67c4d` | 64 | 1, 5 |
| `Faculty_Entrepreneurship_Technical_Startups_Policy.pdf` | https://nu.edu.pk/OricResources/ResearchPolicies/27.pdf?20220530 | `sha256:c2d5c7648d1593daf34d5c0596ede476e8984b0551830cc1690017e6e22f1359` | 8 | 1, 3 |
| `Annual_Report_2019-20.pdf` | https://nu.edu.pk/public/downloads/AnnualReportForm/Annual Report 2019-20.pdf | `sha256:4d1961e340b13273bb039805ab5fd5e2c7bd0144a5bd5870f2ce4da13becd650` | 33 | 1, 2, 4 |
| `Annual_Report_2020-21.pdf` | https://nu.edu.pk/public/downloads/AnnualReportForm/Annual Report 2020-21.pdf | `sha256:996ca07ec6db28647f8c43beb56715726361b5afc8bbe0b84d2270bf7ee752ee` | 33 | 1, 2, 4 |
| `Annual_Report_2021-22.pdf` | https://nu.edu.pk/public/downloads/AnnualReportForm/Annual Report 2021-22.pdf | `sha256:87f182fe9e6ebc4bb2c56b86145f98b35181efd7f2dc7adf064eca0c0703d643` | 36 | 1, 2, 4 |
| `Annual_Report_2022-23.pdf` | https://nu.edu.pk/public/downloads/AnnualReportForm/Annual Report 2022-23.pdf | `sha256:17fefb84832fc0d14723f08a3795bbe70e95c16fd8d57f16eef32ebed805a31d` | 36 | 1, 2, 4 |
| `Annual_Report_2023-24.pdf` | https://nu.edu.pk/public/downloads/AnnualReportForm/Annual Report 2023-24.pdf | `sha256:3c9d89e84af24df4b939f10e32c620a3877b276acea1db52f1aae4098e5c057a` | 85 | 1, 2, 4 |
| `EE_PLOs_2024_onwards_11.pdf` | https://drive.google.com/file/d/1VBkr5aHcgOHmlzAtjpn_GjQZNCXjcSLF/view | `sha256:bbf1eb1291e81dcf0944328748269668495032cf41c14ccc85eaed6ceced93f1` | 1 | 1, 2, 7 |
| `EE_PLOs_before_2024_12.pdf` | https://drive.google.com/file/d/1yZo--h0fZN9lqRapQbUxkYBqm-7AeL3V/view | `sha256:0c782e8beb5cb664baee4822f633b9211f029aeb11c350a4c1241ca84e3841e6` | 2 | 1, 2, 7 |
| `Fee_Structure_page.html` | https://nu.edu.pk/Admissions/FeeStructure | `sha256:ec8872ae77cac7e96e20e6979933f36b00aaeb0ab3f668a2116e521c655e7b90` | 1 | 1, 4, 7 |
| `Grading_page.html` | https://nu.edu.pk/Student/Grading | `sha256:66a995b4d8474e914d37bfa14755a5361f47327d5a7314f9b7ec15d9b6176e6e` | 1 | 1, 4, 7 |
| `Academic_Calendar_page.html` | https://nu.edu.pk/Student/Calender | `sha256:635b62adbbad7e8a9b73d19990f3f42c0721c35d4170f7707a6fca16488729ad` | 1 | 1, 2 |

**Total: 15 documents, 390 pages (requirement: >=6 documents, >=40 pages).**

## Excluded on purpose (property 6 — absent topic)

- **Transport and Hostel Facilities (Prospectus 2026)** — <https://nu.edu.pk/Admissions/ProspectusUpload/Transport%20and%20Hostel%20Facilities.pdf> — Property 6 — deliberately absent topic (transport/hostel rules).
