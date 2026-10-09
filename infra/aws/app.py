#!/usr/bin/env python3
"""AWS CDK entry point for the low-cost demo deployment."""

from __future__ import annotations

import os

import aws_cdk as cdk

from customer_intelligence_stack import CustomerIntelligenceDemoStack, CustomerIntelligenceRepositoryStack


app = cdk.App()

region = os.getenv("CDK_DEFAULT_REGION") or os.getenv("AWS_REGION") or "us-east-1"
account = os.getenv("CDK_DEFAULT_ACCOUNT")
environment = cdk.Environment(account=account, region=region)

repository_stack = CustomerIntelligenceRepositoryStack(
    app,
    "CustomerIntelligenceRepository",
    env=environment,
)

demo_stack = CustomerIntelligenceDemoStack(
    app,
    "CustomerIntelligenceDemo",
    repository=repository_stack.repository,
    allowed_cidr=app.node.try_get_context("allowed_cidr"),
    image_tag=app.node.try_get_context("image_tag") or "latest",
    env=environment,
)
demo_stack.add_dependency(repository_stack)

app.synth()
