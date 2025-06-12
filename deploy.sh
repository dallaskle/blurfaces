#!/bin/bash

# Deployment script for blurfaces app
# Usage: ./deploy.sh

set -e

echo "🚀 Starting deployment of blurfaces app to EC2..."

# Configuration
EC2_HOST="ec2-3-141-200-253.us-east-2.compute.amazonaws.com"
EC2_USER="ec2-user"
SSH_KEY="acm-blur.pem"
APP_DIR="/home/ec2-user/blurfaces"

echo "📦 Creating deployment package..."
# Create a temporary directory for deployment files
mkdir -p deploy_temp
cp blur_faces.py requirements.txt README.md deploy_temp/
cp -r media deploy_temp/ 2>/dev/null || echo "⚠️  media directory not found, skipping..."

echo "🔄 Transferring files to EC2 instance..."
# Transfer files to EC2
scp -i "$SSH_KEY" -r deploy_temp/* "$EC2_USER@$EC2_HOST:~/"

echo "⚙️  Setting up environment on EC2 instance..."
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
    mv /home/ec2-user/requirements.txt ./ 2>/dev/null || true
    mv /home/ec2-user/README.md ./ 2>/dev/null || true
    mv /home/ec2-user/media ./ 2>/dev/null || true
    
    # Install Python dependencies
    pip3 install --user -r requirements.txt
    
    # Make the script executable
    chmod +x blur_faces.py
    
    echo "✅ Deployment completed successfully!"
    echo "📍 App location: /home/ec2-user/blurfaces"
    echo "🎯 Test the app with: python3 blur_faces.py --help"
    
EOF

# Clean up temporary files
rm -rf deploy_temp

echo "🎉 Deployment completed! Your blurfaces app is now available on EC2."
echo "💡 To connect to your instance: ssh -i acm-blur.pem ec2-user@ec2-3-141-200-253.us-east-2.compute.amazonaws.com"
echo "💡 To run the app: cd blurfaces && python3 blur_faces.py --help" 