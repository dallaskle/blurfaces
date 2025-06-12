#!/bin/bash

# Deployment script for BlurFaces FastAPI app
# Usage: ./deploy_fastapi.sh

set -e

echo "🚀 Starting deployment of BlurFaces FastAPI app to EC2..."

# Configuration
EC2_HOST="ec2-3-141-200-253.us-east-2.compute.amazonaws.com"
EC2_USER="ec2-user"
SSH_KEY="acm-blur.pem"
APP_DIR="/home/ec2-user/blurfaces"

echo "📦 Creating deployment package..."
# Create a temporary directory for deployment files
mkdir -p deploy_temp
cp blur_faces.py app.py requirements.txt README.md deploy_temp/
cp -r media deploy_temp/ 2>/dev/null || echo "⚠️  media directory not found, skipping..."
cp -r static deploy_temp/ 2>/dev/null || echo "⚠️  static directory not found, creating..."
mkdir -p deploy_temp/static
cp static/index.html deploy_temp/static/ 2>/dev/null || true

echo "🔄 Transferring files to EC2 instance..."
# Transfer files to EC2
scp -i "$SSH_KEY" -r deploy_temp/* "$EC2_USER@$EC2_HOST:~/"

echo "⚙️  Setting up FastAPI application on EC2 instance..."
# Connect to EC2 and set up the environment
ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" << 'EOF'
    # Update system packages
    sudo yum update -y
    
    # Install Python pip if not installed
    sudo yum install -y python3-pip python3-devel
    
    # Install system dependencies for face_recognition and OpenCV
    sudo yum install -y cmake gcc gcc-c++ make
    sudo yum install -y libX11-devel libXext-devel libXrender-devel libICE-devel libSM-devel
    
    # Install ffmpeg
    sudo yum install -y ffmpeg
    
    # Create app directory
    mkdir -p /home/ec2-user/blurfaces
    cd /home/ec2-user/blurfaces
    
    # Move files to app directory
    mv /home/ec2-user/blur_faces.py ./ 2>/dev/null || true
    mv /home/ec2-user/app.py ./ 2>/dev/null || true
    mv /home/ec2-user/requirements.txt ./ 2>/dev/null || true
    mv /home/ec2-user/README.md ./ 2>/dev/null || true
    mv /home/ec2-user/media ./ 2>/dev/null || true
    mv /home/ec2-user/static ./ 2>/dev/null || true
    
    # Create necessary directories
    mkdir -p uploads processed static
    
    # Install Python dependencies
    pip3 install --user -r requirements.txt
    
    # Create systemd service file
    sudo tee /etc/systemd/system/blurfaces.service > /dev/null << 'SERVICE'
[Unit]
Description=BlurFaces FastAPI Application
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/blurfaces
Environment=PATH=/home/ec2-user/.local/bin:/usr/bin:/bin
ExecStart=/home/ec2-user/.local/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE
    
    # Enable and start the service
    sudo systemctl daemon-reload
    sudo systemctl enable blurfaces.service
    sudo systemctl stop blurfaces.service 2>/dev/null || true
    sudo systemctl start blurfaces.service
    
    # Check service status
    sudo systemctl status blurfaces.service --no-pager
    
    # Configure firewall to allow port 8000
    sudo firewall-cmd --permanent --add-port=8000/tcp 2>/dev/null || true
    sudo firewall-cmd --reload 2>/dev/null || true
    
    # For Amazon Linux 2023, also check security group rules
    echo "⚠️  Make sure your EC2 security group allows inbound traffic on port 8000!"
    
    echo "✅ Deployment completed successfully!"
    echo "📍 App location: /home/ec2-user/blurfaces"
    echo "🌐 API URL: http://${EC2_HOST}:8000"
    echo "📊 Service logs: sudo journalctl -u blurfaces -f"
    
EOF

# Clean up temporary files
rm -rf deploy_temp

# Get the public IP
PUBLIC_IP=$(ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" "curl -s http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null)

echo ""
echo "🎉 Deployment completed! Your BlurFaces API is now available on EC2."
echo ""
echo "📌 Access your API at:"
echo "   🌐 http://$PUBLIC_IP:8000"
echo "   🌐 http://$EC2_HOST:8000"
echo ""
echo "💡 Useful commands:"
echo "   SSH to instance: ssh -i $SSH_KEY $EC2_USER@$EC2_HOST"
echo "   View logs: ssh -i $SSH_KEY $EC2_USER@$EC2_HOST 'sudo journalctl -u blurfaces -f'"
echo "   Restart service: ssh -i $SSH_KEY $EC2_USER@$EC2_HOST 'sudo systemctl restart blurfaces'"
echo ""
echo "⚠️  IMPORTANT: Make sure your EC2 security group allows inbound traffic on port 8000!" 