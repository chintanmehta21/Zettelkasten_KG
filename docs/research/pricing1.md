1. Two types of pricing strategies:
1.a. Subscription : Monthly/Quarterly/Yearly options ; User has a free tier strategy where maximum caps applied; Basic tier has a bit higher cap and Final Max has a very generous max cap (Ok to lose money on this plan to gain customers)
1.b. Custom : Two options -- Either buy Zettels or buy Kastens in ad-hoc manner.. 5 Zettels, 10 Zettels, etc in a linear manner.. So user can buy a multiple of 10 (With option of 1, 5, 10, 20...) Zettels or Kastens and they are priced accordingly
2. Monthly max caps applied on total Zettels creation by user -- Free (2 max per day; 10 max a week; 30 max in a month); Basic (5 max per day; 30 max a week; 50 max in a month); Max (30 max per day; 100 max a week; 200 max in a month)
3. Monthly max caps applied on total Kastens created by user -- Free (1 max per user; 30 questions/Month); Basic (5 max per user; 100 questions/Month); Max (5 max per week; 50 max per user; 500 questions/Month)

***

## 1. Cost model you are pricing around (INR, Gemini Pro + embeddings)

Based on Gemini 2.5 Pro pricing of about **\$1.25 / 1M input tokens** and **\$10 / 1M output tokens**, and embeddings at **\$0.15–0.20 / 1M tokens**, plus a mid‑market rate of ≈ **₹95 per USD**:[^1][^2][^3][^4]

- **Per Zettel** (3 Gemini Pro calls, ~3k in / 1k out tokens each):
    - ≈ 9k input + 3k output tokens → LLM ≈ **\$0.041** → ~**₹3.9**
    - Embeddings (~4k tokens) ≈ **₹0.06**
    - With DB + infra buffer: **price off ≈ ₹5 / Zettel**.[^2][^4]
- **Per Kasten** (2 Pro calls, 4k in / 2k out tokens each):
    - ≈ 8k input + 4k output tokens → LLM ≈ **\$0.05** → ~**₹4.8**
    - With retrieval, embeddings and buffer: **price off ≈ ₹8 / Kasten**.[^2]
- **Per RAG question** (~3k in / 1k out tokens):
    - ≈ **\$0.0138** → ~**₹1.3**
    - With retrieval + logging: **price off ≈ ₹2 / question**.[^2]

Caps you defined:

- Free: 30 Z / month; 1 K; 30 Q.
- Basic: 50 Z; 5 K; 100 Q.
- Max: 200 Z; ~20 K / month (5/week); 500 Q.

Worst‑case *theoretical* cost at these caps:

- Free ≈ **₹218/month**
- Basic ≈ **₹890/month**
- Max ≈ **₹2,160/month**

You’ll rely on real behavior being far below caps (and on future optimization) so prices can be much lower than those worst‑case envelopes.[^5]

***

## 2. Subscription pricing – list vs launch

### 2.1 Monthly prices

**List (long‑term) prices**

- Basic: **₹299 / month**
- Max: **₹499 / month**

**Launch promotional prices**

Shown in UI as “Launch offer / Early supporter pricing”:

- Basic (Launch): **₹149 / month**
- Max (Launch): **₹349 / month**

All caps stay exactly as you specified:

- Basic: 50 Z / month; 5 Kastens; 100 questions.
- Max: 200 Z / month; 5 Kastens/week (50 total); 500 questions.

Effect:

- List prices are a realistic long‑term anchor once you’ve optimized usage and have more paying users.
- Launch prices roughly halve Basic and cut Max materially so onboarding to paid is much easier for Indian users.


### 2.2 Quarterly and yearly prices

You have **two parallel ladders**: list and promo.

#### Basic

- **List**
    - Monthly: **₹299**
    - Quarterly: **₹849** (~₹283/month)
    - Yearly: **₹2,999** (~₹250/month)
- **Launch promo**
    - Monthly: **₹149**
    - Quarterly: **₹399** (~₹133/month)
    - Yearly: **₹1,499** (~₹125/month)


#### Max

- **List**
    - Monthly: **₹499**
    - Quarterly: **₹1,449** (~₹483/month)
    - Yearly: **₹4,999** (~₹417/month)
- **Launch promo**
    - Monthly: **₹349**
    - Quarterly: **₹999** (~₹333/month)
    - Yearly: **₹3,499** (~₹291/month)

How to present in product:

- Show **list prices struck through** with **promo prices highlighted** (“Launch offer – 50% off Basic, ~30% off Max”).
- Lock launch prices to early cohorts (e.g., “valid for first 12 months if you subscribe before date X”) so you can raise later without drama.

***

## 3. Custom per‑use pricing – list vs launch

Goal: packs feel cheap enough that Free users actually buy, but still make subscriptions clearly superior once usage is regular.

### 3.1 Zettel packs

Zettel cost basis ≈ ₹5.

**List prices**

- 1 Zettel: **₹25**
- 5 Zettels: **₹99** (~₹19.8 each)
- 10 Zettels: **₹179** (~₹17.9 each)
- 20 Zettels: **₹329** (~₹16.45 each)

**Launch promo prices**

- 1 Zettel: **₹15**
- 5 Zettels: **₹69** (~₹13.8 each)
- 10 Zettels: **₹99** (~₹9.9 each)
- 20 Zettels: **₹169** (~₹8.45 each)

Implications:

- A user frequently buying 20+ Zettels/month is overpaying vs even Basic list (₹299, 50 Z) and **massively overpaying** vs Basic launch (₹149), nudging them into subscription.


### 3.2 Kasten packs

Kasten cost basis ≈ ₹8.

**List prices**

- 1 Kasten: **₹129**
- 5 Kastens: **₹499** (~₹99.8 each)
- 10 Kastens: **₹899** (~₹89.9 each)
- 20 Kastens: **₹1,599** (~₹79.95 each)

**Launch promo prices**

- 1 Kasten: **₹69**
- 5 Kastens: **₹299** (~₹59.8 each)
- 10 Kastens: **₹499** (~₹49.9 each)
- 20 Kastens: **₹899** (~₹44.95 each)

Effect:

- Small Kasten packs look affordable for occasional deep projects.
- Anyone doing 10–20 new Kastens on a regular basis will find Max promo at ₹349/month obviously better.


### 3.3 RAG question packs

**List**

- 100 questions: **₹149**
- 500 questions: **₹499**

**Launch promo**

- 100 questions: **₹79**
- 500 questions: **₹249**

Position these as top‑ups when someone is clearly RAG‑heavy but not yet ready to move from Basic → Max.

***

## 4. Final INR pricing snapshot for Zettelkasten.in

### 4.1 Subscription tiers

All caps are per your spec.


| Plan | Billing | List Price | Launch Promo | Zettels / month | Kastens | Questions / month |
| :-- | :-- | --: | --: | --: | --: | --: |
| Free | Monthly | ₹0 | ₹0 | 30 | 1 total | 30 |
| Basic | Monthly | ₹299 | **₹149** | 50 | 5/user | 100 |
| Basic | Quarterly | ₹849 | **₹399** | 50 | 5/user | 100 |
| Basic | Yearly | ₹2,999 | **₹1,499** | 50 | 5/user | 100 |
| Max | Monthly | ₹499 | **₹349** | 200 | 5/week (50 total) | 500 |
| Max | Quarterly | ₹1,449 | **₹999** | 200 | 5/week (50 total) | 500 |
| Max | Yearly | ₹4,999 | **₹3,499** | 200 | 5/week (50 total) | 500 |

### 4.2 Custom credits

| Type | Pack | List Price | Launch Promo |
| :-- | :-- | --: | --: |
| Zettels | 1 | ₹25 | ₹15 |
| Zettels | 5 | ₹99 | ₹69 |
| Zettels | 10 | ₹179 | ₹99 |
| Zettels | 20 | ₹329 | ₹169 |
| Kastens | 1 | ₹129 | ₹69 |
| Kastens | 5 | ₹499 | ₹299 |
| Kastens | 10 | ₹899 | ₹499 |
| Kastens | 20 | ₹1,599 | ₹899 |
| Questions | 100 | ₹149 | ₹79 |
| Questions | 500 | ₹499 | ₹249 |


***

[^1]: https://www.metacto.com/blogs/the-true-cost-of-google-gemini-a-guide-to-api-pricing-and-integration

[^2]: https://lemondata.cc/en/models/gemini-1-5/gemini-embedding-001

[^3]: https://deploybase.ai/articles/gemini-api-pricing-2026

[^4]: https://rahulkolekar.com/gemini-pricing-in-2026-gemini-api-vs-vertex-ai-tokens-batch-caching-imagen-veo/

[^5]: https://www.tldl.io/resources/google-gemini-api-pricing

[^6]: https://developers.googleblog.com/gemini-embedding-available-gemini-api/

[^7]: https://costgoat.com/pricing/gemini-api

[^8]: https://wise.com/in/currency-converter/usd-to-inr-rate/history

[^9]: https://www.bookmyforex.com/currency-converter/usd-to-inr/forecast/

[^10]: About.md

[^11]: https://upgrowth.in/saas-pricing-packaging-strategy-india-gtm/

[^12]: https://www.ibef.org/news/ai-adoption-is-highest-among-indians-how-it-is-changing-shopping-trends

[^13]: https://www.business-standard.com/industry/news/ai-adoption-highest-among-indians-changing-shopping-trends-126010700584_1.html

[^14]: https://wise.com/us/currency-converter/usd-to-inr-rate/history

[^15]: https://tokencost.app/blog/gemini-embedding-2-pricing

[^16]: https://getgoapi.com/en/models/gemini-1-5-pro-latest/pricing

[^17]: https://www.xe.com/en-us/currencycharts/?from=USD\&to=INR

[^18]: https://getgoapi.com/en/models/gemini-embedding-2-preview/pricing

[^19]: https://www.exchange-rates.org/exchange-rate-history/usd-inr-2026

[^20]: https://epic.law/ai-generated-derivative-works-the-case-for-mandatory-disclosure-of-weights-and-prompts/

[^21]: https://michellekassorla.substack.com/p/is-your-ai-research-assistant-breaking

[^22]: https://lovable.dev/guides/what-is-mem-ai

[^23]: https://builtin.com/artificial-intelligence/ai-copyright

[^24]: https://www.scribd.com/document/972641461/Who-Owns-Any-Output-a-User-Creates-in-NotebookLM

[^25]: https://skywork.ai/skypage/en/Mem-AI-Your-Personal-Knowledge-Engine-in-2025/1976181401534394368

[^26]: https://www.mcbrayerfirm.com/blogs-intellectual-property-blog,u-s-copyright-office-releases-part-2-of-copyright-and-artificial-intelligence-series-copyrightability-guidance

[^27]: https://connect.ala.org/acrl/discussion/google-notebooklm-copyright-questions

[^28]: https://us.fitgap.com/products/045061/mem-ai

[^29]: https://www.dykema.com/news-insights/the-future-of-creativity-us-copyright-office-clarifies-copyrightability-of-ai-generated-works.html

[^30]: https://answers.justia.com/question/2025/10/27/is-it-legal-to-upload-ai-generated-educa-1089667

[^31]: https://get.mem.ai/pricing

[^32]: https://copyrightalliance.org/ai-report-part-2-copyrightability/

[^33]: https://it.umn.edu/services-technologies/notebooklm

[^34]: https://productivitystack.io/tools/mem/

[^35]: https://flowlyn.com/tools/gemini-api-pricing-calculator

[^36]: https://www.datastudios.org/post/google-ai-studio-free-plans-trials-and-subscriptions-access-tiers-limits-and-upgrade-paths

[^37]: https://llmpricecheck.com/google/gemini-1.5-pro/

[^38]: https://timesofindia.indiatimes.com/technology/tech-news/google-launches-ai-plus-subscription-in-india-at-introductory-price-of-rs-199-per-month-heres-what-googles-ai-plus-subscription-offers/articleshow/125886097.cms

[^39]: https://www.scribd.com/document/1006268004/Gemini-Picing-for-1-5-Pro

[^40]: https://wise.com/in/currency-converter/inr-to-usd-rate/history

[^41]: https://ai.google.dev/gemini-api/docs/pricing

[^42]: https://www.exchange-rates.org/exchange-rate-history/inr-usd-2026

[^43]: https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing

[^44]: https://one.google.com/intl/en_in/about/google-ai-plans/

[^45]: https://ubikon.in/blog/saas-product-development-cost-india

[^46]: https://www.hindustantimes.com/india-news/india-tops-survey-on-ai-usage-ahead-of-united-states-united-kingdom-report-101746038712141.html

[^47]: https://www.promaticsindia.com/blog/cost-of-building-saas-platform

[^48]: https://hr.economictimes.indiatimes.com/news/workplace-4-0/india-leads-global-charge-in-ai-adoption-77-knowledge-workers-use-generative-ai-daily/124102717

[^49]: https://ycharts.com/indicators/us_dollar_to_indian_rupee_exchange_rate

[^50]: https://www.reddit.com/r/StartUpIndia/comments/1paac8s/do_indian_users_actually_pay_for_productivity/

[^51]: https://www.poundsterlinglive.com/history/USD-INR-2026

[^52]: https://rajeshrnair.com/blog/software/saas/saas-development-cost-india.html

[^53]: https://www.pib.gov.in/PressReleasePage.aspx?PRID=2226912\&reg=3\&lang=1

[^54]: https://www.mtfxgroup.com/tools/historical-currency-exchange-rates/usd-to-inr-rate/

