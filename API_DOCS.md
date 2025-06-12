# BlurFaces API Documentation

## Overview

BlurFaces API is a FastAPI-based web service that provides face blurring capabilities for videos. It supports three modes of operation:

1. **Blur All** - Blur all detected faces in a video
2. **Blur Specific** - Blur only faces that match reference images
3. **Blur All Except** - Blur all faces except those that match reference images

## Base URL

```
http://your-ec2-instance:8000
```

## Endpoints

### 1. Health Check

Check if the API is running and healthy.

```
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000000"
}
```

### 2. Blur All Faces

Blur all detected faces in the uploaded video.

```
POST /blur/all
```

**Request:**
- `video` (file): Video file to process
- `model` (string): Face detection model - "hog" (faster) or "cnn" (more accurate)
- `censor_type` (string): Type of blur - "gaussianblur", "pixelation", or "facemasking"
- `count` (integer): Number of times to upsample image for face detection (default: 1)

**Response:**
```json
{
  "job_id": "uuid-string",
  "status": "accepted",
  "check_status_url": "/status/{job_id}"
}
```

### 3. Blur Specific Faces

Blur only faces that match the provided reference images.

```
POST /blur/one
```

**Request:**
- `video` (file): Video file to process
- `reference_faces` (files): One or more reference face images
- `model` (string): Face detection model - "hog" or "cnn"
- `censor_type` (string): Type of blur - "gaussianblur", "pixelation", or "facemasking"
- `count` (integer): Number of times to upsample (default: 1)

**Response:**
```json
{
  "job_id": "uuid-string",
  "status": "accepted",
  "check_status_url": "/status/{job_id}"
}
```

### 4. Blur All Except Specific Faces

Blur all faces except those that match the provided reference images.

```
POST /blur/allexcept
```

**Request:**
- `video` (file): Video file to process
- `reference_faces` (files): One or more reference face images to keep unblurred
- `model` (string): Face detection model - "hog" or "cnn"
- `censor_type` (string): Type of blur - "gaussianblur", "pixelation", or "facemasking"
- `count` (integer): Number of times to upsample (default: 1)

**Response:**
```json
{
  "job_id": "uuid-string",
  "status": "accepted",
  "check_status_url": "/status/{job_id}"
}
```

### 5. Check Job Status

Check the processing status of a video job.

```
GET /status/{job_id}
```

**Response (Processing):**
```json
{
  "status": "processing",
  "progress": 45
}
```

**Response (Completed):**
```json
{
  "status": "completed",
  "progress": 100,
  "output_file": "processed/job-id.mp4",
  "download_url": "/download/{job_id}"
}
```

**Response (Failed):**
```json
{
  "status": "failed",
  "error": "Error message"
}
```

### 6. Download Processed Video

Download the processed video file.

```
GET /download/{job_id}
```

**Response:** Binary video file (MP4)

### 7. Clean Up Job

Remove processed video and job data.

```
DELETE /cleanup/{job_id}
```

**Response:**
```json
{
  "message": "Job cleaned up successfully"
}
```

## Examples

### Using cURL

**Blur all faces:**
```bash
curl -X POST http://your-ec2:8000/blur/all \
  -F "video=@video.mp4" \
  -F "model=hog" \
  -F "censor_type=gaussianblur"
```

**Blur specific faces:**
```bash
curl -X POST http://your-ec2:8000/blur/one \
  -F "video=@video.mp4" \
  -F "reference_faces=@person1.jpg" \
  -F "reference_faces=@person2.jpg" \
  -F "model=cnn" \
  -F "censor_type=pixelation"
```

**Check status:**
```bash
curl http://your-ec2:8000/status/{job_id}
```

**Download result:**
```bash
curl -O http://your-ec2:8000/download/{job_id}
```

### Using Python

See `client_example.py` for a complete Python client implementation.

```python
import requests

# Upload video to blur all faces
with open('video.mp4', 'rb') as f:
    files = {'video': f}
    data = {'model': 'hog', 'censor_type': 'gaussianblur'}
    response = requests.post('http://your-ec2:8000/blur/all', files=files, data=data)
    
job_id = response.json()['job_id']

# Check status
status = requests.get(f'http://your-ec2:8000/status/{job_id}').json()
print(f"Status: {status['status']}, Progress: {status.get('progress', 0)}%")
```

## Notes

- Video processing is asynchronous - jobs are queued and processed in the background
- Progress is reported as a percentage during processing
- Processed videos are stored temporarily and should be downloaded promptly
- The `cnn` model is more accurate but slower than `hog`
- Higher `count` values can detect smaller faces but increase processing time
- Make sure your EC2 security group allows inbound traffic on port 8000 