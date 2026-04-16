import oci
import os
import smtplib
import sys
from email.mime.text import MIMEText

# Config via environment variables (GitHub Secrets)
user = os.environ["OCI_USER_OCID"]
fingerprint = os.environ["OCI_FINGERPRINT"]
tenancy = os.environ["OCI_TENANCY_OCID"]
region = os.environ["OCI_REGION"]
private_key = os.environ["OCI_PRIVATE_KEY"]
gmail_user = os.environ["GMAIL_USER"]
gmail_password = os.environ["GMAIL_APP_PASSWORD"]

# Availability domains to try
AVAILABILITY_DOMAINS = [
    "CwBn:EU-FRANKFURT-1-AD-1",
    "CwBn:EU-FRANKFURT-1-AD-2",
    "CwBn:EU-FRANKFURT-1-AD-3",
]

# Instance config
SHAPE = "VM.Standard.A1.Flex"
OCPUS = 4
MEMORY_GB = 24
# Ubuntu 22.04 ARM image in Frankfurt (update if needed)
IMAGE_ID = "ocid1.image.oc1.eu-frankfurt-1.aaaaaaaav2pwhgbnbqcke5qylrfaijbbfbmj3hy7rxl6qzr5bdl3f7rliqwq"

def get_oci_config():
    """Build OCI config from environment variables."""
    import tempfile
    # Write private key to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as f:
        f.write(private_key)
        key_file = f.name
    
    config = {
        "user": user,
        "fingerprint": fingerprint,
        "tenancy": tenancy,
        "region": region,
        "key_file": key_file,
    }
    return config, key_file

def send_email(subject, body):
    """Send notification email via Gmail."""
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = gmail_user
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email failed: {e}")

def try_create_instance(compute_client, compartment_id, availability_domain):
    """Try to create an ARM instance in the given availability domain."""
    print(f"Trying {availability_domain}...")
    
    # Get subnet
    try:
        network_client = oci.core.VirtualNetworkClient(config)
        vcns = network_client.list_vcns(compartment_id=compartment_id).data
        if not vcns:
            print("No VCN found, creating default...")
            return False
        
        vcn_id = vcns[0].id
        subnets = network_client.list_subnets(
            compartment_id=compartment_id,
            vcn_id=vcn_id
        ).data
        
        if not subnets:
            print("No subnet found")
            return False
            
        subnet_id = subnets[0].id
    except Exception as e:
        print(f"Network error: {e}")
        return False

    # Instance details
    instance_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=compartment_id,
        availability_domain=availability_domain,
        shape=SHAPE,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=OCPUS,
            memory_in_gbs=MEMORY_GB,
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=IMAGE_ID,
            source_type="image",
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet_id,
            assign_public_ip=True,
        ),
        display_name="arm-instance-auto",
        metadata={
            "ssh_authorized_keys": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC791FKuowDyvI6PeJh5yU9UEcbeohEMbvuBoE2JBUZnNaaB1TTgm9d33UmGaBhnWwBfd59QMNYCffN/fFw/U6xgZmlFpQXWY1L6MEa2uWFVulQCRtXsXiKaGTz5e8YY7tdsYsDKHfy4GgN2xJYnUsmOf3tmD1/M8NASE/dEHmn8bInX4XewpWOzhdLgSfPF/wvhQr3nBV0qB58eJhOfBNAlAYdmBwUH0S1ShS6z6UgXocmuNXUXPeLe9jAsAFX7PAU1N8ZRsICftlIeiOLbP4h/nRw950vXaePO5lx3RLmz/t+eGya2+SAJPbBXzc4GE1iHl2CY3plPwzJWmPS8PLz ssh-key-2026-04-16"
        }
    )
    
    try:
        response = compute_client.launch_instance(instance_details)
        instance = response.data
        print(f"SUCCESS! Instance created: {instance.id}")
        print(f"State: {instance.lifecycle_state}")
        return instance
    except oci.exceptions.ServiceError as e:
        if e.status == 500 and "Out of host capacity" in str(e.message):
            print(f"No capacity in {availability_domain}")
        else:
            print(f"Error in {availability_domain}: {e.message}")
        return False

# Main
config, key_file = get_oci_config()
compute_client = oci.core.ComputeClient(config)

# Use tenancy as compartment (root)
compartment_id = tenancy

instance_created = False
for ad in AVAILABILITY_DOMAINS:
    result = try_create_instance(compute_client, compartment_id, ad)
    if result:
        instance_created = True
        send_email(
            "✅ Oracle ARM Instance aangemaakt!",
            f"Je Oracle Cloud ARM instantie is succesvol aangemaakt!\n\n"
            f"Instance ID: {result.id}\n"
            f"Availability Domain: {ad}\n"
            f"Regio: {region}\n\n"
            f"Log in op cloud.oracle.com om je instantie te bekijken."
        )
        break

if not instance_created:
    print("Geen capaciteit beschikbaar in alle availability domains. Volgende run probeert opnieuw.")
    sys.exit(0)  # Exit 0 zodat GitHub Actions niet faalt

# Cleanup temp key file
import os
try:
    os.unlink(key_file)
except:
    pass
