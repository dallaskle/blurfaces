import os
import cv2
import face_recognition
import numpy as np
from multiprocessing import Pool, cpu_count
from concurrent.futures import ProcessPoolExecutor, as_completed
import ffmpeg
from pathlib import Path
import time
from functools import partial

class OptimizedVideoProcessor:
    def __init__(self, model='hog', censor_type='gaussianblur', count=1):
        self.model = model
        self.censor_type = censor_type
        self.count = count
        self.scale_factor = 0.5  # Process at 50% resolution for face detection
        self.skip_frames = 2  # Process every 2nd frame for face detection
        self.batch_size = 32  # Process 32 frames at once (increased for more cores)
        self.num_workers = min(cpu_count(), 8)  # Use up to 8 cores on c4.2xlarge
        print(f"[OPTIMIZED] Detected {cpu_count()} CPU cores, using {self.num_workers} workers")
        
    def detect_faces_scaled(self, frame):
        """Detect faces at lower resolution for speed"""
        # Downscale for detection
        height, width = frame.shape[:2]
        small_frame = cv2.resize(frame, None, fx=self.scale_factor, fy=self.scale_factor)
        
        # Detect faces on smaller frame
        face_locations = face_recognition.face_locations(
            small_frame, 
            number_of_times_to_upsample=self.count, 
            model=self.model
        )
        
        # Scale locations back to original size
        scaled_locations = []
        for top, right, bottom, left in face_locations:
            scaled_locations.append((
                int(top / self.scale_factor),
                int(right / self.scale_factor),
                int(bottom / self.scale_factor),
                int(left / self.scale_factor)
            ))
        
        return scaled_locations
    
    def get_blurred_face_fast(self, frame, face_location):
        """Optimized blur function"""
        top, right, bottom, left = face_location
        
        # Add boundary checks
        height, width = frame.shape[:2]
        top = max(0, top)
        left = max(0, left)
        bottom = min(height, bottom)
        right = min(width, right)
        
        if self.censor_type == 'facemasking':
            frame[top:bottom, left:right] = 0
        elif self.censor_type == 'pixelation':
            face_region = frame[top:bottom, left:right]
            # Faster pixelation
            small = cv2.resize(face_region, (8, 8), interpolation=cv2.INTER_LINEAR)
            pixelated = cv2.resize(small, (right-left, bottom-top), interpolation=cv2.INTER_NEAREST)
            frame[top:bottom, left:right] = pixelated
        else:  # gaussianblur
            face_region = frame[top:bottom, left:right]
            # Use separable filter for faster blur
            blurred = cv2.GaussianBlur(face_region, (21, 21), 0)
            frame[top:bottom, left:right] = blurred
        
        return frame

    def process_frame_batch(self, frames, face_locations_batch, reference_encodings=None, mode='all'):
        """Process a batch of frames in parallel"""
        processed_frames = []
        
        for frame, face_locations in zip(frames, face_locations_batch):
            if mode == 'all':
                # Blur all faces
                for face_location in face_locations:
                    frame = self.get_blurred_face_fast(frame, face_location)
            
            elif mode == 'one' and reference_encodings:
                # Get face encodings for this frame
                if face_locations:
                    face_encodings = face_recognition.face_encodings(frame, face_locations)
                    for face_encoding, face_location in zip(face_encodings, face_locations):
                        # Check if this face matches any reference
                        matches = face_recognition.compare_faces(reference_encodings, face_encoding, tolerance=0.6)
                        if any(matches):
                            frame = self.get_blurred_face_fast(frame, face_location)
            
            elif mode == 'allexcept' and reference_encodings:
                # Get face encodings for this frame
                if face_locations:
                    face_encodings = face_recognition.face_encodings(frame, face_locations)
                    for face_encoding, face_location in zip(face_encodings, face_locations):
                        # Blur faces that DON'T match references
                        matches = face_recognition.compare_faces(reference_encodings, face_encoding, tolerance=0.6)
                        if not any(matches):
                            frame = self.get_blurred_face_fast(frame, face_location)
            
            processed_frames.append(frame)
        
        return processed_frames

    def process_video_optimized(self, video_path, output_path, mode='all', reference_faces=None, progress_callback=None):
        """Main optimized video processing function"""
        print(f"[OPTIMIZED] Processing with {self.num_workers} workers")
        
        # Open video
        video_capture = cv2.VideoCapture(video_path)
        fps = video_capture.get(cv2.CAP_PROP_FPS)
        width = int(video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Create video writer
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        temp_output = str(output_path).replace('.mp4', '_temp.mp4')
        video_writer = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))
        
        # Get reference encodings if needed
        reference_encodings = []
        if mode in ['one', 'allexcept'] and reference_faces:
            for ref_path in reference_faces:
                try:
                    ref_image = face_recognition.load_image_file(ref_path)
                    ref_encodings = face_recognition.face_encodings(ref_image)
                    if ref_encodings:
                        reference_encodings.append(ref_encodings[0])
                except Exception as e:
                    print(f"Error loading reference face {ref_path}: {e}")
        
        # Process video in batches
        frame_count = 0
        last_face_locations = []
        frames_buffer = []
        face_locations_buffer = []
        
        with ProcessPoolExecutor(max_workers=self.num_workers) as executor:
            while True:
                ret, frame = video_capture.read()
                if not ret:
                    break
                
                # Smart frame skipping for face detection
                if frame_count % self.skip_frames == 0:
                    # Detect faces on this frame
                    face_locations = self.detect_faces_scaled(frame)
                    last_face_locations = face_locations
                else:
                    # Reuse previous face locations (assuming faces don't move much)
                    face_locations = last_face_locations
                
                # Add to buffer
                frames_buffer.append(frame)
                face_locations_buffer.append(face_locations)
                
                # Process batch when full
                if len(frames_buffer) >= self.batch_size:
                    # Process this batch
                    processed_frames = self.process_frame_batch(
                        frames_buffer, 
                        face_locations_buffer,
                        reference_encodings,
                        mode
                    )
                    
                    # Write processed frames
                    for processed_frame in processed_frames:
                        video_writer.write(processed_frame)
                    
                    # Clear buffers
                    frames_buffer = []
                    face_locations_buffer = []
                
                # Update progress
                frame_count += 1
                if progress_callback and frame_count % 10 == 0:
                    progress = int((frame_count / total_frames) * 100)
                    progress_callback(progress)
            
            # Process remaining frames
            if frames_buffer:
                processed_frames = self.process_frame_batch(
                    frames_buffer, 
                    face_locations_buffer,
                    reference_encodings,
                    mode
                )
                for processed_frame in processed_frames:
                    video_writer.write(processed_frame)
        
        # Clean up
        video_capture.release()
        video_writer.release()
        
        # Add audio back if present
        try:
            if self.has_audio(video_path):
                print("[OPTIMIZED] Adding audio track...")
                in_av = ffmpeg.input(video_path)
                video_stream = ffmpeg.input(temp_output)
                stream = ffmpeg.output(
                    video_stream, in_av.audio, str(output_path),
                    vcodec='libx264', crf=23, preset='fast'
                ).overwrite_output()
                ffmpeg.run(stream, quiet=True)
                os.remove(temp_output)
            else:
                os.rename(temp_output, output_path)
        except Exception as e:
            print(f"[OPTIMIZED] Error adding audio: {e}")
            os.rename(temp_output, output_path)
        
        if progress_callback:
            progress_callback(100)
    
    def has_audio(self, file_path):
        """Check if video has audio track"""
        try:
            streams = ffmpeg.probe(file_path)['streams']
            return any(stream['codec_type'] == 'audio' for stream in streams)
        except:
            return False

# Convenience function for backward compatibility
def process_video_optimized(video_path, output_path, mode='all', model='hog', 
                          censor_type='gaussianblur', count=1, reference_faces=None, 
                          progress_callback=None):
    """Wrapper function for optimized processing"""
    processor = OptimizedVideoProcessor(model, censor_type, count)
    processor.process_video_optimized(video_path, output_path, mode, reference_faces, progress_callback) 