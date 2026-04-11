terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_availability_zones" "available" {}

locals {
  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.1.2"

  name = "${var.project}-${var.environment}-vpc"
  cidr = var.vpc_cidr

  azs               = slice(data.aws_availability_zones.available.names, 0, 3)
  public_subnets    = var.public_subnets
  private_subnets   = var.private_subnets
  database_subnets  = var.database_subnets

  enable_nat_gateway           = true
  single_nat_gateway           = true
  create_igw                   = true
  create_database_subnet_group = true

  tags = local.tags
}

module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  version         = "20.8.3"

  cluster_name    = "${var.project}-${var.environment}-eks"
  cluster_version = var.cluster_version

  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  vpc_id                   = module.vpc.vpc_id
  subnet_ids               = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  enable_cluster_creator_admin_permissions = true

  tags = local.tags

  eks_managed_node_groups = {
    default = {
      desired_size   = 2
      max_size       = 4
      min_size       = 2
      instance_types = ["t3.medium"]
      capacity_type  = "ON_DEMAND"
    }
  }
}

resource "aws_rds_cluster" "postgres" {
  cluster_identifier = "${var.project}-${var.environment}-aurora"
  engine             = "aurora-postgresql"
  engine_version     = var.postgres_engine_version
  database_name      = "agentprovision"
  master_username    = var.postgres_master_username
  master_password    = var.postgres_master_password
  backup_retention_period = 5
  preferred_backup_window = "02:00-03:00"
  db_subnet_group_name    = module.vpc.database_subnet_group
  vpc_security_group_ids  = [module.vpc.default_security_group_id]
  storage_encrypted       = true
  deletion_protection     = var.enable_rds_deletion_protection
  skip_final_snapshot     = !var.enable_rds_deletion_protection
  tags                    = local.tags
}

resource "aws_s3_bucket" "logs" {
  bucket        = "${var.project}-${var.environment}-logs"
  force_destroy = var.force_destroy_storage
  tags          = local.tags
}

resource "aws_iam_role" "agent_runner" {
  name = "${var.project}-${var.environment}-agent-runner"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action   = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}
