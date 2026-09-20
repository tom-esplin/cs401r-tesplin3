| Component            | Monthly Estimate | Key Assumptions                                              | One Optimization                                    |
|----------------------|------------------|--------------------------------------------------------------|-----------------------------------------------------|
| SageMaker Studio     | 1958.40          | 8 hrs/day 20 workdays a month) at $2.5/hr, 5 data scientists | self hosted notebooks, analysis done on own servers |
| S3 storage           | 7.77             | 100 GB at $0.023/GB, a million requests of each type         | Use only basic features                             |
| Internet Gateway     | 10.50            | $0.01/GB data transfer                                       | None                                                |
| DynamoDB (state lock | 0.25             | On-demand, near-zero reads, less than 1 GB                   | None, basically free                                |
| S3 state bucket      | 0.25             | Minimal storage, same cost as other s3 storage               | None                                                |
| Total                | 1977.17          |                                                              |                                                     |
