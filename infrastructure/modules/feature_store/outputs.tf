output "feature_group_name" {
  description = "Name of the customer-features Feature Group"
  value       = aws_sagemaker_feature_group.customer_features.feature_group_name
}

output "feature_group_arn" {
  description = "ARN of the customer-features Feature Group"
  value       = aws_sagemaker_feature_group.customer_features.arn
}
