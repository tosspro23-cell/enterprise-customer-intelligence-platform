"""Small, explicit AWS stacks for the customer intelligence demo.

The first cloud target intentionally keeps the local modular-monolith contract:
one container, one EC2 host, and one encrypted EBS volume for SQLite. It is a
demo deployment foundation, not the production topology.
"""

from __future__ import annotations

from typing import Optional

from aws_cdk import (
    CfnOutput,
    CfnParameter,
    RemovalPolicy,
    Stack,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class CustomerIntelligenceRepositoryStack(Stack):
    """Container registry kept separate so the image can be pushed first."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.repository = ecr.Repository(
            self,
            "ApplicationRepository",
            repository_name="customer-intelligence-platform",
            image_scan_on_push=True,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=5)],
            removal_policy=RemovalPolicy.RETAIN,
        )

        CfnOutput(
            self,
            "RepositoryUri",
            value=self.repository.repository_uri,
            description="Push the application image to this ECR repository before deploying the demo host.",
        )


class CustomerIntelligenceDemoStack(Stack):
    """Single-host demo runtime with SSM access and persistent SQLite storage."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        repository: ecr.Repository,
        allowed_cidr: Optional[str],
        image_tag: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        image_tag_parameter = CfnParameter(
            self,
            "ImageTag",
            type="String",
            default=image_tag,
            min_length=1,
            description="Immutable image tag to run on the demo host.",
        )
        cidr_kwargs = {
            "type": "String",
            "description": "CIDR allowed to access the HTTP demo endpoint; use a /32 for a private demo.",
        }
        if allowed_cidr:
            cidr_kwargs["default"] = allowed_cidr
        allowed_cidr_parameter = CfnParameter(self, "AllowedCidr", **cidr_kwargs)

        vpc = ec2.Vpc(
            self,
            "DemoVpc",
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        security_group = ec2.SecurityGroup(
            self,
            "DemoSecurityGroup",
            vpc=vpc,
            description="HTTP access for the explicitly scoped demo endpoint",
            allow_all_outbound=True,
        )
        security_group.add_ingress_rule(
            ec2.Peer.ipv4(allowed_cidr_parameter.value_as_string),
            ec2.Port.tcp(80),
            "Workbench HTTP",
        )

        role = iam.Role(
            self,
            "DemoInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSSMManagedInstanceCore"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEC2ContainerRegistryReadOnly"
                ),
            ],
        )

        log_group = logs.LogGroup(
            self,
            "ApplicationLogGroup",
            log_group_name="/customer-intelligence-platform/demo",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[f"{log_group.log_group_arn}:*"],
            )
        )

        registry_host = f"{cdk_aws_account()}.dkr.ecr.{cdk_aws_region()}.amazonaws.com"
        image_uri = f"{repository.repository_uri}:{image_tag_parameter.value_as_string}"
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "set -euxo pipefail",
            "dnf install -y docker",
            "systemctl enable --now docker",
            "install -d -o 10001 -g 10001 /var/lib/customer-intelligence/data",
            f"aws ecr get-login-password --region {cdk_aws_region()} | docker login --username AWS --password-stdin {registry_host}",
            f"docker pull {image_uri}",
            "docker rm --force customer-intelligence || true",
            (
                "docker run --detach --name customer-intelligence --restart unless-stopped "
                "--publish 80:8765 "
                "--env DATABASE_PATH=/app/data/platform.db "
                "--volume /var/lib/customer-intelligence/data:/app/data "
                f"--log-driver awslogs --log-opt awslogs-region={cdk_aws_region()} "
                f"--log-opt awslogs-group={log_group.log_group_name} "
                "--log-opt awslogs-stream=customer-intelligence "
                f"{image_uri}"
            ),
        )

        instance = ec2.Instance(
            self,
            "DemoInstance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType("t3.micro"),
            machine_image=ec2.MachineImage.from_ssm_parameter(
                "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
            ),
            security_group=security_group,
            role=role,
            user_data=user_data,
            require_imdsv2=True,
            associate_public_ip_address=True,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        20,
                        encrypted=True,
                        volume_type=ec2.EbsDeviceVolumeType.GP3,
                        delete_on_termination=True,
                    ),
                )
            ],
        )

        CfnOutput(self, "InstanceId", value=instance.instance_id)
        CfnOutput(self, "PublicIp", value=instance.instance_public_ip)
        CfnOutput(
            self,
            "DemoUrl",
            value=f"http://{instance.instance_public_ip}",
            description="Temporary HTTP URL for the synthetic-data demo.",
        )
        CfnOutput(self, "LogGroupName", value=log_group.log_group_name)


def cdk_aws_account() -> str:
    """Return the deploy-time account token without performing a lookup."""

    from aws_cdk import Aws

    return Aws.ACCOUNT_ID


def cdk_aws_region() -> str:
    """Return the deploy-time region token without performing a lookup."""

    from aws_cdk import Aws

    return Aws.REGION
