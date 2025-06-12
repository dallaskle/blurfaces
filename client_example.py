#!/usr/bin/env python3
"""
BlurFaces API Client Example

This script demonstrates how to use the BlurFaces API programmatically.
"""

import requests
import time
import sys
from pathlib import Path

# API base URL - update this with your EC2 instance URL
API_BASE_URL = "http://ec2-3-141-200-253.us-east-2.compute.amazonaws.com:8000"

def blur_all_faces(video_path):
    """Example: Blur all faces in a video"""
    
    print(f"📹 Uploading video: {video_path}")
    
    with open(video_path, 'rb') as f:
        files = {'video': f}
        data = {
            'model': 'hog',  # or 'cnn' for better accuracy
            'censor_type': 'gaussianblur',  # or 'pixelation' or 'facemasking'
            'count': 1
        }
        
        response = requests.post(f"{API_BASE_URL}/blur/all", files=files, data=data)
    
    if response.status_code != 200:
        print(f"❌ Error: {response.text}")
        return
    
    job_data = response.json()
    job_id = job_data['job_id']
    print(f"✅ Job submitted: {job_id}")
    
    # Poll for status
    while True:
        status_response = requests.get(f"{API_BASE_URL}/status/{job_id}")
        status_data = status_response.json()
        
        if status_data['status'] == 'processing':
            print(f"⏳ Processing... {status_data.get('progress', 0)}%")
        elif status_data['status'] == 'completed':
            print("✅ Processing completed!")
            download_url = f"{API_BASE_URL}{status_data['download_url']}"
            print(f"📥 Download URL: {download_url}")
            
            # Download the processed video
            output_path = f"processed_{Path(video_path).name}"
            download_response = requests.get(download_url)
            with open(output_path, 'wb') as f:
                f.write(download_response.content)
            print(f"💾 Saved to: {output_path}")
            break
        elif status_data['status'] == 'failed':
            print(f"❌ Processing failed: {status_data.get('error', 'Unknown error')}")
            break
        
        time.sleep(2)

def blur_specific_faces(video_path, reference_face_paths):
    """Example: Blur only specific faces that match reference images"""
    
    print(f"📹 Uploading video and {len(reference_face_paths)} reference face(s)")
    
    files = [('video', open(video_path, 'rb'))]
    for ref_path in reference_face_paths:
        files.append(('reference_faces', open(ref_path, 'rb')))
    
    data = {
        'model': 'hog',
        'censor_type': 'pixelation',
        'count': 1
    }
    
    response = requests.post(f"{API_BASE_URL}/blur/one", files=files, data=data)
    
    # Close all file handles
    for _, f in files:
        f.close()
    
    if response.status_code != 200:
        print(f"❌ Error: {response.text}")
        return
    
    job_data = response.json()
    job_id = job_data['job_id']
    print(f"✅ Job submitted: {job_id}")
    
    # Poll for status (same as above)
    while True:
        status_response = requests.get(f"{API_BASE_URL}/status/{job_id}")
        status_data = status_response.json()
        
        if status_data['status'] == 'processing':
            print(f"⏳ Processing... {status_data.get('progress', 0)}%")
        elif status_data['status'] == 'completed':
            print("✅ Processing completed!")
            download_url = f"{API_BASE_URL}{status_data['download_url']}"
            print(f"📥 Download URL: {download_url}")
            break
        elif status_data['status'] == 'failed':
            print(f"❌ Processing failed: {status_data.get('error', 'Unknown error')}")
            break
        
        time.sleep(2)

def main():
    """Main function with usage examples"""
    
    print("🎭 BlurFaces API Client Example\n")
    
    # Check if API is available
    try:
        response = requests.get(f"{API_BASE_URL}/health")
        if response.status_code == 200:
            print(f"✅ API is healthy: {response.json()}\n")
        else:
            print(f"❌ API health check failed")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to API at {API_BASE_URL}")
        print("Make sure the API is running and the URL is correct.")
        sys.exit(1)
    
    # Example 1: Blur all faces
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        print("Example 1: Blurring all faces")
        blur_all_faces(video_path)
    else:
        print("Usage examples:")
        print("  Blur all faces:")
        print("    python client_example.py video.mp4")
        print("")
        print("  Blur specific faces:")
        print("    python client_example.py video.mp4 face1.jpg face2.jpg")

if __name__ == "__main__":
    main() 