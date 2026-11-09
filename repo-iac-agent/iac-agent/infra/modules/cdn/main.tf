variable "project_name" {
  type = string
}

variable "alb_dns_name" {
  description = "The frontend ALB's DNS name (from the ecs-frontend module) — used as CloudFront's origin"
  type        = string
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled = true
  comment = "${var.project_name} frontend + ops dashboard"

  origin {
    domain_name = var.alb_dns_name
    origin_id   = "frontend-alb"

    # HTTP-only to the origin for now — the ALB has no HTTPS listener yet
    # (see ecs-frontend module's comment: needs an ACM cert + real domain
    # first). CloudFront still terminates TLS for the end user either way.
    custom_origin_config {
      http_port              = 80
      https_port              = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods          = ["GET", "HEAD"]
    target_origin_id        = "frontend-alb"
    viewer_protocol_policy  = "redirect-to-https"

    # This app is a dynamic SPA hitting a JSON API (/ops/*, /chat) behind
    # the same origin — caching would serve stale dashboard data and break
    # the chat/approve flows. Forward everything, cache nothing, until
    # there's a real reason (and a plan) to cache specific static assets.
    forwarded_values {
      query_string = true
      headers      = ["*"]
      cookies {
        forward = "all"
      }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # No ACM cert yet — using CloudFront's default certificate. Swap to a
  # real viewer_certificate block (ACM cert + your domain) once Route53 +
  # ACM are set up, per the build guide's open decisions.
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

output "distribution_domain_name" {
  value = aws_cloudfront_distribution.frontend.domain_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.frontend.id
}
