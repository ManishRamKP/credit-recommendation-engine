# Credit Recommendation Engine — v8

A production-deployed Flask API that generates real-time credit scores for invoice financing requests using GST return data and ERP (Tally) data — without needing traditional bank statements or audited financials.

Built for a fintech lending platform, this engine evaluates a borrower and trading partner pair against 7 financial metrics, produces a scored recommendation with highlights and observations, and logs every transaction to S3 for audit purposes.

Deployed on **Kubernetes (EKS)** with a Docker container, pulling data from **AWS Athena** (GST data) and optionally **Google BigQuery** (GCP variant).

---

## What Problem This Solves

Traditional invoice financing decisions require audited financials and bank statements — a slow, manual process. This engine replaces that with:

- Real-time GST return compliance analysis (GSTR1 + GSTR3B)
- Invoice pattern analysis from both GST and Tally ERP data
- A weighted credit score with transparent metric contributions
- An automated approve/flag verdict — all via a single API call

---

## Repository Name

`credit-recommendation-engine` or `cre-v8`

---

## Project Structure

```
credit-recommendation-engine/
│
├── credit_recommendation_engine.py   # Main Flask API — AWS Athena version
├── cre_gcp.py                        # GCP BigQuery variant of the same engine
│
├── config.json                       # Cloud config template (fill in your own values)
├── config_weights.json               # Scoring model weights — tunable without code changes
│
├── Dockerfile                        # Container definition
├── deployment_dev.yaml               # Kubernetes Deployment manifest (dev environment)
├── service_dev.yaml                  # Kubernetes Service manifest (ClusterIP)
├── requirements.txt                  # Python dependencies
│
├── sample_output.json                # Example API response for reference
└── README.md
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | Python, Flask |
| Primary Data (AWS) | AWS Athena (querying S3-backed GST data) |
| Primary Data (GCP) | Google BigQuery |
| ERP Data | Tally via Athena (`prod-erp` database) |
| Audit Logging | AWS S3 (per-transaction JSON logs) |
| Containerisation | Docker |
| Orchestration | Kubernetes (AWS EKS) |
| Auth (GCP variant) | GCP Service Account |

---

## How the Credit Score Is Calculated

The engine uses a **two-layer scoring model**: a base score from 7 weighted metrics, optionally boosted by document verification.

### Layer 1 — Base Score (weighted, max 100)

| Metric | Weight | How it's measured |
|---|---|---|
| Recency Score | 0.25 | Invoice count between borrower & trader across four 3-month windows in the last 12 months |
| Operational Vintage | 0.25 | Months of active GST filing history (GSTR1 records) |
| Invoice Frequency | 0.18 | Number of distinct invoices between the pair in the last 12 months |
| Current Invoice Amount | 0.20 | How the requested invoice compares to the historical average (normalised ratio) |
| Invoice to Cash Flow | 0.10 | EMA(3) of the borrower's invoice-to-cashflow ratio — liquidity proxy |
| Borrower Tax Compliance | 0.01 | Avg compliance score across GSTR1 + GSTR3B for last 3 financial years |
| Trader Tax Compliance | 0.01 | Same, for the trading partner |

All weights are configurable in `config_weights.json` — no code change needed.

### Layer 2 — Document Enhancement (optional, up to +25%)

If supporting documents are verified, the base score gets a proportional boost:

| Document | Weight |
|---|---|
| GRN (Goods Receipt Note) | 25% |
| E-Invoice | 25% |
| E-Way Bill | 25% |
| Trader Partner Confirmation | 25% |

Final score = `min(base_score + (overall_weight × verified_doc_weight × base_score), 100)`

---

## Data Source Selection Logic

The engine automatically picks the best available data source:

1. If **Tally data is more recent** than GST data and is within 45 days → use Tally
2. If **GST data is more recent**, or Tally is missing/outdated → use GST
3. The chosen source is logged in every transaction record (`choosen_data` field)

This is critical because Tally (ERP) data is more granular and up-to-date for active borrowers, while GST data is always available as a fallback.

---

## GST Compliance Scoring

Filing delay bands for GSTR1 and GSTR3B:

| Days late | Score |
|---|---|
| ≤ 30 | 10.0 |
| 31–60 | 7.0 |
| 61–90 | 4.0 |
| 91+ | 2.0 |

Quarterly filers use quarter-end adjusted bands. Scores are averaged across the last 3 financial years for both borrower and trader. **Minimum compliance score of 7.0 required** for both parties before any credit score is calculated.

---

## Verdict Thresholds

| Credit Score | Verdict |
|---|---|
| ≥ 50 | Strongly favorable |
| 40–49 | Generally favorable |
| 30–39 | Neutral standpoint |
| < 30 | Exercise caution |

---

## API Endpoint

### `POST /compute_credit_score`

**Request:**
```json
{
  "invoice_data": {
    "borrower_gst": "YOUR_BORROWER_GSTIN",
    "trader_gst": "YOUR_TRADER_GSTIN",
    "current_invoice_amount": 34692
  },
  "additional_metrics": {
    "grn_present": false,
    "e_invoice_present": true,
    "e_way_bill_present": true,
    "trader_partner_confirmation": false
  }
}
```

**Response:**
```json
{
  "base_score": 30.75,
  "credit_score": 30.75,
  "request_id": "uuid-here",
  "timestamp": "2025-02-14 12:14:10",
  "highlights": ["The borrower showcases commendable financial discipline..."],
  "observations": ["The transaction size deviates from typical patterns..."],
  "final_verdict": "This transaction presents a neutral standpoint."
}
```

Every response is also saved as a timestamped JSON to S3 at:
```
s3://YOUR_AUDIT_BUCKET/credit_recommendation_results/year=YYYY/month=MM/day=DD/{request_id}.json
```

---

## Deployment

### Run locally with Docker

```bash
docker build -t cre-v8 .
docker run -p 8114:8114 \
  -v $(pwd)/config.json:/app/config.json \
  -v $(pwd)/config_weights.json:/app/config_weights.json \
  cre-v8
```

### Deploy to Kubernetes

```bash
kubectl apply -f deployment_dev.yaml
kubectl apply -f service_dev.yaml
```

The service runs as `ClusterIP` on port `8114` within the `profintech-cre-v8-dev` namespace. Update `deployment_dev.yaml` with your ECR image URI before deploying.

---

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/credit-recommendation-engine.git
cd credit-recommendation-engine
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
pip install google-cloud-bigquery google-cloud-storage google-auth python-dateutil
```

### 3. Configure credentials
Copy the config template and fill in your values:
```bash
cp config.json config.local.json  # config.json is already gitignored
```

Fill in your AWS credentials, GCP service account details, S3 bucket names, and Athena output location.

### 4. Run the API
```bash
python credit_recommendation_engine.py
```

Server starts at `http://0.0.0.0:8114`.

---

## Configuration Files

### `config.json` (template — never commit with real values)
Holds AWS credentials, GCP service account, bucket names, and Athena output location. All values are placeholders in this repo.

### `config_weights.json` (safe to commit)
Controls all scoring weights. Credit risk teams can tune these without touching code:
- `base_weights` — per-metric weights summing to 1.0
- `additional_weights` — document verification weights
- `recency_weights` — how to weight the four 3-month invoice windows

---

## Key Design Decisions

**Why Athena over a traditional DB?**
GST data is stored in S3 as partitioned Parquet/CSV. Athena lets us run SQL directly on that — no ETL pipeline needed, and it scales to the full national GST dataset cheaply.

**Why EMA(3) for cash flow?**
A 3-period Exponential Moving Average gives more weight to recent months while smoothing seasonal spikes — better suited for short-tenure (30-day) invoice financing than a simple mean.

**Why IQR outlier handling before EMA?**
A single large one-off invoice can distort the cash flow ratio. IQR-based outlier removal replaces anomalous values with the non-outlier mean before EMA calculation, preventing one unusual month from skewing the score.

**Why a minimum compliance score gate?**
If either the borrower or trader has a compliance score below 7.0, the engine immediately rejects without calculating a credit score. Chronic late filers are a proxy for broader financial mismanagement.

---

## Notes for Reviewers

- `credit_recommendation_engine.py` is the primary AWS/Athena version deployed in production.
- `cre_gcp.py` is the GCP/BigQuery variant — same scoring logic, different data layer.
- All credentials in `config.json` are placeholders. Real values are never committed (see `.gitignore`).
- `sample_output.json` shows a real API response shape with GSTINs redacted.
- The Kubernetes manifests show the actual production deployment configuration used in the dev environment.
