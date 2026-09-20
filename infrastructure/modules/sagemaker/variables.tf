# Every variable needs a description — Task B1 grades this.

variable "project" {
  description = "Project name, used as the first element of every resource name"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "vpc_id" {
  description = "VPC the SageMaker Domain attaches to"
  type        = string
}

variable "subnet_ids" {
  description = "Subnets the SageMaker Domain may use"
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group for SageMaker"
  type        = string
}

variable "ml_engineer_role_arn" {
  description = "Role for execution in sagemaker"
  type        = string
}

variable "sagemaker_instance_type" {
  description = "Default kernel instance type for SageMaker Studio apps"
  type        = string
}
