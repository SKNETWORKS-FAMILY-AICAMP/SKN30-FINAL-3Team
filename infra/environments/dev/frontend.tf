locals {
  frontend_bucket_name   = "${var.project_name}-${local.environment}-frontend-${local.s3_region_code}-${data.aws_caller_identity.current.account_id}"
  frontend_s3_origin_id  = "${local.name_prefix}-frontend-s3"
  frontend_api_origin_id = "${local.name_prefix}-api-alb"
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_s3_bucket" "frontend" {
  bucket        = local.frontend_bucket_name
  force_destroy = false

  tags = {
    Name    = local.frontend_bucket_name
    Purpose = "frontend-origin"
  }
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend"
  description                       = "Signed CloudFront access to the private frontend S3 origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = var.dev_edge_enabled
  is_ipv6_enabled     = false
  wait_for_deployment = true
  comment             = "${local.name_prefix} frontend and same-origin API"
  default_root_object = "index.html"
  http_version        = "http2and3"
  price_class         = "PriceClass_200"

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
    origin_id                = local.frontend_s3_origin_id
  }

  dynamic "origin" {
    for_each = var.dev_edge_enabled ? [aws_lb.app[0].dns_name] : []

    content {
      domain_name = origin.value
      origin_id   = local.frontend_api_origin_id

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "http-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  default_cache_behavior {
    target_origin_id           = local.frontend_s3_origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
  }

  dynamic "ordered_cache_behavior" {
    for_each = var.dev_edge_enabled ? {
      api = {
        path_pattern    = local.frontend_api_path_pattern
        allowed_methods = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
      }
      health = {
        path_pattern    = "/health/*"
        allowed_methods = ["GET", "HEAD", "OPTIONS"]
      }
    } : {}

    content {
      path_pattern               = ordered_cache_behavior.value.path_pattern
      target_origin_id           = local.frontend_api_origin_id
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ordered_cache_behavior.value.allowed_methods
      cached_methods             = ["GET", "HEAD", "OPTIONS"]
      compress                   = true
      cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
      response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
      origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name = "${local.name_prefix}-frontend"
  }

  # start에서는 listener 생성 뒤 origin을 활성화하고, stop에서는 distribution
  # 비활성화 전파가 끝난 뒤 listener와 ALB를 제거한다.
  depends_on = [aws_lb_listener.http]
}

data "aws_iam_policy_document" "frontend_bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.frontend.arn,
      "${aws_s3_bucket.frontend.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "AllowCloudFrontOriginAccessControl"
    effect = "Allow"

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

output "frontend_delivery" {
  description = "Frontend deployment와 동일-origin API 검증에 사용할 CloudFront·S3 식별자"
  value = {
    api_path_pattern     = "/api/*"
    build_output         = "frontend/dist/client"
    bucket_arn           = aws_s3_bucket.frontend.arn
    bucket_name          = aws_s3_bucket.frontend.id
    distribution_arn     = aws_cloudfront_distribution.frontend.arn
    distribution_domain  = aws_cloudfront_distribution.frontend.domain_name
    distribution_enabled = var.dev_edge_enabled
    distribution_id      = aws_cloudfront_distribution.frontend.id
    delivery_prerequisites = [
      "Frontend npm run build must produce a reproducible frontend/dist/client release artifact.",
      "Upload index.html with no-cache or a short TTL, upload hashed assets as immutable, and invalidate the distribution.",
      "Backend HTTP_ALLOWED_HOSTS must allow the ALB DNS Host forwarded by CloudFront; target health Host handling is a separate contract.",
      "Empty the protected frontend bucket before environment teardown.",
    ]
  }
}

output "dev_edge_mode" {
  description = "deep lifecycle에서 관리하는 dev edge 목표 상태"
  value = {
    alb_enabled        = var.dev_edge_enabled
    cloudfront_enabled = var.dev_edge_enabled
    mode               = var.dev_edge_enabled ? "active" : "suspended"
  }
}
