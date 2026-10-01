output "ml_engineer_role_arn" {
  description = "ARN of the MLEngineer role — later labs pass this to SageMaker"
  value       = aws_iam_role.ml_engineer.arn
}

output "data_engineer_role_arn" {
  description = "ARN of the DataEngineer role — Glue crawlers/jobs and the Feature Group assume this"
  value       = aws_iam_role.data_engineer.arn
}

output "model_monitor_role_arn" {
  description = "ARN of the ModelMonitor role — read-only observer of drift/processing jobs and metrics"
  value       = aws_iam_role.model_monitor.arn
}
