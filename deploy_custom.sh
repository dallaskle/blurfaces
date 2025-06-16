#!/bin/bash

# Customizable deployment script for BlurFaces FastAPI app
# Usage: ./deploy_custom.sh

set -e

# ============== CONFIGURATION ==============
# UPDATE THESE VALUES WITH YOUR EC2 INSTANCE DETAILS
EC2_HOST="3.137.166.178"
EC2_USER="ec2-user"  # Use 'ubuntu' if using Ubuntu AMI
SSH_KEY="acm-blur.pem"
APP_DIR="/home/ec2-user/blurfaces"  # Change to /home/ubuntu/blurfaces if using Ubuntu

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting deployment of BlurFaces FastAPI app to EC2...${NC}"

# Validate configuration
if [ "$EC2_HOST" = "YOUR_EC2_PUBLIC_DNS_OR_IP" ]; then
    echo -e "${RED}❌ Please update EC2_HOST in this script with your actual EC2 public DNS or IP address${NC}"
    echo "You can find this in AWS Console → EC2 → Instances → Select your instance"
    echo "Look for 'Public IPv4 DNS' or 'Public IPv4 address'"
    exit 1
fi

# Test SSH connection first
echo -e "${YELLOW}🔍 Testing SSH connection...${NC}"
if ssh -i "$SSH_KEY" -o ConnectTimeout=10 "$EC2_USER@$EC2_HOST" "echo 'SSH connection successful!'" ; then
    echo -e "${GREEN}✅ SSH connection successful!${NC}"
else
    echo -e "${RED}❌ SSH connection failed. Please check:${NC}"
    echo "1. EC2_HOST is correct"
    echo "2. Security group allows SSH (port 22) from your IP"
    echo "3. EC2 instance is running"
    echo "4. SSH key file has correct permissions (chmod 400 $SSH_KEY)"
    exit 1
fi

echo -e "${YELLOW}📦 Creating deployment package...${NC}"
# Create a temporary directory for deployment files
mkdir -p deploy_temp
cp blur_faces.py app.py requirements.txt README.md deploy_temp/
cp -r media deploy_temp/ 2>/dev/null || echo "⚠️  media directory not found, skipping..."
cp -r static deploy_temp/ 2>/dev/null || echo "⚠️  static directory not found, creating..."
mkdir -p deploy_temp/static

echo -e "${YELLOW}🔄 Transferring files to EC2 instance...${NC}"
# Transfer files to EC2
scp -i "$SSH_KEY" -r deploy_temp/* "$EC2_USER@$EC2_HOST:~/"

echo -e "${YELLOW}⚙️  Setting up FastAPI application on EC2 instance...${NC}"
# Connect to EC2 and set up the environment
ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" << EOF
    echo "📦 Updating system packages..."
    sudo yum update -y 2>/dev/null || sudo apt update -y
    
    echo "🐍 Installing Python and development tools..."
    # For Amazon Linux
    sudo yum install -y python3-pip python3-devel cmake gcc gcc-c++ make 2>/dev/null || \
    # For Ubuntu
    sudo apt install -y python3-pip python3-dev cmake build-essential
    
    echo "📺 Installing system dependencies for OpenCV and FFmpeg..."
    # For Amazon Linux
    sudo yum install -y libX11-devel libXext-devel libXrender-devel libICE-devel libSM-devel ffmpeg 2>/dev/null || \
    # For Ubuntu  
    sudo apt install -y libx11-dev libxext-dev libxrender-dev libice-dev libsm-dev ffmpeg
    
    echo "📁 Creating app directory..."
    mkdir -p $APP_DIR
    cd $APP_DIR
    
    echo "📂 Moving files to app directory..."
    mv ~/blur_faces.py ./ 2>/dev/null || true
    mv ~/app.py ./ 2>/dev/null || true
    mv ~/requirements.txt ./ 2>/dev/null || true
    mv ~/README.md ./ 2>/dev/null || true
    mv ~/media ./ 2>/dev/null || true
    mv ~/static ./ 2>/dev/null || true
    
    # Create necessary directories
    mkdir -p uploads processed static
    
    echo "🔧 Installing Python dependencies..."
    pip3 install --user -r requirements.txt
    
    echo "🛠️  Creating systemd service..."
    sudo tee /etc/systemd/system/blurfaces.service > /dev/null << 'SERVICE'
[Unit]
Description=BlurFaces FastAPI Application
After=network.target

[Service]
Type=simple
User=$EC2_USER
WorkingDirectory=$APP_DIR
Environment=PATH=/home/$EC2_USER/.local/bin:/usr/bin:/bin
ExecStart=/home/$EC2_USER/.local/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE
    
    echo "🚀 Starting the service..."
    sudo systemctl daemon-reload
    sudo systemctl enable blurfaces.service
    sudo systemctl stop blurfaces.service 2>/dev/null || true
    sudo systemctl start blurfaces.service
    
    echo "📊 Checking service status..."
    sudo systemctl status blurfaces.service --no-pager
    
    echo "🔥 Configuring firewall..."
    # For Amazon Linux
    sudo firewall-cmd --permanent --add-port=8000/tcp 2>/dev/null || \
    # For Ubuntu
    sudo ufw allow 8000 2>/dev/null || true
    
    sudo firewall-cmd --reload 2>/dev/null || true
    
    echo "✅ Deployment completed successfully!"
    echo "📍 App location: $APP_DIR"
    echo "🌐 API URL: http://$EC2_HOST:8000"
    echo "📊 Service logs: sudo journalctl -u blurfaces -f"
EOF

# Clean up temporary files
rm -rf deploy_temp

# Get the public IP
echo -e "${YELLOW}🔍 Getting public IP address...${NC}"
PUBLIC_IP=\$(ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" "curl -s http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null)

echo ""
echo -e "${GREEN}🎉 Deployment completed! Your BlurFaces API is now available on EC2.${NC}"
echo ""
echo -e "${GREEN}📌 Access your API at:${NC}"
echo "   🌐 http://\$PUBLIC_IP:8000"
echo "   🌐 http://$EC2_HOST:8000"
echo ""
echo -e "${YELLOW}💡 Useful commands:${NC}"
echo "   SSH to instance: ssh -i $SSH_KEY $EC2_USER@$EC2_HOST"
echo "   View logs: ssh -i $SSH_KEY $EC2_USER@$EC2_HOST 'sudo journalctl -u blurfaces -f'"
echo "   Restart service: ssh -i $SSH_KEY $EC2_USER@$EC2_HOST 'sudo systemctl restart blurfaces'"
echo ""
echo -e "${RED}⚠️  IMPORTANT: Make sure your EC2 security group allows inbound traffic on port 8000!${NC}"
echo -e "${YELLOW}   AWS Console → EC2 → Security Groups → Your Security Group → Edit inbound rules${NC}"
echo -e "${YELLOW}   Add rule: Type=Custom TCP, Port Range=8000, Source=0.0.0.0/0${NC}" 