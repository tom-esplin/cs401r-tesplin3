variable "project" {
  description = "Project name, used as the first element of every resource name"
  type        = string
  default     = "northstar"
}

variable "environment" {
  description = "Deployment environment — fixed to local so names never collide with dev"
  type        = string
  default     = "local"
}

variable "aws_region" {
  description = "Region LocalStack emulates; must match awslocal's default"
  type        = string
  default     = "us-east-1"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet; matches environments/dev"
  type        = string
  default     = "10.0.100.0/24"
}

variable "account_id" {
  description = "Account ID LocalStack always reports; used as the data bucket name suffix"
  type        = string
  default     = "000000000000"
}
