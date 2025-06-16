from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import os
import uuid
import tempfile
import shutil
from pathlib import Path
import asyncio
import aiohttp
import aiofiles
from datetime import datetime

# Import the blur faces functionality
from blur_faces import get_video_properties, get_face_encoding, get_blurred_face, decode_fourcc, has_audio
import cv2
import face_recognition
import ffmpeg
import numpy as np
from tqdm import trange

# Import optimized processor if available
try:
    from blur_faces_optimized import OptimizedVideoProcessor, process_video_optimized
    OPTIMIZED_AVAILABLE = True
    print("[INFO] Optimized video processor loaded successfully!")
except ImportError:
    OPTIMIZED_AVAILABLE = False
    print("[WARNING] Optimized processor not available, using standard processing")

app = FastAPI(title="BlurFaces API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set maximum file size (500MB)
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB in bytes

# Create directories for uploads and processed videos
UPLOAD_DIR = Path("uploads")
PROCESSED_DIR = Path("processed")
STATIC_DIR = Path("static")
UPLOAD_DIR.mkdir(exist_ok=True)
PROCESSED_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# Mount static files for processed videos
app.mount("/processed", StaticFiles(directory="processed"), name="processed")

# Store job status
job_status = {}

async def download_video_from_url(url: str, output_path: str) -> None:
    """Download video from URL to local file"""
    try:
        print(f"[DEBUG] Starting download from URL: {url}")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3600)) as session:
            async with session.get(url) as response:
                print(f"[DEBUG] Response status: {response.status}")
                print(f"[DEBUG] Response headers: {dict(response.headers)}")
                
                if response.status != 200:
                    error_text = await response.text()
                    raise HTTPException(400, f"Failed to download video from {url}. HTTP {response.status}. Server response: {error_text[:200]}...")
                
                # Check content length if available
                content_length = response.headers.get('content-length')
                if content_length:
                    size_mb = int(content_length) // (1024*1024)
                    print(f"[DEBUG] Video size: {size_mb}MB")
                    if int(content_length) > MAX_FILE_SIZE:
                        raise HTTPException(413, f"Video file too large ({size_mb}MB). Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")
                
                # Check content type
                content_type = response.headers.get('content-type', '')
                print(f"[DEBUG] Content type: {content_type}")
                if not any(video_type in content_type.lower() for video_type in ['video/', 'application/octet-stream', 'binary']):
                    print(f"[WARNING] Unexpected content type: {content_type}")
                
                # Download and save file
                print(f"[DEBUG] Starting file download to: {output_path}")
                downloaded = 0
                async with aiofiles.open(output_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded % (1024*1024) == 0:  # Log every MB
                            print(f"[DEBUG] Downloaded {downloaded // (1024*1024)}MB")
                
                print(f"[DEBUG] Download completed. Total size: {downloaded} bytes")
                        
    except aiohttp.ClientError as e:
        error_msg = f"Network error downloading video from {url}: {type(e).__name__}: {str(e)}"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(400, error_msg)
    except asyncio.TimeoutError as e:
        error_msg = f"Timeout downloading video from {url}. The download took too long."
        print(f"[ERROR] {error_msg}")
        raise HTTPException(408, error_msg)
    except Exception as e:
        error_msg = f"Unexpected error downloading video from {url}: {type(e).__name__}: {str(e)}"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(500, error_msg)

async def download_image_from_url(url: str, output_path: str) -> None:
    """Download reference image from URL to local file"""
    try:
        print(f"[DEBUG] Starting image download from URL: {url}")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            async with session.get(url) as response:
                print(f"[DEBUG] Image response status: {response.status}")
                
                if response.status != 200:
                    error_text = await response.text()
                    raise HTTPException(400, f"Failed to download image from {url}. HTTP {response.status}. Server response: {error_text[:200]}...")
                
                # Check content type
                content_type = response.headers.get('content-type', '')
                print(f"[DEBUG] Image content type: {content_type}")
                if not any(img_type in content_type.lower() for img_type in ['image/', 'application/octet-stream', 'binary']):
                    print(f"[WARNING] Unexpected image content type: {content_type}")
                
                # Download and save file
                async with aiofiles.open(output_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)
                
                print(f"[DEBUG] Image download completed: {output_path}")
                        
    except aiohttp.ClientError as e:
        error_msg = f"Network error downloading image from {url}: {type(e).__name__}: {str(e)}"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(400, error_msg)
    except Exception as e:
        error_msg = f"Unexpected error downloading image from {url}: {type(e).__name__}: {str(e)}"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(500, error_msg)

@app.get("/")
async def root():
    # Serve the HTML interface if it exists
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    return {
        "message": "Welcome to BlurFaces API",
        "endpoints": {
            "/blur/all": "Blur all faces in video",
            "/blur/one": "Blur specific faces in video (requires reference images)",
            "/blur/allexcept": "Blur all faces except specific ones (requires reference images)",
            "/status/{job_id}": "Check processing status",
            "/download/{job_id}": "Download processed video"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

async def process_video(
    job_id: str,
    video_path: str,
    mode: str,
    model: str = "hog",
    censor_type: str = "gaussianblur",
    count: int = 1,
    reference_faces: List[str] = None
):
    """Background task to process video"""
    try:
        job_status[job_id] = {"status": "processing", "progress": 0}
        
        # Output path
        output_path = PROCESSED_DIR / f"{job_id}.mp4"
        
        # Define progress callback
        def update_progress(progress):
            job_status[job_id]["progress"] = progress
        
        # Use optimized processor if available and model is HOG
        if OPTIMIZED_AVAILABLE and model == "hog":
            print(f"[INFO] Using OPTIMIZED processor for job {job_id}")
            try:
                processor = OptimizedVideoProcessor(model, censor_type, count)
                processor.process_video_optimized(
                    video_path, 
                    str(output_path), 
                    mode, 
                    reference_faces,
                    progress_callback=update_progress
                )
                
                # Update job status
                job_status[job_id] = {
                    "status": "completed",
                    "progress": 100,
                    "output_file": str(output_path),
                    "download_url": f"/download/{job_id}",
                    "processing_method": "optimized"
                }
                return
                
            except Exception as e:
                print(f"[WARNING] Optimized processing failed, falling back to standard: {e}")
                # Fall through to standard processing
        
        # Standard processing (fallback or when optimized not available)
        print(f"[INFO] Using STANDARD processor for job {job_id}")
        
        # Open video
        video_capture = cv2.VideoCapture(video_path)
        width, height, length, fps, fourcc, codec = get_video_properties(video_capture)
        
        temp_video_path = PROCESSED_DIR / f"{job_id}_temp.mp4"
        
        # Create video writer with fallback codec support
        # Try multiple codecs in order of preference
        codecs_to_try = ["mp4v", "XVID", "MJPG", "X264"]
        video_out = None
        
        for codec in codecs_to_try:
            try:
                test_fourcc = cv2.VideoWriter_fourcc(*codec)
                video_out = cv2.VideoWriter(
                    str(temp_video_path), test_fourcc, fps, (width, height)
                )
                # Test if the writer was created successfully
                if video_out.isOpened():
                    print(f"Successfully created VideoWriter with codec: {codec}")
                    break
                else:
                    video_out.release()
                    video_out = None
            except Exception as e:
                print(f"Failed to create VideoWriter with codec {codec}: {e}")
                if video_out:
                    video_out.release()
                    video_out = None
        
        if video_out is None:
            raise Exception("Could not create VideoWriter with any available codec")
        
        # Get reference encodings if needed
        reference_encodings = []
        if mode in ["one", "allexcept"] and reference_faces:
            for ref_face_path in reference_faces:
                try:
                    encoding = get_face_encoding(ref_face_path)
                    reference_encodings.append(encoding)
                except Exception as e:
                    print(f"Error loading reference face {ref_face_path}: {e}")
        
        # Process frames with more frequent progress updates
        for i in range(length + 1):
            ret, frame = video_capture.read()
            if not ret:
                break
            
            # Update progress more frequently
            if i % 5 == 0:  # Update every 5 frames
                progress = int((i / length) * 100)
                job_status[job_id]["progress"] = progress
            
            # Detect faces
            face_locations = face_recognition.face_locations(
                frame, number_of_times_to_upsample=count, model=model
            )
            
            if mode == "all":
                # Blur all faces
                for face_location in face_locations:
                    frame = get_blurred_face(frame, censor_type, face_location)
            
            elif mode == "one" and reference_encodings:
                # Blur only matching faces
                face_encodings = face_recognition.face_encodings(frame, face_locations)
                for face_encoding, face_location in zip(face_encodings, face_locations):
                    matches = face_recognition.compare_faces(reference_encodings, face_encoding)
                    if any(matches):
                        frame = get_blurred_face(frame, censor_type, face_location)
            
            elif mode == "allexcept" and reference_encodings:
                # Blur all except matching faces
                face_encodings = face_recognition.face_encodings(frame, face_locations)
                for face_encoding, face_location in zip(face_encodings, face_locations):
                    matches = face_recognition.compare_faces(reference_encodings, face_encoding)
                    if not any(matches):
                        frame = get_blurred_face(frame, censor_type, face_location)
            
            video_out.write(frame)
        
        # Release resources
        video_capture.release()
        video_out.release()
        # Removed cv2.destroyAllWindows() - no GUI windows to destroy
        
        # Add audio if present
        if has_audio(video_path):
            in_av = ffmpeg.input(video_path)
            blurred_video = ffmpeg.input(str(temp_video_path))
            stream = ffmpeg.output(
                blurred_video, in_av.audio, str(output_path),
                vcodec='libx264', crf=23, preset='fast'
            ).overwrite_output()
            ffmpeg.run(stream, quiet=True)
            os.remove(temp_video_path)
        else:
            shutil.move(str(temp_video_path), str(output_path))
        
        # Update job status
        job_status[job_id] = {
            "status": "completed",
            "progress": 100,
            "output_file": str(output_path),
            "download_url": f"/download/{job_id}",
            "processing_method": "standard"
        }
        
    except Exception as e:
        job_status[job_id] = {
            "status": "failed",
            "error": str(e)
        }
        raise
    finally:
        # Clean up uploaded files
        if os.path.exists(video_path):
            os.remove(video_path)
        if reference_faces:
            for ref_path in reference_faces:
                if os.path.exists(ref_path):
                    os.remove(ref_path)

@app.post("/blur/all")
async def blur_all_faces(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur all faces in the uploaded video"""
    
    # Validate inputs
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, "Model must be 'hog' or 'cnn'")
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, "Invalid censor type")
    
    # Check file size
    content = await video.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save uploaded video
    video_path = UPLOAD_DIR / f"{job_id}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(content)
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="all",
        model=model,
        censor_type=censor_type,
        count=count
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

@app.post("/blur/one")
async def blur_specific_faces(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    reference_faces: List[UploadFile] = File(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur only specific faces that match reference images"""
    
    if not reference_faces:
        raise HTTPException(400, "At least one reference face image is required")
    
    # Validate inputs
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, "Model must be 'hog' or 'cnn'")
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, "Invalid censor type")
    
    # Check video file size
    video_content = await video.read()
    if len(video_content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"Video file too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save uploaded video
    video_path = UPLOAD_DIR / f"{job_id}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video_content)
    
    # Save reference faces
    ref_paths = []
    for i, ref_face in enumerate(reference_faces):
        ref_path = UPLOAD_DIR / f"{job_id}_ref_{i}_{ref_face.filename}"
        with open(ref_path, "wb") as f:
            content = await ref_face.read()
            f.write(content)
        ref_paths.append(str(ref_path))
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="one",
        model=model,
        censor_type=censor_type,
        count=count,
        reference_faces=ref_paths
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

@app.post("/blur/allexcept")
async def blur_all_except_specific_faces(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    reference_faces: List[UploadFile] = File(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur all faces except those that match reference images"""
    
    if not reference_faces:
        raise HTTPException(400, "At least one reference face image is required")
    
    # Validate inputs
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, "Model must be 'hog' or 'cnn'")
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, "Invalid censor type")
    
    # Check video file size
    video_content = await video.read()
    if len(video_content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"Video file too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save uploaded video
    video_path = UPLOAD_DIR / f"{job_id}_{video.filename}"
    with open(video_path, "wb") as f:
        f.write(video_content)
    
    # Save reference faces
    ref_paths = []
    for i, ref_face in enumerate(reference_faces):
        ref_path = UPLOAD_DIR / f"{job_id}_ref_{i}_{ref_face.filename}"
        with open(ref_path, "wb") as f:
            content = await ref_face.read()
            f.write(content)
        ref_paths.append(str(ref_path))
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="allexcept",
        model=model,
        censor_type=censor_type,
        count=count,
        reference_faces=ref_paths
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

# URL-based endpoints for processing videos from URLs
@app.post("/blur/all-url")
async def blur_all_faces_from_url(
    background_tasks: BackgroundTasks,
    video_url: str = Form(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur all faces in a video downloaded from URL"""
    
    print(f"[DEBUG] Received URL request: video_url={video_url}, model={model}, censor_type={censor_type}")
    
    # Validate inputs
    if not video_url or not video_url.strip():
        raise HTTPException(400, "Video URL is required and cannot be empty")
    
    if not video_url.startswith(('http://', 'https://')):
        raise HTTPException(400, f"Invalid video URL format: '{video_url}'. URL must start with http:// or https://")
    
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, f"Invalid model '{model}'. Must be 'hog' (faster) or 'cnn' (more accurate)")
    
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, f"Invalid censor type '{censor_type}'. Must be 'gaussianblur', 'facemasking', or 'pixelation'")
    
    if count < 1 or count > 10:
        raise HTTPException(400, f"Invalid count '{count}'. Must be between 1 and 10")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    print(f"[DEBUG] Generated job ID: {job_id}")
    
    # Download video from URL
    video_filename = f"{job_id}_video.mp4"
    video_path = UPLOAD_DIR / video_filename
    
    try:
        print(f"[DEBUG] Starting video download for job {job_id}")
        await download_video_from_url(video_url, str(video_path))
        print(f"[DEBUG] Video download completed for job {job_id}")
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Failed to download video from URL: {type(e).__name__}: {str(e)}"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(500, error_msg)
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="all",
        model=model,
        censor_type=censor_type,
        count=count
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

@app.post("/blur/one-url")
async def blur_specific_faces_from_url(
    background_tasks: BackgroundTasks,
    video_url: str = Form(...),
    reference_face_urls: List[str] = Form(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur specific faces in a video downloaded from URL using reference images from URLs"""
    
    if not reference_face_urls:
        raise HTTPException(400, "At least one reference face URL is required")
    
    # Validate inputs
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, "Model must be 'hog' or 'cnn'")
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, "Invalid censor type")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Download video from URL
    video_filename = f"{job_id}_video.mp4"
    video_path = UPLOAD_DIR / video_filename
    
    try:
        await download_video_from_url(video_url, str(video_path))
    except Exception as e:
        raise e
    
    # Download reference face images
    ref_paths = []
    for i, ref_url in enumerate(reference_face_urls):
        ref_filename = f"{job_id}_ref_{i}.jpg"
        ref_path = UPLOAD_DIR / ref_filename
        try:
            await download_image_from_url(ref_url, str(ref_path))
            ref_paths.append(str(ref_path))
        except Exception as e:
            # Clean up any downloaded files
            if os.path.exists(video_path):
                os.remove(video_path)
            for cleanup_path in ref_paths:
                if os.path.exists(cleanup_path):
                    os.remove(cleanup_path)
            raise e
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="one",
        model=model,
        censor_type=censor_type,
        count=count,
        reference_faces=ref_paths
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

@app.post("/blur/allexcept-url")
async def blur_all_except_specific_faces_from_url(
    background_tasks: BackgroundTasks,
    video_url: str = Form(...),
    reference_face_urls: List[str] = Form(...),
    model: str = Form("hog"),
    censor_type: str = Form("gaussianblur"),
    count: int = Form(1)
):
    """Blur all faces except specific ones in a video downloaded from URL using reference images from URLs"""
    
    if not reference_face_urls:
        raise HTTPException(400, "At least one reference face URL is required")
    
    # Validate inputs
    if model not in ["hog", "cnn"]:
        raise HTTPException(400, "Model must be 'hog' or 'cnn'")
    if censor_type not in ["gaussianblur", "facemasking", "pixelation"]:
        raise HTTPException(400, "Invalid censor type")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Download video from URL
    video_filename = f"{job_id}_video.mp4"
    video_path = UPLOAD_DIR / video_filename
    
    try:
        await download_video_from_url(video_url, str(video_path))
    except Exception as e:
        raise e
    
    # Download reference face images
    ref_paths = []
    for i, ref_url in enumerate(reference_face_urls):
        ref_filename = f"{job_id}_ref_{i}.jpg"
        ref_path = UPLOAD_DIR / ref_filename
        try:
            await download_image_from_url(ref_url, str(ref_path))
            ref_paths.append(str(ref_path))
        except Exception as e:
            # Clean up any downloaded files
            if os.path.exists(video_path):
                os.remove(video_path)
            for cleanup_path in ref_paths:
                if os.path.exists(cleanup_path):
                    os.remove(cleanup_path)
            raise e
    
    # Start background processing
    background_tasks.add_task(
        process_video,
        job_id=job_id,
        video_path=str(video_path),
        mode="allexcept",
        model=model,
        censor_type=censor_type,
        count=count,
        reference_faces=ref_paths
    )
    
    return {
        "job_id": job_id,
        "status": "accepted",
        "check_status_url": f"/status/{job_id}"
    }

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Check the status of a video processing job"""
    
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    
    return job_status[job_id]

@app.get("/download/{job_id}")
async def download_processed_video(job_id: str):
    """Download the processed video"""
    
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    
    status = job_status[job_id]
    if status["status"] != "completed":
        raise HTTPException(400, f"Job is {status['status']}, not completed")
    
    output_path = Path(status["output_file"])
    if not output_path.exists():
        raise HTTPException(404, "Processed video file not found")
    
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=f"blurred_{job_id}.mp4"
    )

@app.delete("/cleanup/{job_id}")
async def cleanup_job(job_id: str):
    """Clean up processed video and job data"""
    
    if job_id not in job_status:
        raise HTTPException(404, "Job not found")
    
    # Remove processed video
    output_path = PROCESSED_DIR / f"{job_id}.mp4"
    if output_path.exists():
        os.remove(output_path)
    
    # Remove job status
    del job_status[job_id]
    
    return {"message": "Job cleaned up successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 