variable "project" {
  description = "Name of the project used for resource tags"
  type        = string
  default     = "agentprovision"
}

variable "environment" {
  description = "Deployment environment label"
  type        = string
  default     = "staging"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane"
  type        = string
  default     = "1.28"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnets" {
  description = "Public subnet CIDR blocks"
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnets" {
  description = "Private application subnet CIDR blocks"
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24", "10.0.12.0/24"]
}

variable "database_subnets" {
  description = "Private database subnet CIDR blocks"
  type        = list(string)
  default     = ["10.0.20.0/24", "10.0.21.0/24", "10.0.22.0/24"]
}

variable "postgres_engine_version" {
  description = "Aurora PostgreSQL engine version"
  type        = string
  default     = "15.3"
}

variable "postgres_master_username" {
  description = "Database admin username"
  type        = string
  default     = "agent_admin"
}

variable "postgres_master_password" {
  description = "Database admin password (override via tfvars or environment)"
  type        = string
  default     = "ChangeMe123!"
  sensitive   = true
}

variable "enable_rds_deletion_protection" {
  description = "Ensure RDS cluster is protected from accidental deletion"
  type        = bool
  default     = true
}

variable "force_destroy_storage" {
  description = "Allow S3 bucket to be force destroyed"
  type        = bool
  default     = false
}
