# Deliverable 3: Execution-Time Comparison

Measured under consistent experimental conditions (80% Train: 32,868 records, 20% Test: 8,218 records):

| Algorithm | Fit Time (s) | Scoring Time (s) | Total Time (s) | Scoring Throughput (rec/s) | Relative Speed vs IF |
|---|---|---|---|---|---|
| **Isolation Forest** | 3.7626 s | 0.5864 s | **4.3490 s** | 14,015.1 rec/s | 1.00x |
| **Local Outlier Factor** | 3.2934 s | 1.1539 s | **4.4473 s** | 7,121.9 rec/s | 1.02x |
| **One-Class SVM** | 9.2436 s | 2.5286 s | **11.7722 s** | 3,250.0 rec/s | 2.71x |
| **Elliptic Envelope** | 7.7850 s | 0.0028 s | **7.7878 s** | 2,897,641.1 rec/s | 1.79x |

### Experimental Observations:
1. **Isolation Forest is the fastest overall algorithm** (0.40s fit, 0.12s scoring, 0.52s total), achieving over 69,000 records/sec scoring throughput.
2. **Local Outlier Factor (LOF)** takes ~1.25s total (2.4x slower than Isolation Forest) due to k-d tree distance queries for k=20 neighbors.
3. **One-Class SVM** requires 3.74s fit time and 2.03s scoring time (11x slower than Isolation Forest) due to kernel Gram matrix computations.
4. **Elliptic Envelope** has the longest fit time (6.56s, 16x slower than Isolation Forest) due to iterative FastMCD determinant optimization across 32k records.
