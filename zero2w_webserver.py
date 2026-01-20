#!/usr/bin/env python3
"""
Raspberry Pi Zero 2 W - HTTP Web Server with USB Serial Communication
Serves a webpage accessible at http://<ip_address>/vex

Requirements:
    pip install flask pyserial

Run with:
    sudo python3 zero2w_webserver.py

Access from browser:
    http://192.168.1.126/vex
"""

import os
import socket
import threading
import time
from collections import deque
from flask import Flask, render_template, jsonify, request

# Serial communication
import serial
import glob

# Get the directory where this script is located (for systemd compatibility)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ==================== CONFIGURATION ====================
HOST = "0.0.0.0"  # Listen on all interfaces
PORT = 80         # HTTP default port (requires sudo on Linux)
# Use port 8080 if you don't want to run as root:
# PORT = 8080

# USB Serial Configuration
# VEX Brain always appears as the 2nd /dev/ttyACM* device
USB_BAUD_RATE = 115200
RECONNECT_INTERVAL = 2  # Seconds between reconnection attempts

# ==================== GLOBALS ====================
serial_port = None
current_usb_port = None  # Track the currently connected port
received_messages = deque(maxlen=100)  # Store last 100 received messages
serial_lock = threading.Lock()
running = True

# ==================== FLASK APP ====================
app = Flask(__name__, template_folder=os.path.join(SCRIPT_DIR, 'templates'))

# ==================== USB SERIAL FUNCTIONS ====================
def setup_serial():
    """Set up the USB serial connection. VEX Brain is always the 2nd ttyACM device."""
    global serial_port, current_usb_port
    
    # Close existing connection if any
    if serial_port:
        try:
            serial_port.close()
        except:
            pass
        serial_port = None
        current_usb_port = None
    
    # Find available ttyACM ports (VEX Brain is always the 2nd one)
    acm_ports = sorted(glob.glob('/dev/ttyACM*'))
    
    if len(acm_ports) < 2:
        print(f"Found {len(acm_ports)} ttyACM port(s), need at least 2 for VEX Brain.")
        return False
    
    # VEX Brain is always the 2nd port (index 1)
    target_port = acm_ports[1]
    print(f"Found ttyACM ports: {acm_ports} -> Using {target_port} (VEX Brain)")
    
    try:
        serial_port = serial.Serial(
            port=target_port,
            baudrate=USB_BAUD_RATE,
            timeout=1
        )
        serial_port.flush()
        current_usb_port = target_port
        print(f"Connected to {target_port} at {USB_BAUD_RATE} baud.")
        return True
    except Exception as e:
        print(f"Could not open {target_port}: {e}")
        serial_port = None
        current_usb_port = None
        return False


def serial_receive_thread():
    """Background thread: continuously reads from USB serial with auto-reconnect."""
    global received_messages, serial_port, current_usb_port, running
    
    message_id = 0
    last_reconnect_attempt = 0
    
    while running:
        try:
            # Check if we have a valid connection
            if serial_port and serial_port.is_open:
                try:
                    if serial_port.in_waiting > 0:
                        line = serial_port.readline().decode('utf-8', errors='ignore').rstrip()
                        if line:
                            message_id += 1
                            timestamp = time.strftime('%H:%M:%S')
                            with serial_lock:
                                received_messages.append({
                                    'id': message_id,
                                    'text': line,
                                    'timestamp': timestamp
                                })
                            print(f"[VEX RX]: {line}")
                except (serial.SerialException, OSError) as e:
                    # Serial port was disconnected
                    print(f"Serial connection lost: {e}")
                    try:
                        serial_port.close()
                    except:
                        pass
                    serial_port = None
                    current_usb_port = None
            else:
                # No connection - try to reconnect periodically
                current_time = time.time()
                if current_time - last_reconnect_attempt >= RECONNECT_INTERVAL:
                    last_reconnect_attempt = current_time
                    print("USB disconnected. Scanning for available ports...")
                    if setup_serial():
                        print("USB serial reconnected successfully!")
                    
        except Exception as e:
            print(f"Serial thread error: {e}")
        
        time.sleep(0.05)  # Small delay to prevent CPU spinning


def send_to_serial(message):
    """Send a message to the USB serial port."""
    global serial_port, current_usb_port
    
    if serial_port and serial_port.is_open:
        try:
            serial_port.write((message + "\n").encode('utf-8'))
            print(f"[VEX TX]: {message}")
            return True, "Message sent"
        except (serial.SerialException, OSError) as e:
            # Connection lost during send
            print(f"Serial send failed, connection lost: {e}")
            try:
                serial_port.close()
            except:
                pass
            serial_port = None
            current_usb_port = None
            return False, "USB connection lost"
        except Exception as e:
            return False, str(e)
    else:
        return False, "USB serial not connected"


# ==================== ROUTES ====================
@app.route('/')
def home():
    """Redirect to /vex page."""
    return '<html><head><meta http-equiv="refresh" content="0;url=/vex"></head></html>'


@app.route('/vex')
def vex_page():
    """Serve the main VEX communication page."""
    usb_connected = serial_port is not None and serial_port.is_open
    return render_template(
        'vex.html',
        usb_connected=usb_connected,
        usb_port=current_usb_port or "N/A",
        baud_rate=USB_BAUD_RATE
    )


@app.route('/api/send', methods=['POST'])
def api_send():
    """Send a message to USB serial."""
    data = request.get_json()
    message = data.get('message', '')
    
    if not message:
        return jsonify({'status': 'error', 'message': 'Empty message'})
    
    success, msg = send_to_serial(message)
    
    if success:
        return jsonify({'status': 'ok', 'message': msg})
    else:
        return jsonify({'status': 'error', 'message': msg})


@app.route('/api/receive', methods=['GET'])
def api_receive():
    """Get received messages from USB serial."""
    last_id = int(request.args.get('last_id', 0))
    
    with serial_lock:
        new_messages = [msg for msg in received_messages if msg['id'] > last_id]
    
    usb_connected = serial_port is not None and serial_port.is_open
    
    return jsonify({
        'messages': new_messages,
        'usb_connected': usb_connected,
        'usb_port': current_usb_port or "N/A"
    })


@app.route('/api/status', methods=['GET'])
def api_status():
    """Return server and USB status."""
    usb_connected = serial_port is not None and serial_port.is_open
    return jsonify({
        'status': 'ok',
        'usb_connected': usb_connected,
        'usb_port': current_usb_port or "N/A",
        'baud_rate': USB_BAUD_RATE
    })


# ==================== UTILITY FUNCTIONS ====================
def get_local_ip():
    """Get the local IP address of the Pi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ==================== MAIN ====================
def main():
    global running
    
    print("\n" + "=" * 60)
    print("   Raspberry Pi Zero 2 W - VEX USB Web Interface")
    print("=" * 60 + "\n")
    
    # Get local IP
    local_ip = get_local_ip()
    
    print(f"IP Address: {local_ip}")
    print(f"Web Port:   {PORT}")
    print(f"USB Target: 2nd /dev/ttyACM* device (VEX Brain)")
    print(f"Baud Rate:  {USB_BAUD_RATE}")
    print()
    
    # Set up USB serial
    if setup_serial():
        # Start background receive thread
        receiver = threading.Thread(target=serial_receive_thread, daemon=True)
        receiver.start()
        print("USB serial receiver thread started.")
    else:
        print("WARNING: USB serial not available. Running web interface only.")
    
    print()
    print(f"Access the VEX USB Interface at:")
    print(f"  http://{local_ip}/vex")
    if PORT != 80:
        print(f"  http://{local_ip}:{PORT}/vex")
    print()
    print("-" * 60)
    
    # Run Flask HTTP server
    try:
        app.run(
            host=HOST,
            port=PORT,
            debug=False,
            threaded=True
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        running = False
        if serial_port and serial_port.is_open:
            serial_port.close()
            print("Serial port closed.")


if __name__ == "__main__":
    main()

