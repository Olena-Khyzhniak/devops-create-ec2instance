#!/usr/bin/env python3
import boto3
import json
import subprocess
import random
import string
import time
import datetime


def generate_random_string():
    """Generate a random string with your tag."""
    random_part = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{random_part}-okhyzhniak"


# --- EC2 INSTANCE CREATION ---
ec2 = boto3.resource('ec2', region_name='us-east-1')

# Default VPC
default_vpc = list(ec2.vpcs.filter(Filters=[{'Name': 'isDefault', 'Values': ['true']}]))[0]

# Create Security Group
sg_name = generate_random_string()
sg = ec2.create_security_group(
    GroupName=sg_name,
    Description='Allow HTTP and SSH access',
    VpcId=default_vpc.id
)

# Add inbound rules
sg.authorize_ingress(
    IpPermissions=[
        {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
        {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
    ]
)

instance_name = generate_random_string()

# Launch instance
new_instances = ec2.create_instances(
    ImageId='ami-08982f1c5bf93d976',
    MinCount=1,
    MaxCount=1,
    InstanceType='t2.nano',
    SecurityGroupIds=[sg.id],
    KeyName='olenakeypair',
    Placement={'AvailabilityZone': 'us-east-1a'},
    UserData="""#!/bin/bash
yum update -y
yum install httpd -y
systemctl enable httpd
systemctl start httpd

# Get metadata token
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")

# Get metadata
INSTANCE_ID=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s \
  http://169.254.169.254/latest/meta-data/instance-id)
PRIVATE_IP=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s \
  http://169.254.169.254/latest/meta-data/local-ipv4)
INSTANCE_TYPE=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s \
  http://169.254.169.254/latest/meta-data/instance-type)
AVAILABILITY_ZONE=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -s \
  http://169.254.169.254/latest/meta-data/placement/availability-zone)

# Create index.html
echo '<html><head><title>EC2 Metadata</title></head><body>' > /var/www/html/index.html
echo '<h1>Welcome to My EC2 Web Server!</h1>' >> /var/www/html/index.html
echo "<p><b>Instance ID:</b> $INSTANCE_ID</p>" >> /var/www/html/index.html
echo "<p><b>Private IP:</b> $PRIVATE_IP</p>" >> /var/www/html/index.html
echo "<p><b>Instance Type:</b> $INSTANCE_TYPE</p>" >> /var/www/html/index.html
echo "<p><b>Availability Zone:</b> $AVAILABILITY_ZONE</p>" >> /var/www/html/index.html
echo '<img src="https://devops.setudemo.net/logo.jpg" alt="Logo" width="300"/>' >> /var/www/html/index.html
echo '</body></html>' >> /var/www/html/index.html
""",
    TagSpecifications=[{
        'ResourceType': 'instance',
        'Tags': [{'Key': 'Name', 'Value': instance_name}]
    }]
)

instance = new_instances[0]
instance.wait_until_running()
instance.reload()

ip_address = instance.public_ip_address
name_tag = next((tag['Value'] for tag in instance.tags if tag['Key'] == 'Name'), 'Unnamed')

print(f"Instance name: {name_tag} .\nInstance {instance.id} is Running.\nPublic IP: {ip_address}")



#monitoring
try:
    scp = subprocess.run(f"scp -o StrictHostKeyChecking=no -i olenakeypair.pem monitoring.sh ec2-user@{ip_address}:.", capture_output=True, text=True, shell=True) #security copy to the instance monitoring.sh
    print("Securely copied to the instance monitoring.sh. Return code: ", scp.returncode)
except Exception as e:
        print("Error. monitoring.sh was not copied: ", e)

try:
    chmod = subprocess.run(f"ssh -o StrictHostKeyChecking=no -i olenakeypair.pem ec2-user@{ip_address} 'chmod 700 monitoring.sh'", capture_output=True, text=True, shell=True)
    print("Execution permition set for monitoring.sh. ", chmod.stdout)
except Exception as e:
        print("Execution permition was not set: ", e)

try:
    upload = subprocess.run(f"ssh -o StrictHostKeyChecking=no -i olenakeypair.pem ec2-user@{ip_address} './monitoring.sh'", capture_output=True, text=True, shell=True)
    print("A monitoring script is uploaded  and runs remotely", upload.stdout)
except Exception as e:
        print("A monitoring script is NOT running:", e)




# --- S3 BUCKET CREATION ---
s3 = boto3.resource("s3", region_name='us-east-1')
s3client = boto3.client("s3", region_name='us-east-1')

bucket_name = generate_random_string()

try:
    s3.create_bucket(Bucket=bucket_name)
    print(f"Bucket created: {bucket_name}")

    s3client.delete_public_access_block(Bucket=bucket_name)

    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": ["s3:GetObject"],
            "Resource": f"arn:aws:s3:::{bucket_name}/*"
        }]
    }

    s3.Bucket(bucket_name).Policy().put(Policy=json.dumps(bucket_policy))
    print("Public read access granted.")

    # Enable static website hosting
    website_configuration = {
        'ErrorDocument': {'Key': 'error.html'},
        'IndexDocument': {'Suffix': 'index.html'},
    }
    s3.BucketWebsite(bucket_name).put(WebsiteConfiguration=website_configuration)

    # Create local files
    html_content = """
    <html><head><title>My S3 Website</title></head>
    <body>
        <h1>Welcome to my S3-hosted site!</h1>
        <img src="logo.jpg" alt="Logo" width="300"/>
    </body></html>
    """
    with open("index.html", "w") as f:
        f.write(html_content)

    subprocess.run("curl -O http://devops.setudemo.net/logo.jpg", shell=True)
    s3.Bucket(bucket_name).upload_file('logo.jpg', 'logo.jpg', ExtraArgs={'ContentType': 'image/jpeg'})
    s3.Bucket(bucket_name).upload_file('index.html', 'index.html', ExtraArgs={'ContentType': 'text/html'})

    # Save URLs to text file
    ec2_url = f"http://{instance.public_ip_address}/"
    s3_url = f"http://{bucket_name}.s3-website-us-east-1.amazonaws.com"

    with open("okhyzhniak-websites.txt", "w") as f:
        f.write(f"EC2 Website: {ec2_url}\n")
        f.write(f"S3 Website: {s3_url}\n")

    print("URLs saved to okhyzhniak-websites.txt")


    # Create AMI
    time.sleep(10) # give instance a few seconds to stabilize

    ec2_client = boto3.client('ec2', region_name='us-east-1')

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d-%f")
    ami_name = f"ok-{timestamp}"    


    response = ec2_client.create_image(
        InstanceId=instance.id,
        Name=ami_name,
        Description="AMI created after verifying httpd is running",
        NoReboot=True
    )



    ami_id = response['ImageId']
    print(f"AMI creation started successfully! AMI ID: {ami_id}")    


    #create cloud watch
    cloudwatch = boto3.client('cloudwatch', region_name='us-east-1')

    metrics = cloudwatch.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance.id}],
        StartTime=datetime.datetime.utcnow() - datetime.timedelta(minutes=10),
        EndTime=datetime.datetime.utcnow(),
        Period=300,
        Statistics=['Average']
    )

    print("Cloud Watch is created. Recent CPU utilization data points: ")
    for point in metrics['Datapoints']:
        print(point)



except Exception as e:
    print("Error creating:", e)
