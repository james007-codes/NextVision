from flask import Flask, request, jsonify, render_template, Response
from picamera2 import Picamera2
import threading
import time
from flask_socketio import SocketIO, emit
import cv2
from threading import Lock
import os
from datetime import datetime

lock = Lock()
app = Flask(__name__)
socketio = SocketIO(app)
recording = False
camera_lock = threading.Lock()
VIDEO_DIR = 'static'
comments = {}  # Dictionary to store comments for each video
streaming = False  # Flag to control streaming
frames_buffer = []  # Buffer to store frames during streaming

# Ensure the static directory exists
if not os.path.exists(VIDEO_DIR):
    os.makedirs(VIDEO_DIR)

# Initialize the camera safely
def init_camera():
    global camera
    with camera_lock:
        try:
            if 'camera' in globals():
                camera.close()  # Close existing camera instance if it exists
            camera = Picamera2()
            camera.start()
        except Exception as e:
            print(f"Camera initialization error: {e}")

init_camera()

# Function to record video
def record_video():
    global recording
    with camera_lock:
        if recording:
            return  # Prevent multiple recordings
        
        recording = True
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_file = os.path.join(VIDEO_DIR, f"{timestamp}_output.mp4")

        try:
            camera.start_and_record_video(video_file)
            lock.acquire()  # Simulate recording duration
            camera.stop_recording()
            lock.release()
        except Exception as e:
            print(f"Recording error: {e}")
        finally:
            recording = False  # Ensure recording flag is reset

@app.route('/')
def index():
    video_files = [f for f in os.listdir(VIDEO_DIR) if f.endswith('.mp4')]
    video_files.sort(reverse=True)  # Sort by newest first
    return render_template('index.html', recording=recording, video_files=video_files, comments=comments)

@app.route('/start')
def start_recording():
    global recording
    with camera_lock:
        if not recording:
            lock.acquire()
            threading.Thread(target=record_video, daemon=True).start()
    return ('', 204)

@app.route('/stop')
def stop_recording():
    lock.release()
    return ('', 204)

@app.route('/submit_comment', methods=['POST'])
def submit_comment():
    data = request.get_json()
    video = data['video']
    comment = data['comment']

    if video not in comments:
        comments[video] = []
    comments[video].append(comment)

    return ('', 204)  # No content response

@app.route('/comments')
def get_comments():
    video = request.args.get('video')
    return jsonify({'comments': comments.get(video, [])})

def capture_frames():
    global streaming, frames_buffer
    while True:
        if streaming:
            frame = camera.capture_array()
            if frame is not None:
                # Convert from RGB to BGR for OpenCV
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                # Store frame for video saving
                frames_buffer.append(frame)
                # Convert the frame to JPEG format for streaming
                _, buffer = cv2.imencode('.jpg', frame)
                # Emit the frame to the WebSocket
                socketio.emit('video_frame', {'image': buffer.tobytes()})
            time.sleep(0.1)  # Adjust the sleep time as needed
        else:
            time.sleep(0.1)

@socketio.on('start_stream')
def handle_start_stream():
    global streaming, frames_buffer
    if not streaming:
        streaming = True
        frames_buffer = []  # Clear previous frames
        print("Streaming started")

@socketio.on('stop_stream')
def handle_stop_stream():
    global streaming, frames_buffer
    if streaming:
        streaming = False
        print("Streaming stopped")
        
        if len(frames_buffer) > 0:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            video_file = os.path.join(VIDEO_DIR, f"{timestamp}_stream.mp4")
            
            # Get frame dimensions from first frame
            height, width, _ = frames_buffer[0].shape
            
            # Use proper video writer settings
            fourcc = cv2.VideoWriter_fourcc(*'avc1')  # or 'mp4v'
            fps = 20.0  # Match your camera's FPS
            
            try:
                out = cv2.VideoWriter(video_file, fourcc, fps, (width, height))
                
                for frame in frames_buffer:
                    out.write(frame)
                out.release()
                print(f"Successfully saved stream as {video_file}")
                
                # Verify the file was created properly
                if os.path.exists(video_file) and os.path.getsize(video_file) > 0:
                    socketio.emit('new_video', {'filename': os.path.basename(video_file)})
                else:
                    print("Error: Saved video file is empty")
                
            except Exception as e:
                print(f"Error saving video: {e}")
            finally:
                frames_buffer = []

if __name__ == '_main_':
    # Start the frame capture thread
    threading.Thread(target=capture_frames, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=False)
