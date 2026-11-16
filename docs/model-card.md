# Synthetic paid cost experiments

Estimate next-quarter paid expense in USD. Data and targets are fictional. The feature query takes only payments received before the forecast date. Target cost uses a 90-day arrival completion window.

Earlier periods 7, 10, and 13 provide training examples. Period 17 is validation and period 21 is the final holdout. Member identity is disjoint across all four groups. The second fictional tenant is entirely held out. Split fingerprints cover the numeric arrays used in the experiment.

The last-quarter-spend baseline is compared with regularized linear regression and histogram gradient boosting. An opt-in CPU PyTorch experiment trains a small neural net via backpropagation. Metrics are MAE and RMSE. Results on the generated distribution provide no evidence of clinical validity or real-world financial accuracy. Batch predictions served by the API come from the original versioned ridge command, separately from this comparison.

The V2 search selects ridge alpha and boosting leaf count by validation MAE. The comparison report includes per-split RMSE, p95 absolute error, mean error, high-needs and standard-cohort MAE, and standardized ridge coefficients. The validation baseline distribution is signed with the ridge artifact for tenant-level monitoring at inference time.
