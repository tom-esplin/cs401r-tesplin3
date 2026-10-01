output "catalog_database_name" {
  description = "Name of the Glue catalog database"
  value       = aws_glue_catalog_database.this.name
}

output "raw_crawler_name" {
  description = "Name of the raw-data crawler"
  value       = aws_glue_crawler.raw.name
}

output "transform_job_name" {
  description = "Name of the transform ETL job"
  value       = aws_glue_job.transform.name
}

output "network_connection_name" {
  description = "Name of the Glue NETWORK connection — Task 3's feature-engineer job reuses this"
  value       = aws_glue_connection.network.name
}

output "feature_engineer_job_name" {
  description = "Name of the feature-engineer ETL job"
  value       = aws_glue_job.feature_engineer.name
}
