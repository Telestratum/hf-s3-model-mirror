# Presign API Service Automated Deployment

Automated deployment system for the Presign API Python FastAPI service using systemd.

## Overview

This deployment automation:
- ✅ Packages Python source files (no compilation needed)
- ✅ Creates Python virtual environment on the server
- ✅ Installs dependencies with pip
- ✅ Generates systemd service files
- ✅ Packages everything into tar.gz release archives
- ✅ Provides one-command install on target servers
- ✅ Includes Envoy proxy configuration

## Quick Start - Single Command

### Package Release

```bash
cd /home/dayakar/hf-s3-model-mirror/deployment/deploy-automation

# Package everything with one command
./package-release.sh v1.2.0
```

This creates: `../../presign-api-release-v1.2.0.tar.gz`

---

## Step-by-Step Workflow

### Step 1: Package Release (Local Machine)

```bash
cd deployment/deploy-automation

# Package Python source and configs
./package-release.sh v1.2.0
```

This will:
- Copy Python source files (main.py, requirements.txt)
- Copy systemd service files
- Copy Envoy configuration
- Create environment template
- Generate VERSION file
- Create tar.gz archive with checksum

### Step 2: Transfer to Server

```bash
# From project root directory
cd /home/dayakar/hf-s3-model-mirror

# Transfer the release archive
scp presign-api-release-v1.2.0.tar.gz ubuntu@your-server:/home/ubuntu/releases/
```

### Step 3: Extract on Server

```bash
# SSH to server
ssh ubuntu@your-server

# Extract release
cd ~/releases
tar xzf presign-api-release-v1.2.0.tar.gz

# Verify extraction
ls -la presign-api-release-v1.2.0/
```

### Step 4: Install Service

```bash
cd presign-api-release-v1.2.0/scripts

# Install Python app, create venv, install systemd services
sudo ./install.sh install

# Configure environment (CRITICAL!)
sudo nano /opt/presign-api/presign_api/.env

# Enable services
sudo systemctl enable presign-api
sudo systemctl enable envoy-presign-api

# Start services
sudo ./install.sh start

# Check status
./install.sh status

# Test API
curl http://localhost:8000/health
```

---

## Release Package Structure

After running `./package-release.sh v1.2.0`:

```
presign-api-release-v1.2.0/
├── presign_api/                  # Python application
│   ├── main.py
│   └── requirements.txt
├── system/                       # Systemd service files
│   ├── presign-api.service
│   └── envoy-presign-api.service
├── etc/                          # Envoy configuration
│   └── envoy-presign-api.yaml
├── env/                          # Environment templates
│   └── .env.template
├── scripts/                      # Install scripts
│   ├── install.sh
│   └── uninstall.sh
└── VERSION                       # Build metadata
```

---

## Service Architecture

### Main Service
- **presign-api** - FastAPI service (port 8000)
  - Generates presigned S3 URLs for model downloads
  - Python 3.10+ with FastAPI framework
  - Runs in virtual environment

### Proxy
- **envoy-presign-api** - Envoy reverse proxy
  - External access point
  - Load balancing
  - Request routing

---

## Server Installation Paths

After running `install.sh`, files are deployed to:

```
/opt/presign-api/
├── presign_api/
│   ├── main.py
│   ├── requirements.txt
│   └── .env                       # Environment configuration
└── venv/                          # Python virtual environment
    ├── bin/
    │   └── python
    └── lib/

/etc/systemd/system/
├── presign-api.service
└── envoy-presign-api.service

/etc/envoy/
└── envoy-presign-api.yaml

/var/log/presign-api/
└── presign-api.log
```

---

## Python Virtual Environment

The installation creates an isolated Python virtual environment:

- **Location:** `/opt/presign-api/venv/`
- **Python:** System Python 3.10+
- **Dependencies:** Installed from requirements.txt
- **Activation:** Handled automatically by systemd

### Manual venv activation (if needed):

```bash
source /opt/presign-api/venv/bin/activate
```

---

## Management Commands

### Using install.sh (Recommended)

```bash
cd presign-api-release-v1.2.0/scripts

# Install everything
sudo ./install.sh install

# Start services
sudo ./install.sh start

# Stop all services
sudo ./install.sh stop

# Restart services
sudo ./install.sh restart

# Check status
./install.sh status

# Enable services on boot
sudo ./install.sh enable

# Update (reinstall Python source, restart)
sudo ./install.sh update

# Uninstall (removes systemd services, keeps app)
sudo ./install.sh uninstall

# Help
./install.sh help
```

### Using systemctl Directly

```bash
# Start service
sudo systemctl start presign-api

# Stop service
sudo systemctl stop presign-api

# Restart service
sudo systemctl restart presign-api

# Enable on boot
sudo systemctl enable presign-api

# Check status
sudo systemctl status presign-api

# View logs
sudo journalctl -u presign-api -f

# View last 100 lines
sudo journalctl -u presign-api -n 100
```

---

## Environment Configuration

### Critical Settings

Edit `/opt/presign-api/presign_api/.env`:

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-actual-access-key-id
AWS_SECRET_ACCESS_KEY=your-actual-secret-access-key

# S3 Configuration
S3_BUCKET=your-bucket-name
S3_PREFIX=models/

# Presigned URL Configuration
PRESIGN_EXPIRATION=3600  # URL valid for 1 hour

# API Configuration
API_PORT=8000
API_HOST=0.0.0.0

# Logging
LOG_LEVEL=info
LOG_FILE=/var/log/presign-api/presign-api.log
```

**Important:** Configure AWS credentials before starting the service!

---

## API Endpoints

The Presign API provides the following endpoints:

### Health Check
```bash
curl http://localhost:8000/health
```

### Generate Presigned URL
```bash
curl http://localhost:8000/presign?model_path=llm/ios/qwen2.5-0.5b/qwen2.5-0.5b.zip
```

Response:
```json
{
  "url": "https://your-bucket.s3.amazonaws.com/models/llm/ios/qwen2.5-0.5b/qwen2.5-0.5b.zip?...",
  "expires_in": 3600
}
```

---

## Logging

### Log Locations

- **Application logs:** `/var/log/presign-api/presign-api.log`
- **Systemd logs:** `journalctl -u presign-api`
- **Envoy logs:** Configured in envoy.yaml

### View Logs

```bash
# View application log
tail -f /var/log/presign-api/presign-api.log

# View systemd logs (real-time)
sudo journalctl -u presign-api -f

# View logs from last hour
sudo journalctl -u presign-api --since "1 hour ago"

# View only errors
sudo journalctl -u presign-api -p err
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check status
sudo systemctl status presign-api

# View recent logs
sudo journalctl -u presign-api -n 100

# Check Python source exists
ls -la /opt/presign-api/presign_api/

# Check venv
ls -la /opt/presign-api/venv/bin/python

# Test Python app manually
cd /opt/presign-api/presign_api
/opt/presign-api/venv/bin/python main.py
```

### AWS Credentials Issues

```bash
# Verify .env file exists
ls -la /opt/presign-api/presign_api/.env

# Check AWS credentials
cat /opt/presign-api/presign_api/.env | grep AWS_

# Test AWS connection manually
cd /opt/presign-api/presign_api
source /opt/presign-api/venv/bin/activate
python -c "import boto3; print(boto3.client('s3').list_buckets())"
```

### Port Conflicts

```bash
# Check what's using port 8000
sudo netstat -tulpn | grep :8000
sudo lsof -i :8000

# Check if service is already running
ps aux | grep presign-api
```

### Python Dependency Issues

```bash
# Reinstall dependencies
source /opt/presign-api/venv/bin/activate
pip install -r /opt/presign-api/presign_api/requirements.txt

# Check installed packages
pip list
```

---

## Updating Service

### Update Python Source

```bash
# Package new version
./package-release.sh v1.2.1

# Transfer to server
scp presign-api-release-v1.2.1.tar.gz ubuntu@server:/home/ubuntu/releases/

# On server: extract and update
cd ~/releases
tar xzf presign-api-release-v1.2.1.tar.gz
cd presign-api-release-v1.2.1/scripts
sudo ./install.sh update
```

### Update Dependencies Only

```bash
# On server
sudo systemctl stop presign-api
source /opt/presign-api/venv/bin/activate
pip install --upgrade -r /opt/presign-api/presign_api/requirements.txt
sudo systemctl start presign-api
```

---

## Prerequisites

### Local Machine Requirements
- Python 3.10+ (for packaging)
- Bash 4.0+
- tar, gzip

### Target Server Requirements
- Ubuntu 20.04+ or Debian 11+
- Python 3.10+
- python3-venv package
- Systemd
- Envoy proxy 1.24+

### Install Dependencies on Server

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and venv
sudo apt install python3 python3-pip python3-venv -y

# Install Envoy
curl -sL 'https://deb.dl.getenvoy.io/public/gpg.8115BA8E629CC074.key' | sudo gpg --dearmor -o /usr/share/keyrings/getenvoy-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/getenvoy-keyring.gpg] https://deb.dl.getenvoy.io/public/deb/ubuntu focal main" | sudo tee /etc/apt/sources.list.d/getenvoy.list
sudo apt update
sudo apt install getenvoy-envoy -y
```

---

## Security Considerations

1. **AWS Credentials:** Store in `.env` with 600 permissions, never commit to git
2. **User Isolation:** Service runs as `ubuntu` user, not root
3. **Firewall:** Configure UFW to restrict internal ports
4. **TLS/SSL:** Configure Envoy with TLS certificates
5. **S3 Bucket:** Keep private, use presigned URLs only
6. **URL Expiration:** Set reasonable expiration times (default: 1 hour)

### Firewall Configuration

```bash
# Allow SSH, HTTP, HTTPS
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Block internal API port from external access
sudo ufw deny 8000/tcp

# Enable firewall
sudo ufw enable
sudo ufw status
```

---

## Production Deployment Checklist

- [ ] Package service: `./package-release.sh v1.2.0`
- [ ] Transfer release archive to server
- [ ] Extract and verify package contents
- [ ] Run `sudo ./install.sh install`
- [ ] Configure AWS credentials in `.env`
- [ ] Configure S3 bucket and prefix
- [ ] Set presigned URL expiration time
- [ ] Configure Envoy TLS certificates
- [ ] Set up firewall rules
- [ ] Enable services: `sudo ./install.sh enable`
- [ ] Start services: `sudo ./install.sh start`
- [ ] Test health endpoint
- [ ] Test presigned URL generation
- [ ] Configure monitoring and alerting
- [ ] Set up log rotation
- [ ] Document rollback procedures
- [ ] Perform load testing
- [ ] Create backup of working configuration

---

## Integration with Mobile Apps

### Mobile App Flow

1. **Mobile app** requests model download → calls backend API
2. **Backend** calls presign-api → receives presigned S3 URL
3. **Backend** returns URL to mobile app
4. **Mobile app** downloads directly from S3 using presigned URL

**Benefits:**
- No AWS credentials on mobile devices
- Temporary URLs (auto-expire)
- Private S3 bucket
- Audit trail of all downloads

---

## Version History

- **v1.2.x** - Automated deployment with Python venv
- **v1.1.x** - FastAPI service with Envoy
- **v1.0.0** - Initial release

---

## Support

For issues:
1. Check service logs: `/var/log/presign-api/`
2. Check systemd logs: `journalctl -u presign-api`
3. Verify service status: `./install.sh status`
4. Test API: `curl http://localhost:8000/health`
5. Review this documentation

---

## License

Copyright © 2024-2026 PurpleHealth. All rights reserved.
